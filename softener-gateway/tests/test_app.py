import asyncio
import logging
from contextlib import suppress

import pytest

import softener_gateway.app
from softener_gateway.app import run_gateway
from softener_gateway.config import (
    GatewayConfig,
    HttpConfig,
    Mode,
    MqttConfig,
    UnitSystem,
)
from softener_gateway.control import DeviceControl
from softener_gateway.device.shadow import DeviceShadow
from softener_gateway.endpoint import Endpoint
from softener_gateway.events import EventBus
from softener_gateway.mapper import Device, DeviceCommandMapper, DeviceMapper
from tests.test_aws import make_aws_config
from tests.test_endpoint import install_fake_start_server, make_endpoint_config


def test_run_gateway_starts_and_stops_endpoint(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO)
    install_fake_start_server(monkeypatch)

    asyncio.run(_run_gateway())

    assert any(
        message.startswith("Starting TLS endpoint on 127.0.0.1:")
        for message in caplog.messages
    )
    assert any(
        message.startswith("Stopping TLS endpoint on 127.0.0.1:")
        for message in caplog.messages
    )


async def _run_gateway() -> None:
    config = GatewayConfig(mode=Mode.LOCAL, endpoint=make_endpoint_config())
    task = asyncio.create_task(run_gateway(config))

    await asyncio.sleep(0)
    task.cancel()

    with suppress(asyncio.CancelledError):
        await task


def test_run_gateway_runs_bridge_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_start_server(monkeypatch)

    asyncio.run(_run_gateway_runs_bridge_controller(monkeypatch))


async def _run_gateway_runs_bridge_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeBridge:
        def __init__(
            self,
            config: GatewayConfig,
            event_bus: EventBus,
            endpoint: Endpoint,
            shadow: DeviceShadow,
            device: Device,
            mapper: DeviceMapper,
        ) -> None:
            captured["config"] = config
            captured["event_bus"] = event_bus
            captured["endpoint"] = endpoint
            captured["shadow"] = shadow
            captured["device"] = device
            captured["mapper"] = mapper
            captured["controller"] = self

        async def run(self) -> None:
            captured["run"] = True

    monkeypatch.setattr(softener_gateway.app, "Bridge", FakeBridge)

    config = GatewayConfig(
        mode=Mode.BRIDGE,
        endpoint=make_endpoint_config(),
        aws=make_aws_config(),
    )

    await run_gateway(config)

    assert captured["config"] is config
    assert isinstance(captured["event_bus"], EventBus)
    assert isinstance(captured["endpoint"], Endpoint)
    assert isinstance(captured["shadow"], DeviceShadow)
    assert isinstance(captured["device"], Device)
    assert isinstance(captured["mapper"], DeviceMapper)
    assert captured["run"] is True


def test_run_gateway_runs_local_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_start_server(monkeypatch)

    asyncio.run(_run_gateway_runs_local_controller(monkeypatch))


async def _run_gateway_runs_local_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeLocalController:
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
            captured["config"] = config
            captured["event_bus"] = event_bus
            captured["endpoint"] = endpoint
            captured["shadow"] = shadow
            captured["device"] = device
            captured["mapper"] = mapper
            captured["command_mapper"] = command_mapper
            captured["controller"] = self

        async def run(self) -> None:
            captured["run"] = True

    monkeypatch.setattr(softener_gateway.app, "LocalController", FakeLocalController)

    config = GatewayConfig(mode=Mode.LOCAL, endpoint=make_endpoint_config())

    await run_gateway(config)

    assert captured["config"] is config
    assert isinstance(captured["event_bus"], EventBus)
    assert isinstance(captured["endpoint"], Endpoint)
    assert isinstance(captured["shadow"], DeviceShadow)
    assert isinstance(captured["device"], Device)
    assert isinstance(captured["mapper"], DeviceMapper)
    assert isinstance(captured["command_mapper"], DeviceCommandMapper)
    assert captured["run"] is True


def test_run_gateway_starts_and_stops_http_api(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_start_server(monkeypatch)

    asyncio.run(_run_gateway_starts_and_stops_http_api(monkeypatch))


async def _run_gateway_starts_and_stops_http_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeHttpApi:
        def __init__(
            self,
            config: HttpConfig,
            device: Device,
            control: DeviceControl,
        ) -> None:
            captured["http_config"] = config
            captured["http_device"] = device
            captured["http_control"] = control

        async def start(self) -> None:
            captured["http_started"] = True

        async def stop(self) -> None:
            captured["http_stopped"] = True

    class FakeLocalController:
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
            captured["config"] = config
            captured["event_bus"] = event_bus
            captured["endpoint"] = endpoint
            captured["shadow"] = shadow
            captured["device"] = device
            captured["mapper"] = mapper
            captured["command_mapper"] = command_mapper
            captured["controller"] = self

        async def run(self) -> None:
            captured["run"] = True

    monkeypatch.setattr(softener_gateway.app, "HttpApi", FakeHttpApi)
    monkeypatch.setattr(softener_gateway.app, "LocalController", FakeLocalController)

    config = GatewayConfig(
        mode=Mode.LOCAL,
        endpoint=make_endpoint_config(),
        http=HttpConfig(host="127.0.0.1", port=18080),
    )

    await run_gateway(config)

    assert captured["http_config"] is config.http
    assert captured["http_device"] is captured["device"]
    assert captured["http_control"] is captured["controller"]
    assert captured["http_started"] is True
    assert captured["http_stopped"] is True
    assert captured["run"] is True


def test_run_gateway_starts_and_stops_mqtt_api(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_start_server(monkeypatch)

    asyncio.run(_run_gateway_starts_and_stops_mqtt_api(monkeypatch))


async def _run_gateway_starts_and_stops_mqtt_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMqttApi:
        def __init__(
            self,
            config: MqttConfig,
            event_bus: EventBus,
            device: Device,
            control: DeviceControl,
            unit_system: UnitSystem,
        ) -> None:
            captured["mqtt_config"] = config
            captured["mqtt_event_bus"] = event_bus
            captured["mqtt_device"] = device
            captured["mqtt_control"] = control
            captured["mqtt_unit_system"] = unit_system

        async def start(self) -> None:
            captured["mqtt_started"] = True

        async def stop(self) -> None:
            captured["mqtt_stopped"] = True

    class FakeLocalController:
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
            captured["event_bus"] = event_bus
            captured["device"] = device
            captured["controller"] = self

        async def run(self) -> None:
            captured["run"] = True

    monkeypatch.setattr(softener_gateway.app, "MqttApi", FakeMqttApi)
    monkeypatch.setattr(softener_gateway.app, "LocalController", FakeLocalController)

    config = GatewayConfig(
        mode=Mode.LOCAL,
        endpoint=make_endpoint_config(),
        mqtt=MqttConfig(host="127.0.0.1", topic_prefix="softener/test"),
    )

    await run_gateway(config)

    assert captured["mqtt_config"] is config.mqtt
    assert captured["mqtt_event_bus"] is captured["event_bus"]
    assert captured["mqtt_device"] is captured["device"]
    assert captured["mqtt_control"] is captured["controller"]
    assert captured["mqtt_unit_system"] is UnitSystem.METRIC
    assert captured["mqtt_started"] is True
    assert captured["mqtt_stopped"] is True
    assert captured["run"] is True
