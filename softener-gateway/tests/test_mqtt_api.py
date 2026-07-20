import asyncio
import json
from collections.abc import Callable
from typing import Any, cast

import pytest

import softener_gateway.api.mqtt
from softener_gateway.api.mqtt import MqttApi
from softener_gateway.config import MqttConfig, UnitSystem
from softener_gateway.control import ControlRegistry, DeviceControl
from softener_gateway.events import EventBus
from softener_gateway.mapper import Device, DeviceDataUpdatedEvent
from softener_gateway.models import DeviceInfo, Settings, State


def test_mqtt_api_publishes_device_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_mqtt_api_publishes_device_snapshots(monkeypatch))


async def _mqtt_api_publishes_device_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeAiomqttClient] = []

    def fake_client(*args: object, **kwargs: object) -> FakeAiomqttClient:
        client = FakeAiomqttClient(args, kwargs)
        created.append(client)
        return client

    monkeypatch.setattr("softener_gateway.api.mqtt.aiomqtt.Client", fake_client)

    event_bus = EventBus()
    control = FakeDeviceControl()
    device = Device(
        info=DeviceInfo(model_description="Aquahome Duo Smart"),
        state=State(online=False),
        settings=Settings(timezone="Europe/Warsaw"),
    )
    api = MqttApi(
        MqttConfig(
            host="mqtt.example.com",
            port=1884,
            client_id="softener-gateway-test",
            username="user",
            password="pass",
            topic_prefix="softener/test",
        ),
        event_bus,
        device,
        cast(DeviceControl, control),
    )

    await api.start()
    try:
        await wait_for(lambda: len(created) == 1 and len(created[0].publishes) == 4)
        client = created[0]
        will = cast(Any, client.kwargs.pop("will"))
        assert client.kwargs == {
            "hostname": "mqtt.example.com",
            "port": 1884,
            "identifier": "softener-gateway-test",
            "username": "user",
            "password": "pass",
            "logger": softener_gateway.api.mqtt.logger,
        }
        assert will.topic == "softener/test/availability"
        assert will.payload == b"offline"
        assert will.retain is True
        assert [publish.topic for publish in client.publishes] == [
            "softener/test/availability",
            "softener/test/device",
            "softener/test/state",
            "softener/test/settings",
        ]
        assert client.publishes[0].payload == b"online"
        assert client.subscriptions == ["softener/test/control/+"]
        assert all(publish.retain for publish in client.publishes)
        assert _decode_payload(client.publishes[1].payload)["model_description"] == (
            "Aquahome Duo Smart"
        )

        device.state = State(online=True, current_flow=1.23)
        await event_bus.publish(api, DeviceDataUpdatedEvent())
        await wait_for(lambda: len(client.publishes) == 5)

        assert [publish.topic for publish in client.publishes[4:]] == [
            "softener/test/state",
        ]
        assert _decode_payload(client.publishes[4].payload)["current_flow"] == 1.23

        await client.messages.put(
            FakeAiomqttMessage(
                "softener/test/control/set_hardness",
                b'{"value": 310}',
            )
        )
        await wait_for(lambda: control.calls == [("set_hardness", 310.0)])
    finally:
        await api.stop()

    assert created[0].closed
    assert created[0].publishes[-1].topic == "softener/test/availability"
    assert created[0].publishes[-1].payload == b"offline"


def test_mqtt_api_reconnects_after_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_mqtt_api_reconnects_after_connection_error(monkeypatch))


def test_mqtt_api_publishes_homeassistant_device_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_mqtt_api_publishes_homeassistant_device_discovery(monkeypatch))


def test_mqtt_api_formats_imperial_hardness_control_discovery() -> None:
    api = MqttApi(
        MqttConfig(topic_prefix="softener/test", homeassistant_discovery=True),
        EventBus(),
        Device(settings=Settings(hardness=18.0)),
        cast(DeviceControl, FakeDeviceControl()),
        UnitSystem.IMPERIAL,
    )

    discovery = api._build_homeassistant_discovery()
    components = cast(dict[str, Any], discovery["components"])
    control_hardness = cast(dict[str, Any], components["control_set_hardness"])

    assert control_hardness["platform"] == "select"
    assert control_hardness["options"][0] == "1 grain"
    assert control_hardness["options"][-1] == "80 grains"
    assert "grains" in control_hardness["value_template"]


