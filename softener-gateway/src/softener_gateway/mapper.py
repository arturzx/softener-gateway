from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal, TypeVar, cast

from softener_gateway.config import UnitSystem
from softener_gateway.device.data import DeviceConfigurationData, DeviceHistoricalData
from softener_gateway.device.shadow import DeviceShadow
from softener_gateway.events import Event
from softener_gateway.models import (
    AuxOutputMode,
    AuxOutputSettings,
    CapacityState,
    DailyUsageProfile,
    DailyUsageProfileDay,
    DateFormat,
    DeviceInfo,
    DisplaySettings,
    EfficiencyMode,
    FlowAlertSettings,
    HardnessRemovedState,
    HardnessUnit,
    RegenerationSettings,
    RegenerationState,
    RegenerationTrigger,
    SaltSettings,
    SaltState,
    SaltType,
    Settings,
    State,
    TimeFormat,
    VolumeUnit,
    WeightUnit,
)

EnumValueT = TypeVar("EnumValueT")

US_GAL_TO_L = 3.785411784
US_GAL_TO_M3 = 0.003785411784
LB_TO_KG = 0.45359237
GRAINS_PER_LB = 7000
PPM_PER_GPG = 17.1
PUBLIC_FLOAT_PRECISION = 3
SALT_LEVEL_MIN = 1
SALT_LEVEL_MAX = 8

SALT_TYPES = {
    0: SaltType.NACL,
    1: SaltType.KCL,
}
VOLUME_UNITS = {
    0: VolumeUnit.GALLONS,
    1: VolumeUnit.LITERS,
}
WEIGHT_UNITS = {
    0: WeightUnit.LBS,
    1: WeightUnit.KILOGRAMS,
}
HARDNESS_UNITS = {
    0: HardnessUnit.GPG,
    1: HardnessUnit.PPM,
}
DATE_FORMATS = {
    0: DateFormat.MM_DD_YYYY,
    1: DateFormat.DD_MM_YYYY,
}
TIME_FORMATS = {
    0: TimeFormat.H12,
    1: TimeFormat.H24,
}
EFFICIENCY_MODES = {
    0: EfficiencyMode.SALT_SAVING,
    1: EfficiencyMode.AUTO,
}
AUX_OUTPUT_MODES = {
    0: AuxOutputMode.OFF,
    1: AuxOutputMode.BYPASS,
    2: AuxOutputMode.CHLORINE_GENERATOR,
    3: AuxOutputMode.WATER_FLOW,
    4: AuxOutputMode.CHEMICAL_FEED,
    5: AuxOutputMode.FAST_RINSE,
    6: AuxOutputMode.ON,
}
COMMAND_SALT_TYPES = {
    SaltType.NACL: 0,
    SaltType.KCL: 1,
}
COMMAND_VOLUME_UNITS = {
    VolumeUnit.GALLONS: 0,
    VolumeUnit.LITERS: 1,
}
COMMAND_WEIGHT_UNITS = {
    WeightUnit.LBS: 0,
    WeightUnit.KILOGRAMS: 1,
}
COMMAND_HARDNESS_UNITS = {
    HardnessUnit.GPG: 0,
    HardnessUnit.PPM: 1,
}
COMMAND_DATE_FORMATS = {
    DateFormat.MM_DD_YYYY: 0,
    DateFormat.DD_MM_YYYY: 1,
}
COMMAND_TIME_FORMATS = {
    TimeFormat.H12: 0,
    TimeFormat.H24: 1,
}
COMMAND_EFFICIENCY_MODES = {
    EfficiencyMode.SALT_SAVING: 0,
    EfficiencyMode.AUTO: 1,
}
COMMAND_AUX_OUTPUT_MODES = {
    AuxOutputMode.OFF: 0,
    AuxOutputMode.BYPASS: 1,
    AuxOutputMode.CHLORINE_GENERATOR: 2,
    AuxOutputMode.WATER_FLOW: 3,
    AuxOutputMode.CHEMICAL_FEED: 4,
    AuxOutputMode.FAST_RINSE: 5,
    AuxOutputMode.ON: 6,
}
REGENERATION_TRIGGERS = {
    1: RegenerationTrigger.AUTOMATIC,
    2: RegenerationTrigger.MANUAL,
}
ERROR_CODES = {
    10005: "error_code",
    10006: "flow_monitor",
    10007: "low_salt",
    10008: "service_reminder",
    10009: "excessive_water_use",
    10015: "depletion",
    10016: "shutoff_valve",
    10017: "shutoff_valve_manual_override",
    11005: "shutoff_valve_error_code",
    11007: "resin",
}
UNMAPPED_STATE_FIELDS = (
    "internet_connection_thr",
    "valve_pos_switch_enum",
    "valve_motor_state_enum",
    "current_valve_position_enum",
    "requested_valve_pos_enum",
    "aux_control_state_enum",
    "start_cam_speed_secs",
    "current_cam_speed_secs",
    "water_counter_gals",
    "rf_signal_bars",
)
UNMAPPED_SETTINGS_FIELDS = (
    "regen_status_enum",
    "chem_feed_tenths_secs",
    "user_lockout_enum",
    "iron_level_tenths_ppm",
    "regen_enable_enum",
    "internet_connection_thr",
    "salt_monitor_enum",
)


