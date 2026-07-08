import logging
from typing import Protocol

from softener_gateway.api import HttpApi, MqttApi
from softener_gateway.bridge import Bridge
from softener_gateway.config import GatewayConfig, Mode
from softener_gateway.control import DeviceControl
from softener_gateway.device.shadow import DeviceShadow
from softener_gateway.endpoint import Endpoint
from softener_gateway.events import EventBus
from softener_gateway.local import LocalController
from softener_gateway.mapper import Device, DeviceCommandMapper, DeviceMapper

logger = logging.getLogger(__name__)


class _GatewayController(DeviceControl, Protocol):
    async def run(self) -> None:
        pass


async def run_gateway(config: GatewayConfig) -> None:
    logger.info("Starting softener gateway in %s mode", config.mode.value)

    event_bus = EventBus()
    shadow = DeviceShadow()
    device = Device()
    mapper = DeviceMapper()
    endpoint = Endpoint(config.endpoint, event_bus)
    await endpoint.start()
    http_api: HttpApi | None = None
    mqtt_api: MqttApi | None = None

    try:
        match config.mode:
            case Mode.LOCAL:
                command_mapper = DeviceCommandMapper(config.unit_system)
                controller: _GatewayController = LocalController(
                    config,
                    event_bus,
                    endpoint,
                    shadow,
                    device,
                    mapper,
                    command_mapper,
                )
            case Mode.BRIDGE:
                controller = Bridge(config, event_bus, endpoint, shadow, device, mapper)

        if config.http is not None and config.http.enabled:
            http_api = HttpApi(config.http, device, controller)
            await http_api.start()
        if config.mqtt is not None and config.mqtt.enabled:
            mqtt_api = MqttApi(
                config.mqtt,
                event_bus,
                device,
                controller,
                config.unit_system,
            )
            await mqtt_api.start()

        await controller.run()
    finally:
        if mqtt_api is not None:
            await mqtt_api.stop()
        if http_api is not None:
            await http_api.stop()
        await endpoint.stop()
