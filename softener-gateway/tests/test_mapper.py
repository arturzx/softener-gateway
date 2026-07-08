from softener_gateway.config import UnitSystem
from softener_gateway.device.data import DeviceConfigurationData, DeviceHistoricalData
from softener_gateway.device.shadow import DeviceShadow
from softener_gateway.mapper import (
    GRAINS_PER_LB,
    LB_TO_KG,
    PPM_PER_GPG,
    US_GAL_TO_L,
    US_GAL_TO_M3,
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


def test_softener_device_mapper_builds_public_state_and_settings() -> None:
    shadow = DeviceShadow(clock=lambda: 1)
    shadow.apply_reported(
        {
            "Request": {
                "hardness_grains": 17,
                "regen_time_secs": 3600,
            },
            "Status": {
                "current_time_secs": 66178,
                "current_water_flow_gpm": 15,
                "avg_daily_use_gals": 40,
                "gallons_used_today": 38,
                "treated_water_avail_gals": 438,
                "rf_signal_strength_dbm": -59,
                "regen_time_rem_secs": 0,
                "app_active": 1,
                "rf_signal_bars": 3,
            },
            "UnitState": {
                "gateway_connected": True,
                "device_connected": True,
            },
            "Errors": {
                "10005": 0,
                "10006": 0,
                "10007": 1,
                "10008": 0,
                "10009": 1,
                "10015": 0,
                "10016": 1,
                "10017": 0,
                "11005": 1,
                "11007": 0,
                "99999": 1,
            },
        },
    )
    configuration_data = DeviceConfigurationData(
        fields={
            "thing_name": "10_45_356489-Thing",
            "hardness_grains": 18,
            "regen_time_secs": 7200,
            "regen_status_enum": 0,
            "salt_type_enum": 0,
            "salt_level_tenths": 30,
            "flow_monitor_min_rate_gpm": 40,
            "flow_monitor_trip_sec": 1200,
            "fill_secs": 0,
            "draw_secs": 0,
            "backwash_secs": 660,
            "fast_rinse_secs": 300,
            "second_backwash_secs": 660,
            "rinse_type_enum": 1,
            "volume_unit_enum": 1,
            "weight_unit_enum": 1,
            "hardness_unit_enum": 1,
            "date_format_enum": 1,
            "time_format_enum": 1,
            "chem_feed_tenths_secs": 1,
            "user_lockout_enum": 0,
            "iron_level_tenths_ppm": 0,
            "efficiency_mode_enum": 1,
            "regen_enable_enum": 1,
            "internet_connection_thr": 5,
            "salt_monitor_enum": 1,
            "max_days_between_regens": 0,
            "aux_control_type_enum": 4,
            "chem_feed_gals": 1,
            "feature_97pct_enum": 0,
            "total_regens": 162,
            "manual_regens": 20,
            "days_in_operation": 1385,
            "avg_days_between_regens": 1009,
            "days_since_last_regen": 1,
            "total_salt_use_lbs": 4599,
            "salt_effic_grains_per_lb": 2821,
            "avg_salt_per_regen_lbs": 28300,
            "out_of_salt_estimate_days": 256,
            "operating_capacity_grains": 9232,
            "capacity_remaining_percent": 855,
            "average_exhaustion_percent": 910,
            "peak_water_flow_gpm": 1446,
            "total_rock_removed_lbs": 1853,
            "daily_avg_rock_removed_lbs": 1028,
            "rock_removed_since_rech_lbs": 1902,
            "total_untreated_water_gals": 57,
            "power_outage_count": 329,
            "time_lost_events": 10,
            "avg_daily_use_day_1_gals": 38,
            "avg_daily_dev_day_1_gals": 6,
            "build_date_code": 22151,
            "build_year": 2022,
            "build_day": 151,
        },
    )
    historical_data = DeviceHistoricalData(
        totals={"total_outlet_water_gals": 72139},
    )

    device = DeviceMapper().map(
        DeviceMappingInput(
            shadow=shadow,
            configuration_data=configuration_data,
            historical_data=historical_data,
            unit_system=UnitSystem.IMPERIAL,
            online=True,
        )
    )

    assert device.state.online
    assert device.state.module_connected
    assert device.state.device_connected
    assert device.state.time == "18:22:58"
    assert device.state.current_flow == 1.5
    assert device.state.peak_flow == 14.46
    assert device.state.water_used_today == 38
    assert device.state.average_daily_usage == 40
    assert device.state.total_outlet_water == 72139
    assert device.state.total_untreated_water == 57
    assert device.state.regeneration.active is False
    assert device.state.regeneration.since_last == 1
    assert device.state.regeneration.total_count == 162
    assert device.state.regeneration.average_interval == 10.09
    assert device.state.salt.level == 3
    assert device.state.salt.remaining_estimate == 256
    assert device.state.salt.total_used == 459.9
    assert device.state.salt.average_per_regeneration == 2.83
    assert device.state.salt.efficiency == 2821
    assert device.state.capacity.operating == 9232
    assert device.state.capacity.remaining == 85.5
    assert device.state.hardness_removed.total == 185.3
    assert device.state.hardness_removed.daily_average == 0.103
    assert device.state.daily_usage_profile.day_1 is not None
    assert device.state.daily_usage_profile.day_1.average == 38
    assert device.state.daily_usage_profile.day_1.deviation == 6
    assert device.state.errors == {
        "error_code": False,
        "flow_monitor": False,
        "low_salt": True,
        "service_reminder": False,
        "excessive_water_use": True,
        "depletion": False,
        "shutoff_valve": True,
        "shutoff_valve_manual_override": False,
        "shutoff_valve_error_code": True,
        "resin": False,
        "unknown_99999": True,
    }
    assert device.state.wifi_signal_strength == -59
    assert device.info.build_date is not None
    assert device.info.build_date.isoformat() == "2022-05-31"
    assert "thing_name" not in device.info.model_dump()
    assert device.info.operation_time == 1385
    assert device.info.power_outage_count == 329
    assert device.info.time_loss_count == 10
    assert device.state.unmapped == {
        "internet_connection_thr": 5,
        "rf_signal_bars": 3,
    }
    state_dump = device.state.model_dump(mode="json")
    assert "device" not in state_dump
    assert state_dump["regeneration"]["since_last"] == 1
    assert "days_since_last" not in state_dump["regeneration"]
    assert "durations" not in state_dump["regeneration"]
    assert state_dump["salt"]["remaining_estimate"] == 256
    assert "days_remaining_estimate" not in state_dump["salt"]

    assert device.settings.hardness == 18
    assert device.settings.regen_time == "02:00"
    assert device.settings.salt.type is SaltType.NACL
    assert device.settings.salt.level == 3
    assert device.settings.flow_alert.min_rate == 4
    assert device.settings.flow_alert.duration == 20
    assert device.settings.regeneration.fill == 0
    assert device.settings.regeneration.draw == 0
    assert device.settings.regeneration.backwash == 660
    assert device.settings.regeneration.fast_rinse == 300
    assert device.settings.regeneration.second_backwash == 660
    assert device.settings.regeneration.rinse_type == 1
    assert device.settings.display.volume_unit is VolumeUnit.LITERS
    assert device.settings.display.weight_unit is WeightUnit.KILOGRAMS
    assert device.settings.display.hardness_unit is HardnessUnit.PPM
    assert device.settings.display.date_format is DateFormat.DD_MM_YYYY
    assert device.settings.display.time_format is TimeFormat.H24
    assert device.settings.efficiency_mode is EfficiencyMode.AUTO
    assert device.settings.max_days_between_regenerations == "auto"
    assert device.settings.aux_output.mode is AuxOutputMode.CHEMICAL_FEED
    assert device.settings.aux_output.chemical_feed_amount == 1
    assert device.settings.feature_97_percent is False
    assert device.settings.unmapped == {
        "regen_status_enum": 0,
        "chem_feed_tenths_secs": 1,
        "user_lockout_enum": 0,
        "iron_level_tenths_ppm": 0,
        "regen_enable_enum": 1,
        "internet_connection_thr": 5,
        "salt_monitor_enum": 1,
    }
    assert device.settings.model_dump(mode="json")["salt"]["type"] == "nacl"
    assert device.settings.model_dump(mode="json")["display"] == {
        "volume_unit": "liters",
        "weight_unit": "kilograms",
        "hardness_unit": "ppm",
        "date_format": "dd/mm/yyyy",
        "time_format": "24h",
    }
    assert device.settings.model_dump(mode="json")["efficiency_mode"] == "auto"
    assert device.settings.model_dump(mode="json")["aux_output"]["mode"] == "chemical_feed"


def test_softener_device_mapper_converts_public_values_to_metric_units() -> None:
    shadow = DeviceShadow(clock=lambda: 1)
    shadow.apply_reported(
        {
            "Status": {
                "current_water_flow_gpm": 15,
                "avg_daily_use_gals": 40,
                "gallons_used_today": 38,
                "treated_water_avail_gals": 438,
            },
        },
    )
    configuration_data = DeviceConfigurationData(
        fields={
            "hardness_grains": 18,
            "flow_monitor_min_rate_gpm": 40,
            "peak_water_flow_gpm": 1446,
            "chem_feed_gals": 1,
            "operating_capacity_grains": 9232,
            "total_salt_use_lbs": 4599,
            "salt_effic_grains_per_lb": 2821,
            "avg_salt_per_regen_lbs": 28300,
            "total_rock_removed_lbs": 1853,
            "daily_avg_rock_removed_lbs": 1028,
            "rock_removed_since_rech_lbs": 1902,
            "total_untreated_water_gals": 57,
            "avg_daily_use_day_1_gals": 38,
            "avg_daily_dev_day_1_gals": 6,
        },
    )
    historical_data = DeviceHistoricalData(
        totals={"total_outlet_water_gals": 72139},
    )

    device = DeviceMapper().map(
        DeviceMappingInput(
            shadow=shadow,
            configuration_data=configuration_data,
            historical_data=historical_data,
            unit_system=UnitSystem.METRIC,
        )
    )

    assert device.state.current_flow == round(1.5 * US_GAL_TO_L, 3)
    assert device.state.peak_flow == round(14.46 * US_GAL_TO_L, 3)
    assert device.state.water_used_today == round(38 * US_GAL_TO_L, 3)
    assert device.state.average_daily_usage == round(40 * US_GAL_TO_L, 3)
    assert device.state.treated_water_available == round(438 * US_GAL_TO_L, 3)
    assert device.state.total_outlet_water == round(72139 * US_GAL_TO_M3, 3)
    assert device.state.total_untreated_water == round(57 * US_GAL_TO_M3, 3)
    assert device.state.salt.total_used == round(459.9 * LB_TO_KG, 3)
    assert device.state.salt.average_per_regeneration == round(2.83 * LB_TO_KG, 3)
    assert device.state.salt.efficiency == round(2821 * 1000 / GRAINS_PER_LB, 3)
    assert device.state.capacity.operating == round(
        9232 / GRAINS_PER_LB * LB_TO_KG * 1000,
        3,
    )
    assert device.state.hardness_removed.total == round(185.3 * LB_TO_KG * 1000, 3)
    assert device.state.hardness_removed.daily_average == round(
        0.1028 * LB_TO_KG * 1000,
        3,
    )
    assert device.state.hardness_removed.since_regeneration == (
        round(0.1902 * LB_TO_KG * 1000, 3)
    )
    assert device.state.daily_usage_profile.day_1 is not None
    assert device.state.daily_usage_profile.day_1.average == round(38 * US_GAL_TO_L, 3)
    assert device.state.daily_usage_profile.day_1.deviation == round(6 * US_GAL_TO_L, 3)

    assert device.settings.hardness == round(18 * PPM_PER_GPG, 3)
    assert device.settings.flow_alert.min_rate == round(4 * US_GAL_TO_L, 3)
    assert device.settings.aux_output.chemical_feed_amount == round(US_GAL_TO_L, 3)
