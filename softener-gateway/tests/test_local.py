import asyncio
import json
from collections.abc import Mapping
from typing import cast

import pytest

import softener_gateway.local
from softener_gateway.config import GatewayConfig, Mode, UnitSystem
from softener_gateway.control import DeviceNotConnectedError
from softener_gateway.device.data import DeviceConfigurationData, DeviceHistoricalData
from softener_gateway.device.shadow import DeviceShadow, ShadowLifecycle, ShadowOperation
from softener_gateway.endpoint import (
    Endpoint,
    EndpointDataReceivedEvent,
)
from softener_gateway.events import EventBus
from softener_gateway.local import LocalController, MqttAdapter
from softener_gateway.mapper import Device, DeviceCommandMapper, DeviceMapper
from softener_gateway.mqtt_protocol import (
    ConnAckPacket,
    ConnectPacket,
    ConnectReturnCode,
    DisconnectPacket,
    MqttPacket,
    PingReqPacket,
    PingRespPacket,
    PubAckPacket,
    PublishPacket,
    QoS,
    SubAckPacket,
    SubAckReturnCode,
    SubscribePacket,
    TopicSubscription,
    UnsubscribePacket,
    build_packet,
    parse_packets,
)
from tests.test_endpoint import make_endpoint_config


class FakeMqttEndpoint:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def close(self) -> None:
        self.closed = True


class BlockingNextWriteEndpoint(FakeMqttEndpoint):
    def __init__(self) -> None:
        super().__init__()
        self.block_next_write = False
        self.write_started = asyncio.Event()
        self.release_write = asyncio.Event()

    async def write(self, data: bytes) -> None:
        if self.block_next_write:
            self.block_next_write = False
            self.write_started.set()
            await self.release_write.wait()

        await super().write(data)


class FakeControlPublisher:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def publish_control_delta(self, request: Mapping[str, object]) -> None:
        self.requests.append(dict(request))


def test_local_controller_owns_device_state_objects() -> None:
    shadow = DeviceShadow(clock=lambda: 1)
    event_bus = EventBus()
    endpoint = Endpoint(make_endpoint_config(), event_bus)

    controller = LocalController(
        GatewayConfig(mode=Mode.LOCAL, endpoint=make_endpoint_config()),
        event_bus,
        endpoint,
        shadow,
        Device(),
        DeviceMapper(),
        DeviceCommandMapper(UnitSystem.METRIC),
    )

    assert controller.endpoint is endpoint
    assert controller.shadow is shadow
    assert isinstance(controller.configuration_data, DeviceConfigurationData)
    assert isinstance(controller.historical_data, DeviceHistoricalData)
    assert controller.configuration_data.fields == {}
    assert controller.historical_data.errors == []
    assert controller.historical_data.totals == {}


def test_local_controller_publishes_mapped_control_request() -> None:
    asyncio.run(_local_controller_publishes_mapped_control_request())


async def _local_controller_publishes_mapped_control_request() -> None:
    event_bus = EventBus()
    controller = LocalController(
        GatewayConfig(mode=Mode.LOCAL, endpoint=make_endpoint_config()),
        event_bus,
        Endpoint(make_endpoint_config(), event_bus),
        DeviceShadow(),
        Device(),
        DeviceMapper(),
        DeviceCommandMapper(UnitSystem.METRIC),
    )
    publisher = FakeControlPublisher()
    controller._mqtt_adapter = cast(MqttAdapter, publisher)

    await controller.set_hardness(307.8)
    await controller.start_regeneration()

    assert publisher.requests == [
        {"hardness_grains": 18.0},
        {"regen_status_enum": 2},
    ]


def test_shadow_controller_is_not_exported_from_local_module() -> None:
    assert "LocalController" in softener_gateway.local.__all__
    assert "MqttAdapter" in softener_gateway.local.__all__
    assert "ShadowController" not in softener_gateway.local.__all__
    assert not hasattr(softener_gateway.local, "ShadowController")


def test_mqtt_adapter_handles_basic_mqtt_control_packets() -> None:
    asyncio.run(_handle_basic_mqtt_control_packets())


