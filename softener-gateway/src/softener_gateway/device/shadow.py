from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeAlias, cast

ShadowDocument: TypeAlias = dict[str, object]
ShadowState: TypeAlias = dict[str, object]
ShadowMetadata: TypeAlias = dict[str, object]

SHADOW_STATE_KEYS = ("desired", "reported")
MAX_CLIENT_TOKEN_BYTES = 64


class DeviceShadowError(ValueError):
    pass


class ShadowDocumentError(DeviceShadowError):
    pass


class ShadowVersionConflictError(DeviceShadowError):
    def __init__(self, expected_version: int, current_version: int) -> None:
        super().__init__(
            f"Shadow version conflict: expected {expected_version}, current {current_version}"
        )
        self.expected_version = expected_version
        self.current_version = current_version


class ShadowOperation(StrEnum):
    GET = "get"
    UPDATE = "update"
    DELETE = "delete"


class ShadowLifecycle(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DELTA = "delta"
    DOCUMENTS = "documents"


@dataclass(frozen=True, slots=True)
class ShadowTopic:
    thing_name: str
    shadow_name: str | None
    operation: ShadowOperation
    lifecycle: ShadowLifecycle | None


@dataclass(frozen=True, slots=True)
class ShadowUpdateResult:
    accepted: ShadowDocument
    documents: ShadowDocument
    delta: ShadowDocument | None


class DeviceShadow:
    def __init__(self, *, clock: Callable[[], int] | None = None) -> None:
        self._desired: ShadowState = {}
        self._reported: ShadowState = {}
        self._desired_metadata: ShadowMetadata = {}
        self._reported_metadata: ShadowMetadata = {}
        self._version = 0
        self._clock = clock or _epoch_seconds

    @property
    def version(self) -> int:
        return self._version

    @property
    def desired(self) -> ShadowState:
        return _copy_mapping(self._desired)

    @property
    def reported(self) -> ShadowState:
        return _copy_mapping(self._reported)

    @property
    def delta(self) -> ShadowState:
        return _build_delta(self._desired, self._reported)

    def get(self, *, client_token: str | None = None) -> ShadowDocument:
        return self._document(
            include_delta=True,
            timestamp=self._clock(),
            client_token=client_token,
        )

    def update(self, request: Mapping[str, object]) -> ShadowUpdateResult:
        client_token = _read_client_token(request)
        expected_version = _read_version(request)
        if expected_version is not None and expected_version != self._version:
            raise ShadowVersionConflictError(expected_version, self._version)

        state = _read_state(request)
        timestamp = self._clock()
        previous = self._snapshot()
        accepted_state: ShadowState = {}
        accepted_metadata: ShadowMetadata = {}

        for key in SHADOW_STATE_KEYS:
            if key not in state:
                continue

            value = state[key]
            if value is None:
                self._clear_section(key)
                accepted_state[key] = None
                continue

            patch = _require_mapping(value, f"state.{key}")
            target, metadata = self._section(key)
            changed_metadata: ShadowMetadata = {}
            _apply_patch(target, patch, metadata, changed_metadata, timestamp)
            accepted_state[key] = _copy_mapping(patch)
            if changed_metadata:
                accepted_metadata[key] = changed_metadata

        self._version += 1
        current = self._snapshot()
        accepted = self._accepted_document(
            state=accepted_state,
            metadata=accepted_metadata,
            timestamp=timestamp,
            client_token=client_token,
        )
        documents = self._documents_document(
            previous=previous,
            current=current,
            timestamp=timestamp,
            client_token=client_token,
        )
        delta = self._delta_document(timestamp=timestamp, client_token=client_token)

        return ShadowUpdateResult(
            accepted=accepted,
            documents=documents,
            delta=delta,
        )

    def apply_desired(
        self,
        desired: Mapping[str, object] | None,
        *,
        client_token: str | None = None,
        version: int | None = None,
    ) -> ShadowUpdateResult:
        return self.update(_update_request("desired", desired, client_token, version))

    def apply_reported(
        self,
        reported: Mapping[str, object] | None,
        *,
        client_token: str | None = None,
        version: int | None = None,
    ) -> ShadowUpdateResult:
        return self.update(_update_request("reported", reported, client_token, version))

    def delete(self, *, client_token: str | None = None) -> ShadowDocument:
        _validate_client_token(client_token)
        self._desired = {}
        self._reported = {}
        self._desired_metadata = {}
        self._reported_metadata = {}
        self._version += 1

        document: ShadowDocument = {
            "version": self._version,
            "timestamp": self._clock(),
        }
        if client_token is not None:
            document["clientToken"] = client_token

        return document

    def replace(self, document: Mapping[str, object]) -> None:
        version = _read_required_version(document)
        state = _read_optional_mapping(document, "state")
        metadata = _read_optional_mapping(document, "metadata")

        self._desired = _read_state_section(state, "desired")
        self._reported = _read_state_section(state, "reported")
        self._desired_metadata = _read_metadata_section(metadata, "desired")
        self._reported_metadata = _read_metadata_section(metadata, "reported")
        self._version = version

    def apply_remote_update(self, document: Mapping[str, object]) -> None:
        state = _read_state(document)
        metadata = _read_optional_mapping(document, "metadata")
        version = _read_required_version(document)
        timestamp = _read_timestamp(document, self._clock)

        for key in SHADOW_STATE_KEYS:
            if key not in state:
                continue

            value = state[key]
            if value is None:
                self._clear_section(key)
                continue

            target, target_metadata = self._section(key)
            _apply_remote_patch(
                target,
                _require_mapping(value, f"state.{key}"),
                target_metadata,
                _read_metadata_patch(metadata, key),
                timestamp,
            )

        self._version = version

    def apply_remote_delta(self, document: Mapping[str, object]) -> None:
        state = _read_state(document)
        metadata = _read_optional_mapping(document, "metadata")
        version = _read_required_version(document)
        timestamp = _read_timestamp(document, self._clock)

        _apply_remote_patch(
            self._desired,
            state,
            self._desired_metadata,
            metadata,
            timestamp,
        )
        self._version = version

    def apply_remote_delete(self, document: Mapping[str, object]) -> None:
        version = _read_required_version(document)
        self._desired = {}
        self._reported = {}
        self._desired_metadata = {}
        self._reported_metadata = {}
        self._version = version

    def _section(self, key: str) -> tuple[ShadowState, ShadowMetadata]:
        if key == "desired":
            return self._desired, self._desired_metadata
        if key == "reported":
            return self._reported, self._reported_metadata

        raise ShadowDocumentError(f"Unsupported shadow state section: {key}")

    def _clear_section(self, key: str) -> None:
        target, metadata = self._section(key)
        target.clear()
        metadata.clear()

    def _snapshot(self) -> ShadowDocument:
        return self._document(include_delta=False)

    def _document(
        self,
        *,
        include_delta: bool,
        timestamp: int | None = None,
        client_token: str | None = None,
    ) -> ShadowDocument:
        _validate_client_token(client_token)
        document: ShadowDocument = {}
        state = self._state_document(include_delta=include_delta)
        metadata = self._metadata_document(include_delta=include_delta)

        if state:
            document["state"] = state
        if metadata:
            document["metadata"] = metadata

        document["version"] = self._version
        if timestamp is not None:
            document["timestamp"] = timestamp
        if client_token is not None:
            document["clientToken"] = client_token

        return document

    def _accepted_document(
        self,
        *,
        state: ShadowState,
        metadata: ShadowMetadata,
        timestamp: int,
        client_token: str | None,
    ) -> ShadowDocument:
        document: ShadowDocument = {
            "state": state,
            "version": self._version,
            "timestamp": timestamp,
        }
        if metadata:
            document["metadata"] = metadata
        if client_token is not None:
            document["clientToken"] = client_token

        return document

    def _documents_document(
        self,
        *,
        previous: ShadowDocument,
        current: ShadowDocument,
        timestamp: int,
        client_token: str | None,
    ) -> ShadowDocument:
        document: ShadowDocument = {
            "previous": previous,
            "current": current,
            "timestamp": timestamp,
        }
        if client_token is not None:
            document["clientToken"] = client_token

        return document

    def _delta_document(
        self,
        *,
        timestamp: int,
        client_token: str | None,
    ) -> ShadowDocument | None:
        delta = self.delta
        if not delta:
            return None

        metadata = _filter_metadata(self._desired_metadata, delta)
        document: ShadowDocument = {
            "state": delta,
            "version": self._version,
            "timestamp": timestamp,
        }
        if metadata:
            document["metadata"] = metadata
        if client_token is not None:
            document["clientToken"] = client_token

        return document

    def _state_document(self, *, include_delta: bool) -> ShadowState:
        state: ShadowState = {}
        if self._desired:
            state["desired"] = _copy_mapping(self._desired)
        if self._reported:
            state["reported"] = _copy_mapping(self._reported)

        if include_delta:
            delta = self.delta
            if delta:
                state["delta"] = delta

        return state

    def _metadata_document(self, *, include_delta: bool) -> ShadowMetadata:
        metadata: ShadowMetadata = {}
        if self._desired_metadata:
            metadata["desired"] = _copy_mapping(self._desired_metadata)
        if self._reported_metadata:
            metadata["reported"] = _copy_mapping(self._reported_metadata)

        if include_delta:
            delta = self.delta
            delta_metadata = _filter_metadata(self._desired_metadata, delta)
            if delta_metadata:
                metadata["delta"] = delta_metadata

        return metadata


def parse_shadow_topic(topic: str) -> ShadowTopic | None:
    parts = topic.split("/")
    if len(parts) < 5:
        return None
    if parts[0] != "$aws" or parts[1] != "things" or parts[3] != "shadow":
        return None

    thing_name = parts[2]
    if not thing_name:
        return None

    shadow_name = None
    operation_offset = 4
    if len(parts) > operation_offset and parts[operation_offset] == "name":
        if len(parts) < operation_offset + 3:
            return None

        shadow_name = parts[operation_offset + 1]
        if not shadow_name:
            return None
        operation_offset += 2

    try:
        operation = ShadowOperation(parts[operation_offset])
    except (IndexError, ValueError):
        return None

    lifecycle_parts = parts[operation_offset + 1 :]
    if not lifecycle_parts:
        return ShadowTopic(
            thing_name=thing_name,
            shadow_name=shadow_name,
            operation=operation,
            lifecycle=None,
        )
    if len(lifecycle_parts) != 1:
        return None

    try:
        lifecycle = ShadowLifecycle(lifecycle_parts[0])
    except ValueError:
        return None

    if not valid_shadow_lifecycle(operation, lifecycle):
        return None

    return ShadowTopic(
        thing_name=thing_name,
        shadow_name=shadow_name,
        operation=operation,
        lifecycle=lifecycle,
    )


def build_shadow_topic(
    thing_name: str,
    operation: ShadowOperation,
    *,
    lifecycle: ShadowLifecycle | None = None,
    shadow_name: str | None = None,
) -> str:
    if not thing_name:
        raise ShadowDocumentError("thing_name must not be empty")
    if shadow_name == "":
        raise ShadowDocumentError("shadow_name must not be empty")
    if lifecycle is not None and not valid_shadow_lifecycle(operation, lifecycle):
        raise ShadowDocumentError(
            f"{operation.value}/{lifecycle.value} is not a valid shadow topic"
        )

    topic = f"$aws/things/{thing_name}/shadow"
    if shadow_name is not None:
        topic += f"/name/{shadow_name}"
    topic += f"/{operation.value}"
    if lifecycle is not None:
        topic += f"/{lifecycle.value}"

    return topic


def valid_shadow_lifecycle(
    operation: ShadowOperation,
    lifecycle: ShadowLifecycle,
) -> bool:
    match operation:
        case ShadowOperation.GET | ShadowOperation.DELETE:
            return lifecycle in {ShadowLifecycle.ACCEPTED, ShadowLifecycle.REJECTED}
        case ShadowOperation.UPDATE:
            return lifecycle in {
                ShadowLifecycle.ACCEPTED,
                ShadowLifecycle.REJECTED,
                ShadowLifecycle.DELTA,
                ShadowLifecycle.DOCUMENTS,
            }

    return False


def decode_shadow_payload(payload: bytes) -> Mapping[str, object]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowDocumentError(f"payload must be a valid JSON object: {exc}") from exc

    if not isinstance(document, dict):
        raise ShadowDocumentError("payload must be a JSON object")
    for key in document:
        if not isinstance(key, str):
            raise ShadowDocumentError("payload object keys must be strings")

    return cast(Mapping[str, object], document)


def read_current_shadow_document(document: Mapping[str, object]) -> Mapping[str, object]:
    value = document.get("current")
    if not isinstance(value, Mapping):
        raise ShadowDocumentError("current must be a JSON object")
    for key in value:
        if not isinstance(key, str):
            raise ShadowDocumentError("current object keys must be strings")

    return cast(Mapping[str, object], value)


def _update_request(
    section: str,
    value: Mapping[str, object] | None,
    client_token: str | None,
    version: int | None,
) -> ShadowDocument:
    request: ShadowDocument = {"state": {section: value}}
    if client_token is not None:
        request["clientToken"] = client_token
    if version is not None:
        request["version"] = version

    return request


def _read_state(request: Mapping[str, object]) -> Mapping[str, object]:
    value = request.get("state")
    return _require_mapping(value, "state")


def _read_client_token(request: Mapping[str, object]) -> str | None:
    value = request.get("clientToken")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ShadowDocumentError("clientToken must be a string")

    _validate_client_token(value)
    return value


def _read_version(request: Mapping[str, object]) -> int | None:
    value = request.get("version")
    if value is None:
        return None
    if not isinstance(value, int):
        raise ShadowDocumentError("version must be an integer")

    return value


def _read_required_version(document: Mapping[str, object]) -> int:
    value = _read_version(document)
    if value is None:
        raise ShadowDocumentError("version is required")

    return value


def _read_timestamp(
    document: Mapping[str, object],
    clock: Callable[[], int],
) -> int:
    value = document.get("timestamp")
    if value is None:
        return clock()
    if not isinstance(value, int):
        raise ShadowDocumentError("timestamp must be an integer")

    return value


def _read_optional_mapping(
    source: Mapping[str, object],
    field_name: str,
) -> Mapping[str, object] | None:
    value = source.get(field_name)
    if value is None:
        return None

    return _require_mapping(value, field_name)


def _read_state_section(
    state: Mapping[str, object] | None,
    section: str,
) -> ShadowState:
    if state is None:
        return {}

    value = state.get(section)
    if value is None:
        return {}

    return _copy_mapping(_require_mapping(value, f"state.{section}"))


def _read_metadata_section(
    metadata: Mapping[str, object] | None,
    section: str,
) -> ShadowMetadata:
    if metadata is None:
        return {}

    value = metadata.get(section)
    if value is None:
        return {}

    return _copy_mapping(_require_mapping(value, f"metadata.{section}"))


def _read_metadata_patch(
    metadata: Mapping[str, object] | None,
    section: str,
) -> Mapping[str, object] | None:
    if metadata is None:
        return None

    value = metadata.get(section)
    if value is None:
        return None

    return _require_mapping(value, f"metadata.{section}")


def _validate_client_token(client_token: str | None) -> None:
    if client_token is not None and len(client_token.encode("utf-8")) > MAX_CLIENT_TOKEN_BYTES:
        raise ShadowDocumentError("clientToken must not exceed 64 UTF-8 bytes")


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ShadowDocumentError(f"{field_name} must be an object")

    for key in value:
        if not isinstance(key, str):
            raise ShadowDocumentError(f"{field_name} keys must be strings")

    return cast(Mapping[str, object], value)


def _apply_patch(
    target: ShadowState,
    patch: Mapping[str, object],
    metadata: ShadowMetadata,
    changed_metadata: ShadowMetadata,
    timestamp: int,
) -> None:
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
            metadata.pop(key, None)
            continue

        if isinstance(value, Mapping):
            child_target = _child_state(target, key)
            child_metadata = _child_metadata(metadata, key)
            child_changed_metadata: ShadowMetadata = {}
            _apply_patch(
                child_target,
                _require_mapping(value, key),
                child_metadata,
                child_changed_metadata,
                timestamp,
            )
            target[key] = child_target
            metadata[key] = child_metadata
            if child_changed_metadata:
                changed_metadata[key] = child_changed_metadata
            continue

        target[key] = deepcopy(value)
        metadata[key] = {"timestamp": timestamp}
        changed_metadata[key] = {"timestamp": timestamp}


def _apply_remote_patch(
    target: ShadowState,
    patch: Mapping[str, object],
    metadata: ShadowMetadata,
    metadata_patch: Mapping[str, object] | None,
    timestamp: int,
) -> None:
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
            metadata.pop(key, None)
            continue

        patched_metadata = _metadata_value(metadata_patch, key)
        if isinstance(value, Mapping):
            child_target = _child_state(target, key)
            child_metadata = _child_metadata(metadata, key)
            _apply_remote_patch(
                child_target,
                _require_mapping(value, key),
                child_metadata,
                patched_metadata,
                timestamp,
            )
            target[key] = child_target
            metadata[key] = child_metadata
            continue

        target[key] = deepcopy(value)
        metadata[key] = _leaf_metadata(patched_metadata, timestamp)


def _metadata_value(
    metadata: Mapping[str, object] | None,
    key: str,
) -> Mapping[str, object] | None:
    if metadata is None:
        return None

    value = metadata.get(key)
    if value is None:
        return None

    return _require_mapping(value, key)


def _leaf_metadata(
    metadata: Mapping[str, object] | None,
    timestamp: int,
) -> ShadowMetadata:
    if metadata is None:
        return {"timestamp": timestamp}

    return _copy_mapping(metadata)


def _child_state(target: ShadowState, key: str) -> ShadowState:
    value = target.get(key)
    if isinstance(value, dict):
        return cast(ShadowState, value)

    return {}


def _child_metadata(metadata: ShadowMetadata, key: str) -> ShadowMetadata:
    value = metadata.get(key)
    if isinstance(value, dict) and "timestamp" not in value:
        return cast(ShadowMetadata, value)

    return {}


def _build_delta(desired: Mapping[str, object], reported: Mapping[str, object]) -> ShadowState:
    delta: ShadowState = {}

    for key, desired_value in desired.items():
        if key not in reported:
            delta[key] = deepcopy(desired_value)
            continue

        reported_value = reported[key]
        if isinstance(desired_value, Mapping) and isinstance(reported_value, Mapping):
            child_delta = _build_delta(
                _require_mapping(desired_value, key),
                _require_mapping(reported_value, key),
            )
            if child_delta:
                delta[key] = child_delta
            continue

        if desired_value != reported_value:
            delta[key] = deepcopy(desired_value)

    return delta


def _filter_metadata(metadata: Mapping[str, object], state: Mapping[str, object]) -> ShadowMetadata:
    filtered: ShadowMetadata = {}

    for key, value in state.items():
        metadata_value = metadata.get(key)
        if metadata_value is None:
            continue

        if isinstance(value, Mapping) and isinstance(metadata_value, Mapping):
            child_metadata = _filter_metadata(
                _require_mapping(metadata_value, key),
                _require_mapping(value, key),
            )
            if child_metadata:
                filtered[key] = child_metadata
            continue

        filtered[key] = deepcopy(metadata_value)

    return filtered


def _copy_mapping(value: Mapping[str, object]) -> ShadowState:
    return deepcopy(dict(value))


def _epoch_seconds() -> int:
    return int(datetime.now(UTC).timestamp())


__all__ = [
    "DeviceShadow",
    "DeviceShadowError",
    "ShadowDocument",
    "ShadowDocumentError",
    "ShadowLifecycle",
    "ShadowMetadata",
    "ShadowOperation",
    "ShadowState",
    "ShadowTopic",
    "ShadowUpdateResult",
    "ShadowVersionConflictError",
    "build_shadow_topic",
    "decode_shadow_payload",
    "parse_shadow_topic",
    "read_current_shadow_document",
    "valid_shadow_lifecycle",
]
