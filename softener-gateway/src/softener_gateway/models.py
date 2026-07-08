from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SaltType(StrEnum):
    """Raw `salt_type_enum`: 0 -> nacl, 1 -> kcl."""

    NACL = "nacl"
    KCL = "kcl"


class VolumeUnit(StrEnum):
    """Raw `volume_unit_enum`: 0 -> gallons, 1 -> liters."""

    GALLONS = "gallons"
    LITERS = "liters"


class WeightUnit(StrEnum):
    """Raw `weight_unit_enum`: 0 -> lbs, 1 -> kilograms."""

    LBS = "lbs"
    KILOGRAMS = "kilograms"


class HardnessUnit(StrEnum):
    """Raw `hardness_unit_enum`: 0 -> gpg, 1 -> ppm."""

    GPG = "gpg"
    PPM = "ppm"


class DateFormat(StrEnum):
    """Raw `date_format_enum`: 0 -> mm/dd/yyyy, 1 -> dd/mm/yyyy."""

    MM_DD_YYYY = "mm/dd/yyyy"
    DD_MM_YYYY = "dd/mm/yyyy"


class TimeFormat(StrEnum):
    """Raw `time_format_enum`: 0 -> 12h, 1 -> 24h."""

    H12 = "12h"
    H24 = "24h"


class EfficiencyMode(StrEnum):
    """Raw `efficiency_mode_enum`: 0 -> salt_saving, 1 -> auto."""

    SALT_SAVING = "salt_saving"
    AUTO = "auto"


class AuxOutputMode(StrEnum):
    """Raw `aux_control_type_enum`: 0..6 -> output mode."""

    OFF = "off"
    BYPASS = "bypass"
    CHLORINE_GENERATOR = "chlorine_generator"
    WATER_FLOW = "water_flow"
    CHEMICAL_FEED = "chemical_feed"
    FAST_RINSE = "fast_rinse"
    ON = "on"


