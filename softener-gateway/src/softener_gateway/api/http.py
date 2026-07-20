from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

from aiohttp import web
from pydantic import BaseModel

from softener_gateway import __version__
from softener_gateway.config import HttpConfig
from softener_gateway.control import (
    ControlDispatchError,
    ControlRegistry,
    DeviceControl,
    DeviceControlError,
    UnknownControlCommandError,
)
from softener_gateway.mapper import Device
from softener_gateway.models import DeviceInfo, Settings, State

logger = logging.getLogger(__name__)
UI_DIRECTORY_ENV = "SOFTENER_GATEWAY_UI_DIR"
DEFAULT_UI_DIRECTORY = Path("/opt/softener-gateway-ui")


class HealthResponse(BaseModel, extra="forbid"):
    status: Literal["ok"]


class ErrorResponse(BaseModel, extra="forbid"):
    error: str
    message: str


class HttpApi:
    def __init__(
        self,
        config: HttpConfig,
        device: Device,
        control: DeviceControl,
    ) -> None:
        self.config = config
        self.device = device
        self.control = control
        self.control_registry = ControlRegistry.from_device_control()
        self.ui_directory = _ui_directory()
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        if self._runner is not None:
            return

        app = web.Application()
        app.add_routes(
            [
                web.get("/health", self._handle_health),
                web.get("/device", self._handle_device),
                web.get("/state", self._handle_state),
                web.get("/settings", self._handle_settings),
                web.post("/control/{command}", self._handle_control_command),
                web.get("/openapi.json", self._handle_openapi_json),
                web.get("/docs", self._handle_docs),
            ]
        )
        if self.ui_directory is not None:
            assets_directory = self.ui_directory / "assets"
            if assets_directory.is_dir():
                app.router.add_static("/assets/", assets_directory)
            app.add_routes(
                [
                    web.get("/", self._handle_ui_index),
                    web.get("/{tail:.*}", self._handle_ui_index),
                ]
            )

        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, self.config.host, self.config.port)
        await site.start()

        self._app = app
        self._runner = runner
        self._site = site
        logger.info("Started HTTP API on %s:%d", self.config.host, self.config.port)

    async def stop(self) -> None:
        runner = self._runner
        if runner is None:
            return

        logger.info("Stopping HTTP API on %s:%d", self.config.host, self.config.port)
        await runner.cleanup()
        self._site = None
        self._runner = None
        self._app = None

    async def _handle_docs(self, _request: web.Request) -> web.Response:
        return web.Response(text=_swagger_ui_html(), content_type="text/html")

    async def _handle_ui_index(self, _request: web.Request) -> web.FileResponse:
        if self.ui_directory is None:
            raise web.HTTPNotFound

        return web.FileResponse(self.ui_directory / "index.html")

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_openapi_json(self, _request: web.Request) -> web.Response:
        return web.json_response(_openapi_schema(self.control_registry))

    async def _handle_state(self, _request: web.Request) -> web.Response:
        return web.json_response(self.device.state.model_dump(mode="json"))

    async def _handle_settings(self, _request: web.Request) -> web.Response:
        return web.json_response(self.device.settings.model_dump(mode="json"))

    async def _handle_device(self, _request: web.Request) -> web.Response:
        return web.json_response(self.device.info.model_dump(mode="json"))

    async def _handle_control_command(self, request: web.Request) -> web.Response:
        command_name = request.match_info["command"]
        try:
            body = await _read_json_object(request)
            command = self.control_registry.get(command_name)
            await command.execute(self.control, body)
        except UnknownControlCommandError as exc:
            return _error_response("unknown_control_command", str(exc), status=404)
        except ControlDispatchError as exc:
            return _error_response("invalid_control_payload", str(exc), status=400)
        except ValueError as exc:
            return _error_response("invalid_request", str(exc), status=400)
        except DeviceControlError as exc:
            return _error_response("device_control_error", str(exc), status=409)

        return web.Response(status=204)


def _ui_directory() -> Path | None:
    configured = os.environ.get(UI_DIRECTORY_ENV)
    directory = Path(configured) if configured else DEFAULT_UI_DIRECTORY
    if not (directory / "index.html").is_file():
        if configured:
            logger.warning("Configured UI directory has no index.html: %s", directory)
        return None

    return directory


