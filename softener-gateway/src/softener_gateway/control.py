from __future__ import annotations

import inspect
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, get_type_hints

from pydantic import Field, TypeAdapter, ValidationError

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


class DeviceControlError(RuntimeError):
    pass


class ReadOnlyModeError(DeviceControlError):
    pass


class DeviceNotConnectedError(DeviceControlError):
    pass


class ControlDispatchError(ValueError):
    pass


class UnknownControlCommandError(ControlDispatchError):
    pass


class InvalidControlPayloadError(ControlDispatchError):
    pass


class DeviceControl(Protocol):
    async def set_hardness(self, value: float) -> None:
        """Set water hardness.

        Payload: `{"value": 310}`.
        Unit follows configured `unit_system`: metric uses ppm, imperial uses gpg.
        """
        pass

    async def set_regen_time(self, value: str) -> None:
        """Set daily regeneration start time.

        Payload: `{"value": "02:00"}`.
        Value format is `HH:MM`, using 24-hour time.
        """
        pass

    async def set_salt_type(self, value: SaltType) -> None:
        """Set salt type.

        Payload: `{"value": "nacl"}` or `{"value": "kcl"}`.
        """
        pass

    async def set_salt_level(self, value: Annotated[float, Field(ge=1, le=8)]) -> None:
        """Set salt level on the device salt scale.

        Payload: `{"value": 3.0}`.
        Supported writable range is 1..8; higher values have been observed to reset the device.
        """
        pass

    async def set_flow_alert_min_rate(self, value: float) -> None:
        """Set flow alert minimum rate.

        Payload: `{"value": 12.3}`.
        Unit follows configured `unit_system`: metric uses L/min, imperial uses US gal/min.
        """
        pass

    async def set_flow_alert_duration(self, value: float) -> None:
        """Set flow alert duration.

        Payload: `{"value": 20}`.
        Value unit is minutes.
        """
        pass

    async def set_volume_unit(self, value: VolumeUnit) -> None:
        """Set the device display volume unit.

        Payload: `{"value": "liters"}` or `{"value": "gallons"}`.
        """
        pass

    async def set_weight_unit(self, value: WeightUnit) -> None:
        """Set the device display weight unit.

        Payload: `{"value": "kilograms"}` or `{"value": "lbs"}`.
        """
        pass

    async def set_hardness_unit(self, value: HardnessUnit) -> None:
        """Set the device display hardness unit.

        Payload: `{"value": "ppm"}` or `{"value": "gpg"}`.
        """
        pass

    async def set_date_format(self, value: DateFormat) -> None:
        """Set the device display date format.

        Payload: `{"value": "dd/mm/yyyy"}` or `{"value": "mm/dd/yyyy"}`.
        """
        pass

    async def set_time_format(self, value: TimeFormat) -> None:
        """Set the device display time format.

        Payload: `{"value": "24h"}` or `{"value": "12h"}`.
        """
        pass

    async def set_aux_output_mode(self, value: AuxOutputMode) -> None:
        """Set auxiliary output mode.

        Payload: `{"value": "chemical_feed"}`.
        """
        pass

    async def set_aux_chemical_feed_amount(self, value: float) -> None:
        """Set auxiliary chemical feed amount.

        Payload: `{"value": 4}`.
        Unit follows configured `unit_system`: metric uses L, imperial uses US gal.
        """
        pass

    async def set_regeneration_backwash(self, value: int) -> None:
        """Set regeneration backwash duration.

        Payload: `{"value": 660}`.
        Value unit is seconds.
        """
        pass

    async def set_regeneration_fast_rinse(self, value: int) -> None:
        """Set regeneration fast rinse duration.

        Payload: `{"value": 300}`.
        Value unit is seconds.
        """
        pass

    async def set_regeneration_second_backwash(self, value: int) -> None:
        """Set regeneration second backwash duration.

        Payload: `{"value": 660}`.
        Value unit is seconds.
        """
        pass

    async def set_regeneration_rinse_type(self, value: int) -> None:
        """Set regeneration rinse type.

        Payload: `{"value": 1}`.
        Raw integer value is passed through until rinse type meanings are decoded.
        """
        pass

    async def set_feature_97_percent(self, value: bool) -> None:
        """Enable or disable the 97 percent feature.

        Payload: `{"value": true}`.
        """
        pass

    async def set_efficiency_mode(self, value: EfficiencyMode) -> None:
        """Set efficiency mode.

        Payload: `{"value": "auto"}` or `{"value": "salt_saving"}`.
        """
        pass

    async def set_max_days_between_regenerations(
        self,
        value: int | Literal["auto"],
    ) -> None:
        """Set maximum days between regenerations.

        Payload: `{"value": "auto"}` or `{"value": 7}`.
        Integer values are days.
        """
        pass

    async def start_regeneration(self) -> None:
        """Start manual regeneration.

        Payload: `{}`.
        """
        pass


