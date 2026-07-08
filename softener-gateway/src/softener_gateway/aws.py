import asyncio
import logging
import ssl
from contextlib import suppress
from dataclasses import dataclass

from softener_gateway.config import AwsConfig
from softener_gateway.events import Event, EventBus
from softener_gateway.tls import configure_tls_material

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AwsConnectedEvent(Event):
    pass


@dataclass(frozen=True, slots=True)
class AwsDataReceivedEvent(Event):
    data: bytes


@dataclass(frozen=True, slots=True)
class AwsDataWrittenEvent(Event):
    data: bytes


@dataclass(frozen=True, slots=True)
class AwsDisconnectedEvent(Event):
    bytes_read: int
    bytes_written: int


class AwsConnection:
    def __init__(self, config: AwsConfig, event_bus: EventBus) -> None:
        self.config = config
        self.event_bus = event_bus
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ssl_context: ssl.SSLContext | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._bytes_read = 0
        self._bytes_written = 0
        self._disconnected = True

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        if self.is_connected:
            return

        ssl_context = self._create_ssl_context()
        self._reader, self._writer = await asyncio.open_connection(
            host=self.config.host,
            port=self.config.port,
            ssl=ssl_context,
            server_hostname=self.config.host,
        )
        self._ssl_context = ssl_context
        self._bytes_read = 0
        self._bytes_written = 0
        self._disconnected = False
        await self.event_bus.publish(self, AwsConnectedEvent())
        self._reader_task = asyncio.create_task(self._run_reader(self._reader))

    async def write(self, data: bytes) -> None:
        writer = self._writer
        if writer is None or writer.is_closing():
            raise RuntimeError("No active AWS connection")

        writer.write(data)
        await writer.drain()
        self._bytes_written += len(data)
        await self.event_bus.publish(self, AwsDataWrittenEvent(data=data))

    async def close(self) -> None:
        await self._close_connection(cancel_reader=True)

    async def _run_reader(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                data = await reader.read(4096)
                if data == b"":
                    break

                self._bytes_read += len(data)
                await self.event_bus.publish(self, AwsDataReceivedEvent(data=data))
        except Exception:
            logger.exception("AWS connection reader failed")
        finally:
            await self._close_connection(cancel_reader=False)

    async def _close_connection(self, *, cancel_reader: bool) -> None:
        writer = self._writer
        reader_task = self._reader_task
        if writer is None and self._disconnected:
            return

        self._reader = None
        self._writer = None
        self._ssl_context = None
        self._reader_task = None

        if writer is not None:
            writer.close()
            await writer.wait_closed()

        if (
            cancel_reader
            and reader_task is not None
            and reader_task is not asyncio.current_task()
        ):
            reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await reader_task

        if self._disconnected:
            return

        self._disconnected = True
        await self.event_bus.publish(
            self,
            AwsDisconnectedEvent(
                bytes_read=self._bytes_read,
                bytes_written=self._bytes_written,
            ),
        )

    def _create_ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = self.config.check_hostname

        configure_tls_material(
            context,
            self.config,
            temp_file_prefix="softener-gateway-aws",
        )
        return context


__all__ = [
    "AwsConnectedEvent",
    "AwsConnection",
    "AwsDataReceivedEvent",
    "AwsDataWrittenEvent",
    "AwsDisconnectedEvent",
]