async def _mqtt_api_publishes_homeassistant_device_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeAiomqttClient] = []

    def fake_client(*args: object, **kwargs: object) -> FakeAiomqttClient:
        client = FakeAiomqttClient(args, kwargs)
        created.append(client)
        return client

    monkeypatch.setattr("softener_gateway.api.mqtt.aiomqtt.Client", fake_client)

    event_bus = EventBus()
    device = Device(
        info=DeviceInfo(
            model_description="Aquahome Duo Smart",
            software_version="r4.5 MPC01154",
            product_serial_number="7938282-22151-5029",
        ),
        state=State(online=True, current_flow=1.23, total_outlet_water=272.999),
        settings=Settings(hardness=310.0),
    )
    api = MqttApi(
        MqttConfig(
            host="mqtt.example.com",
            topic_prefix="softener/test",
            homeassistant_discovery=True,
        ),
        event_bus,
        device,
        cast(DeviceControl, FakeDeviceControl()),
        UnitSystem.METRIC,
    )

    await api.start()
    try:
        await wait_for(lambda: len(created) == 1 and len(created[0].publishes) == 5)
        client = created[0]
        assert [publish.topic for publish in client.publishes] == [
            "softener/test/availability",
            "homeassistant/device/softener_gateway/config",
            "softener/test/device",
            "softener/test/state",
            "softener/test/settings",
        ]
        assert client.publishes[0].payload == b"online"

        discovery = _decode_payload(client.publishes[1].payload)
        assert discovery["state_topic"] == "softener/test/state"
        assert discovery["availability_topic"] == "softener/test/availability"
        assert discovery["payload_available"] == "online"
        assert discovery["payload_not_available"] == "offline"
        assert discovery["origin"] == {
            "name": "softener_gateway",
            "sw_version": "0.1.1",
        }
        assert discovery["device"] == {
            "identifiers": ["softener_gateway"],
            "name": "Softener",
            "sw_version": "0.1.1",
            "model": "Aquahome Duo Smart",
            "hw_version": "r4.5 MPC01154",
            "serial_number": "7938282-22151-5029",
        }

        components = cast(dict[str, Any], discovery["components"])
        assert len(components) == 94
        assert sum(key.startswith("control_") for key in components) == 21
        current_flow = cast(dict[str, Any], components["current_flow"])
        total_outlet_water = cast(dict[str, Any], components["total_outlet_water"])
        salt_low = cast(dict[str, Any], components["salt_low"])
        error_low_salt = cast(dict[str, Any], components["error_low_salt"])
        shutoff_valve_error = cast(
            dict[str, Any],
            components["error_shutoff_valve_error_code"],
        )
        start_regeneration = cast(dict[str, Any], components["control_start_regeneration"])
        control_hardness = cast(dict[str, Any], components["control_set_hardness"])
        control_salt_level = cast(dict[str, Any], components["control_set_salt_level"])
        control_salt_type = cast(dict[str, Any], components["control_set_salt_type"])
        control_feature_97 = cast(dict[str, Any], components["control_set_feature_97_percent"])
        control_regen_time = cast(dict[str, Any], components["control_set_regen_time"])
        control_max_days = cast(
            dict[str, Any],
            components["control_set_max_days_between_regenerations"],
        )
        peak_flow = cast(dict[str, Any], components["peak_flow"])
        average_daily_usage = cast(dict[str, Any], components["average_daily_usage"])
        capacity_operating = cast(dict[str, Any], components["capacity_operating"])
        capacity_average_exhaustion = cast(
            dict[str, Any],
            components["capacity_average_exhaustion"],
        )
        salt_efficiency = cast(dict[str, Any], components["salt_efficiency"])
        total_untreated_water = cast(dict[str, Any], components["total_untreated_water"])
        online = cast(dict[str, Any], components["online"])
        module_connected = cast(dict[str, Any], components["module_connected"])
        device_connected = cast(dict[str, Any], components["device_connected"])
        regeneration_average_interval = cast(
            dict[str, Any],
            components["regeneration_average_interval"],
        )
        regeneration_stage = cast(dict[str, Any], components["regeneration_stage"])
        regeneration_stage_remaining = cast(
            dict[str, Any],
            components["regeneration_stage_remaining"],
        )
        regeneration_total_count = cast(
            dict[str, Any],
            components["regeneration_total_count"],
        )
        regeneration_manual_count = cast(
            dict[str, Any],
            components["regeneration_manual_count"],
        )

        assert current_flow["unit_of_measurement"] == "L/min"
        assert current_flow["device_class"] == "volume_flow_rate"
        assert online["entity_category"] == "diagnostic"
        assert module_connected["entity_category"] == "diagnostic"
        assert device_connected["entity_category"] == "diagnostic"
        assert peak_flow["entity_category"] == "diagnostic"
        assert average_daily_usage["entity_category"] == "diagnostic"
        assert capacity_operating["entity_category"] == "diagnostic"
        assert capacity_average_exhaustion["entity_category"] == "diagnostic"
        assert salt_efficiency["entity_category"] == "diagnostic"
        assert total_outlet_water["unit_of_measurement"] == "m³"
        assert total_outlet_water["device_class"] == "water"
        assert total_outlet_water["state_class"] == "total_increasing"
        assert "entity_category" not in total_outlet_water
        assert total_untreated_water["entity_category"] == "diagnostic"
        assert regeneration_average_interval["entity_category"] == "diagnostic"
        assert regeneration_stage["entity_category"] == "diagnostic"
        assert regeneration_stage_remaining["entity_category"] == "diagnostic"
        assert regeneration_total_count["entity_category"] == "diagnostic"
        assert regeneration_manual_count["entity_category"] == "diagnostic"
        assert salt_low["name"] == "Salt level low"
        assert error_low_salt["platform"] == "binary_sensor"
        assert error_low_salt["device_class"] == "problem"
        assert "entity_category" not in error_low_salt
        assert shutoff_valve_error["name"] == "Shutoff Valve Error Code"
        assert start_regeneration["platform"] == "button"
        assert start_regeneration["command_topic"] == (
            "softener/test/control/start_regeneration"
        )
        assert start_regeneration["payload_press"] == "{}"
        assert "entity_category" not in start_regeneration
        assert control_hardness["platform"] == "select"
        assert control_hardness["command_topic"] == "softener/test/control/set_hardness"
        assert control_hardness["entity_category"] == "config"
        assert control_hardness["command_template"] == (
            '{"value": {{ value.split(" ")[0] | float }}}'
        )
        assert control_hardness["options"][0] == "20 PPM (1 dH/2 fH)"
        assert control_hardness["options"][-1] == "1370 PPM (77 dH/137 fH)"
        assert "310 PPM (17 dH/31 fH)" in control_hardness["options"]
        assert "PPM" in control_hardness["value_template"]
        assert "dH" in control_hardness["value_template"]
        assert "fH" in control_hardness["value_template"]
        assert control_salt_level["min"] == 1
        assert control_salt_level["max"] == 8
        assert control_salt_type["platform"] == "select"
        assert control_salt_type["entity_category"] == "config"
        assert control_salt_type["options"] == ["nacl", "kcl"]
        assert control_feature_97["platform"] == "switch"
        assert control_feature_97["entity_category"] == "config"
        assert control_feature_97["payload_on"] == '{"value":true}'
        assert control_feature_97["payload_off"] == '{"value":false}'
        assert control_regen_time["platform"] == "select"
        assert control_regen_time["entity_category"] == "config"
        assert control_regen_time["options"][:3] == ["00:00", "00:15", "00:30"]
        assert control_regen_time["options"][-1] == "23:45"
        assert len(control_regen_time["options"]) == 96
        assert control_regen_time["command_template"] == '{"value":"{{ value }}"}'
        assert control_max_days["platform"] == "select"
        assert control_max_days["entity_category"] == "config"
        assert control_max_days["options"] == ["auto", *[str(value) for value in range(1, 16)]]
        assert {
            f"control_{command.name}"
            for command in ControlRegistry.from_device_control()
        } <= components.keys()
        assert not any(key.startswith("setting_") for key in components)
        assert "wsov" not in json.dumps(discovery).lower()
        assert all("unique_id" in component for component in components.values())
        assert all(
            component["enabled_by_default"] is True
            for key, component in components.items()
            if not key.startswith("control_")
        )
        assert all(
            component.get("entity_category") != "config"
            for component in components.values()
            if component["platform"] in {"sensor", "binary_sensor"}
        )
        assert all(
            not (
                component.get("device_class") == "volume"
                and component.get("state_class") == "measurement"
            )
            for component in components.values()
        )
        assert all(
            "device_class" not in component
            for key, component in components.items()
            if key.startswith("control_") and component["platform"] == "number"
        )
        assert all(
            component["mode"] == "box"
            for key, component in components.items()
            if key.startswith("control_") and component["platform"] == "number"
        )
    finally:
        await api.stop()


