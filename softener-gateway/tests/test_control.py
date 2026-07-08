import asyncio
from typing import cast

from softener_gateway.config import UnitSystem
from softener_gateway.control import (
    ControlRegistry,
    DeviceControl,
    InvalidControlPayloadError,
    UnknownControlCommandError,
)
from softener_gateway.mapper import DeviceCommandMapper
from softener_gateway.models import AuxOutputMode, EfficiencyMode, SaltType, VolumeUnit


def test_device_command_mapper_base_stores_unit_system() -> None:
    mapper = DeviceCommandMapper(UnitSystem.METRIC)

    assert mapper.unit_system is UnitSystem.METRIC


def test_softener_device_command_mapper_maps_metric_settings_to_raw_request() -> None:
    mapper = DeviceCommandMapper(UnitSystem.METRIC)

    assert mapper.set_hardness(307.8) == {"hardness_grains": 18.0}
    assert mapper.set_hardness(290) == {"hardness_grains": 17.0}
    assert mapper.set_flow_alert_min_rate(15.142) == {"flow_monitor_min_rate_gpm": 40}
    assert mapper.set_aux_chemical_feed_amount(3.785) == {"chem_feed_gals": 1}
    assert mapper.set_regen_time("02:30") == {"regen_time_secs": 9000}
    assert mapper.set_salt_type(SaltType.KCL) == {"salt_type_enum": 1}
    assert mapper.set_salt_level(3.5) == {"salt_level_tenths": 35}
    assert mapper.set_salt_level(8) == {"salt_level_tenths": 80}
    assert mapper.set_volume_unit(VolumeUnit.LITERS) == {"volume_unit_enum": 1}
    assert mapper.set_aux_output_mode(AuxOutputMode.CHEMICAL_FEED) == {
        "aux_control_type_enum": 4,
    }
    assert mapper.set_feature_97_percent(True) == {"feature_97pct_enum": 1}
    assert mapper.set_efficiency_mode(EfficiencyMode.AUTO) == {"efficiency_mode_enum": 1}
    assert mapper.set_max_days_between_regenerations("auto") == {
        "max_days_between_regens": 0,
    }
    assert mapper.start_regeneration() == {"regen_status_enum": 2}


def test_device_command_mapper_rejects_unsafe_salt_level() -> None:
    mapper = DeviceCommandMapper(UnitSystem.METRIC)

    try:
        mapper.set_salt_level(8.1)
    except ValueError as exc:
        assert str(exc) == "salt level must be between 1 and 8"
    else:
        raise AssertionError("unsafe salt level was accepted")


def test_control_registry_executes_typed_command_payloads() -> None:
    asyncio.run(_control_registry_executes_typed_command_payloads())


async def _control_registry_executes_typed_command_payloads() -> None:
    registry = ControlRegistry.from_device_control()
    control = FakeDeviceControl()
    command = registry.get("set_salt_type")

    assert "Set salt type." in command.description
    assert command.payload_schema()["properties"]["value"]["enum"] == ["nacl", "kcl"]
    salt_level_schema = registry.get("set_salt_level").payload_schema()
    assert salt_level_schema["properties"]["value"]["minimum"] == 1
    assert salt_level_schema["properties"]["value"]["maximum"] == 8

    await command.execute(
        cast(DeviceControl, control),
        {"value": "kcl"},
    )
    await registry.get("set_max_days_between_regenerations").execute(
        cast(DeviceControl, control),
        {"value": "auto"},
    )
    await registry.get("start_regeneration").execute(cast(DeviceControl, control), {})

    assert control.calls == [
        ("set_salt_type", SaltType.KCL),
        ("set_max_days_between_regenerations", "auto"),
        ("start_regeneration", None),
    ]


def test_control_registry_rejects_invalid_payloads() -> None:
    registry = ControlRegistry.from_device_control()

    try:
        registry.get("missing")
    except UnknownControlCommandError:
        pass
    else:
        raise AssertionError("unknown command was accepted")

    try:
        registry.get("set_hardness").decode_payload({})
    except InvalidControlPayloadError:
        pass
    else:
        raise AssertionError("missing value was accepted")

    try:
        registry.get("start_regeneration").decode_payload({"value": 1})
    except InvalidControlPayloadError:
        pass
    else:
        raise AssertionError("unexpected value was accepted")

    try:
        registry.get("set_salt_level").decode_payload({"value": 9})
    except InvalidControlPayloadError:
        pass
    else:
        raise AssertionError("unsafe salt level was accepted")


class FakeDeviceControl:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []

    async def set_salt_type(self, value: SaltType) -> None:
        self.calls.append(("set_salt_type", value))

    async def set_max_days_between_regenerations(self, value: object) -> None:
        self.calls.append(("set_max_days_between_regenerations", value))

    async def start_regeneration(self) -> None:
        self.calls.append(("start_regeneration", None))