@dataclass(frozen=True, slots=True)
class DeviceDataUpdatedEvent(Event):
    pass


@dataclass(frozen=True, slots=True)
class DeviceMappingInput:
    shadow: DeviceShadow
    configuration_data: DeviceConfigurationData
    historical_data: DeviceHistoricalData
    unit_system: UnitSystem = UnitSystem.METRIC
    online: bool = False


@dataclass(slots=True)
class Device:
    info: DeviceInfo = field(default_factory=DeviceInfo)
    state: State = field(default_factory=State)
    settings: Settings = field(default_factory=Settings)

    def rebuild(self, mapper: DeviceMapper, source: DeviceMappingInput) -> None:
        mapped = mapper.map(source)
        self.info = mapped.info
        self.state = mapped.state
        self.settings = mapped.settings


class DeviceMapper:
    def map(self, source: DeviceMappingInput) -> Device:
        return Device(
            info=self.build_info(source),
            state=self.build_state(source),
            settings=self.build_settings(source),
        )

    def build_info(self, source: DeviceMappingInput) -> DeviceInfo:
        return _device_info(_state_raw(source))

    def build_state(self, source: DeviceMappingInput) -> State:
        raw = _state_raw(source)
        unit_state = _unit_state(source)
        errors = _errors_raw(source)

        regeneration_remaining = _int(raw.get("regen_time_rem_secs"))
        regeneration_status = _int(raw.get("regen_status_enum"))
        return State(
            online=source.online,
            module_connected=_bool_flag(unit_state.get("gateway_connected")),
            device_connected=_bool_flag(unit_state.get("device_connected")),
            time=_seconds_to_time(_int(raw.get("current_time_secs"))),
            current_flow=_flow(raw.get("current_water_flow_gpm"), source.unit_system),
            peak_flow=_peak_flow(raw.get("peak_water_flow_gpm"), source.unit_system),
            water_used_today=_volume(raw.get("gallons_used_today"), source.unit_system),
            average_daily_usage=_volume(raw.get("avg_daily_use_gals"), source.unit_system),
            treated_water_available=_volume(
                raw.get("treated_water_avail_gals"),
                source.unit_system,
            ),
            total_outlet_water=_total_volume(
                raw.get("total_outlet_water_gals"),
                source.unit_system,
            ),
            total_untreated_water=_total_volume(
                raw.get("total_untreated_water_gals"),
                source.unit_system,
            ),
            regeneration=RegenerationState(
                active=_regeneration_active(regeneration_remaining, regeneration_status),
                trigger=_enum(raw.get("regen_status_enum"), REGENERATION_TRIGGERS),
                remaining=regeneration_remaining,
                stage_remaining=_int(raw.get("valve_pos_time_left_secs")),
                since_last=_int(raw.get("days_since_last_regen")),
                total_count=_int(raw.get("total_regens")),
                manual_count=_int(raw.get("manual_regens")),
                average_interval=_public_float(
                    _scale(raw.get("avg_days_between_regens"), 100)
                ),
            ),
            salt=SaltState(
                level=_public_float(_scale(raw.get("salt_level_tenths"), 10)),
                low=_bool_flag(raw.get("low_salt_alert")),
                remaining_estimate=_int(raw.get("out_of_salt_estimate_days")),
                total_used=_weight(
                    _scale(raw.get("total_salt_use_lbs"), 10),
                    source.unit_system,
                ),
                average_per_regeneration=_weight(
                    _scale(raw.get("avg_salt_per_regen_lbs"), 10000),
                    source.unit_system,
                ),
                efficiency=_salt_efficiency(
                    raw.get("salt_effic_grains_per_lb"),
                    source.unit_system,
                ),
            ),
            capacity=CapacityState(
                operating=_capacity_weight(
                    raw.get("operating_capacity_grains"),
                    source.unit_system,
                ),
                remaining=_public_float(
                    _scale(raw.get("capacity_remaining_percent"), 10)
                ),
                average_exhaustion=_public_float(
                    _scale(raw.get("average_exhaustion_percent"), 10)
                ),
            ),
            hardness_removed=HardnessRemovedState(
                since_regeneration=_hardness_removed_weight(
                    _scale(raw.get("rock_removed_since_rech_lbs"), 10000),
                    source.unit_system,
                ),
                daily_average=_hardness_removed_weight(
                    _scale(raw.get("daily_avg_rock_removed_lbs"), 10000),
                    source.unit_system,
                ),
                total=_hardness_removed_weight(
                    _scale(raw.get("total_rock_removed_lbs"), 10),
                    source.unit_system,
                ),
            ),
            daily_usage_profile=_daily_usage_profile(raw, source.unit_system),
            errors=_errors(errors),
            wifi_signal_strength=_int(raw.get("rf_signal_strength_dbm")),
            unmapped=_unmapped(raw, UNMAPPED_STATE_FIELDS),
        )

    def build_settings(self, source: DeviceMappingInput) -> Settings:
        request = _optional_mapping(source.shadow.reported.get("Request")) or {}
        raw = _merge(request, source.configuration_data.fields)
        return Settings(
            timezone=_string(raw.get("tz_id")),
            hardness=_hardness(raw.get("hardness_grains"), source.unit_system),
            regen_time=_seconds_to_hour_minute(_int(raw.get("regen_time_secs"))),
            salt=SaltSettings(
                type=_enum(raw.get("salt_type_enum"), SALT_TYPES),
                level=_public_float(_scale(raw.get("salt_level_tenths"), 10)),
            ),
            flow_alert=FlowAlertSettings(
                min_rate=_flow(raw.get("flow_monitor_min_rate_gpm"), source.unit_system),
                duration=_public_float(_scale(raw.get("flow_monitor_trip_sec"), 60)),
            ),
            display=DisplaySettings(
                volume_unit=_enum(raw.get("volume_unit_enum"), VOLUME_UNITS),
                weight_unit=_enum(raw.get("weight_unit_enum"), WEIGHT_UNITS),
                hardness_unit=_enum(raw.get("hardness_unit_enum"), HARDNESS_UNITS),
                date_format=_enum(raw.get("date_format_enum"), DATE_FORMATS),
                time_format=_enum(raw.get("time_format_enum"), TIME_FORMATS),
            ),
            aux_output=AuxOutputSettings(
                mode=_enum(raw.get("aux_control_type_enum"), AUX_OUTPUT_MODES),
                chemical_feed_amount=_volume(raw.get("chem_feed_gals"), source.unit_system),
            ),
            regeneration=RegenerationSettings(
                fill=_int(raw.get("fill_secs")),
                draw=_int(raw.get("draw_secs")),
                backwash=_int(raw.get("backwash_secs")),
                fast_rinse=_int(raw.get("fast_rinse_secs")),
                second_backwash=_int(raw.get("second_backwash_secs")),
                rinse_type=_int(raw.get("rinse_type_enum")),
            ),
            feature_97_percent=_bool_flag(raw.get("feature_97pct_enum")),
            efficiency_mode=_enum(raw.get("efficiency_mode_enum"), EFFICIENCY_MODES),
            max_days_between_regenerations=_max_days_between_regenerations(
                raw.get("max_days_between_regens")
            ),
            unmapped=_unmapped(raw, UNMAPPED_SETTINGS_FIELDS),
        )


