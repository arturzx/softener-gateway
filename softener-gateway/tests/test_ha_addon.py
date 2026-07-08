import json
from pathlib import Path

import pytest
import yaml

from softener_gateway.config import GatewayConfig, Mode, UnitSystem
from softener_gateway.ha_addon import (
    SUPERVISOR_MQTT_HOST_ENV,
    SUPERVISOR_MQTT_PASSWORD_ENV,
    SUPERVISOR_MQTT_USERNAME_ENV,
    AddonOptionsError,
    build_gateway_config_from_addon_options,
    write_gateway_config_from_addon_options,
)
from tests.crypto_material import generate_pem_material


def test_addon_local_config_uses_inline_endpoint_material_without_ca() -> None:
    endpoint = generate_pem_material()

    config = build_gateway_config_from_addon_options(
        {
            "mode": "local",
            "endpoint": {
                "certificate": endpoint.certificate,
                "key": endpoint.key,
            },
            "session_log": False,
            "mqtt": {"enabled": False},
        },
        environ={},
    )

    parsed = GatewayConfig.model_validate(config)

    assert parsed.mode is Mode.LOCAL
    assert parsed.unit_system is UnitSystem.METRIC
    assert parsed.aws is None
    assert parsed.endpoint.ca is None
    assert parsed.endpoint.host == "0.0.0.0"
    assert parsed.endpoint.port == 8883
    assert parsed.http is not None
    assert parsed.http.enabled is True
    assert parsed.http.host == "0.0.0.0"
    assert parsed.http.port == 8080
    assert parsed.mqtt is not None
    assert parsed.mqtt.enabled is False


def test_addon_config_passes_unit_system_and_endpoint_port() -> None:
    endpoint = generate_pem_material()

    config = build_gateway_config_from_addon_options(
        {
            "mode": "local",
            "unit_system": "imperial",
            "endpoint": {
                "port": 18883,
                "certificate": endpoint.certificate,
                "key": endpoint.key,
            },
            "mqtt": {"enabled": False},
        },
        environ={},
    )

    parsed = GatewayConfig.model_validate(config)

    assert parsed.unit_system is UnitSystem.IMPERIAL
    assert parsed.endpoint.host == "0.0.0.0"
    assert parsed.endpoint.port == 18883


def test_addon_bridge_config_requires_aws_material() -> None:
    endpoint = generate_pem_material()

    with pytest.raises(AddonOptionsError, match="aws.host is required"):
        build_gateway_config_from_addon_options(
            {
                "mode": "bridge",
                "endpoint": {
                    "certificate": endpoint.certificate,
                    "key": endpoint.key,
                },
                "aws": {},
                "mqtt": {"enabled": False},
            },
            environ={},
        )


def test_addon_bridge_config_uses_inline_aws_material_without_ca() -> None:
    endpoint = generate_pem_material()
    aws = generate_pem_material()

    config = build_gateway_config_from_addon_options(
        {
            "mode": "bridge",
            "endpoint": {
                "certificate": endpoint.certificate,
                "key": endpoint.key,
            },
            "aws": {
                "host": "aws.example.com",
                "port": 8883,
                "certificate": aws.certificate,
                "key": aws.key,
                "check_hostname": True,
            },
            "mqtt": {"enabled": False},
        },
        environ={},
    )

    parsed = GatewayConfig.model_validate(config)

    assert parsed.mode is Mode.BRIDGE
    assert parsed.aws is not None
    assert parsed.aws.host == "aws.example.com"
    assert parsed.aws.ca is None


def test_addon_session_log_uses_share_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = generate_pem_material()
    session_log_directory = tmp_path / "share" / "softener-gateway" / "sessions"
    monkeypatch.setattr(
        "softener_gateway.ha_addon.SESSION_LOG_DIRECTORY",
        session_log_directory,
    )

    config = build_gateway_config_from_addon_options(
        {
            "mode": "local",
            "endpoint": {
                "certificate": endpoint.certificate,
                "key": endpoint.key,
            },
            "session_log": True,
            "mqtt": {"enabled": False},
        },
        environ={},
    )

    assert config["session_log"] == {"directory": str(session_log_directory)}
    assert session_log_directory.is_dir()


def test_addon_mqtt_can_use_supervisor_service_defaults() -> None:
    endpoint = generate_pem_material()

    config = build_gateway_config_from_addon_options(
        {
            "mode": "local",
            "endpoint": {
                "certificate": endpoint.certificate,
                "key": endpoint.key,
            },
            "mqtt": {
                "enabled": True,
                "host": "",
                "port": 1883,
                "username": "",
                "password": "",
                "client_id": "softener-gateway",
                "topic_prefix": "softener_gateway",
                "homeassistant_discovery": True,
            },
        },
        environ={
            SUPERVISOR_MQTT_HOST_ENV: "core-mosquitto",
            SUPERVISOR_MQTT_USERNAME_ENV: "addon-user",
            SUPERVISOR_MQTT_PASSWORD_ENV: "addon-pass",
        },
    )

    parsed = GatewayConfig.model_validate(config)

    assert parsed.mqtt is not None
    assert parsed.mqtt.enabled is True
    assert parsed.mqtt.host == "core-mosquitto"
    assert parsed.mqtt.username == "addon-user"
    assert parsed.mqtt.password == "addon-pass"
    assert parsed.mqtt.homeassistant_discovery is True


def test_addon_mqtt_requires_host_when_enabled_without_supervisor_service() -> None:
    endpoint = generate_pem_material()

    with pytest.raises(AddonOptionsError, match="mqtt.host is required"):
        build_gateway_config_from_addon_options(
            {
                "mode": "local",
                "endpoint": {
                    "certificate": endpoint.certificate,
                    "key": endpoint.key,
                },
                "mqtt": {"enabled": True, "host": ""},
            },
            environ={},
        )


def test_write_addon_config_outputs_loadable_yaml(tmp_path: Path) -> None:
    endpoint = generate_pem_material()
    options_path = tmp_path / "options.json"
    output_path = tmp_path / "softener-gateway.yaml"
    options_path.write_text(
        json.dumps(
            {
                "mode": "local",
                "endpoint": {
                    "certificate": endpoint.certificate,
                    "key": endpoint.key,
                },
                "mqtt": {"enabled": False},
            },
        ),
        encoding="utf-8",
    )

    write_gateway_config_from_addon_options(
        options_path=options_path,
        output_path=output_path,
        environ={},
    )

    generated = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    parsed = GatewayConfig.model_validate(generated)

    assert parsed.mode is Mode.LOCAL