async def _handle_basic_mqtt_control_packets() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            ConnectPacket(client_id="10_45_356489-Thing", clean_session=True, keep_alive=600),
        )
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            SubscribePacket(
                packet_identifier=7,
                subscriptions=(
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/accepted",
                        QoS.AT_MOST_ONCE,
                    ),
                    TopicSubscription("data/10_45_356489-Thing/remote", QoS.AT_MOST_ONCE),
                ),
            ),
        )
        await publish_endpoint_packet(event_bus, endpoint, PingReqPacket())
        await publish_endpoint_packet(event_bus, endpoint, DisconnectPacket())

        assert read_written_packets(endpoint) == [
            ConnAckPacket(
                session_present=False,
                return_code=ConnectReturnCode.ACCEPTED,
            ),
            SubAckPacket(
                packet_identifier=7,
                return_codes=(
                    SubAckReturnCode.MAXIMUM_QOS_0,
                    SubAckReturnCode.MAXIMUM_QOS_0,
                ),
            ),
            PingRespPacket(),
        ]
        assert endpoint.closed
    finally:
        await adapter.stop()


def test_mqtt_adapter_starts_data_acquisition_after_delta_subscription() -> None:
    asyncio.run(_start_data_acquisition_after_delta_subscription())


def test_mqtt_adapter_serializes_data_acquisition_with_shadow_response() -> None:
    asyncio.run(_serialize_data_acquisition_with_shadow_response())


def test_mqtt_adapter_publishes_get_all_data_delta() -> None:
    asyncio.run(_publish_get_all_data_delta())


def test_mqtt_adapter_publishes_app_active_delta() -> None:
    asyncio.run(_publish_app_active_delta())


def test_mqtt_adapter_publishes_control_delta() -> None:
    asyncio.run(_publish_control_delta())


def test_mqtt_adapter_observes_app_active_reports() -> None:
    asyncio.run(_observe_app_active_reports())


def test_mqtt_adapter_does_not_send_get_all_data_with_app_active() -> None:
    asyncio.run(_do_not_send_get_all_data_with_app_active())


async def _start_data_acquisition_after_delta_subscription() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            SubscribePacket(
                packet_identifier=1,
                subscriptions=(
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/delta",
                        QoS.AT_MOST_ONCE,
                    ),
                ),
            ),
        )

        task = adapter._data_acquisition_task
        assert task is not None
        assert not task.done()

        await publish_endpoint_packet(
            event_bus,
            endpoint,
            UnsubscribePacket(
                packet_identifier=2,
                topic_filters=(
                    "$aws/things/10_45_356489-Thing/shadow/update/delta",
                ),
            ),
        )

        for _ in range(3):
            if adapter._data_acquisition_task is None:
                break
            await asyncio.sleep(0)

        assert adapter._data_acquisition_task is None
    finally:
        await adapter.stop()


async def _publish_get_all_data_delta() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            SubscribePacket(
                packet_identifier=1,
                subscriptions=(
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/delta",
                        QoS.AT_MOST_ONCE,
                    ),
                ),
            ),
        )
        endpoint.writes.clear()

        await adapter._publish_get_all_data_delta("10_45_356489-Thing")

        packets = read_written_packets(endpoint)
        assert len(packets) == 1
        packet = packets[0]
        assert isinstance(packet, PublishPacket)
        assert packet.topic == "$aws/things/10_45_356489-Thing/shadow/update/delta"
        assert json.loads(packet.payload) == {
            "state": {"Request": {"get_all_data": 1}},
        }
    finally:
        await adapter.stop()


async def _publish_app_active_delta() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            SubscribePacket(
                packet_identifier=1,
                subscriptions=(
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/delta",
                        QoS.AT_MOST_ONCE,
                    ),
                ),
            ),
        )
        endpoint.writes.clear()

        await adapter._publish_app_active_delta("10_45_356489-Thing")

        packets = read_written_packets(endpoint)
        assert len(packets) == 1
        packet = packets[0]
        assert isinstance(packet, PublishPacket)
        assert packet.topic == "$aws/things/10_45_356489-Thing/shadow/update/delta"
        assert json.loads(packet.payload) == {
            "state": {
                "Request": {
                    "app_active": 1,
                    "app_active_timeout": 5,
                    "service_active": 1,
                },
            },
        }
    finally:
        await adapter.stop()


async def _publish_control_delta() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        with pytest.raises(DeviceNotConnectedError):
            await adapter.publish_control_delta({"hardness_grains": 18})

        await publish_endpoint_packet(
            event_bus,
            endpoint,
            SubscribePacket(
                packet_identifier=1,
                subscriptions=(
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/delta",
                        QoS.AT_MOST_ONCE,
                    ),
                ),
            ),
        )
        endpoint.writes.clear()

        await adapter.publish_control_delta({"hardness_grains": 18})

        packets = read_written_packets(endpoint)
        assert len(packets) == 1
        packet = packets[0]
        assert isinstance(packet, PublishPacket)
        assert packet.topic == "$aws/things/10_45_356489-Thing/shadow/update/delta"
        assert json.loads(packet.payload) == {
            "state": {"Request": {"hardness_grains": 18}},
        }
    finally:
        await adapter.stop()