def _state_raw(source: DeviceMappingInput) -> dict[str, object]:
    reported = source.shadow.reported
    request = _optional_mapping(reported.get("Request")) or {}
    status = _optional_mapping(reported.get("Status")) or {}
    return _merge(
        request,
        source.configuration_data.fields,
        source.historical_data.totals,
        status,
    )


def _unit_state(source: DeviceMappingInput) -> Mapping[str, object]:
    return _optional_mapping(source.shadow.reported.get("UnitState")) or {}


def _errors_raw(source: DeviceMappingInput) -> Mapping[str, object]:
    return _optional_mapping(source.shadow.reported.get("Errors")) or {}


def _device_info(raw: Mapping[str, object]) -> DeviceInfo:
    build_year = _int(raw.get("build_year"))
    build_day = _int(raw.get("build_day"))
    build_date_code = _string(raw.get("build_date_code"))
    return DeviceInfo(
        system_type=_string(raw.get("system_type")),
        model_id=_int(raw.get("model_id")),
        model_description=_string(raw.get("model_description")),
        serial_number=_string(raw.get("serial_number")),
        product_serial_number=_string(raw.get("product_serial_number")),
        software_version=_string(raw.get("base_software_version")),
        esp_software_part_number=_string(raw.get("esp_software_part_number")),
        ota_status=_int(raw.get("ota_status_flag")),
        pwa_number=_string(raw.get("pwa_number")),
        build_date_code=build_date_code,
        build_year=build_year,
        build_day=build_day,
        build_date=_build_date(build_year, build_day, build_date_code),
        operation_time=_int(raw.get("days_in_operation")),
        power_outage_count=_int(raw.get("power_outage_count")),
        time_loss_count=_int(raw.get("time_lost_events")),
    )


