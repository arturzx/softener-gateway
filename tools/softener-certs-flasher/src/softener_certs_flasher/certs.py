from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from softener_certs_flasher.aws_certs import certificate_fingerprint
from softener_certs_flasher.errors import StopFlashing


class KeyType(StrEnum):
    RSA_2048 = "rsa2048"
    EC_P256 = "ec-p256"


@dataclass(frozen=True, slots=True)
class CertificateMaterial:
    ca_cert_pem: bytes
    ca_key_pem: bytes
    server_cert_pem: bytes
    server_key_pem: bytes
    ca_fingerprint: str
    server_fingerprint: str


def generate_certificate_material(
    *,
    host: str,
    ca_common_name: str,
    server_common_name: str,
    key_type: KeyType,
    valid_days: int,
) -> CertificateMaterial:
    if valid_days <= 0:
        raise StopFlashing("STOP: certificate validity must be positive")

    ca_key = _generate_private_key(key_type)
    server_key = _generate_private_key(key_type)
    now = datetime.now(tz=UTC)
    validity_start = now - timedelta(days=7)
    ca_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AZX"),
            x509.NameAttribute(NameOID.COMMON_NAME, ca_common_name),
        ]
    )
    server_subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, server_common_name)]
    )

    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(validity_start)
        .not_valid_after(now + timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )

    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(validity_start)
        .not_valid_after(now + timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(_subject_alt_name(host), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=isinstance(server_key, rsa.RSAPrivateKey),
                data_encipherment=False,
                key_agreement=isinstance(server_key, ec.EllipticCurvePrivateKey),
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )

    ca_cert_pem = ca_certificate.public_bytes(serialization.Encoding.PEM)
    server_cert_pem = server_certificate.public_bytes(serialization.Encoding.PEM)
    return CertificateMaterial(
        ca_cert_pem=ca_cert_pem,
        ca_key_pem=_private_key_pem(ca_key),
        server_cert_pem=server_cert_pem,
        server_key_pem=_private_key_pem(server_key),
        ca_fingerprint=certificate_fingerprint(ca_certificate),
        server_fingerprint=certificate_fingerprint(server_certificate),
    )


def load_ca_material(ca_cert_pem: bytes, ca_key_pem: bytes | None = None) -> tuple[bytes, str]:
    try:
        certificates = x509.load_pem_x509_certificates(ca_cert_pem)
    except ValueError as exc:
        raise StopFlashing(f"STOP: CA certificate file is not valid PEM: {exc}") from exc
    if len(certificates) != 1:
        raise StopFlashing(
            f"STOP: CA certificate file must contain exactly one certificate, "
            f"found {len(certificates)}"
        )
    certificate = certificates[0]
    try:
        basic_constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
    except x509.ExtensionNotFound as exc:
        raise StopFlashing("STOP: CA certificate lacks basicConstraints") from exc
    if not basic_constraints.ca:
        raise StopFlashing("STOP: CA certificate must have basicConstraints CA:TRUE")

    if ca_key_pem is not None:
        try:
            serialization.load_pem_private_key(ca_key_pem, password=None)
        except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
            raise StopFlashing(f"STOP: CA private key is not valid unencrypted PEM: {exc}") from exc

    return (
        certificate.public_bytes(serialization.Encoding.PEM),
        certificate_fingerprint(certificate),
    )


def _generate_private_key(key_type: KeyType) -> rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey:
    if key_type is KeyType.RSA_2048:
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)
    if key_type is KeyType.EC_P256:
        return ec.generate_private_key(ec.SECP256R1())

    raise StopFlashing(f"STOP: unsupported key type {key_type}")


def _private_key_pem(private_key: Any) -> bytes:
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    if not isinstance(key_pem, bytes):
        raise TypeError("private key serialization did not return bytes")

    return key_pem


def _subject_alt_name(host: str) -> x509.SubjectAlternativeName:
    return x509.SubjectAlternativeName([x509.DNSName(host)])
