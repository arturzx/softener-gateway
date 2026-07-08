import asyncio
import logging
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from softener_gateway.config import EndpointConfig
from softener_gateway.events import Event, EventBus
from softener_gateway.tls import configure_tls_material

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EndpointTlsMetadata:
    protocol_version: str | None = None
    cipher_name: str | None = None
    cipher_protocol: str | None = None
    cipher_bits: int | None = None
    alpn_protocol: str | None = None
    client_certificate: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class EndpointConnectedEvent(Event):
    host: str
    port: int
    tls: EndpointTlsMetadata | None = None


@dataclass(frozen=True, slots=True)
class EndpointDataReceivedEvent(Event):
    data: bytes


@dataclass(frozen=True, slots=True)
class EndpointDataWrittenEvent(Event):
    data: bytes


@dataclass(frozen=True, slots=True)
class EndpointDisconnectedEvent(Event):
    bytes_read: int
    bytes_written: int


@dataclass(slots=True)
class _EndpointConnection:
    writer: asyncio.StreamWriter
    bytes_read: int = 0
    bytes_written: int = 0


class Endpoint:
    def __init__(self, config: EndpointConfig, event_bus: EventBus) -> None:
        self.config = config
        self.event_bus = event_bus
        self._server: asyncio.Server | None = None
        self._ssl_context: ssl.SSLContext | None = None
        self._active_connection: _EndpointConnection | None = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def bound_port(self) -> int:
        if self._server is None or not self._server.sockets:
            return self.config.port

        socket_name = self._server.sockets[0].getsockname()
        return int(socket_name[1])

    @property
    def requires_client_certificate(self) -> bool:
        return (
            self._ssl_context is not None
            and self._ssl_context.verify_mode == ssl.CERT_REQUIRED
        )

    async def start(self) -> None:
        if self._server is not None:
            return

        ssl_context = self._create_ssl_context()
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.config.host,
            port=self.config.port,
            ssl=ssl_context,
        )

        self._ssl_context = ssl_context
        logger.info("Starting TLS endpoint on %s:%s", self.config.host, self.bound_port)

    async def stop(self) -> None:
        if self._server is None:
            return

        logger.info("Stopping TLS endpoint on %s:%s", self.config.host, self.bound_port)
        self._server.close()
        await self._server.wait_closed()
        await self.close()
        self._server = None
        self._ssl_context = None

    async def close(self) -> None:
        connection = self._active_connection
        if connection is None:
            return

        self._active_connection = None
        await self._disconnect_connection(connection)
        await connection.writer.wait_closed()

    async def write(self, data: bytes) -> None:
        connection = self._active_connection
        if connection is None or connection.writer.is_closing():
            raise RuntimeError("No active TLS endpoint connection")

        writer = connection.writer
        writer.write(data)
        await writer.drain()
        connection.bytes_written += len(data)
        await self.event_bus.publish(self, EndpointDataWrittenEvent(data=data))

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        logger.debug("Accepted TLS endpoint connection from %s", peer)

        if self._active_connection is not None:
            logger.info("Closing previous TLS endpoint connection")
            await self._disconnect_connection(self._active_connection)

        connection = _EndpointConnection(writer=writer)
        self._active_connection = connection
        host, port = _get_writer_peer(writer)
        await self.event_bus.publish(
            self,
            EndpointConnectedEvent(
                host=host,
                port=port,
                tls=_get_tls_metadata(writer),
            ),
        )

        try:
            await self._run_client(reader, connection)
        finally:
            if self._active_connection is connection:
                self._active_connection = None
                await self._disconnect_connection(connection)
            else:
                writer.close()

            await writer.wait_closed()

    async def _run_client(
        self,
        reader: asyncio.StreamReader,
        connection: _EndpointConnection | None = None,
    ) -> None:
        while True:
            data = await reader.read(4096)
            if data == b"":
                break

            if connection is not None:
                connection.bytes_read += len(data)
            await self.event_bus.publish(self, EndpointDataReceivedEvent(data=data))

    async def _disconnect_connection(self, connection: _EndpointConnection) -> None:
        connection.writer.close()
        await self.event_bus.publish(
            self,
            EndpointDisconnectedEvent(
                bytes_read=connection.bytes_read,
                bytes_written=connection.bytes_written,
            ),
        )

    def _create_ssl_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2

        configure_tls_material(
            context,
            self.config,
            temp_file_prefix="softener-gateway-endpoint",
        )
        if self.config.ca is not None:
            context.verify_mode = ssl.CERT_REQUIRED

        return context


def _get_writer_peer(writer: asyncio.StreamWriter) -> tuple[str, int]:
    peername = writer.get_extra_info("peername")
    if not isinstance(peername, tuple) or len(peername) < 2:
        raise RuntimeError("TLS endpoint connection peername is unavailable")

    host, port = peername[:2]
    if not isinstance(host, str) or not isinstance(port, int):
        raise RuntimeError("TLS endpoint connection peername is invalid")

    return host, port


def _get_tls_metadata(writer: asyncio.StreamWriter) -> EndpointTlsMetadata | None:
    ssl_object = writer.get_extra_info("ssl_object")
    cipher_value = writer.get_extra_info("cipher")
    if cipher_value is None and ssl_object is not None:
        cipher_value = _call_no_args(ssl_object, "cipher")

    cipher_name, cipher_protocol, cipher_bits = _parse_cipher(cipher_value)

    client_certificate_value = writer.get_extra_info("peercert")
    if client_certificate_value is None and ssl_object is not None:
        client_certificate_value = _call_no_args(ssl_object, "getpeercert")

    client_certificate = (
        cast(dict[str, object], client_certificate_value)
        if isinstance(client_certificate_value, dict)
        else None
    )

    protocol_version_value = (
        _call_no_args(ssl_object, "version") if ssl_object is not None else None
    )
    protocol_version = (
        protocol_version_value if isinstance(protocol_version_value, str) else None
    )

    alpn_protocol_value = (
        _call_no_args(ssl_object, "selected_alpn_protocol")
        if ssl_object is not None
        else None
    )
    alpn_protocol = alpn_protocol_value if isinstance(alpn_protocol_value, str) else None

    if (
        ssl_object is None
        and protocol_version is None
        and cipher_name is None
        and alpn_protocol is None
        and client_certificate is None
    ):
        return None

    return EndpointTlsMetadata(
        protocol_version=protocol_version,
        cipher_name=cipher_name,
        cipher_protocol=cipher_protocol,
        cipher_bits=cipher_bits,
        alpn_protocol=alpn_protocol,
        client_certificate=client_certificate,
    )


def _parse_cipher(cipher_value: object) -> tuple[str | None, str | None, int | None]:
    if not isinstance(cipher_value, tuple) or len(cipher_value) < 3:
        return None, None, None

    name, protocol, bits = cipher_value[:3]
    return (
        name if isinstance(name, str) else None,
        protocol if isinstance(protocol, str) else None,
        bits if isinstance(bits, int) else None,
    )


def _call_no_args(source: object, method_name: str) -> object | None:
    method = getattr(source, method_name, None)
    if not callable(method):
        return None

    return cast(Callable[[], object], method)()


__all__ = [
    "Endpoint",
    "EndpointConnectedEvent",
    "EndpointDataReceivedEvent",
    "EndpointDataWrittenEvent",
    "EndpointDisconnectedEvent",
    "EndpointTlsMetadata",
]
