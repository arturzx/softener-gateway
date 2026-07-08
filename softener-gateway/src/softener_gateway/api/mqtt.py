from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

import aiomqtt

from softener_gateway import __version__
from softener_gateway.config import MqttConfig, UnitSystem
from softener_gateway.control import (
    ControlDispatchError,
    ControlRegistry,
    DeviceControl,
    DeviceControlError,
    UnknownControlCommandError,
)
from softener_gateway.endpoint import EndpointConnectedEvent, EndpointDisconnectedEvent
from softener_gateway.events import EventBus, Subscription
from softener_gateway.mapper import ERROR_CODES, PPM_PER_GPG, Device, DeviceDataUpdatedEvent
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

logger = logging.getLogger(__name__)
MQTT_RECONNECT_DELAY_SECONDS = 5.0
HOME_ASSISTANT_DISCOVERY_PREFIX = "homeassistant"
HOME_ASSISTANT_DEVICE_ID = "softener_gateway"
HARDNESS_MIN_GPG = 1
HARDNESS_MAX_GPG = 80
PPM_PER_DH = 17.848
PPM_PER_FH = 10


class MqttApi:
    def __init__(
        self,
        config: MqttConfig,
        event_bus: EventBus,
        device: Device,
        control: DeviceControl,
        unit_system: UnitSystem = UnitSystem.METRIC,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.device = device
        self.control = control
        self.unit_system = unit_system
        self.control_registry = ControlRegistry.from_device_control()
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._snapshot: dict[str, bytes] = {}
        self._homeassistant_discovery: bytes | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return

        ready = asyncio.Event()
        self._task = asyncio.create_task(self._run(ready))
        await ready.wait()
        logger.info(
            "Started MQTT API for %s:%d with topic prefix %s",
            self.config.host,
            self.config.port,
            self.config.topic_prefix,
        )

    async def stop(self) -> None:
        task = self._task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        self._task = None
        self._client = None

        logger.info("Stopped MQTT API on %s:%d", self.config.host, self.config.port)

    async def _run(self, ready: asyncio.Event) -> None:
        ready.set()
        while True:
            try:
                await self._run_connected()
            except asyncio.CancelledError:
                raise
            except (aiomqtt.MqttError, OSError, TimeoutError) as exc:
                logger.warning(
                    "MQTT API connection failed: %s; reconnecting in %.1fs",
                    exc,
                    MQTT_RECONNECT_DELAY_SECONDS,
                )

            await asyncio.sleep(MQTT_RECONNECT_DELAY_SECONDS)

    async def _run_connected(self) -> None:
        async with aiomqtt.Client(
            hostname=self.config.host,
            port=self.config.port,
            identifier=self.config.client_id,
            username=self.config.username,
            password=self.config.password,
            logger=logger,
            will=aiomqtt.Will(
                self._availability_topic(),
                payload=b"offline",
                retain=True,
            ),
        ) as client:
            self._client = client
            logger.info(
                "Connected MQTT API to %s:%d",
                self.config.host,
                self.config.port,
            )
            try:
                await self._publish_until_disconnected()
            finally:
                with suppress(aiomqtt.MqttError, OSError, TimeoutError):
                    await self._publish_availability("offline")
                self._client = None

    async def _publish_until_disconnected(self) -> None:
        async with self.event_bus.subscribe(
            DeviceDataUpdatedEvent,
            EndpointConnectedEvent,
            EndpointDisconnectedEvent,
        ) as subscription:
            await self._publish_availability("online")
            if self.config.homeassistant_discovery:
                await self._publish_homeassistant_discovery(force=True)
            await self._publish_changed_snapshot(force=True)
            await self._subscribe_control()
            async with asyncio.TaskGroup() as task_group:
                task_group.create_task(self._publish_device_updates(subscription))
                task_group.create_task(self._handle_control_messages())

    async def _publish_device_updates(self, subscription: Subscription) -> None:
        async for _emitter, _event in subscription:
            await asyncio.sleep(0)
            if self.config.homeassistant_discovery:
                await self._publish_homeassistant_discovery()
            await self._publish_changed_snapshot()

    async def _subscribe_control(self) -> None:
        client = self._client
        if client is None:
            return

        await client.subscribe(f"{self.config.topic_prefix}/control/+")

    async def _handle_control_messages(self) -> None:
        client = self._client
        if client is None:
            return

        async for message in client.messages:
            await self._handle_control_message(str(message.topic), message.payload)

    async def _handle_control_message(self, topic: str, payload: bytes) -> None:
        prefix = f"{self.config.topic_prefix}/control/"
        if not topic.startswith(prefix):
            return

        command_name = topic[len(prefix) :]
        if not command_name or "/" in command_name:
            logger.warning("Ignoring invalid MQTT control topic: %s", topic)
            return

        try:
            body = _decode_json_object(payload)
            command = self.control_registry.get(command_name)
            await command.execute(self.control, body)
        except UnknownControlCommandError as exc:
            logger.warning("Ignoring unknown MQTT control command %s: %s", command_name, exc)
        except ControlDispatchError as exc:
            logger.warning("Ignoring invalid MQTT control payload for %s: %s", command_name, exc)
        except ValueError as exc:
            logger.warning("Ignoring invalid MQTT control request for %s: %s", command_name, exc)
        except DeviceControlError as exc:
            logger.warning("MQTT control command %s failed: %s", command_name, exc)
        else:
            logger.info("MQTT control command accepted: %s", command_name)

    async def _publish_changed_snapshot(self, *, force: bool = False) -> None:
        current = self._build_snapshot()
        for name, payload in current.items():
            if not force and self._snapshot.get(name) == payload:
                continue

            await self._publish(name, payload)

        self._snapshot = current

    async def _publish(self, name: str, payload: bytes) -> None:
        client = self._client
        if client is None:
            return

        topic = f"{self.config.topic_prefix}/{name}"
        await client.publish(topic, payload=payload, retain=True)

    async def _publish_availability(self, state: str) -> None:
        client = self._client
        if client is None:
            return

        await client.publish(
            self._availability_topic(),
            payload=state.encode("utf-8"),
            retain=True,
        )

    async def _publish_homeassistant_discovery(self, *, force: bool = False) -> None:
        client = self._client
        if client is None:
            return

        discovery = self._build_homeassistant_discovery()
        payload = _encode_json(discovery)
        if not force and self._homeassistant_discovery == payload:
            return

        topic = self._homeassistant_discovery_topic()
        await client.publish(topic, payload=payload, retain=True)
        self._homeassistant_discovery = payload
        components: dict[str, dict[str, Any]] = discovery["components"]
        controls = sum(key.startswith("control_") for key in components)
        logger.info(
            "Published Home Assistant MQTT discovery: topic=%s components=%d controls=%d",
            topic,
            len(components),
            controls,
        )

    def _build_snapshot(self) -> dict[str, bytes]:
        return dict(
            device=_encode_json(self.device.info.model_dump(mode="json")),
            state=_encode_json(self.device.state.model_dump(mode="json")),
            settings=_encode_json(self.device.settings.model_dump(mode="json")),
        )

    def _build_homeassistant_discovery(self) -> dict[str, Any]:
        return {
            "device": self._homeassistant_device(),
            "origin": {
                "name": "softener_gateway",
                "sw_version": __version__,
            },
            "state_topic": self._snapshot_topic("state"),
            "availability_topic": self._availability_topic(),
            "payload_available": "online",
            "payload_not_available": "offline",
            "components": self._homeassistant_components(),
        }

    def _homeassistant_device(self) -> dict[str, Any]:
        info = self.device.info
        device: dict[str, Any] = {
            "identifiers": [HOME_ASSISTANT_DEVICE_ID],
            "name": "Softener",
            "sw_version": __version__,
        }
        if info.model_description is not None:
            device["model"] = info.model_description
        if info.software_version is not None:
            device["hw_version"] = info.software_version
        if info.product_serial_number is not None:
            device["serial_number"] = info.product_serial_number
        elif info.serial_number is not None:
            device["serial_number"] = info.serial_number

        return device

    def _homeassistant_components(self) -> dict[str, dict[str, Any]]:
        components: dict[str, dict[str, Any]] = {}
        self._add_device_info_components(components)
        self._add_state_components(components)
        self._add_control_components(components)
        return components

    def _add_device_info_components(self, components: dict[str, dict[str, Any]]) -> None:
        topic = self._snapshot_topic("device")
        for key, name in (
            ("system_type", "System type"),
            ("model_id", "Model ID"),
            ("model_description", "Model description"),
            ("serial_number", "Serial number"),
            ("product_serial_number", "Product serial number"),
            ("software_version", "Controller software version"),
            ("esp_software_part_number", "ESP software part number"),
            ("ota_status", "OTA status"),
            ("pwa_number", "PWA number"),
            ("build_date_code", "Build date code"),
            ("build_year", "Build year"),
            ("build_day", "Build day"),
            ("build_date", "Build date"),
        ):
            components[f"device_{key}"] = self._sensor_component(
                f"device_{key}",
                name,
                topic,
                self._value_template(key),
                entity_category="diagnostic",
            )

        components["operation_time"] = self._sensor_component(
            "operation_time",
            "Operation time",
            topic,
            self._value_template("operation_time"),
            unit="d",
            device_class="duration",
            state_class="total_increasing",
            entity_category="diagnostic",
        )
        components["power_outage_count"] = self._sensor_component(
            "power_outage_count",
            "Power outage count",
            topic,
            self._value_template("power_outage_count"),
            state_class="total_increasing",
            entity_category="diagnostic",
            icon="mdi:power-plug-off",
        )
        components["time_loss_count"] = self._sensor_component(
            "time_loss_count",
            "Time loss count",
            topic,
            self._value_template("time_loss_count"),
            state_class="total_increasing",
            entity_category="diagnostic",
            icon="mdi:clock-alert-outline",
        )

    def _add_state_components(self, components: dict[str, dict[str, Any]]) -> None:
        topic = self._snapshot_topic("state")
        components["online"] = self._binary_sensor_component(
            "online",
            "Gateway online",
            topic,
            "value_json.online",
            device_class="connectivity",
            entity_category="diagnostic",
        )
        components["module_connected"] = self._binary_sensor_component(
            "module_connected",
            "Module connected",
            topic,
            "value_json.module_connected",
            device_class="connectivity",
            entity_category="diagnostic",
        )
        components["device_connected"] = self._binary_sensor_component(
            "device_connected",
            "Device connected",
            topic,
            "value_json.device_connected",
            device_class="connectivity",
            entity_category="diagnostic",
        )
        components["time"] = self._sensor_component(
            "time",
            "Device time",
            topic,
            self._value_template("time"),
            entity_category="diagnostic",
        )
        for key, name in (
            ("current_flow", "Current flow"),
            ("peak_flow", "Peak flow"),
        ):
            components[key] = self._sensor_component(
                key,
                name,
                topic,
                self._value_template(key),
                unit=self._flow_unit(),
                device_class="volume_flow_rate",
                state_class="measurement",
                icon="mdi:waves-arrow-right",
                entity_category="diagnostic" if key == "peak_flow" else None,
            )

        for key, name in (
            ("water_used_today", "Water used today"),
            ("average_daily_usage", "Average daily usage"),
            ("treated_water_available", "Treated water available"),
        ):
            components[key] = self._sensor_component(
                key,
                name,
                topic,
                self._value_template(key),
                unit=self._volume_unit(),
                state_class="measurement",
                icon="mdi:water",
                entity_category="diagnostic" if key == "average_daily_usage" else None,
            )

        for key, name in (
            ("total_outlet_water", "Total outlet water"),
            ("total_untreated_water", "Total untreated water"),
        ):
            components[key] = self._sensor_component(
                key,
                name,
                topic,
                self._value_template(key),
                unit=self._total_volume_unit(),
                device_class="water",
                state_class="total_increasing",
                icon="mdi:counter",
                entity_category="diagnostic" if key == "total_untreated_water" else None,
            )

        self._add_regeneration_state_components(components, topic)
        self._add_salt_state_components(components, topic)
        self._add_capacity_state_components(components, topic)
        self._add_hardness_removed_components(components, topic)
        self._add_daily_usage_profile_components(components, topic)

        components["wifi_signal_strength"] = self._sensor_component(
            "wifi_signal_strength",
            "Wi-Fi signal strength",
            topic,
            self._value_template("wifi_signal_strength"),
            unit="dBm",
            device_class="signal_strength",
            state_class="measurement",
            entity_category="diagnostic",
        )

        for code, error_key in ERROR_CODES.items():
            components[f"error_{error_key}"] = self._binary_sensor_component(
                f"error_{error_key}",
                error_key.replace("_", " ").title(),
                topic,
                f"value_json.errors.{error_key} | default(false)",
                device_class="problem",
                icon="mdi:alert-circle-outline",
            )
            components[f"error_{error_key}"]["object_id"] = f"softener_gateway_error_{code}"

    def _add_regeneration_state_components(
        self,
        components: dict[str, dict[str, Any]],
        topic: str,
    ) -> None:
        components["regeneration_active"] = self._binary_sensor_component(
            "regeneration_active",
            "Regeneration active",
            topic,
            "value_json.regeneration.active",
            icon="mdi:sync",
        )
        for key, name in (
            ("trigger", "Regeneration trigger"),
            ("stage", "Regeneration stage"),
        ):
            components[f"regeneration_{key}"] = self._sensor_component(
                f"regeneration_{key}",
                name,
                topic,
                self._value_template(f"regeneration.{key}"),
                entity_category="diagnostic" if key == "stage" else None,
            )

        for key, name in (
            ("remaining", "Regeneration remaining"),
            ("stage_remaining", "Regeneration stage remaining"),
        ):
            components[f"regeneration_{key}"] = self._sensor_component(
                f"regeneration_{key}",
                name,
                topic,
                self._value_template(f"regeneration.{key}"),
                unit="s",
                device_class="duration",
                state_class="measurement",
                entity_category="diagnostic" if key == "stage_remaining" else None,
            )

        components["regeneration_since_last"] = self._sensor_component(
            "regeneration_since_last",
            "Regeneration since last",
            topic,
            self._value_template("regeneration.since_last"),
            unit="d",
            device_class="duration",
            state_class="measurement",
        )
        components["regeneration_average_interval"] = self._sensor_component(
            "regeneration_average_interval",
            "Regeneration average interval",
            topic,
            self._value_template("regeneration.average_interval"),
            unit="d",
            device_class="duration",
            state_class="measurement",
            entity_category="diagnostic",
        )
        for key, name in (
            ("total_count", "Regeneration total count"),
            ("manual_count", "Regeneration manual count"),
        ):
            components[f"regeneration_{key}"] = self._sensor_component(
                f"regeneration_{key}",
                name,
                topic,
                self._value_template(f"regeneration.{key}"),
                state_class="total_increasing",
                icon="mdi:counter",
                entity_category="diagnostic",
            )

    def _add_salt_state_components(
        self,
        components: dict[str, dict[str, Any]],
        topic: str,
    ) -> None:
        components["salt_level"] = self._sensor_component(
            "salt_level",
            "Salt level",
            topic,
            self._value_template("salt.level"),
            state_class="measurement",
            icon="mdi:shaker-outline",
        )
        components["salt_low"] = self._binary_sensor_component(
            "salt_low",
            "Salt level low",
            topic,
            "value_json.salt.low",
            device_class="problem",
            icon="mdi:shaker-outline",
        )
        components["salt_remaining_estimate"] = self._sensor_component(
            "salt_remaining_estimate",
            "Salt remaining estimate",
            topic,
            self._value_template("salt.remaining_estimate"),
            unit="d",
            device_class="duration",
            state_class="measurement",
        )
        components["salt_total_used"] = self._sensor_component(
            "salt_total_used",
            "Salt total used",
            topic,
            self._value_template("salt.total_used"),
            unit=self._weight_unit(),
            device_class="weight",
            state_class="total_increasing",
            entity_category="diagnostic",
        )
        components["salt_average_per_regeneration"] = self._sensor_component(
            "salt_average_per_regeneration",
            "Salt average per regeneration",
            topic,
            self._value_template("salt.average_per_regeneration"),
            unit=self._weight_unit(),
            device_class="weight",
            state_class="measurement",
            entity_category="diagnostic",
        )
        components["salt_efficiency"] = self._sensor_component(
            "salt_efficiency",
            "Salt efficiency",
            topic,
            self._value_template("salt.efficiency"),
            unit=self._salt_efficiency_unit(),
            state_class="measurement",
            icon="mdi:chart-line",
            entity_category="diagnostic",
        )

    def _add_capacity_state_components(
        self,
        components: dict[str, dict[str, Any]],
        topic: str,
    ) -> None:
        components["capacity_operating"] = self._sensor_component(
            "capacity_operating",
            "Operating capacity",
            topic,
            self._value_template("capacity.operating"),
            unit=self._capacity_unit(),
            state_class="measurement",
            icon="mdi:battery-high",
            entity_category="diagnostic",
        )
        for key, name in (
            ("remaining", "Capacity remaining"),
            ("average_exhaustion", "Average capacity exhaustion"),
        ):
            components[f"capacity_{key}"] = self._sensor_component(
                f"capacity_{key}",
                name,
                topic,
                self._value_template(f"capacity.{key}"),
                unit="%",
                state_class="measurement",
                icon="mdi:percent",
                entity_category="diagnostic" if key == "average_exhaustion" else None,
            )

    def _add_hardness_removed_components(
        self,
        components: dict[str, dict[str, Any]],
        topic: str,
    ) -> None:
        for key, name, state_class, device_class in (
            ("since_regeneration", "Hardness removed since regeneration", "measurement", "weight"),
            ("daily_average", "Hardness removed daily average", "measurement", None),
            ("total", "Hardness removed total", "total_increasing", "weight"),
        ):
            components[f"hardness_removed_{key}"] = self._sensor_component(
                f"hardness_removed_{key}",
                name,
                topic,
                self._value_template(f"hardness_removed.{key}"),
                unit=self._hardness_removed_unit(daily=key == "daily_average"),
                device_class=device_class,
                state_class=state_class,
                entity_category="diagnostic",
            )

    def _add_daily_usage_profile_components(
        self,
        components: dict[str, dict[str, Any]],
        topic: str,
    ) -> None:
        for index in range(1, 8):
            for key, name in (
                ("average", "average"),
                ("deviation", "deviation"),
            ):
                day_key = f"day_{index}"
                component_key = f"daily_usage_{day_key}_{key}"
                components[component_key] = self._sensor_component(
                    component_key,
                    f"Daily usage {day_key.replace('_', ' ')} {name}",
                    topic,
                    (
                        "{{ value_json.daily_usage_profile."
                        f"{day_key}.{key} if value_json.daily_usage_profile.{day_key} "
                        "else none }}"
                    ),
                    unit=self._volume_unit(),
                    state_class="measurement",
                    entity_category="diagnostic",
                )

    def _add_control_components(self, components: dict[str, dict[str, Any]]) -> None:
        settings_topic = self._snapshot_topic("settings")

        components["control_start_regeneration"] = self._button_component(
            "control_start_regeneration",
            "Start regeneration",
            "start_regeneration",
            icon="mdi:sync",
        )
        components["control_set_hardness"] = self._select_component(
            "control_set_hardness",
            "Set hardness",
            "set_hardness",
            settings_topic,
            self._hardness_value_template(),
            self._hardness_options(),
            command_template='{"value": {{ value.split(" ")[0] | float }}}',
        )
        components["control_set_regen_time"] = self._select_component(
            "control_set_regen_time",
            "Set regeneration time",
            "set_regen_time",
            settings_topic,
            self._value_template("regen_time"),
            _quarter_hour_options(),
        )
        components["control_set_salt_type"] = self._select_component(
            "control_set_salt_type",
            "Set salt type",
            "set_salt_type",
            settings_topic,
            self._value_template("salt.type"),
            [value.value for value in SaltType],
        )
        components["control_set_salt_level"] = self._number_component(
            "control_set_salt_level",
            "Set salt level",
            "set_salt_level",
            settings_topic,
            self._value_template("salt.level"),
            minimum=1,
            maximum=8,
            step=0.1,
        )
        components["control_set_flow_alert_min_rate"] = self._number_component(
            "control_set_flow_alert_min_rate",
            "Set flow alert min rate",
            "set_flow_alert_min_rate",
            settings_topic,
            self._value_template("flow_alert.min_rate"),
            unit=self._flow_unit(),
            minimum=0,
            maximum=250 if self.unit_system is UnitSystem.METRIC else 70,
            step=0.1,
        )
        components["control_set_flow_alert_duration"] = self._number_component(
            "control_set_flow_alert_duration",
            "Set flow alert duration",
            "set_flow_alert_duration",
            settings_topic,
            self._value_template("flow_alert.duration"),
            unit="min",
            minimum=0,
            maximum=1080,
            step=1,
        )
        components["control_set_volume_unit"] = self._select_component(
            "control_set_volume_unit",
            "Set display volume unit",
            "set_volume_unit",
            settings_topic,
            self._value_template("display.volume_unit"),
            [value.value for value in VolumeUnit],
        )
        components["control_set_weight_unit"] = self._select_component(
            "control_set_weight_unit",
            "Set display weight unit",
            "set_weight_unit",
            settings_topic,
            self._value_template("display.weight_unit"),
            [value.value for value in WeightUnit],
        )
        components["control_set_hardness_unit"] = self._select_component(
            "control_set_hardness_unit",
            "Set display hardness unit",
            "set_hardness_unit",
            settings_topic,
            self._value_template("display.hardness_unit"),
            [value.value for value in HardnessUnit],
        )
        components["control_set_date_format"] = self._select_component(
            "control_set_date_format",
            "Set date format",
            "set_date_format",
            settings_topic,
            self._value_template("display.date_format"),
            [value.value for value in DateFormat],
        )
        components["control_set_time_format"] = self._select_component(
            "control_set_time_format",
            "Set time format",
            "set_time_format",
            settings_topic,
            self._value_template("display.time_format"),
            [value.value for value in TimeFormat],
        )
        components["control_set_aux_output_mode"] = self._select_component(
            "control_set_aux_output_mode",
            "Set aux output mode",
            "set_aux_output_mode",
            settings_topic,
            self._value_template("aux_output.mode"),
            [value.value for value in AuxOutputMode],
        )
        components["control_set_aux_chemical_feed_amount"] = self._number_component(
            "control_set_aux_chemical_feed_amount",
            "Set aux chemical feed amount",
            "set_aux_chemical_feed_amount",
            settings_topic,
            self._value_template("aux_output.chemical_feed_amount"),
            unit=self._volume_unit(),
            minimum=0,
            maximum=1000 if self.unit_system is UnitSystem.METRIC else 255,
            step=1,
        )
        components["control_set_regeneration_backwash"] = self._number_component(
            "control_set_regeneration_backwash",
            "Set regeneration backwash",
            "set_regeneration_backwash",
            settings_topic,
            self._value_template("regeneration.backwash"),
            unit="s",
            minimum=0,
            maximum=3600,
            step=1,
        )
        components["control_set_regeneration_fast_rinse"] = self._number_component(
            "control_set_regeneration_fast_rinse",
            "Set regeneration fast rinse",
            "set_regeneration_fast_rinse",
            settings_topic,
            self._value_template("regeneration.fast_rinse"),
            unit="s",
            minimum=0,
            maximum=3600,
            step=1,
        )
        components["control_set_regeneration_second_backwash"] = self._number_component(
            "control_set_regeneration_second_backwash",
            "Set regeneration second backwash",
            "set_regeneration_second_backwash",
            settings_topic,
            self._value_template("regeneration.second_backwash"),
            unit="s",
            minimum=0,
            maximum=3600,
            step=1,
        )
        components["control_set_regeneration_rinse_type"] = self._number_component(
            "control_set_regeneration_rinse_type",
            "Set regeneration rinse type",
            "set_regeneration_rinse_type",
            settings_topic,
            self._value_template("regeneration.rinse_type"),
            minimum=0,
            maximum=10,
            step=1,
        )
        components["control_set_feature_97_percent"] = self._switch_component(
            "control_set_feature_97_percent",
            "Set feature 97 percent",
            "set_feature_97_percent",
            settings_topic,
            "value_json.feature_97_percent",
        )
        components["control_set_efficiency_mode"] = self._select_component(
            "control_set_efficiency_mode",
            "Set efficiency mode",
            "set_efficiency_mode",
            settings_topic,
            self._value_template("efficiency_mode"),
            [value.value for value in EfficiencyMode],
        )
        components["control_set_max_days_between_regenerations"] = self._select_component(
            "control_set_max_days_between_regenerations",
            "Set max days between regenerations",
            "set_max_days_between_regenerations",
            settings_topic,
            self._value_template("max_days_between_regenerations"),
            ["auto", *[str(value) for value in range(1, 16)]],
            command_template=(
                '{"value": {% if value == "auto" %}"auto"{% else %}'
                "{{ value | int }}{% endif %}}"
            ),
        )

    def _sensor_component(
        self,
        key: str,
        name: str,
        state_topic: str,
        value_template: str,
        *,
        unit: str | None = None,
        device_class: str | None = None,
        state_class: str | None = None,
        icon: str | None = None,
        entity_category: str | None = None,
    ) -> dict[str, Any]:
        component: dict[str, Any] = {
            "platform": "sensor",
            "unique_id": f"{HOME_ASSISTANT_DEVICE_ID}_{key}",
            "name": name,
            "state_topic": state_topic,
            "availability_topic": self._availability_topic(),
            "value_template": value_template,
            "enabled_by_default": True,
        }
        if unit is not None:
            component["unit_of_measurement"] = unit
        if device_class is not None:
            component["device_class"] = device_class
        if state_class is not None:
            component["state_class"] = state_class
        if icon is not None:
            component["icon"] = icon
        if entity_category is not None:
            component["entity_category"] = entity_category

        return component

    def _binary_sensor_component(
        self,
        key: str,
        name: str,
        state_topic: str,
        expression: str,
        *,
        device_class: str | None = None,
        icon: str | None = None,
        entity_category: str | None = None,
    ) -> dict[str, Any]:
        component: dict[str, Any] = {
            "platform": "binary_sensor",
            "unique_id": f"{HOME_ASSISTANT_DEVICE_ID}_{key}",
            "name": name,
            "state_topic": state_topic,
            "availability_topic": self._availability_topic(),
            "payload_on": "ON",
            "payload_off": "OFF",
            "value_template": f"{{{{ 'ON' if {expression} else 'OFF' }}}}",
            "enabled_by_default": True,
        }
        if device_class is not None:
            component["device_class"] = device_class
        if icon is not None:
            component["icon"] = icon
        if entity_category is not None:
            component["entity_category"] = entity_category

        return component

    def _button_component(
        self,
        key: str,
        name: str,
        command: str,
        *,
        icon: str | None = None,
    ) -> dict[str, Any]:
        component: dict[str, Any] = {
            "platform": "button",
            "unique_id": f"{HOME_ASSISTANT_DEVICE_ID}_{key}",
            "name": name,
            "availability_topic": self._availability_topic(),
            "command_topic": self._control_topic(command),
            "payload_press": "{}",
        }
        if icon is not None:
            component["icon"] = icon

        return component

    def _number_component(
        self,
        key: str,
        name: str,
        command: str,
        state_topic: str,
        value_template: str,
        *,
        unit: str | None = None,
        minimum: float | int,
        maximum: float | int,
        step: float | int,
    ) -> dict[str, Any]:
        component: dict[str, Any] = {
            "platform": "number",
            "unique_id": f"{HOME_ASSISTANT_DEVICE_ID}_{key}",
            "name": name,
            "state_topic": state_topic,
            "availability_topic": self._availability_topic(),
            "command_topic": self._control_topic(command),
            "command_template": '{"value": {{ value }}}',
            "value_template": value_template,
            "min": minimum,
            "max": maximum,
            "step": step,
            "mode": "box",
            "entity_category": "config",
        }
        if unit is not None:
            component["unit_of_measurement"] = unit

        return component

    def _select_component(
        self,
        key: str,
        name: str,
        command: str,
        state_topic: str,
        value_template: str,
        options: list[str],
        *,
        command_template: str = '{"value":"{{ value }}"}',
    ) -> dict[str, Any]:
        return {
            "platform": "select",
            "unique_id": f"{HOME_ASSISTANT_DEVICE_ID}_{key}",
            "name": name,
            "state_topic": state_topic,
            "availability_topic": self._availability_topic(),
            "command_topic": self._control_topic(command),
            "command_template": command_template,
            "options": options,
            "value_template": value_template,
            "entity_category": "config",
        }

    def _switch_component(
        self,
        key: str,
        name: str,
        command: str,
        state_topic: str,
        expression: str,
    ) -> dict[str, Any]:
        return {
            "platform": "switch",
            "unique_id": f"{HOME_ASSISTANT_DEVICE_ID}_{key}",
            "name": name,
            "state_topic": state_topic,
            "availability_topic": self._availability_topic(),
            "command_topic": self._control_topic(command),
            "payload_on": '{"value":true}',
            "payload_off": '{"value":false}',
            "state_on": "ON",
            "state_off": "OFF",
            "value_template": f"{{{{ 'ON' if {expression} else 'OFF' }}}}",
            "entity_category": "config",
        }

    def _value_template(self, path: str) -> str:
        return f"{{{{ value_json.{path} }}}}"

    def _snapshot_topic(self, name: str) -> str:
        return f"{self.config.topic_prefix}/{name}"

    def _control_topic(self, command: str) -> str:
        return f"{self.config.topic_prefix}/control/{command}"

    def _availability_topic(self) -> str:
        return f"{self.config.topic_prefix}/availability"

    def _homeassistant_discovery_topic(self) -> str:
        return f"{HOME_ASSISTANT_DISCOVERY_PREFIX}/device/{HOME_ASSISTANT_DEVICE_ID}/config"

    def _flow_unit(self) -> str:
        return "L/min" if self.unit_system is UnitSystem.METRIC else "gal/min"

    def _volume_unit(self) -> str:
        return "L" if self.unit_system is UnitSystem.METRIC else "gal"

    def _total_volume_unit(self) -> str:
        return "m³" if self.unit_system is UnitSystem.METRIC else "gal"

    def _hardness_unit(self) -> str:
        return "ppm" if self.unit_system is UnitSystem.METRIC else "gpg"

    def _hardness_options(self) -> list[str]:
        if self.unit_system is UnitSystem.METRIC:
            return [
                _hardness_metric_option(grains)
                for grains in range(HARDNESS_MIN_GPG, HARDNESS_MAX_GPG + 1)
            ]

        return [
            _hardness_imperial_option(grains)
            for grains in range(HARDNESS_MIN_GPG, HARDNESS_MAX_GPG + 1)
        ]

    def _hardness_value_template(self) -> str:
        if self.unit_system is UnitSystem.METRIC:
            return (
                "{% set ppm = ((value_json.hardness | float / 10) | round(0) * 10) "
                "| int %}{{ ppm }} PPM ({{ (ppm / "
                f"{PPM_PER_DH}"
                ") | round(0) | int }} dH/{{ (ppm / "
                f"{PPM_PER_FH}"
                ") | round(0) | int }} fH)"
            )

        return (
            "{% set grains = (value_json.hardness | float) | round(0) | int %}"
            "{{ grains }} {{ 'grain' if grains == 1 else 'grains' }}"
        )

    def _weight_unit(self) -> str:
        return "kg" if self.unit_system is UnitSystem.METRIC else "lb"

    def _hardness_removed_unit(self, *, daily: bool = False) -> str:
        if self.unit_system is UnitSystem.METRIC:
            return "g/day" if daily else "g"

        return "lb/day" if daily else "lb"

    def _capacity_unit(self) -> str:
        return "g" if self.unit_system is UnitSystem.METRIC else "grains"

    def _salt_efficiency_unit(self) -> str:
        return "g/kg" if self.unit_system is UnitSystem.METRIC else "grains/lb"


def _encode_json(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def _decode_json_object(payload: bytes) -> dict[str, object]:
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise ControlDispatchError("payload must be a valid JSON object") from exc

    if not isinstance(data, dict):
        raise ControlDispatchError("payload must be a valid JSON object")

    return data


def _hardness_metric_option(grains: int) -> str:
    ppm = _round_to_nearest_10(grains * PPM_PER_GPG)
    dh = round(ppm / PPM_PER_DH)
    fh = round(ppm / PPM_PER_FH)
    return f"{ppm} PPM ({dh} dH/{fh} fH)"


def _hardness_imperial_option(grains: int) -> str:
    unit = "grain" if grains == 1 else "grains"
    return f"{grains} {unit}"


def _round_to_nearest_10(value: float) -> int:
    return int(((value + 5) // 10) * 10)


def _quarter_hour_options() -> list[str]:
    return [
        f"{minute // 60:02d}:{minute % 60:02d}"
        for minute in range(0, 24 * 60, 15)
    ]


__all__ = [
    "MqttApi",
]
