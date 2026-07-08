import asyncio
import json
import logging
from contextlib import suppress
from pathlib import Path
from typing import cast

import pytest

import softener_gateway.bridge
from softener_gateway.aws import AwsDataReceivedEvent, AwsDisconnectedEvent
from softener_gateway.bridge import (
    Bridge,
    DataMirror,
    MqttDirection,
    MqttObserver,
    MqttPacketEvent,
    MqttParseErrorEvent,
    MqttSessionLogger,
    ShadowMirror,
)
from softener_gateway.config import AwsConfig, GatewayConfig, Mode, MqttSessionLogConfig
from softener_gateway.control import ReadOnlyModeError
from softener_gateway.device.shadow import DeviceShadow
from softener_gateway.endpoint import (
    Endpoint,
    EndpointConnectedEvent,
    EndpointDataReceivedEvent,
    EndpointDisconnectedEvent,
)
from softener_gateway.events import EventBus
from softener_gateway.mapper import Device, DeviceMapper
from softener_gateway.mqtt_protocol import (
    PingReqPacket,
    PingRespPacket,
    PublishPacket,
    build_packet,
)
from tests.test_aws import make_aws_config
from tests.test_endpoint import make_endpoint_config


class FakeBridgeEndpoint:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False
        self.close_count = 0

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def close(self) -> None:
        self.closed = True
        self.close_count += 1


async def wait_for_bridge_ready(event_bus: EventBus, created: list[object]) -> None:
    for _ in range(10):
        if created and event_bus.subscriber_count == 5:
            return

        await asyncio.sleep(0)

    raise AssertionError("bridge did not become ready")


def test_bridge_relays_data_between_endpoint_and_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_bridge_relays_data_between_endpoint_and_aws(monkeypatch))


async def _bridge_relays_data_between_endpoint_and_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []

    class FakeAwsConnection:
        def __init__(self, config: AwsConfig, event_bus: EventBus) -> None:
            self.config = config
            self.event_bus = event_bus
            self.connected = False
            self.closed = False
            self.writes: list[bytes] = []
            created.append(self)

        @property
        def is_connected(self) -> bool:
            return self.connected and not self.closed

        async def connect(self) -> None:
            self.connected = True
            self.closed = False

        async def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(softener_gateway.bridge, "AwsConnection", FakeAwsConnection)

    event_bus = EventBus()
    endpoint = FakeBridgeEndpoint()
    bridge = Bridge(
        GatewayConfig(
            mode=Mode.BRIDGE,
            endpoint=make_endpoint_config(),
            aws=make_aws_config(),
        ),
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        Device(),
        DeviceMapper(),
    )
    task = asyncio.create_task(bridge.run())

    try:
        await wait_for_bridge_ready(event_bus, created)
        aws = cast(FakeAwsConnection, created[0])

        await event_bus.publish(
            endpoint,
            EndpointConnectedEvent(host="192.0.2.10", port=1234),
        )
        await asyncio.sleep(0)

        assert aws.connected

        await event_bus.publish(
            endpoint,
            EndpointDataReceivedEvent(data=b"from-device"),
        )
        await asyncio.sleep(0)

        assert aws.writes == [b"from-device"]

        await event_bus.publish(aws, AwsDataReceivedEvent(data=b"from-aws"))
        await asyncio.sleep(0)

        assert endpoint.writes == [b"from-aws"]

        await event_bus.publish(
            endpoint,
            EndpointDisconnectedEvent(bytes_read=11, bytes_written=0),
        )
        await asyncio.sleep(0)

        assert aws.closed

        await event_bus.publish(
            aws,
            AwsDisconnectedEvent(bytes_read=8, bytes_written=11),
        )
        await asyncio.sleep(0)

        assert endpoint.closed
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def test_bridge_device_control_is_read_only() -> None:
    asyncio.run(_bridge_device_control_is_read_only())


