from __future__ import annotations

import pytest

from softener_certs_flasher.aws_certs import (
    AwsCertsLayout,
    parse_aws_certs,
    patch_aws_certs,
)
from softener_certs_flasher.errors import StopFlashing
from tests.crypto_helpers import generate_ca_pem_material, generate_pem_material

AWS_HOST = "a1u0ne27rnnqid-ats.iot.us-east-1.amazonaws.com"
AWS_PORT = "8883"


def test_newline_delimited_payload_allows_ca_longer_than_original_ca() -> None:
    old_ca = generate_ca_pem_material("ca")
    new_ca = generate_ca_pem_material(
        "replacement-ca-with-longer-subject-for-softener-tests"
    )
    client = generate_pem_material("softener-client")
    original_payload = _payload(
        AWS_HOST.encode("ascii"),
        AWS_PORT.encode("ascii"),
        b"10_45_356489-Thing",
        b"45",
        b"10",
        b"002411881212167528871224" + old_ca.certificate,
        client.key,
        client.certificate,
    )
    original = _partition(original_payload, len(original_payload) + 4096)

    assert len(new_ca.certificate) > len(old_ca.certificate)

    result = patch_aws_certs(
        original,
        new_ca_pem=new_ca.certificate,
        host="softener-gateway.home.arpa",
        port=8883,
    )

    assert result.original.layout is AwsCertsLayout.NEWLINE_DELIMITED_PAYLOAD
    assert result.patched.host == "softener-gateway.home.arpa"
    assert result.patched.port == 8883
    assert len(result.image) == len(original)
    assert result.plan.free_bytes == len(result.image) - result.plan.final_payload_size
    assert result.image[result.plan.final_payload_size :] == b"\xff" * result.plan.free_bytes
    assert result.plan.padding == "0xff"
    assert result.plan.client_certificate_unchanged
    assert result.plan.private_key_unchanged
    assert result.plan.changed_ranges


def test_newline_delimited_payload_rejects_rebuilt_payload_larger_than_partition() -> None:
    old_ca = generate_ca_pem_material("ca")
    new_ca = generate_ca_pem_material(
        "replacement-ca-with-longer-subject-for-softener-tests"
    )
    client = generate_pem_material("softener-client")
    original_payload = _payload(
        AWS_HOST.encode("ascii"),
        AWS_PORT.encode("ascii"),
        old_ca.certificate,
        client.key,
        client.certificate,
    )
    original = _partition(original_payload, len(original_payload) + 1)

    with pytest.raises(StopFlashing) as error:
        patch_aws_certs(
            original,
            new_ca_pem=new_ca.certificate,
            host=None,
            port=None,
        )

    assert "aws_certs partition size is" in str(error.value)
    assert "rebuilt payload size is" in str(error.value)
    assert "missing" in str(error.value)
    assert "EC P-256" in str(error.value)


def test_host_replacement_rejects_single_label_hostname() -> None:
    old_ca = generate_ca_pem_material("ca")
    new_ca = generate_ca_pem_material("replacement-ca")
    client = generate_pem_material("softener-client")
    original_payload = _payload(
        AWS_HOST.encode("ascii"),
        AWS_PORT.encode("ascii"),
        old_ca.certificate,
        client.key,
        client.certificate,
    )
    original = _partition(original_payload, len(original_payload) + 4096)

    with pytest.raises(StopFlashing, match="invalid host replacement"):
        patch_aws_certs(
            original,
            new_ca_pem=new_ca.certificate,
            host="homeassistant",
            port=None,
        )


def test_host_replacement_allows_ipv4_address() -> None:
    old_ca = generate_ca_pem_material("ca")
    new_ca = generate_ca_pem_material("replacement-ca")
    client = generate_pem_material("softener-client")
    original_payload = _payload(
        AWS_HOST.encode("ascii"),
        AWS_PORT.encode("ascii"),
        old_ca.certificate,
        client.key,
        client.certificate,
    )
    original = _partition(original_payload, len(original_payload) + 4096)

    result = patch_aws_certs(
        original,
        new_ca_pem=new_ca.certificate,
        host="192.168.1.50",
        port=None,
    )

    assert result.patched.host == "192.168.1.50"


