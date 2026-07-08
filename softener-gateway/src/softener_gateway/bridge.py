from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, NoReturn, TextIO, cast

from softener_gateway.aws import (
    AwsConnection,
    AwsDataReceivedEvent,
    AwsDisconnectedEvent,
)
from softener_gateway.config import AwsConfig, GatewayConfig, MqttSessionLogConfig
from softener_gateway.control import ReadOnlyModeError
from softener_gateway.device.data import DeviceConfigurationData, DeviceHistoricalData
from softener_gateway.device.shadow import (
    DeviceShadow,
    DeviceShadowError,
    ShadowLifecycle,
    ShadowOperation,
    ShadowTopic,
    decode_shadow_payload,
    parse_shadow_topic,
    read_current_shadow_document,
)
from softener_gateway.endpoint import (
    Endpoint,
    EndpointConnectedEvent,
    EndpointDataReceivedEvent,
    EndpointDisconnectedEvent,
)
from softener_gateway.events import Event, EventBus
from softener_gateway.mapper import (
    Device,
    DeviceDataUpdatedEvent,
    DeviceMapper,
    DeviceMappingInput,
)
from softener_gateway.models import (
    AuxOutputMode,
    DateFormat,
    EfficiencyMode,
    HardnessUnit,
    SaltType,
    TimeFormat,
    VolumeUnit,
    WeightUnit,
)
from softener_gateway.mqtt_protocol import MqttPacket, MqttParseError, PublishPacket, parse_packets

logger = logging.getLogger(__name__)


