from softener_gateway.device.data import DeviceConfigurationData, DeviceHistoricalData


def test_device_configuration_data_defaults_are_independent() -> None:
    first = DeviceConfigurationData()
    second = DeviceConfigurationData()

    first.fields["thing_name"] = "10_45_356489-Thing"

    assert second.fields == {}


def test_device_historical_data_defaults_are_independent() -> None:
    first = DeviceHistoricalData()
    second = DeviceHistoricalData()

    first.errors.append({"error_type": 10005, "status": 0})
    first.totals["total_outlet_water_gals"] = 72060

    assert second.errors == []
    assert second.totals == {}
