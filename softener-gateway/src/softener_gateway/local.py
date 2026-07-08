from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, cast

from softener_gateway.config import GatewayConfig
from softener_gateway.control import DeviceNotConnectedError
from softener_gateway.device.data import DeviceConfigurationData, DeviceHistoricalData
from softener_gateway.device.shadow import (
    DeviceShadow,
    DeviceShadowError,
    ShadowDocumentError,
    ShadowLifecycle,
    ShadowOperation,
    ShadowTopic,
    ShadowVersionConflictError,
    build_shadow_topic,
    decode_shadow_payload,
    parse_shadow_topic,
)
from softener_gateway.endpoint import (
    Endpoint,
    EndpointConnectedEvent,
    EndpointDataReceivedEvent,
    EndpointDisconnectedEvent,
)
from softener_gateway.events import EventBus
from softener_gateway.mapper import (
    Device,
    DeviceCommandMapper,
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
from softener_gateway.mqtt_protocol import (
    ConnAckPacket,
    ConnectPacket,
    ConnectReturnCode,
    DisconnectPacket,
    MqttPacket,
    MqttParseError,
    PingReqPacket,
    PingRespPacket,
    PubAckPacket,
    PublishPacket,
    QoS,
    SubAckPacket,
    SubAckReturnCode,
    SubscribePacket,
    UnsubAckPacket,
    UnsubscribePacket,
    build_packet,
    parse_packets,
)

logger = logging.getLogger(__name__)
DATA_ACQUISITION_WAKE_INTERVAL_SECONDS = 5.0
GET_ALL_DATA_REQUEST_INTERVAL_SECONDS = 60.0
APP_ACTIVE_RETRY_INTERVAL_SECONDS = 15.0
APP_ACTIVE_TIMEOUT_MINUTES = 5
APP_ACTIVE_REFRESH_INTERVAL_SECONDS = APP_ACTIVE_TIMEOUT_MINUTES * 60.0 * 0.9


class LocalController:
    def __init__(
        self,
        config: GatewayConfig,
        event_bus: EventBus,
        endpoint: Endpoint,
        shadow: DeviceShadow,
        device: Device,
        mapper: DeviceMapper,
        command_mapper: DeviceCommandMapper,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.endpoint = endpoint
        self.shadow = shadow
        self.device = device
        self.mapper = mapper
        self.command_mapper = command_mapper
        self.configuration_data = DeviceConfigurationData()
        self.historical_data = DeviceHistoricalData()
        self._mqtt_adapter = MqttAdapter(
            event_bus,
            endpoint,
            shadow,
            self.configuration_data,
            self.historical_data,
        )
        self._device_online = False
        self._device_projector_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        logger.info("Local mode selected")
        await self._start_device_projector()
        await self._mqtt_adapter.start()
        try:
            while True:
                await asyncio.sleep(0)
        finally:
            await self._mqtt_adapter.stop()
            await self._stop_device_projector()

    async def set_hardness(self, value: float) -> None:
        await self._publish_control_request(self.command_mapper.set_hardness(value))

    async def set_regen_time(self, value: str) -> None:
        await self._publish_control_request(self.command_mapper.set_regen_time(value))

    async def set_salt_type(self, value: SaltType) -> None:
        await self._publish_control_request(self.command_mapper.set_salt_type(value))

    async def set_salt_level(self, value: float) -> None:
        await self._publish_control_request(self.command_mapper.set_salt_level(value))

    async def set_flow_alert_min_rate(self, value: float) -> None:
        await self._publish_control_request(
            self.command_mapper.set_flow_alert_min_rate(value)
        )

    async def set_flow_alert_duration(self, value: float) -> None:
        await self._publish_control_request(
            self.command_mapper.set_flow_alert_duration(value)
        )

    async def set_volume_unit(self, value: VolumeUnit) -> None:
        await self._publish_control_request(self.command_mapper.set_volume_unit(value))

    async def set_weight_unit(self, value: WeightUnit) -> None:
        await self._publish_control_request(self.command_mapper.set_weight_unit(value))

    async def set_hardness_unit(self, value: HardnessUnit) -> None:
        await self._publish_control_request(self.command_mapper.set_hardness_unit(value))

    async def set_date_format(self, value: DateFormat) -> None:
        await self._publish_control_request(self.command_mapper.set_date_format(value))

    async def set_time_format(self, value: TimeFormat) -> None:
        await self._publish_control_request(self.command_mapper.set_time_format(value))

    async def set_aux_output_mode(self, value: AuxOutputMode) -> None:
        await self._publish_control_request(self.command_mapper.set_aux_output_mode(value))

    async def set_aux_chemical_feed_amount(self, value: float) -> None:
        await self._publish_control_request(
            self.command_mapper.set_aux_chemical_feed_amount(value)
        )

    async def set_regeneration_backwash(self, value: int) -> None:
        await self._publish_control_request(
            self.command_mapper.set_regeneration_backwash(value)
        )

    async def set_regeneration_fast_rinse(self, value: int) -> None:
        await self._publish_control_request(
            self.command_mapper.set_regeneration_fast_rinse(value)
        )

    async def set_regeneration_second_backwash(self, value: int) -> None:
        await self._publish_control_request(
            self.command_mapper.set_regeneration_second_backwash(value)
        )

    async def set_regeneration_rinse_type(self, value: int) -> None:
        await self._publish_control_request(
            self.command_mapper.set_regeneration_rinse_type(value)
        )

    async def set_feature_97_percent(self, value: bool) -> None:
        await self._publish_control_request(
            self.command_mapper.set_feature_97_percent(value)
        )

    async def set_efficiency_mode(self, value: EfficiencyMode) -> None:
        await self._publish_control_request(self.command_mapper.set_efficiency_mode(value))

    async def set_max_days_between_regenerations(
        self,
        value: int | Literal["auto"],
    ) -> None:
        await self._publish_control_request(
            self.command_mapper.set_max_days_between_regenerations(value)
        )

    async def start_regeneration(self) -> None:
        await self._publish_control_request(self.command_mapper.start_regeneration())

    async def _publish_control_request(self, request: Mapping[str, object]) -> None:
        await self._mqtt_adapter.publish_control_delta(request)

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
                    if emitter is not self._mqtt_adapter:
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
                configuration_data=self.configuration_data,
                historical_data=self.historical_data,
                unit_system=self.config.unit_system,
                online=self._device_online,
            ),
        )


