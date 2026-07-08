from pathlib import Path
from textwrap import indent

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa

from softener_gateway.config import (
    AwsConfig,
    ConfigError,
    HttpConfig,
    Mode,
    MqttConfig,
    UnitSystem,
    load_config,
)
from tests.crypto_material import PemMaterial, generate_ec_pem_material, generate_pem_material


def write_pem_files(directory: Path, material: PemMaterial) -> None:
    certs_dir = directory / "certs"
    certs_dir.mkdir()
    (certs_dir / "server.crt").write_text(material.certificate, encoding="utf-8")
    (certs_dir / "server.key").write_text(material.key, encoding="utf-8")


def endpoint_config_with_paths() -> str:
    return """
endpoint:
  certificate_path: certs/server.crt
  key_path: certs/server.key
""".lstrip()


def endpoint_config_with_pem(material: PemMaterial) -> str:
    return f"""
endpoint:
  certificate: |
{indent(material.certificate, "    ")}
  key: |
{indent(material.key, "    ")}
""".lstrip()


def test_rejects_missing_mode_without_config() -> None:
    with pytest.raises(ConfigError, match="mode: field is required"):
        load_config()


def test_loads_mode_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: bridge
{endpoint_config_with_paths()}
aws:
  host: aws.example.com
  certificate_path: certs/server.crt
  key_path: certs/server.key
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config(path)

    assert config.mode is Mode.BRIDGE
    assert config.endpoint.host == "0.0.0.0"
    assert config.endpoint.port == 8883
    assert config.unit_system is UnitSystem.METRIC
    assert isinstance(config.endpoint.certificate, x509.Certificate)
    assert isinstance(config.endpoint.key, rsa.RSAPrivateKey)
    assert config.endpoint.ca is None


def test_loads_unit_system_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: local
unit_system: metric
{endpoint_config_with_paths()}
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config(path)

    assert config.unit_system is UnitSystem.METRIC


def test_loads_aws_config_from_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: bridge
{endpoint_config_with_paths()}
aws:
  host: aws.example.com
  port: 8883
  check_hostname: false
  certificate_path: certs/server.crt
  key_path: certs/server.key
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config(path)

    assert isinstance(config.aws, AwsConfig)
    assert config.aws.host == "aws.example.com"
    assert config.aws.port == 8883
    assert config.aws.check_hostname is False
    assert isinstance(config.aws.certificate, x509.Certificate)
    assert isinstance(config.aws.key, rsa.RSAPrivateKey)
    assert config.aws.ca is None


def test_loads_http_config_from_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: local
{endpoint_config_with_paths()}
http:
  host: 0.0.0.0
  port: 18080
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config(path)

    assert isinstance(config.http, HttpConfig)
    assert config.http.enabled is True
    assert config.http.host == "0.0.0.0"
    assert config.http.port == 18080


def test_loads_mqtt_api_config_from_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: local
{endpoint_config_with_paths()}
mqtt:
  enabled: false
  host: mqtt.example.com
  port: 1884
  client_id: softener-gateway-test
  username: user
  password: pass
  topic_prefix: softener/test
  homeassistant_discovery: true
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config(path)

    assert isinstance(config.mqtt, MqttConfig)
    assert config.mqtt.enabled is False
    assert config.mqtt.host == "mqtt.example.com"
    assert config.mqtt.port == 1884
    assert config.mqtt.client_id == "softener-gateway-test"
    assert config.mqtt.username == "user"
    assert config.mqtt.password == "pass"
    assert config.mqtt.topic_prefix == "softener/test"
    assert config.mqtt.homeassistant_discovery is True


def test_mqtt_api_homeassistant_discovery_is_disabled_by_default() -> None:
    assert MqttConfig().homeassistant_discovery is False


def test_aws_config_verifies_hostname_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: bridge
{endpoint_config_with_paths()}
aws:
  host: aws.example.com
  certificate_path: certs/server.crt
  key_path: certs/server.key
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config(path)

    assert config.aws is not None
    assert config.aws.check_hostname is True


def test_keeps_relative_session_log_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: bridge
{endpoint_config_with_paths()}
aws:
  host: aws.example.com
  certificate_path: certs/server.crt
  key_path: certs/server.key
session_log:
  directory: logs/mqtt
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config(path)

    assert config.session_log is not None
    assert config.session_log.directory == Path("logs/mqtt")


def test_requires_aws_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: bridge
{endpoint_config_with_paths()}
aws:
  certificate_path: certs/server.crt
  key_path: certs/server.key
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="aws.host: field is required"):
        load_config(path)


def test_rejects_invalid_aws_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: bridge
{endpoint_config_with_paths()}
aws:
  host: aws.example.com
  port: 0
  certificate_path: certs/server.crt
  key_path: certs/server.key
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    assert "aws.port" in str(exc_info.value)


def test_requires_aws_config_in_bridge_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: bridge
{endpoint_config_with_paths()}
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="aws is required in bridge mode"):
        load_config(path)


def test_loads_inline_endpoint_material_with_ca(tmp_path: Path) -> None:
    material = generate_pem_material()
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: local
endpoint:
  certificate: |
{indent(material.certificate, "    ")}
  key: |
{indent(material.key, "    ")}
  ca: |
{indent(material.certificate, "    ")}
""".lstrip(),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.mode is Mode.LOCAL
    assert config.endpoint.ca is not None
    assert len(config.endpoint.ca) == 1


def test_rejects_invalid_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: invalid
{endpoint_config_with_paths()}
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="mode: Input should be 'local' or 'bridge'"):
        load_config(path)


def test_rejects_missing_mode_in_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        endpoint_config_with_paths(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="mode: field is required"):
        load_config(path)


def test_rejects_unknown_config_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: local
{endpoint_config_with_paths()}
unknown: value
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="unknown: Extra inputs are not permitted"):
        load_config(path)


def test_rejects_missing_endpoint_in_yaml(tmp_path: Path) -> None:
    path = tmp_path / "gateway.yaml"
    path.write_text("mode: local\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="endpoint: field is required"):
        load_config(path)


def test_rejects_invalid_endpoint_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        """
mode: local
endpoint:
  port: 70000
  certificate_path: certs/server.crt
  key_path: certs/server.key
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    assert "endpoint.port" in str(exc_info.value)


def test_rejects_mismatched_certificate_and_key(tmp_path: Path) -> None:
    certificate_material = generate_pem_material()
    key_material = generate_pem_material()
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: local
endpoint:
  certificate: |
{indent(certificate_material.certificate, "    ")}
  key: |
{indent(key_material.key, "    ")}
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="certificate public key does not match private key"):
        load_config(path)


def test_rejects_rsa_key_smaller_than_2048_bits(tmp_path: Path) -> None:
    material = generate_pem_material(key_size=1024)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: local
{endpoint_config_with_pem(material)}
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="at least 2048 bits"):
        load_config(path)


def test_rejects_ec_endpoint_key(tmp_path: Path) -> None:
    material = generate_ec_pem_material()
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: local
{endpoint_config_with_pem(material)}
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="certificate public key must be RSA"):
        load_config(path)


def test_rejects_both_certificate_and_certificate_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = generate_pem_material()
    write_pem_files(tmp_path, material)
    path = tmp_path / "gateway.yaml"
    path.write_text(
        f"""
mode: local
endpoint:
  certificate: |
{indent(material.certificate, "    ")}
  certificate_path: certs/server.crt
  key_path: certs/server.key
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="provide either certificate or certificate_path"):
        load_config(path)


def test_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    path = tmp_path / "gateway.yaml"
    path.write_text("- local\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="YAML mapping"):
        load_config(path)