class RegenerationTrigger(StrEnum):
    """Raw `regen_status_enum`: 1 -> automatic probable, 2 -> manual confirmed."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class StateModel(BaseModel, extra="forbid"):
    """Base class for public state models."""


class DeviceInfo(BaseModel, extra="forbid"):
    """Device identity and build information.

    Raw mapping:
    - `system_type` -> `system_type`.
    - `model_id` -> `model_id`.
    - `model_description` -> `model_description`.
    - `serial_number` -> `serial_number`.
    - `product_serial_number` -> `product_serial_number`.
    - `base_software_version` -> `software_version`.
    - `esp_software_part_number` -> `esp_software_part_number`.
    - `ota_status_flag` -> `ota_status`.
    - `pwa_number` -> `pwa_number`.
      PWA means Printed Wiring Assembly: controller/electronics board part number.
    - `build_date_code` -> `build_date_code`.
      Format: <YY><DDD>, where DDD is day of year. Keep as string because DDD
      may contain leading zeros.
    - `build_year` -> `build_year`.
    - `build_day` -> `build_day`.
    - `build_date`: derive from `build_year` + `build_day`; fallback to
      `build_date_code`.
    - `days_in_operation` -> `operation_time`, raw days.
    - `power_outage_count` -> `power_outage_count`.
    - `time_lost_events` -> `time_loss_count`.

    Example:
    - `build_date_code = "22151"`
    - `build_year = 2022`
    - `build_day = 151`
    - `build_date = 2022-05-31`
    """

    system_type: str | None = Field(
        default=None,
        description="Device system/category reported by the controller.",
    )
    model_id: int | None = Field(default=None, description="Numeric device model identifier.")
    model_description: str | None = Field(
        default=None,
        description="Human-readable device model name.",
    )

    serial_number: str | None = Field(
        default=None,
        description="Controller or valve serial number.",
    )
    product_serial_number: str | None = Field(
        default=None,
        description="Product serial number for the complete softener unit.",
    )

    software_version: str | None = Field(
        default=None,
        description="Base controller firmware/software version.",
    )
    esp_software_part_number: str | None = Field(
        default=None,
        description="ESP communication module software part number.",
    )
    ota_status: int | None = Field(
        default=None,
        description="OTA update status flag reported by the device.",
    )

    pwa_number: str | None = Field(
        default=None,
        description="Printed Wiring Assembly/controller board part number.",
    )

    build_date_code: str | None = Field(
        default=None,
        description="Manufacturing/build date code in YYDDD format.",
    )
    build_year: int | None = Field(default=None, description="Manufacturing/build year.")
    build_day: int | None = Field(
        default=None,
        description="Manufacturing/build day of year.",
    )
    build_date: date | None = Field(default=None, description="Manufacturing/build date.")

    operation_time: int | None = Field(
        default=None,
        description="Total device operation time, in days.",
    )
    power_outage_count: int | None = Field(
        default=None,
        description="Total number of recorded power outages.",
    )
    time_loss_count: int | None = Field(
        default=None,
        description="Total number of recorded clock/time-loss events.",
    )


class RegenerationState(StateModel):
    """Current and historical regeneration state.

    Raw mapping:
    - `regen_status_enum`:
      1 -> `RegenerationTrigger.AUTOMATIC`, probable.
      2 -> `RegenerationTrigger.MANUAL`, confirmed.
      0/missing -> `trigger` is None.
    - `active`: True if `regen_time_rem_secs > 0` or raw regeneration status
      indicates active regeneration; otherwise False.
    - `regen_time_rem_secs` -> `remaining`, raw seconds.
    - `valve_pos_time_left_secs` -> `stage_remaining`, raw seconds.
    - `days_since_last_regen` -> `since_last`, raw days.
    - `total_regens` -> `total_count`.
    - `manual_regens` -> `manual_count`.
    - `avg_days_between_regens`: raw / 100 days -> `average_interval`.

    Stage mapping:
    - `current_valve_position_enum`, `requested_valve_pos_enum`,
      `valve_motor_state_enum` are not decoded yet.
    - For now keep raw values in `State.unmapped`.
    - Optionally later: `current_valve_position_enum == 0` may be "SERVICE";
      otherwise stage remains "UNKNOWN" or None until decoded.
    """

    active: bool | None = Field(
        default=None,
        description="Whether a regeneration cycle is currently active.",
    )
    trigger: RegenerationTrigger | None = Field(
        default=None,
        description="Current or last regeneration trigger type when known.",
    )
    stage: str | None = Field(
        default=None,
        description="Current regeneration stage when decoded.",
    )

    remaining: int | None = Field(
        default=None,
        description="Time remaining in the current regeneration, in seconds.",
    )
    stage_remaining: int | None = Field(
        default=None,
        description="Time remaining in the current regeneration stage, in seconds.",
    )

    since_last: int | None = Field(
        default=None,
        description="Time since the previous regeneration, in days.",
    )
    total_count: int | None = Field(
        default=None,
        description="Total number of completed regenerations.",
    )
    manual_count: int | None = Field(
        default=None,
        description="Total number of manual regenerations.",
    )
    average_interval: float | None = Field(
        default=None,
        description="Average interval between regenerations, in days.",
    )


class SaltState(StateModel):
    """Runtime salt state and salt usage counters.

    Raw mapping:
    - `salt_level_tenths`: raw / 10 -> `level`.
      Example: 30 -> 3.0.
    - `low_salt_alert`: 0 -> False, 1 -> True -> `low`.
    - `out_of_salt_estimate_days` -> `remaining_estimate`, raw days.
    - `total_salt_use_lbs`: raw / 10 lb -> `total_used`.
      Metric value: lb * 0.45359237 kg.
    - `avg_salt_per_regen_lbs`: raw / 10000 lb -> `average_per_regeneration`.
      Metric value: lb * 0.45359237 kg.
    - `salt_effic_grains_per_lb`: raw grains/lb -> `efficiency`.
      Imperial value: raw grains/lb.
      Metric value: raw * 1000 / 7000 g/kg.

    Observed validation:
    - 28300 / 10000 = 2.83 lb
    - 2.83 lb = 1.28 kg
    """

    level: float | None = Field(
        default=None,
        description="Current salt level on the device scale.",
    )
    low: bool | None = Field(default=None, description="Whether the low-salt alert is active.")
    remaining_estimate: int | None = Field(
        default=None,
        description="Estimated time remaining until salt depletion, in days.",
    )
    total_used: float | None = Field(
        default=None,
        description="Total salt used, kg / lb.",
    )
    average_per_regeneration: float | None = Field(
        default=None,
        description="Average salt used per regeneration, kg / lb.",
    )
    efficiency: float | None = Field(
        default=None,
        description="Softening efficiency, g/kg / grains/lb.",
    )


class CapacityState(StateModel):
    """Softening capacity state.

    Raw mapping:
    - `operating_capacity_grains`: raw grains -> `operating`.
      Imperial value: grains.
      Metric value: grains / 7000 * 453.59237 g.
      Meaning: effective full-cycle softening capacity, not consumed capacity.
      Example: 9000 grains / 18 gpg = 500 gal available.
    - `capacity_remaining_percent`: raw / 10 percent -> `remaining`.
      Example: 850 -> 85.0.
    - `average_exhaustion_percent`: raw / 10 percent -> `average_exhaustion`.
      Example: 910 -> 91.0.

    Meaning:
    - `average_exhaustion` is average cycle capacity exhaustion before regeneration,
      not resin lifetime wear.
    """

    operating: float | None = Field(
        default=None,
        description="Effective operating softening capacity, g / grains.",
    )
    remaining: float | None = Field(
        default=None,
        description="Remaining operating capacity, in percent.",
    )
    average_exhaustion: float | None = Field(
        default=None,
        description="Average capacity exhaustion before regeneration, in percent.",
    )


class HardnessRemovedState(StateModel):
    """Removed hardness/mineral counters.

    Raw mapping:
    - `rock_removed_since_rech_lbs`: raw / 10000 lb -> `since_regeneration`.
      Metric value: lb * 453.59237 g.
    - `daily_avg_rock_removed_lbs`: raw / 10000 lb/day -> `daily_average`.
      Metric value: lb/day * 453.59237 g/day.
    - `total_rock_removed_lbs`: raw / 10 lb -> `total`.
      Metric value: lb * 453.59237 g.

    Domain meaning:
    - `rock` means removed hardness/minerals, likely CaCO3 equivalent.
    - `since_rech` means since recharge, i.e. since last regeneration.

    Observed validation:
    - `total_rock_removed_lbs = 1853`
    - 1853 / 10 = 185.3 lb
    - 185.3 lb * 7000 = 1,297,100 grains
    - 1,297,100 / 72079 gal = 17.99 gpg
    - 17.99 * 17.1 = 307.6 ppm
    """

    since_regeneration: float | None = Field(
        default=None,
        description="Removed hardness/minerals since the last regeneration, g / lb.",
    )
    daily_average: float | None = Field(
        default=None,
        description="Average daily removed hardness/minerals, g/day / lb/day.",
    )
    total: float | None = Field(
        default=None,
        description="Total removed hardness/minerals, g / lb.",
    )


class DailyUsageProfileDay(StateModel):
    """Single daily usage profile bucket.

    Raw mapping:
    - `avg_daily_use_day_X_gals` -> `average`.
    - `avg_daily_dev_day_X_gals` -> `deviation`.

    Raw unit:
    - US gallons.
    - Imperial value: gallons.
    - Metric value: gallons * 3.785411784 liters.

    Meaning:
    - `avg_daily_dev_day_X_gals` likely means deviation, variability, or safety
      margin. Do not call it standard deviation until confirmed.
    """

    average: float | None = Field(
        default=None,
        description="Average water usage for this profile day, L / US gal.",
    )
    deviation: float | None = Field(
        default=None,
        description="Usage deviation or safety margin for this profile day, L / US gal.",
    )


class DailyUsageProfile(StateModel):
    """Daily usage profile.

    Keep neutral day names. Do not guess whether day_1 is Monday or Sunday.

    Raw mapping:
    - `avg_daily_use_day_1_gals` -> `day_1.average`
    - `avg_daily_use_day_2_gals` -> `day_2.average`
    - `avg_daily_use_day_3_gals` -> `day_3.average`
    - `avg_daily_use_day_4_gals` -> `day_4.average`
    - `avg_daily_use_day_5_gals` -> `day_5.average`
    - `avg_daily_use_day_6_gals` -> `day_6.average`
    - `avg_daily_use_day_7_gals` -> `day_7.average`
    - `avg_daily_dev_day_1_gals` -> `day_1.deviation`
    - `avg_daily_dev_day_2_gals` -> `day_2.deviation`
    - `avg_daily_dev_day_3_gals` -> `day_3.deviation`
    - `avg_daily_dev_day_4_gals` -> `day_4.deviation`
    - `avg_daily_dev_day_5_gals` -> `day_5.deviation`
    - `avg_daily_dev_day_6_gals` -> `day_6.deviation`
    - `avg_daily_dev_day_7_gals` -> `day_7.deviation`
    """

    day_1: DailyUsageProfileDay | None = Field(
        default=None,
        description="Daily usage profile bucket 1.",
    )
    day_2: DailyUsageProfileDay | None = Field(
        default=None,
        description="Daily usage profile bucket 2.",
    )
    day_3: DailyUsageProfileDay | None = Field(
        default=None,
        description="Daily usage profile bucket 3.",
    )
    day_4: DailyUsageProfileDay | None = Field(
        default=None,
        description="Daily usage profile bucket 4.",
    )
    day_5: DailyUsageProfileDay | None = Field(
        default=None,
        description="Daily usage profile bucket 5.",
    )
    day_6: DailyUsageProfileDay | None = Field(
        default=None,
        description="Daily usage profile bucket 6.",
    )
    day_7: DailyUsageProfileDay | None = Field(
        default=None,
        description="Daily usage profile bucket 7.",
    )


class State(StateModel):
    """Runtime state, counters, statistics, and errors.

    Sources:
    - shadow `reported.Status`
    - shadow `reported.UnitState`
    - shadow `reported.Errors`

    Do not use `data/historical/.../errors` to build `errors`.

    Top-level raw mapping:
    - `online`: runtime endpoint/bridge state, not directly from shadow.
    - `UnitState.gateway_connected` -> `module_connected`.
      Public name avoids confusion with softener-gateway itself.
    - `UnitState.device_connected` -> `device_connected`.
    - `current_time_secs`: seconds from midnight -> `time` as "HH:MM:SS".
    - `current_water_flow_gpm`: raw = GPM * 10 -> `current_flow`.
      Imperial value: raw / 10 gal/min.
      Metric value: raw / 10 * 3.785411784 L/min.
    - `peak_water_flow_gpm`: observed raw = GPM * 100 -> `peak_flow`.
      Imperial value: raw / 100 gal/min.
      Metric value: raw / 100 * 3.785411784 L/min.
    - `gallons_used_today`: raw US gallons -> `water_used_today`.
      Metric value: gallons * 3.785411784 liters.
    - `avg_daily_use_gals`: raw US gallons -> `average_daily_usage`.
      Metric value: gallons * 3.785411784 liters.
    - `treated_water_avail_gals`: raw US gallons -> `treated_water_available`.
      Metric value: gallons * 3.785411784 liters.
    - `total_outlet_water_gals`: raw US gallons -> `total_outlet_water`.
      Metric value: gallons * 0.003785411784 cubic meters.
    - `total_untreated_water_gals`: raw US gallons -> `total_untreated_water`.
      Metric value: gallons * 0.003785411784 cubic meters.
    - `rf_signal_strength_dbm` -> `wifi_signal_strength`.
    - `reported.Errors` -> `errors`.
      Known raw error codes map to semantic keys; unknown codes use keys like
      `unknown_<code>`. Raw 0 -> False, raw 1 -> True.

    Explicitly ignored AWS Shadow plumbing:
    - `clientToken`, `version`, `timestamp`, `metadata`, `desired`, `reported`, `state`.

    Internal live mode fields not public:
    - `app_active`, `service_active`, `app_active_timeout`.

    `unmapped` raw fields for now:
    - `internet_connection_thr`
    - `valve_pos_switch_enum`
    - `valve_motor_state_enum`
    - `current_valve_position_enum`
    - `requested_valve_pos_enum`
    - `aux_control_state_enum`
    - `start_cam_speed_secs`
    - `current_cam_speed_secs`
    - `water_counter_gals`
    - `rf_signal_bars`

    Unmapped notes:
    - Valve/motor enum fields are likely used later to decode regeneration stage.
    - `valve_pos_switch_enum` is likely valve position switch / limit switch state.
    - `start_cam_speed_secs` and `current_cam_speed_secs` are likely cam/valve
      diagnostics. Unit appears to be seconds despite "speed" in the raw name.
    - `water_counter_gals` is observed close/equal to `total_outlet_water_gals`.
    - `rf_signal_bars` is not public; public model uses dBm.
    """

    online: bool = Field(
        default=False,
        description="Whether the gateway currently considers the device online.",
    )

    module_connected: bool | None = Field(
        default=None,
        description="Whether the device reports cloud/module connectivity.",
    )
    device_connected: bool | None = Field(
        default=None,
        description="Whether the device reports softener/controller connectivity.",
    )

    time: str | None = Field(
        default=None,
        description="Current device local time, formatted as HH:MM:SS.",
    )

    current_flow: float | None = Field(
        default=None,
        description="Current water flow, L/min / US gal/min.",
    )
    peak_flow: float | None = Field(
        default=None,
        description="Peak water flow, L/min / US gal/min.",
    )
    water_used_today: float | None = Field(
        default=None,
        description="Water used today, L / US gal.",
    )
    average_daily_usage: float | None = Field(
        default=None,
        description="Average daily water usage, L / US gal.",
    )
    treated_water_available: float | None = Field(
        default=None,
        description="Estimated treated water remaining, L / US gal.",
    )
    total_outlet_water: float | None = Field(
        default=None,
        description="Lifetime treated/outlet water total, m^3 / US gal.",
    )
    total_untreated_water: float | None = Field(
        default=None,
        description="Lifetime untreated water total, m^3 / US gal.",
    )

    regeneration: RegenerationState = Field(
        default_factory=RegenerationState,
        description="Current and historical regeneration state.",
    )
    salt: SaltState = Field(
        default_factory=SaltState,
        description="Runtime salt state and salt usage counters.",
    )
    capacity: CapacityState = Field(
        default_factory=CapacityState,
        description="Softening capacity state.",
    )
    hardness_removed: HardnessRemovedState = Field(
        default_factory=HardnessRemovedState,
        description="Removed hardness/mineral counters.",
    )
    daily_usage_profile: DailyUsageProfile = Field(
        default_factory=DailyUsageProfile,
        description="Seven-bucket daily usage profile.",
    )

    errors: dict[str, bool] = Field(
        default_factory=dict,
        description="Current reported alert/error states keyed by semantic error name.",
    )

    wifi_signal_strength: int | None = Field(
        default=None,
        description="Wi-Fi signal strength, in dBm.",
    )

    unmapped: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw fields not yet represented by the public state model.",
    )


class SettingsModel(BaseModel, extra="forbid"):
    """Base class for public settings models."""


class SaltSettings(SettingsModel):
    """Salt settings.

    Raw mapping:
    - `salt_type_enum`: 0 -> `SaltType.NACL`, 1 -> `SaltType.KCL`.
    - `salt_level_tenths`: raw / 10 -> `level`.
      Example: 30 -> 3.0.
    """

    type: SaltType | None = Field(default=None, description="Configured salt type.")
    level: float | None = Field(
        default=None,
        description="Configured salt level on the device scale.",
    )


class FlowAlertSettings(SettingsModel):
    """Flow alert settings.

    Raw mapping:
    - `flow_monitor_min_rate_gpm`: raw = GPM * 10.
      Imperial value: raw / 10 gal/min.
      Metric value: raw / 10 * 3.785411784 L/min.
    - `flow_monitor_trip_sec`: raw seconds.
      Model `duration` is minutes: raw / 60.
      Examples: 60 -> 1, 1200 -> 20, 64800 -> 1080.
    """

    min_rate: float | None = Field(
        default=None,
        description="Flow alert threshold, L/min / US gal/min.",
    )
    duration: float | None = Field(
        default=None,
        description="Flow alert duration, in minutes.",
    )


class DisplaySettings(SettingsModel):
    """Display and preferred unit settings.

    Raw mapping:
    - `volume_unit_enum`: 0 -> "gallons", 1 -> "liters".
    - `weight_unit_enum`: 0 -> "lbs", 1 -> "kilograms".
    - `hardness_unit_enum`: 0 -> "gpg", 1 -> "ppm".
    - `date_format_enum`: 0 -> "mm/dd/yyyy", 1 -> "dd/mm/yyyy".
    - `time_format_enum`: 0 -> "12h", 1 -> "24h".
    """

    volume_unit: VolumeUnit | None = Field(
        default=None,
        description="Device display volume unit preference.",
    )
    weight_unit: WeightUnit | None = Field(
        default=None,
        description="Device display weight unit preference.",
    )
    hardness_unit: HardnessUnit | None = Field(
        default=None,
        description="Device display hardness unit preference.",
    )
    date_format: DateFormat | None = Field(
        default=None,
        description="Device display date format preference.",
    )
    time_format: TimeFormat | None = Field(
        default=None,
        description="Device display time format preference.",
    )


class AuxOutputSettings(SettingsModel):
    """Auxiliary output settings.

    Raw mapping:
    - `aux_control_type_enum`:
      0 off, 1 bypass, 2 chlorine_generator, 3 water_flow,
      4 chemical_feed, 5 fast_rinse, 6 on.
    - `chem_feed_gals`: raw whole US gallons.
      Imperial value: raw gallons.
      Metric value: raw * 3.785411784 liters.

    Observed examples:
    - 4 L UI -> `chem_feed_gals = 1`
    - 23 L UI -> `chem_feed_gals = 6`
    - 965 L UI -> `chem_feed_gals = 255`
    """

    mode: AuxOutputMode | None = Field(
        default=None,
        description="Auxiliary output operating mode.",
    )
    chemical_feed_amount: float | None = Field(
        default=None,
        description="Chemical feed amount, L / US gal.",
    )


class RegenerationSettings(SettingsModel):
    """Durable regeneration cycle settings.

    Raw mapping:
    - `fill_secs` -> `fill`, raw seconds.
      Meaning: likely brine tank fill duration.
    - `draw_secs` -> `draw`, raw seconds.
      Meaning: likely brine draw duration.
    - `backwash_secs` -> `backwash`, raw seconds.
    - `fast_rinse_secs` -> `fast_rinse`, raw seconds.
    - `second_backwash_secs` -> `second_backwash`, raw seconds.
    - `rinse_type_enum` -> `rinse_type`.
      Raw enum value kept as integer until decoded.
    """

    fill: int | None = Field(
        default=None,
        description="Brine tank fill duration, in seconds.",
    )
    draw: int | None = Field(
        default=None,
        description="Brine draw duration, in seconds.",
    )
    backwash: int | None = Field(
        default=None,
        description="Backwash duration, in seconds.",
    )
    fast_rinse: int | None = Field(
        default=None,
        description="Fast rinse duration, in seconds.",
    )
    second_backwash: int | None = Field(
        default=None,
        description="Second backwash duration, in seconds.",
    )
    rinse_type: int | None = Field(
        default=None,
        description="Rinse type code; not decoded yet.",
    )


class Settings(SettingsModel):
    """Durable softener settings and preferences.

    Source of truth:
    - Primary: `data/configuration/10/45`.
    - Fallback: shadow `reported.Request`.
    - Do not use shadow `desired.Request` as final truth; it is desired/pending state.

    Raw mapping:
    - `tz_id` -> `timezone`; example: "Europe/Warsaw".
    - `tz_dev`: internal/generated from timezone, not exposed.
    - `hardness_grains`: raw GPG -> `hardness`.
      Imperial value: raw gpg.
      Metric value: raw * 17.1 ppm.
      Observed: 18.1 gpg ~= 310 ppm, 35.1 gpg ~= 600 ppm, 80 gpg ~= 1370 ppm.
    - `regen_time_secs`: seconds from midnight -> `regen_time` as "HH:MM".
      Examples: 7200 -> "02:00", 18000 -> "05:00".
    - `fill_secs`, `draw_secs`, `backwash_secs`,
      `fast_rinse_secs`, `second_backwash_secs`:
      regeneration cycle durations in raw seconds -> `regeneration`.
    - `feature_97pct_enum`: 0 -> False, 1 -> True.
    - `efficiency_mode_enum`: 0 -> "salt_saving", 1 -> "auto".
    - `max_days_between_regens`: 0 -> "auto", 1..15 -> integer days.
    - `rinse_type_enum`: raw enum value -> `regeneration.rinse_type`.

    Not public settings:
    - `unit_system`: gateway/application preference, not a softener setting.
    - `app_active`, `service_active`, `app_active_timeout`: internal live mode.

    `unmapped` raw fields for now:
    - `regen_status_enum`
    - `chem_feed_tenths_secs`
    - `user_lockout_enum`
    - `iron_level_tenths_ppm`
    - `regen_enable_enum`
    - `internet_connection_thr`
    - `salt_monitor_enum`
    """

    timezone: str | None = Field(
        default=None,
        description="IANA timezone identifier used by the device.",
    )
    hardness: float | None = Field(
        default=None,
        description="Configured water hardness, ppm / gpg.",
    )
    regen_time: str | None = Field(
        default=None,
        description="Scheduled regeneration start time, formatted as HH:MM.",
    )

    salt: SaltSettings = Field(
        default_factory=SaltSettings,
        description="Salt-related durable settings.",
    )
    flow_alert: FlowAlertSettings = Field(
        default_factory=FlowAlertSettings,
        description="Water flow alert settings.",
    )
    display: DisplaySettings = Field(
        default_factory=DisplaySettings,
        description="Device display and unit preferences.",
    )
    aux_output: AuxOutputSettings = Field(
        default_factory=AuxOutputSettings,
        description="Auxiliary output settings.",
    )
    regeneration: RegenerationSettings = Field(
        default_factory=RegenerationSettings,
        description="Durable regeneration cycle settings.",
    )

    feature_97_percent: bool | None = Field(
        default=None,
        description="Whether the 97 percent capacity feature is enabled.",
    )
    efficiency_mode: EfficiencyMode | None = Field(
        default=None,
        description="Regeneration efficiency mode.",
    )
    max_days_between_regenerations: int | Literal["auto"] | None = Field(
        default=None,
        description="Maximum interval between regenerations, in days, or auto.",
    )

    unmapped: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw settings not yet represented by the public settings model.",
    )


__all__ = [
    "AuxOutputMode",
    "AuxOutputSettings",
    "CapacityState",
    "DailyUsageProfile",
    "DailyUsageProfileDay",
    "DateFormat",
    "DeviceInfo",
    "EfficiencyMode",
    "FlowAlertSettings",
    "HardnessRemovedState",
    "HardnessUnit",
    "RegenerationSettings",
    "RegenerationState",
    "RegenerationTrigger",
    "SaltSettings",
    "SaltState",
    "SaltType",
    "Settings",
    "SettingsModel",
    "State",
    "StateModel",
    "TimeFormat",
    "VolumeUnit",
    "WeightUnit",
]
