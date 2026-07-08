from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import yaml
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import ErrorDetails


class ConfigError(ValueError):
    pass


class Mode(StrEnum):
    LOCAL = "local"
    BRIDGE = "bridge"


class UnitSystem(StrEnum):
    METRIC = "metric"
    IMPERIAL = "imperial"


class ConfigBaseModel(BaseModel, frozen=True, extra="forbid"):
    pass


class TlsConfig(ConfigBaseModel, frozen=True, arbitrary_types_allowed=True):
    certificate: x509.Certificate
    key: rsa.RSAPrivateKey
    ca: tuple[x509.Certificate, ...] | None = None

    @model_validator(mode="before")
    @classmethod
    def load_pem_files(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        values = dict(data)

        _load_path_value(values, "certificate", "certificate_path")
        _load_path_value(values, "key", "key_path")
        _load_path_value(values, "ca", "ca_path")

        return values

    @field_validator("certificate", mode="before")
    @classmethod
    def parse_certificate(cls, value: object) -> x509.Certificate:
        if isinstance(value, x509.Certificate):
            return _validate_tls_certificate(value)

        try:
            certificate = x509.load_pem_x509_certificate(_pem_bytes(value, "certificate"))
        except ValueError as exc:
            raise ValueError(f"certificate must be a valid PEM certificate: {exc}") from exc

        return _validate_tls_certificate(certificate)

    @field_validator("key", mode="before")
    @classmethod
    def parse_key(cls, value: object) -> rsa.RSAPrivateKey:
        if isinstance(value, rsa.RSAPrivateKey):
            return _validate_tls_key(value)

        try:
            key = serialization.load_pem_private_key(_pem_bytes(value, "key"), password=None)
        except (ValueError, UnsupportedAlgorithm) as exc:
            raise ValueError(f"key must be a valid unencrypted PEM private key: {exc}") from exc

        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("key must be an RSA private key")

        return _validate_tls_key(key)

    @field_validator("ca", mode="before")
    @classmethod
    def parse_ca(cls, value: object) -> tuple[x509.Certificate, ...] | None:
        if value is None:
            return None

        if isinstance(value, x509.Certificate):
            return (value,)

        if isinstance(value, list | tuple) and all(
            isinstance(item, x509.Certificate) for item in value
        ):
            return tuple(value)

        try:
            certificates = x509.load_pem_x509_certificates(_pem_bytes(value, "ca"))
        except ValueError as exc:
            raise ValueError(f"ca must be a valid PEM certificate bundle: {exc}") from exc

        if not certificates:
            raise ValueError("ca must contain at least one PEM certificate")

        return tuple(certificates)

    @model_validator(mode="after")
    def validate_key_matches_certificate(self) -> Self:
        certificate_public_key = _certificate_rsa_public_key(self.certificate)
        key_public_key = self.key.public_key()

        if _public_key_bytes(certificate_public_key) != _public_key_bytes(key_public_key):
            raise ValueError("certificate public key does not match private key")

        return self


DEFAULT_MQTTS_PORT = 8883
DEFAULT_CONFIG_PATH = Path("softener-gateway.yaml")


class EndpointConfig(TlsConfig, frozen=True):
    host: str = Field(default="0.0.0.0", min_length=1)
    port: int = Field(default=DEFAULT_MQTTS_PORT, ge=0, le=65535)


class AwsConfig(TlsConfig, frozen=True):
    host: str = Field(min_length=1)
    port: int = Field(default=DEFAULT_MQTTS_PORT, ge=1, le=65535)
    check_hostname: bool = True


class MqttSessionLogConfig(ConfigBaseModel, frozen=True):
    directory: Path

    @field_validator("directory", mode="before")
    @classmethod
    def parse_directory(cls, value: object) -> Path:
        if not isinstance(value, str | Path):
            raise ValueError("directory must be a string path")

        return Path(value)


class HttpConfig(ConfigBaseModel, frozen=True):
    enabled: bool = True
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8080, ge=1, le=65535)


