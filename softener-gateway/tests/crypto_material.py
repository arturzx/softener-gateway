from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID


@dataclass(frozen=True)
class PemMaterial:
    certificate: str
    key: str


def generate_pem_material(common_name: str = "localhost", key_size: int = 2048) -> PemMaterial:
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    return _generate_pem_material(key, common_name)


def generate_ec_pem_material(common_name: str = "localhost") -> PemMaterial:
    key = ec.generate_private_key(ec.SECP256R1())
    return _generate_pem_material(key, common_name)


def generate_ca_pem_material(common_name: str = "test-ca") -> PemMaterial:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _generate_pem_material(key, common_name, is_ca=True)


def generate_signed_pem_material(
    ca: PemMaterial,
    common_name: str = "client",
) -> PemMaterial:
    ca_certificate = x509.load_pem_x509_certificate(ca.certificate.encode("ascii"))
    ca_key = serialization.load_pem_private_key(ca.key.encode("ascii"), password=None)
    if not isinstance(ca_key, rsa.RSAPrivateKey):
        raise TypeError("CA material must use an RSA private key")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _generate_pem_material(
        key,
        common_name,
        issuer_certificate=ca_certificate,
        issuer_key=ca_key,
    )


def _generate_pem_material(
    key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey,
    common_name: str,
    *,
    issuer_certificate: x509.Certificate | None = None,
    issuer_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | None = None,
    is_ca: bool = False,
) -> PemMaterial:
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    issuer = issuer_certificate.subject if issuer_certificate is not None else subject
    signing_key = issuer_key if issuer_key is not None else key
    now = datetime.now(tz=UTC)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .sign(private_key=signing_key, algorithm=hashes.SHA256())
    )

    return PemMaterial(
        certificate=certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        key=key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii"),
    )