class DeviceCommandMapper:
    def __init__(self, unit_system: UnitSystem) -> None:
        self.unit_system = unit_system

    def set_hardness(self, value: float) -> dict[str, object]:
        return {"hardness_grains": _public_hardness_to_gpg(value, self.unit_system)}

    def set_regen_time(self, value: str) -> dict[str, object]:
        return {"regen_time_secs": _hour_minute_to_seconds(value)}

    def set_salt_type(self, value: SaltType) -> dict[str, object]:
        return {"salt_type_enum": _command_enum_value(value, COMMAND_SALT_TYPES)}

    def set_salt_level(self, value: float) -> dict[str, object]:
        return {"salt_level_tenths": _salt_level_tenths(value)}

    def set_flow_alert_min_rate(self, value: float) -> dict[str, object]:
        return {
            "flow_monitor_min_rate_gpm": _flow_to_raw_tenths(
                value,
                self.unit_system,
            ),
        }

    def set_flow_alert_duration(self, value: float) -> dict[str, object]:
        return {"flow_monitor_trip_sec": round(value * 60)}

    def set_volume_unit(self, value: VolumeUnit) -> dict[str, object]:
        return {"volume_unit_enum": _command_enum_value(value, COMMAND_VOLUME_UNITS)}

    def set_weight_unit(self, value: WeightUnit) -> dict[str, object]:
        return {"weight_unit_enum": _command_enum_value(value, COMMAND_WEIGHT_UNITS)}

    def set_hardness_unit(self, value: HardnessUnit) -> dict[str, object]:
        return {"hardness_unit_enum": _command_enum_value(value, COMMAND_HARDNESS_UNITS)}

    def set_date_format(self, value: DateFormat) -> dict[str, object]:
        return {"date_format_enum": _command_enum_value(value, COMMAND_DATE_FORMATS)}

    def set_time_format(self, value: TimeFormat) -> dict[str, object]:
        return {"time_format_enum": _command_enum_value(value, COMMAND_TIME_FORMATS)}

    def set_aux_output_mode(self, value: AuxOutputMode) -> dict[str, object]:
        return {
            "aux_control_type_enum": _command_enum_value(value, COMMAND_AUX_OUTPUT_MODES),
        }

    def set_aux_chemical_feed_amount(self, value: float) -> dict[str, object]:
        return {"chem_feed_gals": _volume_to_whole_gallons(value, self.unit_system)}

    def set_regeneration_backwash(self, value: int) -> dict[str, object]:
        return {"backwash_secs": value}

    def set_regeneration_fast_rinse(self, value: int) -> dict[str, object]:
        return {"fast_rinse_secs": value}

    def set_regeneration_second_backwash(self, value: int) -> dict[str, object]:
        return {"second_backwash_secs": value}

    def set_regeneration_rinse_type(self, value: int) -> dict[str, object]:
        return {"rinse_type_enum": value}

    def set_feature_97_percent(self, value: bool) -> dict[str, object]:
        return {"feature_97pct_enum": _bool_enum(value)}

    def set_efficiency_mode(self, value: EfficiencyMode) -> dict[str, object]:
        return {
            "efficiency_mode_enum": _command_enum_value(
                value,
                COMMAND_EFFICIENCY_MODES,
            ),
        }

    def set_max_days_between_regenerations(
        self,
        value: int | Literal["auto"],
    ) -> dict[str, object]:
        return {"max_days_between_regens": 0 if value == "auto" else value}

    def start_regeneration(self) -> dict[str, object]:
        return {"regen_status_enum": 2}