def _swagger_ui_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Softener Gateway API</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>
    body {
      margin: 0;
      background: #fafafa;
    }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    window.onload = () => {
      SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: "#swagger-ui",
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout"
      });
    };
  </script>
</body>
</html>
"""


def _openapi_schema(control_registry: ControlRegistry) -> dict[str, Any]:
    components = _openapi_components()
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Softener Gateway API",
            "version": __version__,
            "description": _api_description(control_registry),
        },
        "paths": {
            "/health": {
                "get": {
                    "operationId": "getHealth",
                    "responses": {
                        "200": _json_response("HealthResponse"),
                    },
                },
            },
            "/device": {
                "get": {
                    "operationId": "getDevice",
                    "responses": {
                        "200": _json_response("DeviceInfo"),
                    },
                },
            },
            "/state": {
                "get": {
                    "operationId": "getState",
                    "responses": {
                        "200": _json_response("State"),
                    },
                },
            },
            "/settings": {
                "get": {
                    "operationId": "getSettings",
                    "responses": {
                        "200": _json_response("Settings"),
                    },
                },
            },
            "/control/{command}": {
                "post": {
                    "operationId": "executeControlCommand",
                    "parameters": [
                        {
                            "name": "command",
                            "in": "path",
                            "required": True,
                            "description": "Control command name.",
                            "schema": {
                                "type": "string",
                                "enum": _control_command_names(control_registry),
                            },
                        },
                    ],
                    "requestBody": _control_request_body(control_registry),
                    "responses": {
                        "204": {"description": "Control command accepted"},
                        "400": _json_response("ErrorResponse"),
                        "404": _json_response("ErrorResponse"),
                        "409": _json_response("ErrorResponse"),
                    },
                },
            },
        },
        "components": {
            "schemas": components,
        },
    }


def _api_description(control_registry: ControlRegistry) -> str:
    return "\n\n".join(
        (
            (
                "Returned measurement units depend on the gateway application "
                "`unit_system` setting. When a field description lists units as "
                "`metric / imperial`, the first unit is used in metric mode and the "
                "second unit is used in imperial mode. All gallons returned by this "
                "API are US gallons, not UK imperial gallons."
            ),
            (
                "Control commands are exposed through `POST /control/{command}`. "
                "Commands with one argument use payload `{\"value\": ...}`; commands "
                "without arguments use payload `{}`."
            ),
            _control_commands_description(control_registry),
        )
    )


def _control_commands_description(control_registry: ControlRegistry) -> str:
    lines = ["Available control commands:"]
    for command in control_registry:
        payload = '{"value": ...}' if command.requires_value else "{}"
        lines.append(f"- `{command.name}` payload `{payload}`")
        if command.description:
            lines.append(f"  {command.description.replace(chr(10), chr(10) + '  ')}")

    return "\n".join(lines)


def _control_command_names(control_registry: ControlRegistry) -> list[str]:
    return [command.name for command in control_registry]


def _openapi_components() -> dict[str, Any]:
    components: dict[str, Any] = {}
    for model in (HealthResponse, ErrorResponse, DeviceInfo, State, Settings):
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = schema.pop("$defs", {})
        components.update(definitions)
        components[model.__name__] = schema

    _strip_component_descriptions(components)
    return components


def _control_request_body(control_registry: ControlRegistry) -> dict[str, Any]:
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "description": (
                        "Control command payload. Commands with one argument use "
                        '`{"value": ...}`; commands without arguments use `{}`.'
                    ),
                    "oneOf": [command.payload_schema() for command in control_registry],
                },
            },
        },
    }


def _json_response(schema_name: str) -> dict[str, Any]:
    return {
        "description": "OK",
        "content": {
            "application/json": {
                "schema": {
                    "$ref": f"#/components/schemas/{schema_name}",
                },
            },
        },
    }


def _strip_component_descriptions(components: dict[str, Any]) -> None:
    for schema in components.values():
        if isinstance(schema, dict):
            schema.pop("description", None)


async def _read_json_object(request: web.Request) -> dict[str, object]:
    try:
        body = await request.json()
    except ValueError as exc:
        raise ValueError("request body must be a valid JSON object") from exc

    if not isinstance(body, dict):
        raise ValueError("request body must be a valid JSON object")

    return body


def _error_response(error: str, message: str, *, status: int) -> web.Response:
    return web.json_response({"error": error, "message": message}, status=status)


__all__ = [
    "HttpApi",
]
