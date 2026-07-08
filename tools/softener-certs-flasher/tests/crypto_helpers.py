from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID


@dataclass(frozen=True)
class PemMaterial:
    certificate: bytes
    key: bytes


def generate_pem_material(common_name: str = "localhost") -> PemMaterial:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _generate_pem_material(key, common_name, is_ca=False)


def generate_ca_pem_material(common_name: str = "test-ca") -> PemMaterial:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _generate_pem_material(key, common_name, is_ca=True)


def generate_ec_ca_pem_material(common_name: str = "test-ca") -> PemMaterial:
    key = ec.generate_private_key(ec.SECP256R1())
    return _generate_pem_material(key, common_name, is_ca=True)


def _generate_pem_material(
    key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey,
    common_name: str,
    *,
    is_ca: bool,
) -> PemMaterial:
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(tz=UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .sign(private_key=key, algorithm=hashes.SHA256())
    )
    return PemMaterial(
        certificate=certificate.public_bytes(serialization.Encoding.PEM),
        key=key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
