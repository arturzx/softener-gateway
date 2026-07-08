import asyncio
import ssl
from collections.abc import Callable
from typing import Any, cast

import pytest

from softener_gateway.config import EndpointConfig
from softener_gateway.endpoint import (
    Endpoint,
    EndpointConnectedEvent,
    EndpointDataReceivedEvent,
    EndpointDataWrittenEvent,
    EndpointDisconnectedEvent,
    EndpointTlsMetadata,
    _EndpointConnection,
)
from softener_gateway.events import EventBus
from tests.crypto_material import (
    PemMaterial,
    generate_ca_pem_material,
    generate_pem_material,
)


class FakeSocket:
    def getsockname(self) -> tuple[str, int]:
        return ("127.0.0.1", 12345)


class FakeServer:
    def __init__(self) -> None:
        self.sockets = [FakeSocket()]
        self.closed = False
        self.waited_closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited_closed = True


class FakeReader:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started = asyncio.Event()

    async def read(self, _limit: int = -1) -> bytes:
        self.started.set()
        await self.release.wait()
        return b""


class FakeChunkReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def read(self, _limit: int = -1) -> bytes:
        if not self._chunks:
            return b""

        return self._chunks.pop(0)


class FakeSslObject:
    def version(self) -> str:
        return "TLSv1.3"

    def selected_alpn_protocol(self) -> str:
        return "mqtt"


class FakeWriter:
    def __init__(
        self,
        peername: tuple[str, int],
        reader: FakeReader,
        *,
        extra_info: dict[str, object] | None = None,
    ) -> None:
        self.extra_info: dict[str, object] = {"peername": peername}
        if extra_info is not None:
            self.extra_info.update(extra_info)
        self.reader = reader
        self.closed = False
        self.waited_closed = False
        self.writes: list[bytes] = []
        self.drained = False

    def get_extra_info(self, name: str) -> object | None:
        return self.extra_info.get(name)

    def close(self) -> None:
        self.closed = True
        self.reader.release.set()

    def is_closing(self) -> bool:
        return self.closed

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        self.drained = True

    async def wait_closed(self) -> None:
        self.waited_closed = True


def make_endpoint_config(
    material: PemMaterial | None = None,
    *,
    ca: str | None = None,
    port: int = 8883,
) -> EndpointConfig:
    material = material or generate_pem_material()
    data = {
        "host": "127.0.0.1",
        "port": port,
        "certificate": material.certificate,
        "key": material.key,
    }
    if ca is not None:
        data["ca"] = ca

    return EndpointConfig.model_validate(data)


def install_fake_start_server(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FakeServer, dict[str, Any]]:
    fake_server = FakeServer()
    captured: dict[str, Any] = {}

    async def fake_start_server(
        client_connected_cb: Callable[[asyncio.StreamReader, asyncio.StreamWriter], object],
        host: str,
        port: int,
        ssl: ssl.SSLContext,
    ) -> FakeServer:
        captured["client_connected_cb"] = client_connected_cb
        captured["host"] = host
        captured["port"] = port
        captured["ssl"] = ssl
        return fake_server

    monkeypatch.setattr(asyncio, "start_server", fake_start_server)
    return fake_server, captured


def test_endpoint_start_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_server, captured = install_fake_start_server(monkeypatch)

    asyncio.run(_start_stop_endpoint(fake_server, captured))


async def _start_stop_endpoint(fake_server: FakeServer, captured: dict[str, Any]) -> None:
    endpoint = Endpoint(make_endpoint_config(), EventBus())

    assert not endpoint.is_running

    await endpoint.start()

    assert endpoint.is_running
    assert endpoint.bound_port == 12345
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8883
    assert isinstance(captured["ssl"], ssl.SSLContext)

    await endpoint.stop()

    assert not endpoint.is_running
    assert fake_server.closed
    assert fake_server.waited_closed


def test_endpoint_start_stop_are_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_start_server(monkeypatch)

    asyncio.run(_start_stop_endpoint_idempotently())


async def _start_stop_endpoint_idempotently() -> None:
    endpoint = Endpoint(make_endpoint_config(), EventBus())

    await endpoint.start()
    await endpoint.start()

    assert endpoint.is_running

    await endpoint.stop()
    await endpoint.stop()

    assert not endpoint.is_running


def test_endpoint_uses_tls_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_server, captured = install_fake_start_server(monkeypatch)

    asyncio.run(_start_endpoint_with_tls_context(captured))


async def _start_endpoint_with_tls_context(captured: dict[str, Any]) -> None:
    endpoint = Endpoint(make_endpoint_config(), EventBus())
    await endpoint.start()

    try:
        context = captured["ssl"]
        assert isinstance(context, ssl.SSLContext)
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2
        assert not endpoint.requires_client_certificate
    finally:
        await endpoint.stop()


