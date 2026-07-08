import pytest

from softener_gateway.device.shadow import (
    DeviceShadow,
    ShadowDocumentError,
    ShadowLifecycle,
    ShadowOperation,
    ShadowTopic,
    ShadowVersionConflictError,
    build_shadow_topic,
    decode_shadow_payload,
    parse_shadow_topic,
    read_current_shadow_document,
)


class FakeClock:
    def __init__(self, timestamp: int = 1_700_000_000) -> None:
        self.timestamp = timestamp

    def __call__(self) -> int:
        return self.timestamp


def test_empty_shadow_get_document() -> None:
    shadow = DeviceShadow(clock=FakeClock())

    assert shadow.get() == {
        "version": 0,
        "timestamp": 1_700_000_000,
    }


def test_shadow_update_builds_aws_lifecycle_documents() -> None:
    clock = FakeClock()
    shadow = DeviceShadow(clock=clock)

    result = shadow.update(
        {
            "state": {
                "desired": {
                    "mode": "eco",
                    "target": 12,
                }
            },
            "clientToken": "token-1",
        }
    )

    assert shadow.version == 1
    assert shadow.desired == {"mode": "eco", "target": 12}
    assert result.accepted == {
        "state": {
            "desired": {
                "mode": "eco",
                "target": 12,
            }
        },
        "metadata": {
            "desired": {
                "mode": {"timestamp": 1_700_000_000},
                "target": {"timestamp": 1_700_000_000},
            }
        },
        "version": 1,
        "timestamp": 1_700_000_000,
        "clientToken": "token-1",
    }
    assert result.documents == {
        "previous": {"version": 0},
        "current": {
            "state": {
                "desired": {
                    "mode": "eco",
                    "target": 12,
                }
            },
            "metadata": {
                "desired": {
                    "mode": {"timestamp": 1_700_000_000},
                    "target": {"timestamp": 1_700_000_000},
                }
            },
            "version": 1,
        },
        "timestamp": 1_700_000_000,
        "clientToken": "token-1",
    }
    assert result.delta == {
        "state": {
            "mode": "eco",
            "target": 12,
        },
        "metadata": {
            "mode": {"timestamp": 1_700_000_000},
            "target": {"timestamp": 1_700_000_000},
        },
        "version": 1,
        "timestamp": 1_700_000_000,
        "clientToken": "token-1",
    }


def test_shadow_reported_state_resolves_delta() -> None:
    shadow = DeviceShadow(clock=FakeClock())

    shadow.apply_desired({"mode": "eco", "target": 12})
    result = shadow.apply_reported({"mode": "eco", "target": 12})

    assert shadow.version == 2
    assert shadow.delta == {}
    assert result.delta is None
    assert shadow.get()["state"] == {
        "desired": {"mode": "eco", "target": 12},
        "reported": {"mode": "eco", "target": 12},
    }


def test_shadow_delta_contains_nested_difference() -> None:
    shadow = DeviceShadow(clock=FakeClock())

    shadow.apply_desired(
        {
            "salt": {
                "level": 75,
                "unit": "%",
            }
        }
    )
    shadow.apply_reported(
        {
            "salt": {
                "level": 50,
                "unit": "%",
            }
        }
    )

    assert shadow.delta == {"salt": {"level": 75}}
    assert shadow.get()["state"] == {
        "desired": {
            "salt": {
                "level": 75,
                "unit": "%",
            }
        },
        "reported": {
            "salt": {
                "level": 50,
                "unit": "%",
            }
        },
        "delta": {
            "salt": {
                "level": 75,
            }
        },
    }


def test_shadow_update_with_null_removes_state_field() -> None:
    shadow = DeviceShadow(clock=FakeClock())
    shadow.apply_desired({"mode": "eco", "target": 12})

    result = shadow.apply_desired({"target": None})

    assert shadow.desired == {"mode": "eco"}
    assert result.accepted["state"] == {"desired": {"target": None}}
    assert shadow.get()["state"] == {
        "desired": {
            "mode": "eco",
        },
        "delta": {
            "mode": "eco",
        },
    }


def test_shadow_update_rejects_stale_version() -> None:
    shadow = DeviceShadow(clock=FakeClock())
    shadow.apply_desired({"mode": "eco"})

    with pytest.raises(ShadowVersionConflictError) as exc_info:
        shadow.apply_reported({"mode": "eco"}, version=0)

    assert exc_info.value.expected_version == 0
    assert exc_info.value.current_version == 1
    assert shadow.version == 1