class Bridge:
    def __init__(
        self,
        config: GatewayConfig,
        event_bus: EventBus,
        endpoint: Endpoint,
        shadow: DeviceShadow,
        device: Device,
        mapper: DeviceMapper,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.endpoint = endpoint
        self.shadow = shadow
        self.device = device
        self.mapper = mapper
        self._aws = AwsConnection(cast(AwsConfig, config.aws), event_bus)
        self._mqtt_observer = MqttObserver(event_bus)
        self._shadow_mirror = ShadowMirror(event_bus, shadow)
        self._data_mirror = DataMirror(event_bus)
        self._session_logger = (
            MqttSessionLogger(event_bus, config.session_log)
            if config.session_log is not None
            else None
        )
        self._device_online = False
        self._device_projector_task: asyncio.Task[None] | None = None

    def _read_only(self) -> NoReturn:
        raise ReadOnlyModeError("device control is not available in bridge mode")

    async def set_hardness(self, value: float) -> None:
        self._read_only()

    async def set_regen_time(self, value: str) -> None:
        self._read_only()

    async def set_salt_type(self, value: SaltType) -> None:
        self._read_only()

    async def set_salt_level(self, value: float) -> None:
        self._read_only()

    async def set_flow_alert_min_rate(self, value: float) -> None:
        self._read_only()

    async def set_flow_alert_duration(self, value: float) -> None:
        self._read_only()

    async def set_volume_unit(self, value: VolumeUnit) -> None:
        self._read_only()

    async def set_weight_unit(self, value: WeightUnit) -> None:
        self._read_only()

    async def set_hardness_unit(self, value: HardnessUnit) -> None:
        self._read_only()

    async def set_date_format(self, value: DateFormat) -> None:
        self._read_only()

    async def set_time_format(self, value: TimeFormat) -> None:
        self._read_only()

    async def set_aux_output_mode(self, value: AuxOutputMode) -> None:
        self._read_only()

    async def set_aux_chemical_feed_amount(self, value: float) -> None:
        self._read_only()

    async def set_regeneration_backwash(self, value: int) -> None:
        self._read_only()

    async def set_regeneration_fast_rinse(self, value: int) -> None:
        self._read_only()

    async def set_regeneration_second_backwash(self, value: int) -> None:
        self._read_only()

    async def set_regeneration_rinse_type(self, value: int) -> None:
        self._read_only()

    async def set_feature_97_percent(self, value: bool) -> None:
        self._read_only()

    async def set_efficiency_mode(self, value: EfficiencyMode) -> None:
        self._read_only()

    async def set_max_days_between_regenerations(
        self,
        value: int | Literal["auto"],
    ) -> None:
        self._read_only()

    async def start_regeneration(self) -> None:
        self._read_only()

    async def run(self) -> None:
        logger.info("Bridge mode selected")

        await self._start_device_projector()
        if self._session_logger is not None:
            await self._session_logger.start()
        await self._mqtt_observer.start()
        await self._shadow_mirror.start()
        await self._data_mirror.start()
        try:
            async with self.event_bus.subscribe(
                EndpointConnectedEvent,
                EndpointDataReceivedEvent,
                EndpointDisconnectedEvent,
                AwsDataReceivedEvent,
                AwsDisconnectedEvent,
            ) as subscription:
                async for _emitter, event in subscription:
                    match event:
                        case EndpointConnectedEvent():
                            await self._connect_aws()
                        case EndpointDataReceivedEvent(data=data):
                            await self._write_to_aws(data)
                        case EndpointDisconnectedEvent():
                            await self._aws.close()
                        case AwsDataReceivedEvent(data=data):
                            await self.endpoint.write(data)
                        case AwsDisconnectedEvent():
                            await self.endpoint.close()
        finally:
            await self._data_mirror.stop()
            await self._shadow_mirror.stop()
            await self._mqtt_observer.stop()
            if self._session_logger is not None:
                await self._session_logger.stop()
            await self._stop_device_projector()
            await self._aws.close()

    async def _start_device_projector(self) -> None:
        if self._device_projector_task is not None:
            return

        ready = asyncio.Event()
        self._device_projector_task = asyncio.create_task(self._run_device_projector(ready))
        await ready.wait()

    async def _stop_device_projector(self) -> None:
        task = self._device_projector_task
        if task is None:
            return

        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

        if self._device_projector_task is task:
            self._device_projector_task = None

    async def _run_device_projector(self, ready: asyncio.Event) -> None:
        async with self.event_bus.subscribe(
            DeviceDataUpdatedEvent,
            EndpointConnectedEvent,
            EndpointDisconnectedEvent,
        ) as subscription:
            self._rebuild_device()
            ready.set()
            async for emitter, event in subscription:
                if isinstance(event, DeviceDataUpdatedEvent):
                    if emitter not in (self._shadow_mirror, self._data_mirror):
                        continue
                elif isinstance(event, EndpointConnectedEvent | EndpointDisconnectedEvent):
                    if emitter is not self.endpoint:
                        continue
                    self._device_online = isinstance(event, EndpointConnectedEvent)

                self._rebuild_device()

    def _rebuild_device(self) -> None:
        self.device.rebuild(
            self.mapper,
            DeviceMappingInput(
                shadow=self.shadow,
                configuration_data=self._data_mirror.configuration_data,
                historical_data=self._data_mirror.historical_data,
                unit_system=self.config.unit_system,
                online=self._device_online,
            ),
        )

    async def _connect_aws(self) -> None:
        try:
            await self._aws.connect()
        except Exception:
            logger.exception("Failed to connect to AWS; closing endpoint connection")
            await self._aws.close()
            await self.endpoint.close()

    async def _write_to_aws(self, data: bytes) -> None:
        if not self._aws.is_connected:
            logger.debug("Dropping endpoint data because AWS connection is not active")
            await self.endpoint.close()
            return

        await self._aws.write(data)


class MqttDirection(StrEnum):
    DEVICE_TO_AWS = "device -> AWS"
    AWS_TO_DEVICE = "AWS -> device"


@dataclass(frozen=True, slots=True)
class MqttPacketEvent(Event):
    direction: MqttDirection
    packet: MqttPacket


@dataclass(frozen=True, slots=True)
class MqttParseErrorEvent(Event):
    direction: MqttDirection
    error: str


class DataMirrorError(ValueError):
    pass


class MqttSessionLogger:
    def __init__(self, event_bus: EventBus, config: MqttSessionLogConfig) -> None:
        self.event_bus = event_bus
        self.config = config
        self._task: asyncio.Task[None] | None = None
        self._file: TextIO | None = None
        self._session_path: Path | None = None
        self._session_index = 0

    async def start(self) -> None:
        if self._task is not None:
            return

        ready = asyncio.Event()
        self._task = asyncio.create_task(self._run(ready))
        await ready.wait()

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return

        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self._close_session("logger_stopped")

    async def _run(self, ready: asyncio.Event) -> None:
        async with self.event_bus.subscribe(
            EndpointConnectedEvent,
            EndpointDataReceivedEvent,
            EndpointDisconnectedEvent,
            AwsDataReceivedEvent,
            AwsDisconnectedEvent,
            MqttPacketEvent,
            MqttParseErrorEvent,
        ) as subscription:
            ready.set()
            async for _emitter, event in subscription:
                try:
                    self._handle_event(event)
                except OSError:
                    logger.exception("MQTT session logger failed")
                    self._close_session("logger_failed")

    def _handle_event(self, event: Event) -> None:
        match event:
            case EndpointConnectedEvent():
                self._open_session(event)
            case EndpointDataReceivedEvent(data=data):
                self._write_raw_data(event, MqttDirection.DEVICE_TO_AWS, data)
            case AwsDataReceivedEvent(data=data):
                self._write_raw_data(event, MqttDirection.AWS_TO_DEVICE, data)
            case MqttPacketEvent(direction=direction, packet=packet):
                self._write_mqtt_packet(event, direction, packet)
            case MqttParseErrorEvent(direction=direction, error=error):
                self._write_mqtt_parse_error(event, direction, error)
            case AwsDisconnectedEvent(bytes_read=bytes_read, bytes_written=bytes_written):
                self._write_record(
                    {
                        "type": "aws_disconnected",
                        "timestamp": _format_event_timestamp(event),
                        "bytes_read": bytes_read,
                        "bytes_written": bytes_written,
                    }
                )
            case EndpointDisconnectedEvent(bytes_read=bytes_read, bytes_written=bytes_written):
                self._write_record(
                    {
                        "type": "session_ended",
                        "timestamp": _format_event_timestamp(event),
                        "bytes_read": bytes_read,
                        "bytes_written": bytes_written,
                    }
                )
                self._close_session("endpoint_disconnected")

    def _open_session(self, event: EndpointConnectedEvent) -> None:
        if self._file is not None:
            self._close_session("session_replaced")

        self.config.directory.mkdir(parents=True, exist_ok=True)
        self._session_index += 1
        self._session_path = self.config.directory / _session_filename(
            event,
            self._session_index,
        )
        self._file = self._session_path.open("x", encoding="utf-8")

        record: dict[str, object] = {
            "type": "session_started",
            "timestamp": _format_event_timestamp(event),
            "peer": {
                "host": event.host,
                "port": event.port,
            },
        }
        if event.tls is not None:
            record["tls"] = asdict(event.tls)

        self._write_record(record)

    def _close_session(self, reason: str) -> None:
        if self._file is None:
            return

        self._write_record(
            {
                "type": "session_log_closed",
                "reason": reason,
            }
        )
        self._file.close()
        self._file = None
        self._session_path = None

    def _write_raw_data(
        self,
        event: Event,
        direction: MqttDirection,
        data: bytes,
    ) -> None:
        self._write_record(
            {
                "type": "raw_data",
                "timestamp": _format_event_timestamp(event),
                "direction": direction.value,
                "size": len(data),
                "data_base64": _base64(data),
            }
        )

    def _write_mqtt_packet(
        self,
        event: Event,
        direction: MqttDirection,
        packet: MqttPacket,
    ) -> None:
        record: dict[str, object] = {
            "type": "mqtt_packet",
            "timestamp": _format_event_timestamp(event),
            "direction": direction.value,
            "packet_type": packet.__class__.__name__,
            "packet": repr(packet),
        }
        if isinstance(packet, PublishPacket):
            record.update(
                {
                    "topic": packet.topic,
                    "qos": int(packet.qos),
                    "dup": packet.dup,
                    "retain": packet.retain,
                    "payload_size": len(packet.payload),
                    "payload_base64": _base64(packet.payload),
                }
            )

        self._write_record(record)

    def _write_mqtt_parse_error(
        self,
        event: Event,
        direction: MqttDirection,
        error: str,
    ) -> None:
        self._write_record(
            {
                "type": "mqtt_parse_error",
                "timestamp": _format_event_timestamp(event),
                "direction": direction.value,
                "error": error,
            }
        )

    def _write_record(self, record: Mapping[str, object]) -> None:
        if self._file is None:
            return

        self._file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        self._file.write("\n")
        self._file.flush()


class MqttObserver:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._device_to_aws_parser = _MqttTrafficParser(
            event_bus,
            self,
            MqttDirection.DEVICE_TO_AWS,
        )
        self._aws_to_device_parser = _MqttTrafficParser(
            event_bus,
            self,
            MqttDirection.AWS_TO_DEVICE,
        )
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return

        ready = asyncio.Event()
        self._task = asyncio.create_task(self._run(ready))
        await ready.wait()

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return

        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self._device_to_aws_parser.reset()
        self._aws_to_device_parser.reset()

    async def _run(self, ready: asyncio.Event) -> None:
        async with self.event_bus.subscribe(
            EndpointDataReceivedEvent,
            EndpointDisconnectedEvent,
            AwsDataReceivedEvent,
            AwsDisconnectedEvent,
        ) as subscription:
            ready.set()
            async for _emitter, event in subscription:
                match event:
                    case EndpointDataReceivedEvent(data=data):
                        await self._device_to_aws_parser.feed(data)
                    case EndpointDisconnectedEvent():
                        self._device_to_aws_parser.reset()
                    case AwsDataReceivedEvent(data=data):
                        await self._aws_to_device_parser.feed(data)
                    case AwsDisconnectedEvent():
                        self._aws_to_device_parser.reset()


class ShadowMirror:
    def __init__(self, event_bus: EventBus, shadow: DeviceShadow) -> None:
        self.event_bus = event_bus
        self.shadow = shadow
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return

        ready = asyncio.Event()
        self._task = asyncio.create_task(self._run(ready))
        await ready.wait()

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return

        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self, ready: asyncio.Event) -> None:
        async with self.event_bus.subscribe(MqttPacketEvent) as subscription:
            ready.set()
            async for emitter, event in subscription:
                if isinstance(event, MqttPacketEvent):
                    await self._handle_mqtt_packet(emitter, event)

    async def _handle_mqtt_packet(self, emitter: object, event: MqttPacketEvent) -> None:
        packet = event.packet
        if not isinstance(packet, PublishPacket):
            return

        logger.debug(
            "Shadow mirror observed MQTT publish from %r on %s",
            emitter,
            packet.topic,
        )

        shadow_topic = parse_shadow_topic(packet.topic)
        if shadow_topic is None:
            return

        if event.direction is not MqttDirection.AWS_TO_DEVICE:
            return

        if shadow_topic.lifecycle is ShadowLifecycle.REJECTED:
            logger.debug("Shadow mirror observed rejected shadow response on %s", packet.topic)
            return
        if shadow_topic.lifecycle is None:
            return

        try:
            document = decode_shadow_payload(packet.payload)
            changed = self._apply_shadow_document(shadow_topic, document)
        except DeviceShadowError as exc:
            logger.warning("Ignoring invalid shadow document on %s: %s", packet.topic, exc)
            return

        if changed:
            await self.event_bus.publish(self, DeviceDataUpdatedEvent())

    def _apply_shadow_document(
        self,
        topic: ShadowTopic,
        document: Mapping[str, object],
    ) -> bool:
        match topic.operation, topic.lifecycle:
            case ShadowOperation.GET, ShadowLifecycle.ACCEPTED:
                self.shadow.replace(document)
                return True
            case ShadowOperation.UPDATE, ShadowLifecycle.ACCEPTED:
                self.shadow.apply_remote_update(document)
                return True
            case ShadowOperation.UPDATE, ShadowLifecycle.DOCUMENTS:
                self.shadow.replace(read_current_shadow_document(document))
                return True
            case ShadowOperation.UPDATE, ShadowLifecycle.DELTA:
                self.shadow.apply_remote_delta(document)
                return True
            case ShadowOperation.DELETE, ShadowLifecycle.ACCEPTED:
                self.shadow.apply_remote_delete(document)
                return True

        return False