def test_endpoint_enables_mtls_when_ca_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_server, captured = install_fake_start_server(monkeypatch)

    asyncio.run(_start_endpoint_with_mtls(captured))


async def _start_endpoint_with_mtls(captured: dict[str, Any]) -> None:
    server_material = generate_pem_material()
    ca_material = generate_ca_pem_material()
    endpoint = Endpoint(
        make_endpoint_config(server_material, ca=ca_material.certificate),
        EventBus(),
    )
    await endpoint.start()

    try:
        assert endpoint.requires_client_certificate
        context = captured["ssl"]
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED
    finally:
        await endpoint.stop()


def test_new_connection_closes_previous_connection() -> None:
    asyncio.run(_replace_active_connection())


async def _replace_active_connection() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(EndpointConnectedEvent, EndpointDisconnectedEvent)
    endpoint = Endpoint(make_endpoint_config(), event_bus)
    first_reader = FakeReader()
    first_writer = cast(asyncio.StreamWriter, FakeWriter(("192.0.2.1", 1000), first_reader))
    second_reader = FakeReader()
    second_writer = cast(asyncio.StreamWriter, FakeWriter(("192.0.2.2", 2000), second_reader))

    first_task = asyncio.create_task(
        endpoint._handle_client(
            cast(asyncio.StreamReader, first_reader),
            first_writer,
        )
    )
    await first_reader.started.wait()

    assert endpoint._active_connection is not None
    assert endpoint._active_connection.writer is first_writer
    emitter, first_connected = await anext(subscription)
    assert emitter is endpoint
    assert isinstance(first_connected, EndpointConnectedEvent)
    assert first_connected.host == "192.0.2.1"
    assert first_connected.port == 1000

    second_task = asyncio.create_task(
        endpoint._handle_client(
            cast(asyncio.StreamReader, second_reader),
            second_writer,
        )
    )
    await second_reader.started.wait()

    assert cast(FakeWriter, first_writer).closed
    assert endpoint._active_connection is not None
    assert endpoint._active_connection.writer is second_writer
    emitter, first_disconnected = await anext(subscription)
    assert emitter is endpoint
    emitter, second_connected = await anext(subscription)
    assert emitter is endpoint
    assert isinstance(first_disconnected, EndpointDisconnectedEvent)
    assert first_disconnected.bytes_read == 0
    assert first_disconnected.bytes_written == 0
    assert isinstance(second_connected, EndpointConnectedEvent)
    assert second_connected.host == "192.0.2.2"
    assert second_connected.port == 2000

    first_reader.release.set()
    await first_task

    assert endpoint._active_connection is not None
    assert endpoint._active_connection.writer is second_writer
    assert cast(FakeWriter, first_writer).waited_closed

    second_reader.release.set()
    await second_task

    emitter, second_disconnected = await anext(subscription)
    assert emitter is endpoint

    assert isinstance(second_disconnected, EndpointDisconnectedEvent)
    assert second_disconnected.bytes_read == 0
    assert second_disconnected.bytes_written == 0
    assert endpoint._active_connection is None
    assert cast(FakeWriter, second_writer).closed
    assert cast(FakeWriter, second_writer).waited_closed


def test_endpoint_publishes_connected_and_disconnected() -> None:
    asyncio.run(_publish_connected_and_disconnected())


async def _publish_connected_and_disconnected() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(EndpointConnectedEvent, EndpointDisconnectedEvent)
    endpoint = Endpoint(make_endpoint_config(), event_bus)
    reader = FakeReader()
    writer = cast(
        asyncio.StreamWriter,
        FakeWriter(
            ("192.0.2.10", 1234),
            reader,
            extra_info={
                "ssl_object": FakeSslObject(),
                "cipher": ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256),
                "peercert": {"subject": ((("commonName", "softener"),),)},
            },
        ),
    )

    task = asyncio.create_task(
        endpoint._handle_client(
            cast(asyncio.StreamReader, reader),
            writer,
        )
    )
    await reader.started.wait()

    emitter, connected = await anext(subscription)

    assert emitter is endpoint
    assert isinstance(connected, EndpointConnectedEvent)
    assert connected.host == "192.0.2.10"
    assert connected.port == 1234
    assert connected.tls == EndpointTlsMetadata(
        protocol_version="TLSv1.3",
        cipher_name="TLS_AES_256_GCM_SHA384",
        cipher_protocol="TLSv1.3",
        cipher_bits=256,
        alpn_protocol="mqtt",
        client_certificate={"subject": ((("commonName", "softener"),),)},
    )

    reader.release.set()
    await task

    emitter, disconnected = await anext(subscription)

    assert emitter is endpoint
    assert isinstance(disconnected, EndpointDisconnectedEvent)
    assert disconnected.bytes_read == 0
    assert disconnected.bytes_written == 0