async def _mqtt_api_reconnects_after_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeAiomqttClient] = []

    def fake_client(*args: object, **kwargs: object) -> FakeAiomqttClient:
        client = FakeAiomqttClient(args, kwargs, fail_enter=len(created) == 0)
        created.append(client)
        return client

    monkeypatch.setattr("softener_gateway.api.mqtt.aiomqtt.Client", fake_client)
    monkeypatch.setattr("softener_gateway.api.mqtt.MQTT_RECONNECT_DELAY_SECONDS", 0.01)

    event_bus = EventBus()
    device = Device(state=State(online=True))
    api = MqttApi(
        MqttConfig(host="mqtt.example.com", topic_prefix="softener/test"),
        event_bus,
        device,
        cast(DeviceControl, FakeDeviceControl()),
    )

    await api.start()
    try:
        await wait_for(lambda: len(created) == 2 and len(created[1].publishes) == 4)
    finally:
        await api.stop()

    assert not created[0].closed
    assert created[1].closed


async def wait_for(condition: Callable[[], bool]) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 1.0
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("condition was not met before timeout")

        await asyncio.sleep(0.01)


def _decode_payload(payload: bytes) -> dict[str, Any]:
    decoded = json.loads(payload)
    assert isinstance(decoded, dict)
    return decoded