def _daily_usage_profile(
    raw: Mapping[str, object],
    unit_system: UnitSystem,
) -> DailyUsageProfile:
    days: dict[str, DailyUsageProfileDay] = {}
    for index in range(1, 8):
        average = _volume(raw.get(f"avg_daily_use_day_{index}_gals"), unit_system)
        deviation = _volume(raw.get(f"avg_daily_dev_day_{index}_gals"), unit_system)
        if average is not None or deviation is not None:
            days[f"day_{index}"] = DailyUsageProfileDay(
                average=average,
                deviation=deviation,
            )

    return DailyUsageProfile(**days)


def _errors(raw: Mapping[str, object]) -> dict[str, bool]:
    return {
        ERROR_CODES.get(code, f"unknown_{code}"): bool(value)
        for raw_code, value in raw.items()
        if (code := _error_code(raw_code)) is not None and _is_integer(value)
    }


def _error_code(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _unmapped(raw: Mapping[str, object], fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: raw[field]
        for field in fields
        if field in raw
    }


def _merge(*mappings: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for mapping in mappings:
        result.update(mapping)

    return result


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None

    return cast(Mapping[str, object], value)


def _enum(
    value: object,
    values: Mapping[int, EnumValueT],
) -> EnumValueT | None:
    integer = _int(value)
    if integer is None:
        return None

    return values.get(integer)


def _public_hardness_to_gpg(value: float, unit_system: UnitSystem) -> float:
    if unit_system is UnitSystem.METRIC:
        return float(round(value / PPM_PER_GPG))

    return value


def _hour_minute_to_seconds(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 3600 + int(minute) * 60


def _tenths(value: float) -> int:
    return round(value * 10)


def _salt_level_tenths(value: float) -> int:
    if not SALT_LEVEL_MIN <= value <= SALT_LEVEL_MAX:
        raise ValueError(
            f"salt level must be between {SALT_LEVEL_MIN} and {SALT_LEVEL_MAX}"
        )

    return _tenths(value)


def _flow_to_raw_tenths(value: float, unit_system: UnitSystem) -> int:
    gallons_per_minute = value / US_GAL_TO_L if unit_system is UnitSystem.METRIC else value
    return round(gallons_per_minute * 10)


def _volume_to_whole_gallons(value: float, unit_system: UnitSystem) -> int:
    gallons = value / US_GAL_TO_L if unit_system is UnitSystem.METRIC else value
    return round(gallons)


def _bool_enum(value: bool) -> int:
    return 1 if value else 0


def _command_enum_value(value: EnumValueT, mapping: Mapping[EnumValueT, int]) -> int:
    return mapping[value]


def _max_days_between_regenerations(value: object) -> int | Literal["auto"] | None:
    integer = _int(value)
    if integer is None:
        return None
    if integer == 0:
        return "auto"

    return integer


def _regeneration_active(remaining: int | None, status: int | None) -> bool | None:
    if remaining is None and status is None:
        return None

    return (remaining or 0) > 0 or status not in (None, 0)


def _scale(value: object, divisor: float) -> float | None:
    number = _float(value)
    if number is None:
        return None

    return number / divisor


def _public_float(value: float | None) -> float | None:
    if value is None:
        return None

    return round(value, PUBLIC_FLOAT_PRECISION)


def _flow(value: object, unit_system: UnitSystem) -> float | None:
    gallons_per_minute = _scale(value, 10)
    if gallons_per_minute is None:
        return None
    if unit_system is UnitSystem.METRIC:
        return _public_float(gallons_per_minute * US_GAL_TO_L)

    return _public_float(gallons_per_minute)


def _peak_flow(value: object, unit_system: UnitSystem) -> float | None:
    gallons_per_minute = _scale(value, 100)
    if gallons_per_minute is None:
        return None
    if unit_system is UnitSystem.METRIC:
        return _public_float(gallons_per_minute * US_GAL_TO_L)

    return _public_float(gallons_per_minute)


def _volume(value: object, unit_system: UnitSystem) -> float | None:
    gallons = _float(value)
    if gallons is None:
        return None
    if unit_system is UnitSystem.METRIC:
        return _public_float(gallons * US_GAL_TO_L)

    return _public_float(gallons)


def _total_volume(value: object, unit_system: UnitSystem) -> float | None:
    gallons = _float(value)
    if gallons is None:
        return None
    if unit_system is UnitSystem.METRIC:
        return _public_float(gallons * US_GAL_TO_M3)

    return _public_float(gallons)


def _hardness(value: object, unit_system: UnitSystem) -> float | None:
    gpg = _float(value)
    if gpg is None:
        return None
    if unit_system is UnitSystem.METRIC:
        return _public_float(gpg * PPM_PER_GPG)

    return _public_float(gpg)


def _weight(value: float | None, unit_system: UnitSystem) -> float | None:
    if value is None:
        return None
    if unit_system is UnitSystem.METRIC:
        return _public_float(value * LB_TO_KG)

    return _public_float(value)


def _hardness_removed_weight(value: float | None, unit_system: UnitSystem) -> float | None:
    if value is None:
        return None
    if unit_system is UnitSystem.METRIC:
        return _public_float(value * LB_TO_KG * 1000)

    return _public_float(value)


def _capacity_weight(value: object, unit_system: UnitSystem) -> float | None:
    grains = _float(value)
    if grains is None:
        return None
    if unit_system is UnitSystem.METRIC:
        return _public_float(grains / GRAINS_PER_LB * LB_TO_KG * 1000)

    return _public_float(grains)


def _salt_efficiency(value: object, unit_system: UnitSystem) -> float | None:
    grains_per_lb = _float(value)
    if grains_per_lb is None:
        return None
    if unit_system is UnitSystem.METRIC:
        return _public_float(grains_per_lb * 1000 / GRAINS_PER_LB)

    return _public_float(grains_per_lb)


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)

    return None


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value

    return None


def _string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if _is_integer(value):
        return str(value)

    return None


def _bool_flag(value: object) -> bool | None:
    if isinstance(value, bool):
        return value

    integer = _int(value)
    if integer is None:
        return None
    if integer not in (0, 1):
        return None

    return bool(integer)


def _seconds_to_hour_minute(value: int | None) -> str | None:
    if value is None:
        return None

    hours, remainder = divmod(value, 3600)
    minutes = remainder // 60
    return f"{hours % 24:02d}:{minutes:02d}"


def _seconds_to_time(value: int | None) -> str | None:
    if value is None:
        return None

    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours % 24:02d}:{minutes:02d}:{seconds:02d}"


def _build_date(
    build_year: int | None,
    build_day: int | None,
    build_date_code: str | None,
) -> date | None:
    if build_year is not None and build_day is not None:
        return _date_from_year_day(build_year, build_day)
    if build_date_code is None or len(build_date_code) != 5 or not build_date_code.isdigit():
        return None

    return _date_from_year_day(2000 + int(build_date_code[:2]), int(build_date_code[2:]))


def _date_from_year_day(year: int, day: int) -> date | None:
    if day < 1:
        return None

    try:
        return date(year, 1, 1) + timedelta(days=day - 1)
    except ValueError:
        return None


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = [
    "Device",
    "DeviceCommandMapper",
    "DeviceDataUpdatedEvent",
    "DeviceMapper",
    "DeviceMappingInput",
    "GRAINS_PER_LB",
    "LB_TO_KG",
    "PPM_PER_GPG",
    "US_GAL_TO_L",
    "US_GAL_TO_M3",
]