class MqttConfig(ConfigBaseModel, frozen=True):
    enabled: bool = True
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=1883, ge=1, le=65535)
    client_id: str = Field(default="softener-gateway", min_length=1)
    username: str | None = None
    password: str | None = None
    topic_prefix: str = Field(default="softener_gateway", min_length=1)
    homeassistant_discovery: bool = False

    @field_validator("topic_prefix")
    @classmethod
    def validate_topic_prefix(cls, value: str) -> str:
        if value.startswith("/") or value.endswith("/"):
            raise ValueError("topic_prefix must not start or end with /")
        if "+" in value or "#" in value or "\x00" in value:
            raise ValueError("topic_prefix must not contain MQTT wildcards or null bytes")

        return value


class GatewayConfig(ConfigBaseModel, frozen=True):
    mode: Mode
    endpoint: EndpointConfig
    aws: AwsConfig | None = None
    unit_system: UnitSystem = UnitSystem.METRIC
    session_log: MqttSessionLogConfig | None = None
    http: HttpConfig | None = None
    mqtt: MqttConfig | None = None

    @model_validator(mode="after")
    def validate_aws_required_for_bridge(self) -> Self:
        if self.mode is Mode.BRIDGE and self.aws is None:
            raise ValueError("aws is required in bridge mode")

        return self


def load_config(path: Path | None = None) -> GatewayConfig:
    data = _load_yaml(path or DEFAULT_CONFIG_PATH)

    try:
        return GatewayConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file)
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Cannot parse config file {path}: {exc}") from exc

    if loaded is None:
        return {}

    if not isinstance(loaded, dict):
        raise ConfigError(f"Config file {path} must contain a YAML mapping")

    return loaded


def _load_path_value(
    values: dict[Any, Any],
    target_field: str,
    path_field: str,
) -> None:
    if target_field in values and path_field in values:
        raise ValueError(f"provide either {target_field} or {path_field}, not both")

    if path_field not in values:
        return

    values[target_field] = _read_pem_file(values.pop(path_field), path_field)


def _read_pem_file(path_value: object, field_name: str) -> str:
    if not isinstance(path_value, str | Path):
        raise ValueError(f"{field_name} must be a string path")

    path = Path(path_value)

    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {field_name} {path}: {exc}") from exc


def _pem_bytes(value: object, field_name: str) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")

    if isinstance(value, bytes):
        return value

    raise ValueError(f"{field_name} must be a PEM string")


def _validate_tls_certificate(certificate: x509.Certificate) -> x509.Certificate:
    _certificate_rsa_public_key(certificate)
    return certificate


def _certificate_rsa_public_key(certificate: x509.Certificate) -> rsa.RSAPublicKey:
    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise ValueError("certificate public key must be RSA")

    if public_key.key_size < 2048:
        raise ValueError("certificate public key must be RSA with at least 2048 bits")

    return public_key


def _validate_tls_key(key: rsa.RSAPrivateKey) -> rsa.RSAPrivateKey:
    if key.key_size < 2048:
        raise ValueError("key must be an RSA private key with at least 2048 bits")

    return key


def _public_key_bytes(public_key: rsa.RSAPublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _format_validation_error(error: ValidationError) -> str:
    lines = ["Invalid config:"]

    for detail in error.errors(include_url=False):
        location = _format_error_location(detail["loc"])
        message = _format_error_message(detail)
        lines.append(f"- {location}: {message}")

    return "\n".join(lines)


def _format_error_location(location: tuple[int | str, ...]) -> str:
    if not location:
        return "<root>"

    return ".".join(str(part) for part in location)


def _format_error_message(detail: ErrorDetails) -> str:
    if detail["type"] == "missing":
        return "field is required"

    if detail["type"] == "value_error":
        context = detail.get("ctx")
        if isinstance(context, dict):
            error = context.get("error")
            if isinstance(error, ValueError):
                return str(error)

    return str(detail["msg"])