class MqttAdapter:
    def __init__(
        self,
        event_bus: EventBus,
        endpoint: Endpoint,
        shadow: DeviceShadow,
        configuration_data: DeviceConfigurationData,
        historical_data: DeviceHistoricalData,
    ) -> None:
        self.event_bus = event_bus
        self.endpoint = endpoint
        self.shadow = shadow
        self.configuration_data = configuration_data
        self.historical_data = historical_data
        self._task: asyncio.Task[None] | None = None
        self._data_acquisition_task: asyncio.Task[None] | None = None
        self._shadow_lock = asyncio.Lock()
        self._app_active = False
        self._app_active_token = 0
        self._thing_name: str | None = None
        self._buffer = b""
        self._subscriptions: dict[str, QoS] = {}

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

        await self._reset_session()

    async def _run(self, ready: asyncio.Event) -> None:
        try:
            async with self.event_bus.subscribe(
                EndpointDataReceivedEvent,
                EndpointDisconnectedEvent,
            ) as subscription:
                ready.set()
                async for emitter, event in subscription:
                    if emitter is not self.endpoint:
                        continue

                    match event:
                        case EndpointDataReceivedEvent(data=data):
                            await self._handle_data(data)
                        case EndpointDisconnectedEvent():
                            await self._reset_session()
        finally:
            await self._stop_data_acquisition()

    async def _handle_data(self, data: bytes) -> None:
        self._buffer += data
        try:
            packets, self._buffer = parse_packets(self._buffer)
        except MqttParseError:
            logger.exception("Local MQTT parse error; closing endpoint connection")
            await self._reset_session()
            await self.endpoint.close()
            return

        for packet in packets:
            logger.debug("Local MQTT received: %r", packet)
            match packet:
                case ConnectPacket():
                    await self._handle_connect(packet)
                case SubscribePacket():
                    await self._handle_subscribe(packet)
                case UnsubscribePacket():
                    await self._handle_unsubscribe(packet)
                case PublishPacket():
                    await self._handle_publish(packet)
                case PingReqPacket():
                    await self._write(PingRespPacket())
                case DisconnectPacket():
                    await self._reset_session()
                    await self.endpoint.close()
                case PubAckPacket():
                    logger.debug(
                        "Local MQTT received PUBACK for packet %d",
                        packet.packet_identifier,
                    )
                case _:
                    logger.debug("Ignoring unsupported local MQTT packet: %r", packet)

    @property
    def thing_name(self) -> str | None:
        return self._thing_name

    async def publish_control_delta(self, request: Mapping[str, object]) -> None:
        thing_name = self._thing_name
        if thing_name is None:
            raise DeviceNotConnectedError("device is not connected")
        if not any(_is_shadow_delta_subscription(topic) for topic in self._subscriptions):
            raise DeviceNotConnectedError("device is not subscribed to shadow delta")

        logger.info(
            "DEVICE_CONTROL send shadow delta: thing_name=%s request=%s",
            thing_name,
            request,
        )
        await self._publish_control_shadow_response(
            thing_name,
            ShadowOperation.UPDATE,
            ShadowLifecycle.DELTA,
            {"state": {"Request": dict(request)}},
        )

    async def _handle_connect(self, packet: ConnectPacket) -> None:
        await self._reset_session()
        self._thing_name = packet.client_id
        await self._write(
            ConnAckPacket(
                session_present=False,
                return_code=ConnectReturnCode.ACCEPTED,
            )
        )

    async def _handle_subscribe(self, packet: SubscribePacket) -> None:
        return_codes: list[SubAckReturnCode] = []
        accepted_delta_subscription: ShadowTopic | None = None
        for subscription in packet.subscriptions:
            if subscription.qos is QoS.AT_MOST_ONCE:
                self._subscriptions[subscription.topic_filter] = QoS.AT_MOST_ONCE
                return_codes.append(SubAckReturnCode.MAXIMUM_QOS_0)
                accepted_delta_subscription = accepted_delta_subscription or (
                    _parse_shadow_delta_subscription(subscription.topic_filter)
                )
            elif subscription.qos is QoS.AT_LEAST_ONCE:
                self._subscriptions[subscription.topic_filter] = QoS.AT_LEAST_ONCE
                return_codes.append(SubAckReturnCode.MAXIMUM_QOS_1)
                accepted_delta_subscription = accepted_delta_subscription or (
                    _parse_shadow_delta_subscription(subscription.topic_filter)
                )
            else:
                return_codes.append(SubAckReturnCode.FAILURE)

        await self._write(
            SubAckPacket(
                packet_identifier=packet.packet_identifier,
                return_codes=tuple(return_codes),
            )
        )
        if accepted_delta_subscription:
            self._thing_name = accepted_delta_subscription.thing_name
            self._start_data_acquisition(accepted_delta_subscription.thing_name)

    async def _handle_unsubscribe(self, packet: UnsubscribePacket) -> None:
        for topic_filter in packet.topic_filters:
            self._subscriptions.pop(topic_filter, None)

        await self._write(UnsubAckPacket(packet_identifier=packet.packet_identifier))
        if not any(_is_shadow_delta_subscription(topic) for topic in self._subscriptions):
            await self._stop_data_acquisition()

    async def _handle_publish(self, packet: PublishPacket) -> None:
        if packet.qos is QoS.AT_LEAST_ONCE:
            if packet.packet_identifier is None:
                logger.warning(
                    "Closing endpoint after malformed QoS 1 PUBLISH without packet identifier"
                )
                await self._reset_session()
                await self.endpoint.close()
                return
            await self._write(PubAckPacket(packet.packet_identifier))

        shadow_topic = parse_shadow_topic(packet.topic)
        if shadow_topic is not None:
            await self._handle_shadow_publish(packet)
            return

        data_topic = _parse_data_topic(packet.topic)
        if data_topic is not None:
            await self._handle_data_publish(data_topic, packet)

    async def _handle_shadow_publish(self, packet: PublishPacket) -> None:
        topic = parse_shadow_topic(packet.topic)
        if topic is None or topic.lifecycle is not None:
            return
        if topic.shadow_name is not None:
            logger.debug("Ignoring named shadow topic in local mode: %s", packet.topic)
            return

        changed = False
        async with self._shadow_lock:
            try:
                request = decode_shadow_payload(packet.payload)
                match topic.operation:
                    case ShadowOperation.GET:
                        response = self.shadow.get(client_token=_client_token(request))
                        await self._publish_shadow_response(
                            topic.thing_name,
                            ShadowOperation.GET,
                            ShadowLifecycle.ACCEPTED,
                            response,
                        )
                    case ShadowOperation.UPDATE:
                        result = self.shadow.update(request)
                        changed = True
                        self._observe_app_active(request)
                        await self._publish_shadow_response(
                            topic.thing_name,
                            ShadowOperation.UPDATE,
                            ShadowLifecycle.ACCEPTED,
                            result.accepted,
                        )
                        if result.delta is not None:
                            await self._publish_shadow_response(
                                topic.thing_name,
                                ShadowOperation.UPDATE,
                                ShadowLifecycle.DELTA,
                                result.delta,
                            )
                    case ShadowOperation.DELETE:
                        response = self.shadow.delete(client_token=_client_token(request))
                        changed = True
                        await self._publish_shadow_response(
                            topic.thing_name,
                            ShadowOperation.DELETE,
                            ShadowLifecycle.ACCEPTED,
                            response,
                        )
            except ShadowVersionConflictError as exc:
                await self._publish_shadow_rejected(
                    packet,
                    topic.thing_name,
                    topic.operation,
                    code=409,
                    message=str(exc),
                )
            except DeviceShadowError as exc:
                await self._publish_shadow_rejected(
                    packet,
                    topic.thing_name,
                    topic.operation,
                    code=400,
                    message=str(exc),
                )

        if changed:
            await self.event_bus.publish(self, DeviceDataUpdatedEvent())

    async def _publish_data_acquisition_shadow_response(
        self,
        thing_name: str,
        operation: ShadowOperation,
        lifecycle: ShadowLifecycle,
        document: Mapping[str, object],
    ) -> None:
        async with self._shadow_lock:
            await self._publish_shadow_response(
                thing_name,
                operation,
                lifecycle,
                document,
            )

    async def _publish_control_shadow_response(
        self,
        thing_name: str,
        operation: ShadowOperation,
        lifecycle: ShadowLifecycle,
        document: Mapping[str, object],
    ) -> None:
        async with self._shadow_lock:
            await self._publish_shadow_response(
                thing_name,
                operation,
                lifecycle,
                document,
            )

    async def _publish_shadow_response(
        self,
        thing_name: str,
        operation: ShadowOperation,
        lifecycle: ShadowLifecycle,
        document: Mapping[str, object],
    ) -> None:
        topic = build_shadow_topic(
            thing_name,
            operation,
            lifecycle=lifecycle,
        )
        await self._publish_to_device(topic, _encode_json(document))

    async def _publish_shadow_rejected(
        self,
        packet: PublishPacket,
        thing_name: str,
        operation: ShadowOperation,
        *,
        code: int,
        message: str,
    ) -> None:
        document: dict[str, object] = {
            "code": code,
            "message": message,
        }
        client_token = _try_read_client_token(packet.payload)
        if client_token is not None:
            document["clientToken"] = client_token

        await self._publish_shadow_response(
            thing_name,
            operation,
            ShadowLifecycle.REJECTED,
            document,
        )

    async def _handle_data_publish(self, topic: DataTopic, packet: PublishPacket) -> None:
        try:
            payload = _decode_data_payload(packet.payload)
        except ValueError as exc:
            logger.warning("Ignoring invalid data payload on %s: %s", packet.topic, exc)
            return

        match topic.kind:
            case DataTopicKind.CONFIGURATION:
                self.configuration_data.fields.update(_without_thing_name(payload))
            case DataTopicKind.HISTORICAL_ERRORS:
                self.historical_data.errors.append(dict(_without_thing_name(payload)))
            case DataTopicKind.HISTORICAL_TOTALS:
                self.historical_data.totals.update(_without_thing_name(payload))

        await self.event_bus.publish(self, DeviceDataUpdatedEvent())

    async def _publish_to_device(self, topic: str, payload: bytes) -> None:
        if not self._is_subscribed(topic):
            return

        await self._write(PublishPacket(topic=topic, payload=payload))

    async def _write(self, packet: MqttPacket) -> None:
        await self.endpoint.write(build_packet(packet))

    def _is_subscribed(self, topic: str) -> bool:
        return any(
            _topic_matches_filter(topic_filter, topic)
            for topic_filter in self._subscriptions
        )

    def _start_data_acquisition(self, thing_name: str) -> None:
        if self._data_acquisition_task is not None:
            return

        self._data_acquisition_task = asyncio.create_task(
            self._run_data_acquisition(thing_name)
        )

    async def _stop_data_acquisition(self) -> None:
        task = self._data_acquisition_task
        if task is None:
            return

        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

        if self._data_acquisition_task is task:
            self._data_acquisition_task = None

    async def _run_data_acquisition(self, thing_name: str) -> None:
        last_app_active_request: float | None = None
        last_get_all_data_request: float | None = None
        while True:
            await asyncio.sleep(DATA_ACQUISITION_WAKE_INTERVAL_SECONDS)
            now = time.monotonic()
            if not self._app_active:
                if (
                    last_app_active_request is None
                    or now - last_app_active_request
                    > APP_ACTIVE_RETRY_INTERVAL_SECONDS
                ):
                    await self._publish_app_active_delta(thing_name)
                    last_app_active_request = now
                continue

            if (
                last_app_active_request is None
                or now - last_app_active_request
                > APP_ACTIVE_REFRESH_INTERVAL_SECONDS
            ):
                await self._publish_app_active_delta(thing_name)
                last_app_active_request = now
                continue

            if (
                last_get_all_data_request is None
                or now - last_get_all_data_request
                > GET_ALL_DATA_REQUEST_INTERVAL_SECONDS
            ):
                await self._publish_get_all_data_delta(thing_name)
                last_get_all_data_request = now

    async def _publish_get_all_data_delta(self, thing_name: str) -> None:
        logger.info("DATA_ACQ send get_all_data: thing_name=%s", thing_name)
        await self._publish_data_acquisition_shadow_response(
            thing_name,
            ShadowOperation.UPDATE,
            ShadowLifecycle.DELTA,
            {"state": {"Request": {"get_all_data": 1}}},
        )

    async def _publish_app_active_delta(self, thing_name: str) -> None:
        token = self._next_app_active_token()
        logger.info(
            "APP_ACTIVE send: thing_name=%s token=%d timeout_minutes=%d",
            thing_name,
            token,
            APP_ACTIVE_TIMEOUT_MINUTES,
        )
        await self._publish_data_acquisition_shadow_response(
            thing_name,
            ShadowOperation.UPDATE,
            ShadowLifecycle.DELTA,
            {
                "state": {
                    "Request": {
                        "app_active": token,
                        "app_active_timeout": APP_ACTIVE_TIMEOUT_MINUTES,
                        "service_active": token,
                    },
                },
            },
        )

    def _next_app_active_token(self) -> int:
        self._app_active_token = self._app_active_token % 65_535 + 1
        return self._app_active_token

    def _observe_app_active(self, document: Mapping[str, object]) -> None:
        state = _optional_mapping(document.get("state"))
        if state is None:
            return

        reported = _optional_mapping(state.get("reported"))
        if reported is None:
            return

        request = _optional_mapping(reported.get("Request"))
        if request is not None:
            app_active = request.get("app_active")
            service_active = request.get("service_active")
            if (
                _is_integer(app_active)
                and _is_integer(service_active)
                and app_active == service_active
            ):
                self._app_active = app_active != 0

        status = _optional_mapping(reported.get("Status"))
        if status is not None and status.get("app_active") == 0:
            self._app_active = False

    async def _reset_session(self) -> None:
        self._buffer = b""
        self._subscriptions.clear()
        self._app_active = False
        self._thing_name = None
        await self._stop_data_acquisition()


