from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

DeviceDataFields: TypeAlias = dict[str, object]


@dataclass(slots=True)
class DeviceConfigurationData:
    fields: DeviceDataFields = field(default_factory=dict)


@dataclass(slots=True)
class DeviceHistoricalData:
    errors: list[DeviceDataFields] = field(default_factory=list)
    totals: DeviceDataFields = field(default_factory=dict)