def test_host_replacement_rejects_ipv6_address() -> None:
    old_ca = generate_ca_pem_material("ca")
    new_ca = generate_ca_pem_material("replacement-ca")
    client = generate_pem_material("softener-client")
    original_payload = _payload(
        AWS_HOST.encode("ascii"),
        AWS_PORT.encode("ascii"),
        old_ca.certificate,
        client.key,
        client.certificate,
    )
    original = _partition(original_payload, len(original_payload) + 4096)

    with pytest.raises(StopFlashing, match="invalid host replacement"):
        patch_aws_certs(
            original,
            new_ca_pem=new_ca.certificate,
            host="fd00::1",
            port=None,
        )


@pytest.mark.parametrize("host", ["homeassistant.local", "homeassistant.LOCAL."])
def test_host_replacement_rejects_local_domains(host: str) -> None:
    old_ca = generate_ca_pem_material("ca")
    new_ca = generate_ca_pem_material("replacement-ca")
    client = generate_pem_material("softener-client")
    original_payload = _payload(
        AWS_HOST.encode("ascii"),
        AWS_PORT.encode("ascii"),
        old_ca.certificate,
        client.key,
        client.certificate,
    )
    original = _partition(original_payload, len(original_payload) + 4096)

    with pytest.raises(StopFlashing, match="invalid host replacement"):
        patch_aws_certs(
            original,
            new_ca_pem=new_ca.certificate,
            host=host,
            port=None,
        )


def test_host_and_port_are_positional_text_fields() -> None:
    old_ca = generate_ca_pem_material("ca")
    client = generate_pem_material("softener-client")
    original_payload = _payload(
        AWS_HOST.encode("ascii"),
        AWS_PORT.encode("ascii"),
        b"thing.local",
        old_ca.certificate,
        client.key,
        client.certificate,
    )
    original = _partition(original_payload, len(original_payload) + 4096)

    parsed = parse_aws_certs(original)

    assert parsed.host == AWS_HOST
    assert parsed.port == int(AWS_PORT)


def test_null_delimited_partition_stops() -> None:
    old_ca = generate_ca_pem_material("ca")
    new_ca = generate_ca_pem_material(
        "replacement-ca-with-longer-subject-for-softener-tests"
    )
    client = generate_pem_material("softener-client")
    original = b"".join(
        [
            AWS_HOST.encode("ascii"),
            b"\x00" * 96,
            AWS_PORT.encode("ascii"),
            b"\x00" * 96,
            old_ca.certificate,
            b"\x00" * 96,
            client.certificate,
            b"\x00" * 96,
            client.key,
            b"\x00" * 256,
        ]
    )

    parsed = parse_aws_certs(bytes(original))
    assert parsed.layout is AwsCertsLayout.UNKNOWN

    with pytest.raises(StopFlashing, match="recognized newline-delimited payload"):
        patch_aws_certs(
            bytes(original),
            new_ca_pem=new_ca.certificate,
            host=None,
            port=None,
        )


def test_unparseable_payload_stops() -> None:
    new_ca = generate_ca_pem_material("replacement-ca")
    unknown = _partition(b"not-an-aws-certs-layout\n", 128)

    assert parse_aws_certs(unknown).layout is AwsCertsLayout.UNKNOWN
    with pytest.raises(StopFlashing, match="recognized newline-delimited payload"):
        patch_aws_certs(unknown, new_ca_pem=new_ca.certificate, host=None, port=None)


def _payload(*fields: bytes) -> bytes:
    return b"".join(
        field if field.endswith(b"\n") else field + b"\n" for field in fields
    )


def _partition(payload: bytes, size: int) -> bytes:
    assert len(payload) <= size
    return payload + b"\xff" * (size - len(payload))