class DataTopicKind(StrEnum):
    CONFIGURATION = "configuration"
    HISTORICAL_ERRORS = "historical_errors"
    HISTORICAL_TOTALS = "historical_totals"


@dataclass(frozen=True, slots=True)
class DataTopic:
    kind: DataTopicKind


def _parse_data_topic(topic: str) -> DataTopic | None:
    parts = topic.split("/")
    match parts:
        case ["data", "configuration", _, _]:
            return DataTopic(DataTopicKind.CONFIGURATION)
        case ["data", "historical", _, _, "errors"]:
            return DataTopic(DataTopicKind.HISTORICAL_ERRORS)
        case ["data", "historical", _, _, "totals"]:
            return DataTopic(DataTopicKind.HISTORICAL_TOTALS)

    return None


def _decode_data_payload(payload: bytes) -> Mapping[str, object]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"payload must be a valid JSON object: {exc}") from exc

    if not isinstance(document, dict):
        raise ValueError("payload must be a JSON object")
    for key in document:
        if not isinstance(key, str):
            raise ValueError("payload object keys must be strings")

    return cast(Mapping[str, object], document)


def _without_thing_name(payload: Mapping[str, object]) -> Mapping[str, object]:
    return {key: value for key, value in payload.items() if key != "thing_name"}