def test_endpoint_publishes_data_received() -> None:
    asyncio.run(_publish_data_received())


async def _publish_data_received() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(EndpointDataReceivedEvent)
    endpoint = Endpoint(make_endpoint_config(), event_bus)
    reader = cast(asyncio.StreamReader, FakeChunkReader([b"first", b"second", b""]))

    await endpoint._run_client(reader)

    emitter, first = await anext(subscription)
    assert emitter is endpoint
    emitter, second = await anext(subscription)
    assert emitter is endpoint

    assert isinstance(first, EndpointDataReceivedEvent)
    assert first.data == b"first"
    assert isinstance(second, EndpointDataReceivedEvent)
    assert second.data == b"second"


def test_endpoint_disconnected_event_contains_bytes_read() -> None:
    asyncio.run(_publish_disconnected_with_bytes_read())


async def _publish_disconnected_with_bytes_read() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(EndpointConnectedEvent, EndpointDisconnectedEvent)
    endpoint = Endpoint(make_endpoint_config(), event_bus)
    reader = cast(asyncio.StreamReader, FakeChunkReader([b"first", b"second", b""]))
    writer = cast(
        asyncio.StreamWriter,
        FakeWriter(("192.0.2.10", 1234), FakeReader()),
    )

    await endpoint._handle_client(reader, writer)

    emitter, connected = await anext(subscription)
    assert emitter is endpoint
    emitter, disconnected = await anext(subscription)
    assert emitter is endpoint

    assert isinstance(connected, EndpointConnectedEvent)
    assert isinstance(disconnected, EndpointDisconnectedEvent)
    assert disconnected.bytes_read == len(b"firstsecond")
    assert disconnected.bytes_written == 0


def test_endpoint_write_sends_data_and_publishes_data_written() -> None:
    asyncio.run(_write_data())


async def _write_data() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(EndpointDataWrittenEvent, EndpointDisconnectedEvent)
    endpoint = Endpoint(make_endpoint_config(), event_bus)
    reader = FakeReader()
    writer = FakeWriter(("192.0.2.10", 1234), reader)

    task = asyncio.create_task(
        endpoint._handle_client(
            cast(asyncio.StreamReader, reader),
            cast(asyncio.StreamWriter, writer),
        )
    )
    await reader.started.wait()

    await endpoint.write(b"payload")

    assert writer.writes == [b"payload"]
    assert writer.drained

    emitter, event = await anext(subscription)

    assert emitter is endpoint
    assert isinstance(event, EndpointDataWrittenEvent)
    assert event.data == b"payload"

    reader.release.set()
    await task

    emitter, disconnected = await anext(subscription)

    assert emitter is endpoint
    assert isinstance(disconnected, EndpointDisconnectedEvent)
    assert disconnected.bytes_read == 0
    assert disconnected.bytes_written == len(b"payload")


def test_endpoint_write_requires_active_connection() -> None:
    asyncio.run(_write_without_active_connection())


async def _write_without_active_connection() -> None:
    endpoint = Endpoint(make_endpoint_config(), EventBus())

    with pytest.raises(RuntimeError, match="No active TLS endpoint connection"):
        await endpoint.write(b"payload")


def test_endpoint_close_disconnects_active_connection() -> None:
    asyncio.run(_close_active_connection())


async def _close_active_connection() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(EndpointConnectedEvent, EndpointDisconnectedEvent)
    endpoint = Endpoint(make_endpoint_config(), event_bus)
    reader = FakeReader()
    writer = FakeWriter(("192.0.2.10", 1234), reader)

    task = asyncio.create_task(
        endpoint._handle_client(
            cast(asyncio.StreamReader, reader),
            cast(asyncio.StreamWriter, writer),
        )
    )
    await reader.started.wait()

    emitter, connected = await anext(subscription)
    assert emitter is endpoint
    await endpoint.close()
    emitter, disconnected = await anext(subscription)
    assert emitter is endpoint
    await task
    await endpoint.close()

    assert isinstance(connected, EndpointConnectedEvent)
    assert isinstance(disconnected, EndpointDisconnectedEvent)
    assert disconnected.bytes_read == 0
    assert disconnected.bytes_written == 0
    assert endpoint._active_connection is None
    assert writer.closed
    assert writer.waited_closed


def test_endpoint_write_rejects_closing_connection() -> None:
    asyncio.run(_write_to_closing_connection())


async def _write_to_closing_connection() -> None:
    endpoint = Endpoint(make_endpoint_config(), EventBus())
    writer = FakeWriter(("192.0.2.10", 1234), FakeReader())
    writer.close()
    endpoint._active_connection = _EndpointConnection(cast(asyncio.StreamWriter, writer))

    with pytest.raises(RuntimeError, match="No active TLS endpoint connection"):
        await endpoint.write(b"payload")