class PublishedMessage:
    def __init__(self, topic: str, payload: bytes, retain: bool) -> None:
        self.topic = topic
        self.payload = payload
        self.retain = retain


class FakeAiomqttMessage:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


class FakeMessages:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[FakeAiomqttMessage] = asyncio.Queue()

    def __aiter__(self) -> "FakeMessages":
        return self

    async def __anext__(self) -> FakeAiomqttMessage:
        return await self._queue.get()

    async def put(self, message: FakeAiomqttMessage) -> None:
        await self._queue.put(message)


class FakeAiomqttClient:
    def __init__(
        self,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        *,
        fail_enter: bool = False,
    ) -> None:
        self.args = args
        self.kwargs = kwargs
        self.fail_enter = fail_enter
        self.publishes: list[PublishedMessage] = []
        self.subscriptions: list[str] = []
        self.messages = FakeMessages()
        self.closed = False

    async def __aenter__(self) -> "FakeAiomqttClient":
        if self.fail_enter:
            raise OSError("connection refused")

        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True

    async def publish(
        self,
        topic: str,
        payload: bytes | None = None,
        *,
        retain: bool = False,
    ) -> None:
        assert payload is not None
        self.publishes.append(PublishedMessage(topic, payload, retain))

    async def subscribe(self, topic: str) -> tuple[int, ...]:
        self.subscriptions.append(topic)
        return (0,)


class FakeDeviceControl:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def set_hardness(self, value: float) -> None:
        self.calls.append(("set_hardness", value))