class DataTopicKind(StrEnum):
    CONFIGURATION = "configuration"
    HISTORICAL_ERRORS = "historical_errors"
    HISTORICAL_TOTALS = "historical_totals"


@dataclass(frozen=True, slots=True)
class DataTopic:
    kind: DataTopicKind
    device_family: str
    device_model: str


class DataMirror:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.configuration_data = DeviceConfigurationData()
        self.historical_data = DeviceHistoricalData()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return

        ready = asyncio.Event()
        self._task = asyncio.create_task(self._run(ready))
        await ready.wait()

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return

        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self, ready: asyncio.Event) -> None:
        async with self.event_bus.subscribe(MqttPacketEvent) as subscription:
            ready.set()
            async for emitter, event in subscription:
                if isinstance(event, MqttPacketEvent):
                    await self._handle_mqtt_packet(emitter, event)

    async def _handle_mqtt_packet(self, emitter: object, event: MqttPacketEvent) -> None:
        packet = event.packet
        if not isinstance(packet, PublishPacket):
            return

        logger.debug(
            "Data mirror observed MQTT publish from %r on %s",
            emitter,
            packet.topic,
        )

        if event.direction is not MqttDirection.DEVICE_TO_AWS:
            return

        data_topic = _parse_data_topic(packet.topic)
        if data_topic is None:
            return

        try:
            payload = _decode_data_payload(packet)
        except DataMirrorError as exc:
            logger.warning("Ignoring invalid data payload on %s: %s", packet.topic, exc)
            return

        match data_topic.kind:
            case DataTopicKind.CONFIGURATION:
                self.configuration_data.fields.update(payload)
            case DataTopicKind.HISTORICAL_ERRORS:
                self.historical_data.errors.append(dict(payload))
            case DataTopicKind.HISTORICAL_TOTALS:
                self.historical_data.totals.update(payload)

        await self.event_bus.publish(self, DeviceDataUpdatedEvent())