async def _bridge_device_control_is_read_only() -> None:
    event_bus = EventBus()
    bridge = Bridge(
        GatewayConfig(
            mode=Mode.BRIDGE,
            endpoint=make_endpoint_config(),
            aws=make_aws_config(),
        ),
        event_bus,
        Endpoint(make_endpoint_config(), event_bus),
        DeviceShadow(),
        Device(),
        DeviceMapper(),
    )

    with pytest.raises(ReadOnlyModeError):
        await bridge.set_hardness(18)

    with pytest.raises(ReadOnlyModeError):
        await bridge.start_regeneration()


def test_bridge_closes_endpoint_when_aws_connect_fails(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.ERROR)
    asyncio.run(_bridge_closes_endpoint_when_aws_connect_fails(monkeypatch))

    assert "Failed to connect to AWS; closing endpoint connection" in caplog.messages


async def _bridge_closes_endpoint_when_aws_connect_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []

    class FailingAwsConnection:
        def __init__(self, config: AwsConfig, event_bus: EventBus) -> None:
            self.config = config
            self.event_bus = event_bus
            self.closed = False
            self.writes: list[bytes] = []
            created.append(self)

        @property
        def is_connected(self) -> bool:
            return False

        async def connect(self) -> None:
            raise OSError("connection refused")

        async def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(softener_gateway.bridge, "AwsConnection", FailingAwsConnection)

    event_bus = EventBus()
    endpoint = FakeBridgeEndpoint()
    bridge = Bridge(
        GatewayConfig(
            mode=Mode.BRIDGE,
            endpoint=make_endpoint_config(),
            aws=make_aws_config(),
        ),
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        Device(),
        DeviceMapper(),
    )
    task = asyncio.create_task(bridge.run())

    try:
        await wait_for_bridge_ready(event_bus, created)
        aws = cast(FailingAwsConnection, created[0])

        await event_bus.publish(
            endpoint,
            EndpointConnectedEvent(host="192.0.2.10", port=1234),
        )
        await asyncio.sleep(0)

        assert not task.done()
        assert aws.closed
        assert endpoint.closed

        await event_bus.publish(
            endpoint,
            EndpointDataReceivedEvent(data=b"queued-payload"),
        )
        await asyncio.sleep(0)

        assert aws.writes == []
        assert endpoint.close_count == 2
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def test_mqtt_observer_publishes_packet_events_and_logs_packets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="softener_gateway.bridge")

    asyncio.run(_publish_packet_events())

    assert "MQTT device -> AWS: PingReqPacket()" in caplog.messages
    assert "MQTT AWS -> device: PingRespPacket()" in caplog.messages


async def _publish_packet_events() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(MqttPacketEvent)
    observer = MqttObserver(event_bus)
    endpoint_emitter = object()
    aws_emitter = object()
    await observer.start()

    try:
        device_packet = build_packet(PingReqPacket())
        await event_bus.publish(
            endpoint_emitter,
            EndpointDataReceivedEvent(data=device_packet[:1]),
        )
        await asyncio.sleep(0)

        assert subscription._queue.empty()

        await event_bus.publish(
            endpoint_emitter,
            EndpointDataReceivedEvent(data=device_packet[1:]),
        )
        await asyncio.sleep(0)

        emitter, device_event = await anext(subscription)

        assert emitter is observer
        assert isinstance(device_event, MqttPacketEvent)
        assert device_event.direction is MqttDirection.DEVICE_TO_AWS
        assert device_event.packet == PingReqPacket()

        aws_packet = build_packet(PingRespPacket())
        await event_bus.publish(aws_emitter, AwsDataReceivedEvent(data=aws_packet))
        await asyncio.sleep(0)

        emitter, aws_event = await anext(subscription)

        assert emitter is observer
        assert isinstance(aws_event, MqttPacketEvent)
        assert aws_event.direction is MqttDirection.AWS_TO_DEVICE
        assert aws_event.packet == PingRespPacket()
    finally:
        await observer.stop()


def test_mqtt_observer_resets_buffer_on_disconnect() -> None:
    asyncio.run(_reset_buffer_on_disconnect())


