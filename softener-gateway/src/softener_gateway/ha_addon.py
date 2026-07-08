from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

SESSION_LOG_DIRECTORY = Path("/share/softener-gateway/sessions")
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
ENDPOINT_HOST = "0.0.0.0"
ENDPOINT_PORT = 8883
DEFAULT_AWS_PORT = 8883
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_CLIENT_ID = "softener-gateway"
DEFAULT_MQTT_TOPIC_PREFIX = "softener_gateway"

SUPERVISOR_MQTT_HOST_ENV = "SOFTENER_GATEWAY_SUPERVISOR_MQTT_HOST"
SUPERVISOR_MQTT_PORT_ENV = "SOFTENER_GATEWAY_SUPERVISOR_MQTT_PORT"
SUPERVISOR_MQTT_USERNAME_ENV = "SOFTENER_GATEWAY_SUPERVISOR_MQTT_USERNAME"
SUPERVISOR_MQTT_PASSWORD_ENV = "SOFTENER_GATEWAY_SUPERVISOR_MQTT_PASSWORD"


class AddonOptionsError(ValueError):
    pass


def build_gateway_config_from_addon_options(
    options: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    mode = _choice(_option(options, "mode", "local"), "mode", {"local", "bridge"})
    unit_system = _choice(
        _option(options, "unit_system", "metric"),
        "unit_system",
        {"metric", "imperial"},
    )
    endpoint_options = _mapping_option(options, "endpoint")

    config: dict[str, Any] = {
        "mode": mode,
        "unit_system": unit_system,
        "endpoint": {
            "host": ENDPOINT_HOST,
            "port": _port_option(
                _option(endpoint_options, "port", ENDPOINT_PORT),
                "endpoint.port",
            ),
            "certificate": _required_string(
                endpoint_options,
                "certificate",
                "endpoint.certificate",
            ),
            "key": _required_string(endpoint_options, "key", "endpoint.key"),
        },
        "http": {
            "enabled": True,
            "host": HTTP_HOST,
            "port": HTTP_PORT,
        },
        "mqtt": _mqtt_config(_mapping_option(options, "mqtt"), env),
    }

    if mode == "bridge":
        config["aws"] = _aws_config(_mapping_option(options, "aws"))

    if _bool_option(_option(options, "session_log", False), "session_log"):
        SESSION_LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
        config["session_log"] = {"directory": str(SESSION_LOG_DIRECTORY)}

    return config


def write_gateway_config_from_addon_options(
    *,
    options_path: Path,
    output_path: Path,
    environ: Mapping[str, str] | None = None,
) -> None:
    options = _load_options(options_path)
    config = build_gateway_config_from_addon_options(options, environ=environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _load_options(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AddonOptionsError(f"cannot read add-on options {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AddonOptionsError(f"cannot parse add-on options {path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise AddonOptionsError("add-on options root must be an object")

    return loaded


def _aws_config(options: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": _required_string(options, "host", "aws.host").strip(),
        "port": _port_option(_option(options, "port", DEFAULT_AWS_PORT), "aws.port"),
        "certificate": _required_string(options, "certificate", "aws.certificate"),
        "key": _required_string(options, "key", "aws.key"),
        "check_hostname": _bool_option(
            _option(options, "check_hostname", True),
            "aws.check_hostname",
        ),
    }


def _mqtt_config(options: dict[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    enabled = _bool_option(_option(options, "enabled", False), "mqtt.enabled")
    host = _optional_string(options, "host", "mqtt.host")
    supervisor_host = env.get(SUPERVISOR_MQTT_HOST_ENV, "").strip()
    effective_host = host.strip() or supervisor_host

    if enabled and not effective_host:
        raise AddonOptionsError(
            "mqtt.host is required when MQTT is enabled and Supervisor MQTT service "
            "configuration is not available"
        )

    return {
        "enabled": enabled,
        "host": effective_host or "127.0.0.1",
        "port": _mqtt_port(options, env),
        "client_id": (
            _optional_string(options, "client_id", "mqtt.client_id").strip()
            or DEFAULT_MQTT_CLIENT_ID
        ),
        "username": _optional_string(options, "username", "mqtt.username").strip()
        or _empty_string_as_none(env.get(SUPERVISOR_MQTT_USERNAME_ENV, "")),
        "password": _optional_string(options, "password", "mqtt.password")
        or _empty_string_as_none(env.get(SUPERVISOR_MQTT_PASSWORD_ENV, "")),
        "topic_prefix": (
            _optional_string(options, "topic_prefix", "mqtt.topic_prefix").strip()
            or DEFAULT_MQTT_TOPIC_PREFIX
        ),
        "homeassistant_discovery": _bool_option(
            _option(options, "homeassistant_discovery", True),
            "mqtt.homeassistant_discovery",
        ),
    }


def _mqtt_port(options: dict[str, Any], env: Mapping[str, str]) -> int:
    if _has_non_empty_option(options, "port"):
        return _port_option(options["port"], "mqtt.port")

    supervisor_port = env.get(SUPERVISOR_MQTT_PORT_ENV, "").strip()
    if supervisor_port:
        return _port_option(supervisor_port, SUPERVISOR_MQTT_PORT_ENV)

    return DEFAULT_MQTT_PORT


def _option(options: dict[str, Any], key: str, default: object) -> object:
    return options.get(key, default)


def _mapping_option(options: dict[str, Any], key: str) -> dict[str, Any]:
    value = options.get(key, {})
    if not isinstance(value, dict):
        raise AddonOptionsError(f"{key} must be an object")

    return value


def _choice(value: object, path: str, choices: set[str]) -> str:
    if not isinstance(value, str):
        raise AddonOptionsError(f"{path} must be a string")
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise AddonOptionsError(f"{path} must be one of: {allowed}")

    return value


def _required_string(options: dict[str, Any], key: str, path: str) -> str:
    value = options.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AddonOptionsError(f"{path} is required")

    return value


def _optional_string(options: dict[str, Any], key: str, path: str) -> str:
    value = options.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AddonOptionsError(f"{path} must be a string")

    return value


def _bool_option(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise AddonOptionsError(f"{path} must be a boolean")

    return value


def _port_option(value: object, path: str) -> int:
    if isinstance(value, bool):
        raise AddonOptionsError(f"{path} must be a port number")
    if isinstance(value, int):
        port = value
    elif isinstance(value, str):
        try:
            port = int(value)
        except ValueError as exc:
            raise AddonOptionsError(f"{path} must be a port number") from exc
    else:
        raise AddonOptionsError(f"{path} must be a port number")
    if not 1 <= port <= 65535:
        raise AddonOptionsError(f"{path} must be in range 1-65535")

    return port


def _has_non_empty_option(options: dict[str, Any], key: str) -> bool:
    value = options.get(key)
    return value is not None and value != ""


def _empty_string_as_none(value: str) -> str | None:
    return value if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Softener Gateway config for HA add-on")
    parser.add_argument("--options", type=Path, default=Path("/data/options.json"))
    parser.add_argument("--output", type=Path, default=Path("/data/softener-gateway.yaml"))
    args = parser.parse_args()

    try:
        write_gateway_config_from_addon_options(
            options_path=args.options,
            output_path=args.output,
        )
    except AddonOptionsError as exc:
        raise SystemExit(f"STOP: {exc}") from exc


if __name__ == "__main__":
    main()