def _client_token(document: Mapping[str, object]) -> str | None:
    value = document.get("clientToken")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ShadowDocumentError("clientToken must be a string")

    return value


def _try_read_client_token(payload: bytes) -> str | None:
    try:
        document = decode_shadow_payload(payload)
        return _client_token(document)
    except DeviceShadowError:
        return None


def _encode_json(document: Mapping[str, object]) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None

    return cast(Mapping[str, object], value)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_shadow_delta_subscription(topic_filter: str) -> bool:
    return _parse_shadow_delta_subscription(topic_filter) is not None


def _parse_shadow_delta_subscription(topic_filter: str) -> ShadowTopic | None:
    topic = parse_shadow_topic(topic_filter)
    if (
        topic is not None
        and topic.shadow_name is None
        and topic.operation is ShadowOperation.UPDATE
        and topic.lifecycle is ShadowLifecycle.DELTA
    ):
        return topic

    return None


def _topic_matches_filter(topic_filter: str, topic: str) -> bool:
    filter_levels = topic_filter.split("/")
    topic_levels = topic.split("/")

    for index, filter_level in enumerate(filter_levels):
        if filter_level == "#":
            return index == len(filter_levels) - 1
        if index >= len(topic_levels):
            return False
        if filter_level == "+":
            continue
        if filter_level != topic_levels[index]:
            return False

    return len(topic_levels) == len(filter_levels)


__all__ = ["LocalController", "MqttAdapter"]
