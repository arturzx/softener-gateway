import asyncio
import json
import socket
from pathlib import Path
from typing import Any, cast

import pytest
from aiohttp import ClientSession

from softener_gateway.api.http import HttpApi
from softener_gateway.config import HttpConfig
from softener_gateway.control import DeviceControl, ReadOnlyModeError
from softener_gateway.mapper import Device
from softener_gateway.models import DeviceInfo, Settings, State


def test_http_api_serves_device_models() -> None:
    asyncio.run(_http_api_serves_device_models())


async def _http_api_serves_device_models() -> None:
    port = _unused_tcp_port()
    device = Device(
        info=DeviceInfo(model_description="Aquahome Duo Smart"),
        state=State(online=True, current_flow=1.23),
        settings=Settings(timezone="Europe/Warsaw"),
    )
    control = FakeDeviceControl()
    api = HttpApi(
        HttpConfig(host="127.0.0.1", port=port),
        device,
        cast(DeviceControl, control),
    )

    await api.start()
    try:
        async with ClientSession() as session:
            assert await _get_json(session, port, "/health") == {"status": "ok"}

            state = await _get_json(session, port, "/state")
            assert state["online"] is True
            assert state["current_flow"] == 1.23

            settings = await _get_json(session, port, "/settings")
            assert settings["timezone"] == "Europe/Warsaw"

            device_info = await _get_json(session, port, "/device")
            assert list(device_info)[:3] == [
                "system_type",
                "model_id",
                "model_description",
            ]
            assert device_info["model_description"] == "Aquahome Duo Smart"
            assert "state" not in device_info
            assert "settings" not in device_info

            response = await _post_json(
                session,
                port,
                "/control/set_hardness",
                {"value": 320},
            )
            assert response == (204, "")
            last_call: tuple[str, object | None] = control.calls[-1]
            assert last_call == ("set_hardness", 320.0)

            status, body = await _post_json(
                session,
                port,
                "/control/set_hardness",
                {},
            )
            assert status == 400
            payload = json.loads(body)
            assert payload["error"] == "invalid_control_payload"

            openapi = await _get_json(session, port, "/openapi.json")
            assert openapi["openapi"] == "3.1.0"
            info = cast(dict[str, Any], openapi["info"])
            assert "unit_system" in cast(str, info["description"])
            assert "US gallons" in cast(str, info["description"])
            assert "Available control commands" in cast(str, info["description"])
            assert "Set water hardness." in cast(str, info["description"])

            paths = cast(dict[str, Any], openapi["paths"])
            assert list(paths) == [
                "/health",
                "/device",
                "/state",
                "/settings",
                "/control/{command}",
            ]
            control_path = cast(dict[str, Any], paths["/control/{command}"])
            control_post = cast(dict[str, Any], control_path["post"])
            control_parameters = cast(list[dict[str, Any]], control_post["parameters"])
            command_schema = cast(dict[str, Any], control_parameters[0]["schema"])
            assert "set_hardness" in cast(list[str], command_schema["enum"])
            assert "start_regeneration" in cast(list[str], command_schema["enum"])
            control_request_body = cast(dict[str, Any], control_post["requestBody"])
            control_content = cast(dict[str, Any], control_request_body["content"])
            control_json = cast(dict[str, Any], control_content["application/json"])
            control_schema = cast(dict[str, Any], control_json["schema"])
            assert "oneOf" in control_schema

            components = cast(dict[str, Any], openapi["components"])
            schemas = cast(dict[str, Any], components["schemas"])
            assert "State" in schemas
            assert "Settings" in schemas
            assert "DeviceInfo" in schemas
            assert "HealthResponse" in schemas
            assert "ErrorResponse" in schemas

            state_schema = cast(dict[str, Any], schemas["State"])
            settings_schema = cast(dict[str, Any], schemas["Settings"])
            device_info_schema = cast(dict[str, Any], schemas["DeviceInfo"])
            state_properties = cast(dict[str, Any], state_schema["properties"])
            settings_properties = cast(dict[str, Any], settings_schema["properties"])
            device_info_properties = cast(dict[str, Any], device_info_schema["properties"])

            assert "online" in state_properties
            assert "device" not in state_properties
            assert "L/min / US gal/min" in cast(
                str,
                cast(dict[str, Any], state_properties["current_flow"])["description"],
            )
            assert "m^3 / US gal" in cast(
                str,
                cast(dict[str, Any], state_properties["total_outlet_water"])["description"],
            )
            assert "timezone" in settings_properties
            assert "ppm / gpg" in cast(
                str,
                cast(dict[str, Any], settings_properties["hardness"])["description"],
            )
            assert "model_description" in device_info_properties
            assert "days" in cast(
                str,
                cast(dict[str, Any], device_info_properties["operation_time"])["description"],
            )
            assert "app_active" not in json.dumps(openapi)

            docs = await _get_text(session, port, "/docs")
            assert "SwaggerUIBundle" in docs
            assert 'url: "/openapi.json"' in docs
    finally:
        await api.stop()


def test_http_api_rejects_control_in_bridge_mode() -> None:
    asyncio.run(_http_api_rejects_control_in_bridge_mode())