async def _observe_app_active_reports() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            PublishPacket(
                topic="$aws/things/10_45_356489-Thing/shadow/update",
                payload=b'{"state":{"reported":{"Request":{"app_active":42,"app_active_timeout":5,"service_active":42}}}}',
            ),
        )

        assert adapter._app_active

        await publish_endpoint_packet(
            event_bus,
            endpoint,
            PublishPacket(
                topic="$aws/things/10_45_356489-Thing/shadow/update",
                payload=b'{"state":{"reported":{"Status":{"app_active":0}}}}',
            ),
        )

        assert not adapter._app_active
    finally:
        await adapter.stop()


async def _do_not_send_get_all_data_with_app_active() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            SubscribePacket(
                packet_identifier=1,
                subscriptions=(
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/delta",
                        QoS.AT_MOST_ONCE,
                    ),
                ),
            ),
        )
        endpoint.writes.clear()

        await asyncio.sleep(5.1)

        packets = read_written_packets(endpoint)
        assert len(packets) == 1
        packet = packets[0]
        assert isinstance(packet, PublishPacket)
        assert json.loads(packet.payload) == {
            "state": {
                "Request": {
                    "app_active": 1,
                    "app_active_timeout": 5,
                    "service_active": 1,
                },
            },
        }
    finally:
        await adapter.stop()


async def _serialize_data_acquisition_with_shadow_response() -> None:
    event_bus = EventBus()
    endpoint = BlockingNextWriteEndpoint()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(clock=lambda: 1),
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            SubscribePacket(
                packet_identifier=1,
                subscriptions=(
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/accepted",
                        QoS.AT_MOST_ONCE,
                    ),
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/delta",
                        QoS.AT_MOST_ONCE,
                    ),
                ),
            ),
        )
        endpoint.writes.clear()
        endpoint.block_next_write = True

        await publish_endpoint_packet(
            event_bus,
            endpoint,
            PublishPacket(
                topic="$aws/things/10_45_356489-Thing/shadow/update",
                payload=b'{"state":{"desired":{"regen_status_enum":2}}}',
            ),
        )
        await endpoint.write_started.wait()

        data_acquisition_write = asyncio.create_task(
            adapter._publish_data_acquisition_shadow_response(
                "10_45_356489-Thing",
                ShadowOperation.UPDATE,
                ShadowLifecycle.DELTA,
                {"state": {"Request": {"app_active": 1}}},
            )
        )
        await asyncio.sleep(0)

        assert not data_acquisition_write.done()
        assert endpoint.writes == []

        endpoint.release_write.set()
        await data_acquisition_write

        packets = read_written_packets(endpoint)
        assert [packet.topic for packet in packets if isinstance(packet, PublishPacket)] == [
            "$aws/things/10_45_356489-Thing/shadow/update/accepted",
            "$aws/things/10_45_356489-Thing/shadow/update/delta",
            "$aws/things/10_45_356489-Thing/shadow/update/delta",
        ]
    finally:
        await adapter.stop()


def test_mqtt_adapter_acks_qos_one_data_publish_and_updates_data() -> None:
    asyncio.run(_ack_qos_one_data_publish_and_update_data())


async def _ack_qos_one_data_publish_and_update_data() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    configuration_data = DeviceConfigurationData()
    historical_data = DeviceHistoricalData()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        configuration_data,
        historical_data,
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            PublishPacket(
                topic="data/configuration/10/45",
                payload=b'{"thing_name":"10_45_356489-Thing","salt_level_tenths":30}',
                qos=QoS.AT_LEAST_ONCE,
                packet_identifier=9,
            ),
        )
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            PublishPacket(
                topic="data/historical/10/45/totals",
                payload=b'{"total_outlet_water_gals":72060}',
                qos=QoS.AT_LEAST_ONCE,
                packet_identifier=10,
            ),
        )
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            PublishPacket(
                topic="data/historical/10/45/errors",
                payload=b'{"thing_name":"10_45_356489-Thing","error_type":10006,"status":0}',
                qos=QoS.AT_LEAST_ONCE,
                packet_identifier=11,
            ),
        )

        assert read_written_packets(endpoint) == [
            PubAckPacket(packet_identifier=9),
            PubAckPacket(packet_identifier=10),
            PubAckPacket(packet_identifier=11),
        ]
        assert configuration_data.fields == {"salt_level_tenths": 30}
        assert historical_data.totals == {"total_outlet_water_gals": 72060}
        assert historical_data.errors == [{"error_type": 10006, "status": 0}]
    finally:
        await adapter.stop()