async def _reset_buffer_on_disconnect() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(MqttPacketEvent)
    observer = MqttObserver(event_bus)
    endpoint_emitter = object()
    await observer.start()

    try:
        packet = build_packet(PingReqPacket())
        await event_bus.publish(
            endpoint_emitter,
            EndpointDataReceivedEvent(data=packet[:1]),
        )
        await asyncio.sleep(0)

        await event_bus.publish(
            endpoint_emitter,
            EndpointDisconnectedEvent(bytes_read=1, bytes_written=0),
        )
        await asyncio.sleep(0)

        await event_bus.publish(
            endpoint_emitter,
            EndpointDataReceivedEvent(data=packet[1:]),
        )
        await asyncio.sleep(0)

        assert subscription._queue.empty()
    finally:
        await observer.stop()


def test_mqtt_observer_publishes_parse_error_event() -> None:
    asyncio.run(_publish_parse_error_event())


async def _publish_parse_error_event() -> None:
    event_bus = EventBus()
    subscription = event_bus.subscribe(MqttParseErrorEvent)
    observer = MqttObserver(event_bus)
    aws_emitter = object()
    await observer.start()

    try:
        await event_bus.publish(
            aws_emitter,
            AwsDataReceivedEvent(data=b"\x30\x80\x80\x80\x80"),
        )
        await asyncio.sleep(0)

        emitter, event = await anext(subscription)

        assert emitter is observer
        assert isinstance(event, MqttParseErrorEvent)
        assert event.direction is MqttDirection.AWS_TO_DEVICE
        assert event.error == "Malformed MQTT Remaining Length"

        await event_bus.publish(
            aws_emitter,
            AwsDisconnectedEvent(bytes_read=0, bytes_written=0),
        )
        await asyncio.sleep(0)
    finally:
        await observer.stop()


def test_mqtt_session_logger_writes_jsonl_session(tmp_path: Path) -> None:
    asyncio.run(_write_jsonl_session(tmp_path))


async def _write_jsonl_session(tmp_path: Path) -> None:
    event_bus = EventBus()
    session_logger = MqttSessionLogger(
        event_bus,
        MqttSessionLogConfig(directory=tmp_path),
    )
    endpoint_emitter = object()
    aws_emitter = object()
    await session_logger.start()

    try:
        await event_bus.publish(
            endpoint_emitter,
            EndpointConnectedEvent(host="192.0.2.10", port=1234),
        )
        await event_bus.publish(
            endpoint_emitter,
            EndpointDataReceivedEvent(data=build_packet(PingReqPacket())),
        )
        await event_bus.publish(
            object(),
            MqttPacketEvent(
                direction=MqttDirection.DEVICE_TO_AWS,
                packet=PingReqPacket(),
            ),
        )
        await event_bus.publish(
            aws_emitter,
            AwsDataReceivedEvent(data=build_packet(PingRespPacket())),
        )
        await event_bus.publish(
            object(),
            MqttPacketEvent(
                direction=MqttDirection.AWS_TO_DEVICE,
                packet=PingRespPacket(),
            ),
        )
        await event_bus.publish(
            endpoint_emitter,
            EndpointDisconnectedEvent(bytes_read=2, bytes_written=2),
        )
        await asyncio.sleep(0)
    finally:
        await session_logger.stop()

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1

    records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]

    assert [record["type"] for record in records] == [
        "session_started",
        "raw_data",
        "mqtt_packet",
        "raw_data",
        "mqtt_packet",
        "session_ended",
        "session_log_closed",
    ]
    assert records[0]["peer"] == {"host": "192.0.2.10", "port": 1234}
    assert records[1]["direction"] == MqttDirection.DEVICE_TO_AWS.value
    assert records[2]["packet_type"] == "PingReqPacket"
    assert records[3]["direction"] == MqttDirection.AWS_TO_DEVICE.value
    assert records[4]["packet_type"] == "PingRespPacket"
    assert records[5]["bytes_read"] == 2
    assert records[5]["bytes_written"] == 2