@dataclass(frozen=True, slots=True)
class ControlCommand:
    name: str
    description: str
    value_adapter: TypeAdapter[Any] | None

    @property
    def requires_value(self) -> bool:
        return self.value_adapter is not None

    @classmethod
    def from_method(cls, name: str, method: object) -> ControlCommand:
        if not inspect.isfunction(method):
            raise TypeError(f"{name} is not a function")

        signature = inspect.signature(method)
        parameters = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.name != "self"
        ]
        description = inspect.getdoc(method) or ""
        if len(parameters) > 1:
            raise TypeError(f"{name} has unsupported control signature")
        if not parameters:
            return cls(name=name, description=description, value_adapter=None)

        parameter = parameters[0]
        hints = get_type_hints(method, include_extras=True)
        value_type = hints.get(parameter.name, parameter.annotation)
        if value_type is inspect.Signature.empty:
            value_type = Any

        return cls(
            name=name,
            description=description,
            value_adapter=TypeAdapter(value_type),
        )

    def payload_schema(self) -> dict[str, Any]:
        if self.value_adapter is None:
            return {
                "title": self.name,
                "description": self.description,
                "type": "object",
                "additionalProperties": False,
            }

        return {
            "title": self.name,
            "description": self.description,
            "type": "object",
            "properties": {
                "value": self.value_adapter.json_schema(),
            },
            "required": ["value"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        control: DeviceControl,
        payload: Mapping[str, object],
    ) -> None:
        values = self.decode_payload(payload)
        method = getattr(control, self.name)
        await method(*values)

    def decode_payload(self, payload: Mapping[str, object]) -> tuple[object, ...]:
        if self.value_adapter is None:
            if payload:
                raise InvalidControlPayloadError("payload must be empty")

            return ()

        if "value" not in payload:
            raise InvalidControlPayloadError("payload must contain value")

        extra_fields = set(payload) - {"value"}
        if extra_fields:
            fields = ", ".join(sorted(extra_fields))
            raise InvalidControlPayloadError(f"unexpected payload field(s): {fields}")

        try:
            value = self.value_adapter.validate_python(payload["value"])
        except ValidationError as exc:
            raise InvalidControlPayloadError(str(exc)) from exc

        return (value,)


class ControlRegistry:
    def __init__(self, commands: Mapping[str, ControlCommand]) -> None:
        self._commands = dict(commands)

    @classmethod
    def from_device_control(cls) -> ControlRegistry:
        commands = {
            name: ControlCommand.from_method(name, method)
            for name, method in DeviceControl.__dict__.items()
            if not name.startswith("_") and inspect.isfunction(method)
        }
        return cls(commands)

    def get(self, name: str) -> ControlCommand:
        try:
            return self._commands[name]
        except KeyError as exc:
            raise UnknownControlCommandError(f"unknown control command: {name}") from exc

    def __contains__(self, name: str) -> bool:
        return name in self._commands

    def __iter__(self) -> Iterator[ControlCommand]:
        return iter(self._commands.values())


__all__ = [
    "ControlCommand",
    "ControlDispatchError",
    "ControlRegistry",
    "DeviceControl",
    "DeviceControlError",
    "DeviceNotConnectedError",
    "InvalidControlPayloadError",
    "ReadOnlyModeError",
    "UnknownControlCommandError",
]