class _MqttTrafficParser:
    def __init__(
        self,
        event_bus: EventBus,
        emitter: object,
        direction: MqttDirection,
    ) -> None:
        self._event_bus = event_bus
        self._emitter = emitter
        self._direction = direction
        self._buffer = b""

    async def feed(self, data: bytes) -> None:
        self._buffer += data
        try:
            packets, self._buffer = parse_packets(self._buffer)
        except MqttParseError as exc:
            logger.warning("MQTT %s parse error: %s", self._direction, exc)
            self._buffer = b""
            await self._event_bus.publish(
                self._emitter,
                MqttParseErrorEvent(direction=self._direction, error=str(exc)),
            )
            return

        for packet in packets:
            logger.debug("MQTT %s: %r", self._direction, packet)
            await self._event_bus.publish(
                self._emitter,
                MqttPacketEvent(direction=self._direction, packet=packet),
            )

    def reset(self) -> None:
        if self._buffer:
            logger.debug(
                "MQTT %s: discarding %d buffered byte(s)",
                self._direction,
                len(self._buffer),
            )
            self._buffer = b""


def _parse_data_topic(topic: str) -> DataTopic | None:
    parts = topic.split("/")
    if len(parts) < 4 or parts[0] != "data":
        return None

    match parts:
        case ["data", "configuration", device_family, device_model]:
            return DataTopic(
                kind=DataTopicKind.CONFIGURATION,
                device_family=device_family,
                device_model=device_model,
            )
        case ["data", "historical", device_family, device_model, "errors"]:
            return DataTopic(
                kind=DataTopicKind.HISTORICAL_ERRORS,
                device_family=device_family,
                device_model=device_model,
            )
        case ["data", "historical", device_family, device_model, "totals"]:
            return DataTopic(
                kind=DataTopicKind.HISTORICAL_TOTALS,
                device_family=device_family,
                device_model=device_model,
            )

    return None


def _decode_data_payload(packet: PublishPacket) -> Mapping[str, object]:
    try:
        document = json.loads(packet.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataMirrorError(f"payload must be a valid JSON object: {exc}") from exc

    if not isinstance(document, dict):
        raise DataMirrorError("payload must be a JSON object")
    for key in document:
        if not isinstance(key, str):
            raise DataMirrorError("payload object keys must be strings")

    return cast(Mapping[str, object], document)


def _session_filename(event: EndpointConnectedEvent, session_index: int) -> str:
    timestamp = event.timestamp.strftime("%Y%m%dT%H%M%S%f")
    host = _sanitize_filename_part(event.host)
    return f"{timestamp}_{session_index:04d}_{host}_{event.port}.jsonl"


def _sanitize_filename_part(value: str) -> str:
    sanitized = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in value
    )
    return sanitized or "unknown"


def _format_event_timestamp(event: Event) -> str:
    return event.timestamp.isoformat()


def _base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


__all__ = [
    "Bridge",
    "DataMirror",
    "MqttDirection",
    "MqttObserver",
    "MqttPacketEvent",
    "MqttParseErrorEvent",
    "MqttSessionLogger",
    "ShadowMirror",
]
