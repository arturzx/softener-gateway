import asyncio
import ssl
from typing import Any, cast

import pytest

from softener_gateway.aws import (
    AwsConnectedEvent,
    AwsConnection,
    AwsDataReceivedEvent,
    AwsDataWrittenEvent,
    AwsDisconnectedEvent,
)
from softener_gateway.config import AwsConfig
from softener_gateway.events import Event, EventBus
from tests.crypto_material import generate_pem_material


class BlockingReader:
    async def read(self, _limit: int = -1) -> bytes:
        future: asyncio.Future[bytes] = asyncio.Future()
        return await future


class FakeChunkReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def read(self, _limit: int = -1) -> bytes:
        if not self._chunks:
            return b""

        return self._chunks.pop(0)


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False
        self.waited_closed = False
        self.writes: list[bytes] = []
        self.drained = False

    def is_closing(self) -> bool:
        return self.closed

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        self.drained = True

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited_closed = True


def make_aws_config(*, check_hostname: bool = True) -> AwsConfig:
    material = generate_pem_material()
    return AwsConfig.model_validate(
        {
            "host": "aws.example.com",
            "port": 8883,
            "check_hostname": check_hostname,
            "certificate": material.certificate,
            "key": material.key,
        }
    )


def test_aws_connection_stores_config() -> None:
    config = make_aws_config()
    event_bus = EventBus()

    connection = AwsConnection(config, event_bus)

    assert connection.config is config
    assert connection.event_bus is event_bus


def test_aws_events() -> None:
    connected = AwsConnectedEvent()
    received = AwsDataReceivedEvent(data=b"received")
    written = AwsDataWrittenEvent(data=b"written")
    disconnected = AwsDisconnectedEvent(bytes_read=8, bytes_written=7)

    assert isinstance(connected, Event)
    assert received.data == b"received"
    assert written.data == b"written"
    assert disconnected.bytes_read == 8
    assert disconnected.bytes_written == 7


def test_aws_connection_connects_with_tls_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured, _writer = install_fake_open_connection(monkeypatch)

    asyncio.run(_connect(captured))


async def _connect(captured: dict[str, Any]) -> None:
    connection = AwsConnection(make_aws_config(), EventBus())

    await connection.connect()

    try:
        assert connection.is_connected
        assert captured["host"] == "aws.example.com"
        assert captured["port"] == 8883
        assert captured["server_hostname"] == "aws.example.com"

        context = captured["ssl"]
        assert isinstance(context, ssl.SSLContext)
        assert context.check_hostname
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    finally:
        await connection.close()


def test_aws_connection_can_disable_hostname_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured, _writer = install_fake_open_connection(monkeypatch)

    asyncio.run(_connect_without_hostname_verification(captured))


async def _connect_without_hostname_verification(captured: dict[str, Any]) -> None:
    connection = AwsConnection(make_aws_config(check_hostname=False), EventBus())

    await connection.connect()

    try:
        context = captured["ssl"]
        assert isinstance(context, ssl.SSLContext)
        assert not context.check_hostname
        assert captured["server_hostname"] == "aws.example.com"
    finally:
        await connection.close()


def test_aws_connection_write(monkeypatch: pytest.MonkeyPatch) -> None:
    _captured, writer = install_fake_open_connection(monkeypatch)

    asyncio.run(_write(writer))


async def _write(writer: FakeWriter) -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(AwsDataWrittenEvent)
    connection = AwsConnection(make_aws_config(), event_bus)
    await connection.connect()

    try:
        await connection.write(b"payload")

        emitter, event = await anext(subscription)

        assert writer.writes == [b"payload"]
        assert writer.drained
        assert emitter is connection
        assert isinstance(event, AwsDataWrittenEvent)
        assert event.data == b"payload"
    finally:
        await connection.close()


def test_aws_connection_write_requires_active_connection() -> None:
    asyncio.run(_write_without_active_connection())


async def _write_without_active_connection() -> None:
    connection = AwsConnection(make_aws_config(), EventBus())

    with pytest.raises(RuntimeError, match="No active AWS connection"):
        await connection.write(b"payload")


def test_aws_connection_close(monkeypatch: pytest.MonkeyPatch) -> None:
    _captured, writer = install_fake_open_connection(monkeypatch)

    asyncio.run(_close(writer))


async def _close(writer: FakeWriter) -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(AwsConnectedEvent, AwsDisconnectedEvent)
    connection = AwsConnection(make_aws_config(), event_bus)
    await connection.connect()

    emitter, connected = await anext(subscription)
    assert emitter is connection
    await connection.close()
    emitter, disconnected = await anext(subscription)
    assert emitter is connection
    await connection.close()

    assert isinstance(connected, AwsConnectedEvent)
    assert isinstance(disconnected, AwsDisconnectedEvent)
    assert disconnected.bytes_read == 0
    assert disconnected.bytes_written == 0
    assert not connection.is_connected
    assert writer.closed
    assert writer.waited_closed


def test_aws_connection_publishes_received_data(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = FakeChunkReader([b"first", b"second", b""])
    _captured, writer = install_fake_open_connection(monkeypatch, reader=reader)

    asyncio.run(_publish_received_data(writer))


async def _publish_received_data(writer: FakeWriter) -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(AwsDataReceivedEvent, AwsDisconnectedEvent)
    connection = AwsConnection(make_aws_config(), event_bus)

    await connection.connect()

    emitter, first = await anext(subscription)
    assert emitter is connection
    emitter, second = await anext(subscription)
    assert emitter is connection
    emitter, disconnected = await anext(subscription)
    assert emitter is connection

    assert isinstance(first, AwsDataReceivedEvent)
    assert first.data == b"first"
    assert isinstance(second, AwsDataReceivedEvent)
    assert second.data == b"second"
    assert isinstance(disconnected, AwsDisconnectedEvent)
    assert disconnected.bytes_read == len(b"firstsecond")
    assert disconnected.bytes_written == 0
    assert not connection.is_connected
    assert writer.closed
    assert writer.waited_closed


def install_fake_open_connection(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reader: object | None = None,
) -> tuple[dict[str, Any], FakeWriter]:
    captured: dict[str, Any] = {}
    writer = FakeWriter()
    connection_reader = reader or BlockingReader()

    async def fake_open_connection(
        host: str,
        port: int,
        ssl: ssl.SSLContext,
        server_hostname: str,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        captured["host"] = host
        captured["port"] = port
        captured["ssl"] = ssl
        captured["server_hostname"] = server_hostname
        return (
            cast(asyncio.StreamReader, connection_reader),
            cast(asyncio.StreamWriter, writer),
        )

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)
    return captured, writer