async def _http_api_rejects_control_in_bridge_mode() -> None:
    port = _unused_tcp_port()
    api = HttpApi(
        HttpConfig(host="127.0.0.1", port=port),
        Device(),
        cast(DeviceControl, FakeReadOnlyDeviceControl()),
    )

    await api.start()
    try:
        async with ClientSession() as session:
            status, body = await _post_json(
                session,
                port,
                "/control/set_hardness",
                {"value": 310},
            )

            assert status == 409
            payload = json.loads(body)
            assert payload["error"] == "device_control_error"
    finally:
        await api.stop()


def test_http_api_serves_built_ui_from_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_http_api_serves_built_ui_from_root(tmp_path, monkeypatch))


async def _http_api_serves_built_ui_from_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui_directory = tmp_path / "ui"
    assets_directory = ui_directory / "assets"
    assets_directory.mkdir(parents=True)
    (ui_directory / "index.html").write_text(
        '<!doctype html><script src="./assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets_directory / "app.js").write_text("window.softenerGateway = true;", encoding="utf-8")
    monkeypatch.setenv("SOFTENER_GATEWAY_UI_DIR", str(ui_directory))

    port = _unused_tcp_port()
    api = HttpApi(
        HttpConfig(host="127.0.0.1", port=port),
        Device(),
        cast(DeviceControl, FakeDeviceControl()),
    )

    await api.start()
    try:
        async with ClientSession() as session:
            index = await _get_text(session, port, "/")
            assert "./assets/app.js" in index

            ingress_index = await _get_text(session, port, "////")
            assert "./assets/app.js" in ingress_index

            async with session.get(f"http://127.0.0.1:{port}/assets/app.js") as response:
                assert response.status == 200
                assert await response.text() == "window.softenerGateway = true;"
    finally:
        await api.stop()


async def _get_json(
    session: ClientSession,
    port: int,
    path: str,
) -> dict[str, Any]:
    async with session.get(f"http://127.0.0.1:{port}{path}") as response:
        assert response.status == 200
        return cast(dict[str, Any], await response.json())


async def _post_json(
    session: ClientSession,
    port: int,
    path: str,
    payload: dict[str, object],
) -> tuple[int, str]:
    async with session.post(f"http://127.0.0.1:{port}{path}", json=payload) as response:
        return response.status, await response.text()


async def _get_text(
    session: ClientSession,
    port: int,
    path: str,
) -> str:
    async with session.get(f"http://127.0.0.1:{port}{path}") as response:
        assert response.status == 200
        assert response.content_type == "text/html"
        return await response.text()


def _unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class FakeDeviceControl:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []

    async def set_hardness(self, value: float) -> None:
        self.calls.append(("set_hardness", value))

    async def set_regen_time(self, value: str) -> None:
        self.calls.append(("set_regen_time", value))

    async def set_salt_type(self, value: object) -> None:
        self.calls.append(("set_salt_type", str(value)))

    async def set_salt_level(self, value: float) -> None:
        self.calls.append(("set_salt_level", value))

    async def set_flow_alert_min_rate(self, value: float) -> None:
        self.calls.append(("set_flow_alert_min_rate", value))

    async def set_flow_alert_duration(self, value: float) -> None:
        self.calls.append(("set_flow_alert_duration", value))

    async def set_volume_unit(self, value: object) -> None:
        self.calls.append(("set_volume_unit", str(value)))

    async def set_weight_unit(self, value: object) -> None:
        self.calls.append(("set_weight_unit", str(value)))

    async def set_hardness_unit(self, value: object) -> None:
        self.calls.append(("set_hardness_unit", str(value)))

    async def set_date_format(self, value: object) -> None:
        self.calls.append(("set_date_format", str(value)))

    async def set_time_format(self, value: object) -> None:
        self.calls.append(("set_time_format", str(value)))

    async def set_aux_output_mode(self, value: object) -> None:
        self.calls.append(("set_aux_output_mode", str(value)))

    async def set_aux_chemical_feed_amount(self, value: float) -> None:
        self.calls.append(("set_aux_chemical_feed_amount", value))

    async def set_regeneration_backwash(self, value: int) -> None:
        self.calls.append(("set_regeneration_backwash", value))

    async def set_regeneration_fast_rinse(self, value: int) -> None:
        self.calls.append(("set_regeneration_fast_rinse", value))

    async def set_regeneration_second_backwash(self, value: int) -> None:
        self.calls.append(("set_regeneration_second_backwash", value))

    async def set_regeneration_rinse_type(self, value: int) -> None:
        self.calls.append(("set_regeneration_rinse_type", value))

    async def set_feature_97_percent(self, value: bool) -> None:
        self.calls.append(("set_feature_97_percent", value))

    async def set_efficiency_mode(self, value: object) -> None:
        self.calls.append(("set_efficiency_mode", str(value)))

    async def set_max_days_between_regenerations(self, value: object) -> None:
        self.calls.append(("set_max_days_between_regenerations", value))

    async def start_regeneration(self) -> None:
        self.calls.append(("start_regeneration", None))


class FakeReadOnlyDeviceControl:
    async def set_hardness(self, value: float) -> None:
        raise ReadOnlyModeError("device control is not available in bridge mode")

    async def start_regeneration(self) -> None:
        raise ReadOnlyModeError("device control is not available in bridge mode")