def test_shadow_mirror_replaces_shadow_from_get_accepted() -> None:
    asyncio.run(_replace_shadow_from_get_accepted())


async def _replace_shadow_from_get_accepted() -> None:
    event_bus = EventBus()
    shadow = DeviceShadow()
    mirror = ShadowMirror(event_bus, shadow)
    await mirror.start()

    try:
        await publish_shadow_packet(
            event_bus,
            "$aws/things/softener/shadow/get/accepted",
            (
                b'{"state":{"desired":{"mode":"eco"},'
                b'"reported":{"mode":"eco","salt":50},'
                b'"delta":{"ignored":true}},"version":7,"timestamp":10}'
            ),
        )

        assert shadow.version == 7
        assert shadow.desired == {"mode": "eco"}
        assert shadow.reported == {"mode": "eco", "salt": 50}
    finally:
        await mirror.stop()


def test_shadow_mirror_applies_update_accepted() -> None:
    asyncio.run(_apply_update_accepted())


async def _apply_update_accepted() -> None:
    event_bus = EventBus()
    shadow = DeviceShadow()
    mirror = ShadowMirror(event_bus, shadow)
    await mirror.start()

    try:
        await publish_shadow_packet(
            event_bus,
            "$aws/things/softener/shadow/update/accepted",
            (
                b'{"state":{"reported":{"salt":{"level":42}}},'
                b'"metadata":{"reported":{"salt":{"level":{"timestamp":11}}}},'
                b'"version":8,"timestamp":11}'
            ),
        )

        assert shadow.version == 8
        assert shadow.reported == {"salt": {"level": 42}}
    finally:
        await mirror.stop()


def test_shadow_mirror_replaces_shadow_from_update_documents() -> None:
    asyncio.run(_replace_shadow_from_update_documents())


async def _replace_shadow_from_update_documents() -> None:
    event_bus = EventBus()
    shadow = DeviceShadow()
    shadow.apply_reported({"stale": True})
    mirror = ShadowMirror(event_bus, shadow)
    await mirror.start()

    try:
        await publish_shadow_packet(
            event_bus,
            "$aws/things/softener/shadow/update/documents",
            (
                b'{"previous":{"version":8},'
                b'"current":{"state":{"desired":{"mode":"eco"},'
                b'"reported":{"mode":"manual"}},"version":9},'
                b'"timestamp":12}'
            ),
        )

        assert shadow.version == 9
        assert shadow.desired == {"mode": "eco"}
        assert shadow.reported == {"mode": "manual"}
    finally:
        await mirror.stop()


def test_shadow_mirror_applies_delta_and_delete() -> None:
    asyncio.run(_apply_delta_and_delete())


async def _apply_delta_and_delete() -> None:
    event_bus = EventBus()
    shadow = DeviceShadow()
    mirror = ShadowMirror(event_bus, shadow)
    await mirror.start()

    try:
        await publish_shadow_packet(
            event_bus,
            "$aws/things/softener/shadow/update/delta",
            b'{"state":{"mode":"eco"},"metadata":{"mode":{"timestamp":13}},"version":10}',
        )

        assert shadow.version == 10
        assert shadow.desired == {"mode": "eco"}

        await publish_shadow_packet(
            event_bus,
            "$aws/things/softener/shadow/delete/accepted",
            b'{"version":11,"timestamp":14}',
        )

        assert shadow.version == 11
        assert shadow.desired == {}
        assert shadow.reported == {}
    finally:
        await mirror.stop()


def test_shadow_mirror_ignores_device_to_aws_shadow_requests() -> None:
    asyncio.run(_ignore_device_to_aws_shadow_requests())


async def _ignore_device_to_aws_shadow_requests() -> None:
    event_bus = EventBus()
    shadow = DeviceShadow()
    mirror = ShadowMirror(event_bus, shadow)
    await mirror.start()

    try:
        await publish_shadow_packet(
            event_bus,
            "$aws/things/softener/shadow/update",
            b'{"state":{"reported":{"mode":"eco"}},"version":1}',
            direction=MqttDirection.DEVICE_TO_AWS,
        )

        assert shadow.version == 0
        assert shadow.reported == {}
    finally:
        await mirror.stop()


