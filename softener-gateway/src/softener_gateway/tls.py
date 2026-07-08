import ssl
from tempfile import NamedTemporaryFile

from cryptography.hazmat.primitives import serialization

from softener_gateway.config import TlsConfig


def configure_tls_material(
    context: ssl.SSLContext,
    config: TlsConfig,
    *,
    temp_file_prefix: str = "softener-gateway",
) -> None:
    with (
        NamedTemporaryFile(prefix=f"{temp_file_prefix}-cert-") as cert_file,
        NamedTemporaryFile(prefix=f"{temp_file_prefix}-key-") as key_file,
    ):
        cert_file.write(config.certificate.public_bytes(serialization.Encoding.PEM))
        cert_file.seek(0)
        key_file.write(
            config.key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        key_file.seek(0)
        context.load_cert_chain(certfile=cert_file.name, keyfile=key_file.name)

    if config.ca is not None:
        context.load_verify_locations(cadata=_certificate_bundle_pem(config))


def _certificate_bundle_pem(config: TlsConfig) -> str:
    if config.ca is None:
        return ""

    return (
        b"".join(
            certificate.public_bytes(serialization.Encoding.PEM)
            for certificate in config.ca
        )
    ).decode("ascii")
