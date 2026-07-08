from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.x509.oid import NameOID

from softener_certs_flasher.certs import KeyType, generate_certificate_material

SERVER_HOST = "softener-gateway.home.arpa"


def test_generated_certificates_are_valid_from_one_week_ago() -> None:
    before = datetime.now(tz=UTC)

    material = generate_certificate_material(
        host=SERVER_HOST,
        ca_common_name="Softener Test CA",
        server_common_name=SERVER_HOST,
        key_type=KeyType.EC_P256,
        valid_days=30,
    )

    after = datetime.now(tz=UTC)
    lower_bound = before - timedelta(days=7, seconds=5)
    upper_bound = after - timedelta(days=7) + timedelta(seconds=5)
    ca_certificate = x509.load_pem_x509_certificate(material.ca_cert_pem)
    server_certificate = x509.load_pem_x509_certificate(material.server_cert_pem)

    assert lower_bound <= ca_certificate.not_valid_before_utc <= upper_bound
    assert lower_bound <= server_certificate.not_valid_before_utc <= upper_bound
    assert ca_certificate.not_valid_before_utc == server_certificate.not_valid_before_utc


def test_generated_certificates_include_key_identifiers() -> None:
    material = generate_certificate_material(
        host=SERVER_HOST,
        ca_common_name="Softener Test CA",
        server_common_name=SERVER_HOST,
        key_type=KeyType.RSA_2048,
        valid_days=30,
    )

    ca_certificate = x509.load_pem_x509_certificate(material.ca_cert_pem)
    server_certificate = x509.load_pem_x509_certificate(material.server_cert_pem)
    ca_subject_key_identifier = ca_certificate.extensions.get_extension_for_class(
        x509.SubjectKeyIdentifier
    ).value
    ca_authority_key_identifier = ca_certificate.extensions.get_extension_for_class(
        x509.AuthorityKeyIdentifier
    ).value
    server_subject_key_identifier = server_certificate.extensions.get_extension_for_class(
        x509.SubjectKeyIdentifier
    ).value
    server_authority_key_identifier = server_certificate.extensions.get_extension_for_class(
        x509.AuthorityKeyIdentifier
    ).value

    assert ca_authority_key_identifier.key_identifier == ca_subject_key_identifier.digest
    assert server_subject_key_identifier.digest
    assert server_authority_key_identifier.key_identifier == ca_subject_key_identifier.digest


def test_generated_ca_subject_contains_organization_without_country() -> None:
    material = generate_certificate_material(
        host=SERVER_HOST,
        ca_common_name="Softener Test CA",
        server_common_name=SERVER_HOST,
        key_type=KeyType.RSA_2048,
        valid_days=30,
    )

    ca_certificate = x509.load_pem_x509_certificate(material.ca_cert_pem)
    server_certificate = x509.load_pem_x509_certificate(material.server_cert_pem)

    assert ca_certificate.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME) == []
    assert (
        ca_certificate.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)[0].value
        == "AZX"
    )
    assert (
        ca_certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        == "Softener Test CA"
    )
    assert server_certificate.issuer == ca_certificate.subject
    assert (
        server_certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        == SERVER_HOST
    )
    subject_alt_name = server_certificate.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    assert subject_alt_name.get_values_for_type(x509.DNSName) == [SERVER_HOST]


def test_generated_server_certificate_puts_ip_host_in_dns_san_only() -> None:
    host = "192.168.1.50"
    material = generate_certificate_material(
        host=host,
        ca_common_name="Softener Test CA",
        server_common_name=host,
        key_type=KeyType.RSA_2048,
        valid_days=30,
    )

    server_certificate = x509.load_pem_x509_certificate(material.server_cert_pem)
    subject_alt_name = server_certificate.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value

    assert subject_alt_name.get_values_for_type(x509.DNSName) == [host]
    assert subject_alt_name.get_values_for_type(x509.IPAddress) == []