def test_data_mirror_updates_configuration_data() -> None:
    asyncio.run(_update_configuration_data())


async def _update_configuration_data() -> None:
    event_bus = EventBus()
    mirror = DataMirror(event_bus)
    await mirror.start()

    try:
        await publish_data_packet(
            event_bus,
            "data/configuration/10/45",
            b'{"thing_name":"10_45_356489-Thing","salt_level_tenths":30}',
        )
        await publish_data_packet(
            event_bus,
            "data/configuration/10/45",
            b'{"salt_level_tenths":40,"regen_status_enum":2}',
        )

        assert mirror.configuration_data.fields == {
            "thing_name": "10_45_356489-Thing",
            "salt_level_tenths": 40,
            "regen_status_enum": 2,
        }
        assert mirror.historical_data.errors == []
        assert mirror.historical_data.totals == {}
    finally:
        await mirror.stop()


def test_data_mirror_updates_historical_data() -> None:
    asyncio.run(_update_historical_data())


async def _update_historical_data() -> None:
    event_bus = EventBus()
    mirror = DataMirror(event_bus)
    await mirror.start()

    try:
        await publish_data_packet(
            event_bus,
            "data/historical/10/45/errors",
            b'{"thing_name":"10_45_356489-Thing","error_type":10005,"status":0}',
        )
        await publish_data_packet(
            event_bus,
            "data/historical/10/45/errors",
            b'{"thing_name":"10_45_356489-Thing","error_type":10006,"status":0}',
        )
        await publish_data_packet(
            event_bus,
            "data/historical/10/45/totals",
            b'{"thing_name":"10_45_356489-Thing","total_outlet_water_gals":72060}',
        )
        await publish_data_packet(
            event_bus,
            "data/historical/10/45/totals",
            b'{"total_outlet_water_gals":72061}',
        )

        assert mirror.historical_data.errors == [
            {
                "thing_name": "10_45_356489-Thing",
                "error_type": 10005,
                "status": 0,
            },
            {
                "thing_name": "10_45_356489-Thing",
                "error_type": 10006,
                "status": 0,
            },
        ]
        assert mirror.historical_data.totals == {
            "thing_name": "10_45_356489-Thing",
            "total_outlet_water_gals": 72061,
        }
    finally:
        await mirror.stop()


def test_data_mirror_ignores_non_device_data_publish() -> None:
    asyncio.run(_ignore_non_device_data_publish())


async def _ignore_non_device_data_publish() -> None:
    event_bus = EventBus()
    mirror = DataMirror(event_bus)
    await mirror.start()

    try:
        await publish_data_packet(
            event_bus,
            "data/configuration/10/45",
            b'{"salt_level_tenths":30}',
            direction=MqttDirection.AWS_TO_DEVICE,
        )
        await publish_data_packet(
            event_bus,
            "data/10_45_356489-Thing/remote",
            b'{"command":"unknown"}',
        )

        assert mirror.configuration_data.fields == {}
        assert mirror.historical_data.errors == []
        assert mirror.historical_data.totals == {}
    finally:
        await mirror.stop()


async def publish_shadow_packet(
    event_bus: EventBus,
    topic: str,
    payload: bytes,
    *,
    direction: MqttDirection = MqttDirection.AWS_TO_DEVICE,
) -> None:
    await event_bus.publish(
        object(),
        MqttPacketEvent(
            direction=direction,
            packet=PublishPacket(topic=topic, payload=payload),
        ),
    )
    await asyncio.sleep(0)


async def publish_data_packet(
    event_bus: EventBus,
    topic: str,
    payload: bytes,
    *,
    direction: MqttDirection = MqttDirection.DEVICE_TO_AWS,
) -> None:
    await event_bus.publish(
        object(),
        MqttPacketEvent(
            direction=direction,
            packet=PublishPacket(topic=topic, payload=payload),
        ),
    )
    await asyncio.sleep(0)