def test_shadow_delete_clears_state_and_keeps_incrementing_version() -> None:
    shadow = DeviceShadow(clock=FakeClock())
    shadow.apply_desired({"mode": "eco"})

    response = shadow.delete(client_token="delete-token")

    assert response == {
        "version": 2,
        "timestamp": 1_700_000_000,
        "clientToken": "delete-token",
    }
    assert shadow.get() == {
        "version": 2,
        "timestamp": 1_700_000_000,
    }


def test_shadow_rejects_too_long_client_token() -> None:
    shadow = DeviceShadow(clock=FakeClock())

    with pytest.raises(ShadowDocumentError, match="clientToken"):
        shadow.apply_desired({"mode": "eco"}, client_token="x" * 65)


def test_parse_classic_shadow_update_topics_from_device_sessions() -> None:
    assert parse_shadow_topic("$aws/things/10_45_356489-Thing/shadow/update") == ShadowTopic(
        thing_name="10_45_356489-Thing",
        shadow_name=None,
        operation=ShadowOperation.UPDATE,
        lifecycle=None,
    )
    assert parse_shadow_topic(
        "$aws/things/10_45_356489-Thing/shadow/update/accepted"
    ) == ShadowTopic(
        thing_name="10_45_356489-Thing",
        shadow_name=None,
        operation=ShadowOperation.UPDATE,
        lifecycle=ShadowLifecycle.ACCEPTED,
    )
    assert parse_shadow_topic(
        "$aws/things/10_45_356489-Thing/shadow/update/rejected"
    ) == ShadowTopic(
        thing_name="10_45_356489-Thing",
        shadow_name=None,
        operation=ShadowOperation.UPDATE,
        lifecycle=ShadowLifecycle.REJECTED,
    )
    assert parse_shadow_topic(
        "$aws/things/10_45_356489-Thing/shadow/update/delta"
    ) == ShadowTopic(
        thing_name="10_45_356489-Thing",
        shadow_name=None,
        operation=ShadowOperation.UPDATE,
        lifecycle=ShadowLifecycle.DELTA,
    )


def test_parse_named_shadow_topic() -> None:
    assert parse_shadow_topic("$aws/things/softener/shadow/name/mobile/update/accepted") == (
        ShadowTopic(
            thing_name="softener",
            shadow_name="mobile",
            operation=ShadowOperation.UPDATE,
            lifecycle=ShadowLifecycle.ACCEPTED,
        )
    )


def test_parse_shadow_topic_rejects_invalid_lifecycle_for_operation() -> None:
    assert parse_shadow_topic("$aws/things/softener/shadow/get/delta") is None
    assert parse_shadow_topic("$aws/things/softener/shadow/delete/documents") is None
    assert parse_shadow_topic("$aws/things/softener/shadow/update/accepted/extra") is None


def test_build_shadow_topic() -> None:
    assert (
        build_shadow_topic(
            "10_45_356489-Thing",
            ShadowOperation.UPDATE,
            lifecycle=ShadowLifecycle.ACCEPTED,
        )
        == "$aws/things/10_45_356489-Thing/shadow/update/accepted"
    )
    assert (
        build_shadow_topic(
            "softener",
            ShadowOperation.GET,
            lifecycle=ShadowLifecycle.REJECTED,
            shadow_name="mobile",
        )
        == "$aws/things/softener/shadow/name/mobile/get/rejected"
    )


def test_build_shadow_topic_rejects_invalid_lifecycle_for_operation() -> None:
    with pytest.raises(ShadowDocumentError, match="not a valid shadow topic"):
        build_shadow_topic("softener", ShadowOperation.GET, lifecycle=ShadowLifecycle.DELTA)


def test_decode_shadow_payload_requires_json_object() -> None:
    assert decode_shadow_payload(b'{"clientToken":"token-1"}') == {"clientToken": "token-1"}

    with pytest.raises(ShadowDocumentError, match="valid JSON object"):
        decode_shadow_payload(b"{")
    with pytest.raises(ShadowDocumentError, match="JSON object"):
        decode_shadow_payload(b"[]")


def test_read_current_shadow_document() -> None:
    current = {"state": {"reported": {"mode": "eco"}}, "version": 3}

    assert read_current_shadow_document({"previous": {"version": 2}, "current": current}) is current

    with pytest.raises(ShadowDocumentError, match="current"):
        read_current_shadow_document({"previous": {"version": 2}})