def test_mqtt_adapter_closes_endpoint_on_malformed_qos_one_publish() -> None:
    asyncio.run(_close_endpoint_on_malformed_qos_one_publish())


async def _close_endpoint_on_malformed_qos_one_publish() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        DeviceShadow(),
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await adapter._handle_publish(
            PublishPacket(
                topic="data/configuration/10/45",
                payload=b"{}",
                qos=QoS.AT_LEAST_ONCE,
            )
        )

        assert endpoint.closed
        assert endpoint.writes == []
    finally:
        await adapter.stop()


def test_mqtt_adapter_ignores_named_shadow_topics() -> None:
    asyncio.run(_ignore_named_shadow_topics())


async def _ignore_named_shadow_topics() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    shadow = DeviceShadow(clock=lambda: 1)
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        shadow,
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            PublishPacket(
                topic="$aws/things/10_45_356489-Thing/shadow/name/mobile/update",
                payload=b'{"state":{"desired":{"mode":"eco"}},"clientToken":"token-1"}',
            ),
        )

        assert endpoint.writes == []
        assert shadow.desired == {}
    finally:
        await adapter.stop()


def test_mqtt_adapter_handles_shadow_update_like_aws() -> None:
    asyncio.run(_handle_shadow_update_like_aws())


async def _handle_shadow_update_like_aws() -> None:
    event_bus = EventBus()
    endpoint = FakeMqttEndpoint()
    shadow = DeviceShadow(clock=lambda: 1)
    adapter = MqttAdapter(
        event_bus,
        cast(Endpoint, endpoint),
        shadow,
        DeviceConfigurationData(),
        DeviceHistoricalData(),
    )
    await adapter.start()

    try:
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            ConnectPacket(client_id="10_45_356489-Thing", clean_session=True, keep_alive=600),
        )
        await publish_endpoint_packet(
            event_bus,
            endpoint,
            SubscribePacket(
                packet_identifier=1,
                subscriptions=(
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/accepted",
                        QoS.AT_MOST_ONCE,
                    ),
                    TopicSubscription(
                        "$aws/things/10_45_356489-Thing/shadow/update/delta",
                        QoS.AT_MOST_ONCE,
                    ),
                ),
            ),
        )
        endpoint.writes.clear()

        await publish_endpoint_packet(
            event_bus,
            endpoint,
            PublishPacket(
                topic="$aws/things/10_45_356489-Thing/shadow/update",
                payload=b'{"state":{"desired":{"regen_status_enum":2}},"clientToken":"token-1"}',
            ),
        )

        packets = read_written_packets(endpoint)

        assert len(packets) == 2
        accepted = packets[0]
        delta = packets[1]
        assert isinstance(accepted, PublishPacket)
        assert accepted.topic == "$aws/things/10_45_356489-Thing/shadow/update/accepted"
        assert accepted.qos is QoS.AT_MOST_ONCE
        assert json.loads(accepted.payload) == {
            "state": {"desired": {"regen_status_enum": 2}},
            "metadata": {"desired": {"regen_status_enum": {"timestamp": 1}}},
            "version": 1,
            "timestamp": 1,
            "clientToken": "token-1",
        }
        assert isinstance(delta, PublishPacket)
        assert delta.topic == "$aws/things/10_45_356489-Thing/shadow/update/delta"
        assert json.loads(delta.payload) == {
            "state": {"regen_status_enum": 2},
            "metadata": {"regen_status_enum": {"timestamp": 1}},
            "version": 1,
            "timestamp": 1,
            "clientToken": "token-1",
        }
        assert shadow.desired == {"regen_status_enum": 2}
    finally:
        await adapter.stop()


async def publish_endpoint_packet(
    event_bus: EventBus,
    endpoint: FakeMqttEndpoint,
    packet: MqttPacket,
) -> None:
    await event_bus.publish(
        endpoint,
        EndpointDataReceivedEvent(data=build_packet(packet)),
    )
    await asyncio.sleep(0)


def read_written_packets(endpoint: FakeMqttEndpoint) -> list[MqttPacket]:
    packets: list[MqttPacket] = []
    for data in endpoint.writes:
        parsed, remaining = parse_packets(data)
        assert remaining == b""
        packets.extend(parsed)

    return packets
