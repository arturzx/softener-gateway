import pytest
from click.testing import CliRunner

import softener_gateway.app
from softener_gateway.cli import main
from softener_gateway.config import GatewayConfig
from softener_gateway.device.shadow import DeviceShadow
from softener_gateway.endpoint import Endpoint
from softener_gateway.events import EventBus
from softener_gateway.mapper import Device, DeviceMapper
from tests.crypto_material import generate_pem_material


def test_cli_loads_mode_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    material = generate_pem_material()

    async def start_endpoint(endpoint: Endpoint) -> None:
        return None

    async def stop_endpoint(endpoint: Endpoint) -> None:
        return None

    class FakeBridge:
        def __init__(
            self,
            config: GatewayConfig,
            event_bus: EventBus,
            endpoint: Endpoint,
            shadow: DeviceShadow,
            device: Device,
            mapper: DeviceMapper,
        ) -> None:
            pass

        async def run(self) -> None:
            return None

    monkeypatch.setattr(Endpoint, "start", start_endpoint)
    monkeypatch.setattr(Endpoint, "stop", stop_endpoint)
    monkeypatch.setattr(softener_gateway.app, "Bridge", FakeBridge)

    with runner.isolated_filesystem():
        with open("server.crt", "w", encoding="utf-8") as file:
            file.write(material.certificate)
        with open("server.key", "w", encoding="utf-8") as file:
            file.write(material.key)
        with open("gateway.yaml", "w", encoding="utf-8") as file:
            file.write(
                """
mode: bridge
endpoint:
  certificate_path: server.crt
  key_path: server.key
aws:
  host: aws.example.com
  certificate_path: server.crt
  key_path: server.key
""".lstrip()
            )

        result = runner.invoke(main, ["--config", "gateway.yaml"])

    assert result.exit_code == 0


def test_cli_reports_invalid_config_path() -> None:
    result = CliRunner().invoke(main, ["--config", "missing.yaml"])

    assert result.exit_code == 1
    assert "Cannot read config file" in result.output


def test_cli_loads_default_config_from_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    material = generate_pem_material()

    async def start_endpoint(endpoint: Endpoint) -> None:
        return None

    async def stop_endpoint(endpoint: Endpoint) -> None:
        return None

    monkeypatch.setattr(Endpoint, "start", start_endpoint)
    monkeypatch.setattr(Endpoint, "stop", stop_endpoint)

    with runner.isolated_filesystem():
        with open("server.crt", "w", encoding="utf-8") as file:
            file.write(material.certificate)
        with open("server.key", "w", encoding="utf-8") as file:
            file.write(material.key)
        with open("softener-gateway.yaml", "w", encoding="utf-8") as file:
            file.write(
                """
mode: local
endpoint:
  certificate_path: server.crt
  key_path: server.key
""".lstrip()
            )

        result = runner.invoke(main, [])

    assert result.exit_code == 0


def test_cli_reports_missing_default_config() -> None:
    result = CliRunner().invoke(main, [])

    assert result.exit_code == 1
    assert "Cannot read config file softener-gateway.yaml" in result.output
