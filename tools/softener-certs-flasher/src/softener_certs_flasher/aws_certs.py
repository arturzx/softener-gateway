from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtensionOID

from softener_certs_flasher.errors import StopFlashing


class AwsCertsLayout(StrEnum):
    NEWLINE_DELIMITED_PAYLOAD = "newline_delimited_payload"
    UNKNOWN = "unknown"


class AwsCertsFieldKind(StrEnum):
    HOST = "host"
    PORT = "port"
    ROOT_CA = "root_ca"
    CLIENT_CERTIFICATE = "client_certificate"
    PRIVATE_KEY = "private_key"
    EXTRA = "extra"
    CERTIFICATE = "certificate"


@dataclass(slots=True)
class AwsCertsField:
    kind: AwsCertsFieldKind
    value: bytes
    start: int
    end: int
    text: str | None = None
    certificate: x509.Certificate | None = None
    private_key: Any | None = None


@dataclass(frozen=True, slots=True)
class AwsCertsPart:
    value: bytes
    field: AwsCertsField | None = None


@dataclass(frozen=True, slots=True)
class AwsCertsToken:
    start: int
    end: int
    parts: tuple[AwsCertsPart, ...]


@dataclass(frozen=True, slots=True)
class ParsedAwsCerts:
    layout: AwsCertsLayout
    partition_size: int
    tokens: tuple[AwsCertsToken, ...] = ()
    fields: tuple[AwsCertsField, ...] = ()
    payload_size: int = 0
    error: str | None = None

    @property
    def host(self) -> str | None:
        field = self.field(AwsCertsFieldKind.HOST)
        return field.text if field is not None else None

    @property
    def port(self) -> int | None:
        field = self.field(AwsCertsFieldKind.PORT)
        if field is None or field.text is None:
            return None

        return int(field.text)

    def field(self, kind: AwsCertsFieldKind) -> AwsCertsField | None:
        for field in self.fields:
            if field.kind is kind:
                return field

        return None


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class AwsCertsPatchPlan:
    host_old: str | None
    host_new: str | None
    port_old: int | None
    port_new: int | None
    root_ca_fingerprint_old: str
    root_ca_fingerprint_new: str
    client_certificate_fingerprint_old: str
    client_certificate_fingerprint_new: str
    client_certificate_unchanged: bool
    private_key_public_fingerprint_old: str
    private_key_public_fingerprint_new: str
    private_key_unchanged: bool
    final_payload_size: int
    free_bytes: int
    padding: str
    changed_ranges: tuple[ByteRange, ...]


@dataclass(frozen=True, slots=True)
class AwsCertsPatchResult:
    image: bytes
    original: ParsedAwsCerts
    patched: ParsedAwsCerts
    plan: AwsCertsPatchPlan


class _ParseFailure(ValueError):
    pass


_PEM_BLOCK_RE = re.compile(
    rb"-----BEGIN ([A-Z0-9 ]+)-----\r?\n.*?-----END \1-----\r?\n?",
    re.DOTALL,
)


def parse_aws_certs(data: bytes) -> ParsedAwsCerts:
    try:
        return _parse_newline_delimited_payload(data)
    except _ParseFailure as parse_error:
        return ParsedAwsCerts(
            layout=AwsCertsLayout.UNKNOWN,
            partition_size=len(data),
            error=(
                "aws_certs is not a recognized newline-delimited payload: "
                f"{parse_error}"
            ),
        )


def patch_aws_certs(
    original_image: bytes,
    *,
    new_ca_pem: bytes,
    host: str | None,
    port: int | None,
    client_certificate_pem: bytes | None = None,
    private_key_pem: bytes | None = None,
) -> AwsCertsPatchResult:
    original = parse_aws_certs(original_image)
    if original.layout is AwsCertsLayout.UNKNOWN:
        error = original.error or "aws_certs is not a recognized newline-delimited payload"
        raise StopFlashing(f"STOP: {error}")

    _validate_original(original)
    replacements = _build_replacements(
        original,
        new_ca_pem=new_ca_pem,
        host=host,
        port=port,
        client_certificate_pem=client_certificate_pem,
        private_key_pem=private_key_pem,
    )

    patched_image, payload_size = _build_newline_delimited_image(original, replacements)

    patched = parse_aws_certs(patched_image)
    _validate_patched(
        original,
        patched,
        patched_image,
        payload_size,
        host=host,
        port=port,
        client_certificate_replaced=client_certificate_pem is not None,
        private_key_replaced=private_key_pem is not None,
    )

    return AwsCertsPatchResult(
        image=patched_image,
        original=original,
        patched=patched,
        plan=_build_patch_plan(original, patched, original_image, patched_image, payload_size),
    )


def format_patch_plan(result: AwsCertsPatchResult) -> str:
    plan = result.plan
    root_ca = _require_field(result.patched, AwsCertsFieldKind.ROOT_CA)
    if root_ca.certificate is None:
        raise StopFlashing("STOP: patched root CA certificate did not parse")

    lines = [
        f"aws_certs payload format: {result.original.layout.value}",
        "planned aws_certs write:",
        f"- host: {_format_change(plan.host_old, plan.host_new)}",
        f"- port: {_format_change(plan.port_old, plan.port_new)}",
        *format_certificate_summary("new root CA", root_ca.certificate).splitlines(),
        "- device certificate: unchanged; left intact"
        if plan.client_certificate_unchanged
        else "- device certificate: will be replaced",
        "- device private key: unchanged; left intact"
        if plan.private_key_unchanged
        else "- device private key: will be replaced",
        f"- final payload size: {plan.final_payload_size} bytes",
        f"- free bytes left in aws_certs partition: {plan.free_bytes} bytes",
        f"- padding: {plan.padding}",
    ]

    return "\n".join(lines)


def format_certificate_summary(label: str, certificate: x509.Certificate) -> str:
    return "\n".join(
        [
            f"- {label}:",
            f"  serial: {_format_certificate_serial(certificate)}",
            f"  issuer: {certificate.issuer.rfc4514_string()}",
            f"  subject: {certificate.subject.rfc4514_string()}",
            (
                "  validity: "
                f"{_format_certificate_time(certificate.not_valid_before_utc)} to "
                f"{_format_certificate_time(certificate.not_valid_after_utc)}"
            ),
        ]
    )


def format_private_key_summary(
    label: str,
    private_key: Any,
    *,
    certificate: x509.Certificate | None = None,
) -> str:
    match_text = ""
    if certificate is not None:
        match_text = (
            "; matches device certificate"
            if _private_key_matches_certificate(private_key, certificate)
            else "; does not match device certificate"
        )

    return "\n".join(
        [
            f"- {label}: present{match_text}",
            f"  public key: {_format_public_key(private_key.public_key())}",
        ]
    )


def certificate_fingerprint(certificate: x509.Certificate) -> str:
    return certificate.fingerprint(hashes.SHA256()).hex()


def private_key_public_fingerprint(private_key: Any) -> str:
    return hashlib.sha256(_public_key_der(private_key.public_key())).hexdigest()


def public_key_fingerprint(public_key: Any) -> str:
    return hashlib.sha256(_public_key_der(public_key)).hexdigest()


def _parse_newline_delimited_payload(data: bytes) -> ParsedAwsCerts:
    if not data:
        raise _ParseFailure("partition is empty")

    payload_size = len(data.rstrip(b"\xff"))
    if payload_size == 0:
        raise _ParseFailure("partition contains only 0xff padding")

    payload = data[:payload_size]
    if b"\x00" in payload:
        raise _ParseFailure("newline-delimited payload contains a NUL byte")
    if b"\n" not in payload:
        raise _ParseFailure("newline-delimited payload has no newline separators")

    tokens = _parse_newline_delimited_tokens(payload)
    if not tokens:
        raise _ParseFailure("newline-delimited payload has no fields")

    fields = _fields_from_tokens(tokens)
    _classify_fields(fields)
    return ParsedAwsCerts(
        layout=AwsCertsLayout.NEWLINE_DELIMITED_PAYLOAD,
        partition_size=len(data),
        tokens=tuple(tokens),
        fields=fields,
        payload_size=payload_size,
    )


def _parse_newline_delimited_tokens(payload: bytes) -> list[AwsCertsToken]:
    tokens: list[AwsCertsToken] = []
    cursor = 0
    while cursor < len(payload):
        match = _PEM_BLOCK_RE.search(payload, cursor)
        if match is None:
            _append_newline_text_tokens(tokens, payload[cursor:], cursor)
            break

        prefix = payload[cursor : match.start()]
        last_newline_index = prefix.rfind(b"\n")
        if last_newline_index >= 0:
            complete_lines_end = cursor + last_newline_index + 1
            _append_newline_text_tokens(
                tokens,
                payload[cursor:complete_lines_end],
                cursor,
            )
            token_start = complete_lines_end
        else:
            token_start = cursor

        token_end = match.end()
        token_value = payload[token_start:token_end]
        tokens.append(
            AwsCertsToken(
                start=token_start,
                end=token_end,
                parts=_parse_token_parts(token_value, token_start),
            )
        )
        cursor = token_end

    return tokens


def _append_newline_text_tokens(
    tokens: list[AwsCertsToken],
    value: bytes,
    absolute_start: int,
) -> None:
    cursor = 0
    while cursor < len(value):
        newline_index = value.find(b"\n", cursor)
        token_end = len(value) if newline_index < 0 else newline_index + 1
        token_value = value[cursor:token_end]
        if not token_value.strip(b" \t\r\n"):
            raise _ParseFailure("empty newline-delimited text field")

        token_start = absolute_start + cursor
        tokens.append(
            AwsCertsToken(
                start=token_start,
                end=absolute_start + token_end,
                parts=_parse_token_parts(token_value, token_start),
            )
        )
        cursor = token_end


def _parse_token_parts(token: bytes, token_start: int) -> tuple[AwsCertsPart, ...]:
    matches = tuple(_PEM_BLOCK_RE.finditer(token))
    if not matches:
        if b"-----BEGIN " in token or b"-----END " in token:
            raise _ParseFailure("malformed PEM block")

        return (AwsCertsPart(value=token, field=_parse_text_field(token, token_start)),)

    parts: list[AwsCertsPart] = []
    cursor = 0
    for match in matches:
        prefix = token[cursor : match.start()]
        if prefix:
            if _is_ascii_whitespace(prefix):
                parts.append(AwsCertsPart(value=prefix))
            else:
                parts.append(
                    AwsCertsPart(
                        value=prefix,
                        field=_parse_text_field(prefix, token_start + cursor),
                    )
                )

        pem_block = match.group(0)
        field = _parse_pem_field(
            pem_block,
            match.group(1).decode("ascii"),
            token_start + match.start(),
        )
        parts.append(AwsCertsPart(value=pem_block, field=field))
        cursor = match.end()

    suffix = token[cursor:]
    if not _is_ascii_whitespace(suffix):
        raise _ParseFailure("non-whitespace bytes found after PEM block")
    if suffix:
        parts.append(AwsCertsPart(value=suffix))

    return tuple(parts)


def _parse_text_field(token: bytes, field_start: int) -> AwsCertsField:
    text = _decode_text_token(token)
    return AwsCertsField(
        kind=AwsCertsFieldKind.EXTRA,
        value=token,
        start=field_start,
        end=field_start + len(token),
        text=text,
    )


def _parse_pem_field(pem_block: bytes, pem_type: str, field_start: int) -> AwsCertsField:
    if pem_type == "CERTIFICATE":
        try:
            certificate = x509.load_pem_x509_certificate(pem_block)
        except ValueError as exc:
            raise _ParseFailure(f"invalid PEM certificate: {exc}") from exc

        return AwsCertsField(
            kind=AwsCertsFieldKind.CERTIFICATE,
            value=pem_block,
            start=field_start,
            end=field_start + len(pem_block),
            certificate=certificate,
        )

    if pem_type.endswith("PRIVATE KEY"):
        try:
            private_key = serialization.load_pem_private_key(pem_block, password=None)
        except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
            raise _ParseFailure(f"invalid unencrypted PEM private key: {exc}") from exc

        return AwsCertsField(
            kind=AwsCertsFieldKind.PRIVATE_KEY,
            value=pem_block,
            start=field_start,
            end=field_start + len(pem_block),
            private_key=private_key,
        )

    raise _ParseFailure(f"unsupported PEM block type {pem_type!r}")


def _classify_fields(fields: tuple[AwsCertsField, ...]) -> None:
    ca_fields: list[AwsCertsField] = []
    client_fields: list[AwsCertsField] = []
    for field in fields:
        if field.kind is not AwsCertsFieldKind.CERTIFICATE or field.certificate is None:
            continue
        if _certificate_has_ca_true(field.certificate):
            ca_fields.append(field)
        else:
            client_fields.append(field)

    if len(ca_fields) != 1:
        raise _ParseFailure(f"expected exactly one CA:TRUE certificate, found {len(ca_fields)}")
    if len(client_fields) != 1:
        raise _ParseFailure(
            f"expected exactly one client certificate, found {len(client_fields)}"
        )

    ca_fields[0].kind = AwsCertsFieldKind.ROOT_CA
    client_fields[0].kind = AwsCertsFieldKind.CLIENT_CERTIFICATE

    key_fields = [field for field in fields if field.kind is AwsCertsFieldKind.PRIVATE_KEY]
    if len(key_fields) != 1:
        raise _ParseFailure(f"expected exactly one private key, found {len(key_fields)}")

    text_fields = [
        field
        for field in fields
        if field.kind is AwsCertsFieldKind.EXTRA and field.text is not None
    ]
    if len(text_fields) < 2:
        raise _ParseFailure(
            f"expected at least host and port text fields, found {len(text_fields)}"
        )

    text_fields[0].kind = AwsCertsFieldKind.HOST
    text_fields[1].kind = AwsCertsFieldKind.PORT


def _build_replacements(
    original: ParsedAwsCerts,
    *,
    new_ca_pem: bytes,
    host: str | None,
    port: int | None,
    client_certificate_pem: bytes | None,
    private_key_pem: bytes | None,
) -> dict[AwsCertsFieldKind, bytes]:
    root_ca = _load_one_certificate(new_ca_pem, "new CA")
    _require_ca_true(root_ca, "new CA")
    replacements = {
        AwsCertsFieldKind.ROOT_CA: root_ca.public_bytes(serialization.Encoding.PEM),
    }

    if host is not None:
        if original.field(AwsCertsFieldKind.HOST) is None:
            raise StopFlashing("STOP: host replacement requested but host field was not found")
        replacements[AwsCertsFieldKind.HOST] = _host_bytes(host)

    if port is not None:
        if original.field(AwsCertsFieldKind.PORT) is None:
            raise StopFlashing("STOP: port replacement requested but port field was not found")
        replacements[AwsCertsFieldKind.PORT] = _port_bytes(port)

    if client_certificate_pem is not None:
        client_certificate = _load_one_certificate(
            client_certificate_pem,
            "replacement client certificate",
        )
        replacements[AwsCertsFieldKind.CLIENT_CERTIFICATE] = client_certificate.public_bytes(
            serialization.Encoding.PEM
        )

    if private_key_pem is not None:
        private_key = _load_private_key(private_key_pem, "replacement private key")
        replacements[AwsCertsFieldKind.PRIVATE_KEY] = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    return replacements


def _build_newline_delimited_image(
    original: ParsedAwsCerts,
    replacements: dict[AwsCertsFieldKind, bytes],
) -> tuple[bytes, int]:
    token_values = [_build_token_value(token, replacements) for token in original.tokens]
    payload = b"".join(token_values)
    _ensure_payload_fits(len(payload), original.partition_size)
    return payload + b"\xff" * (original.partition_size - len(payload)), len(payload)


def _build_token_value(
    token: AwsCertsToken,
    replacements: dict[AwsCertsFieldKind, bytes],
) -> bytes:
    chunks: list[bytes] = []
    for part in token.parts:
        if part.field is None:
            chunks.append(part.value)
            continue

        replacement = replacements.get(part.field.kind)
        chunks.append(
            part.value if replacement is None else _format_like(part.field.value, replacement)
        )

    return b"".join(chunks)


def _validate_original(parsed: ParsedAwsCerts) -> None:
    root_ca = _require_field(parsed, AwsCertsFieldKind.ROOT_CA)
    client_certificate = _require_field(parsed, AwsCertsFieldKind.CLIENT_CERTIFICATE)
    private_key = _require_field(parsed, AwsCertsFieldKind.PRIVATE_KEY)
    if root_ca.certificate is None:
        raise StopFlashing("STOP: original CA certificate did not parse")
    if client_certificate.certificate is None:
        raise StopFlashing("STOP: original client certificate did not parse")
    if private_key.private_key is None:
        raise StopFlashing("STOP: original private key did not parse")

    _require_ca_true(root_ca.certificate, "original CA")
    _require_key_matches_certificate(
        private_key.private_key,
        client_certificate.certificate,
        "original",
    )
    if parsed.field(AwsCertsFieldKind.HOST) is not None and not parsed.host:
        raise StopFlashing("STOP: original host field is empty")
    if parsed.field(AwsCertsFieldKind.PORT) is not None:
        _validate_port(parsed.port)


def _validate_patched(
    original: ParsedAwsCerts,
    patched: ParsedAwsCerts,
    patched_image: bytes,
    payload_size: int,
    *,
    host: str | None,
    port: int | None,
    client_certificate_replaced: bool,
    private_key_replaced: bool,
) -> None:
    if patched.layout is AwsCertsLayout.UNKNOWN:
        detail = f": {patched.error}" if patched.error else ""
        raise StopFlashing(f"STOP: patched aws_certs cannot be parsed{detail}")
    if patched.layout is not original.layout:
        raise StopFlashing(
            "STOP: patched aws_certs layout changed from "
            f"{original.layout.value} to {patched.layout.value}"
        )
    if len(patched_image) != original.partition_size:
        raise StopFlashing(
            "STOP: patched aws_certs size mismatch: "
            f"expected {original.partition_size}, got {len(patched_image)}"
        )
    _ensure_payload_fits(payload_size, original.partition_size)
    if patched_image[payload_size:] != b"\xff" * (original.partition_size - payload_size):
        raise StopFlashing("STOP: patched aws_certs trailing padding is not 0xff")
    if _required_kinds(original) != _required_kinds(patched):
        raise StopFlashing(
            "STOP: parser patched image returned a different required field set"
        )

    root_ca = _require_field(patched, AwsCertsFieldKind.ROOT_CA)
    client_certificate = _require_field(patched, AwsCertsFieldKind.CLIENT_CERTIFICATE)
    private_key = _require_field(patched, AwsCertsFieldKind.PRIVATE_KEY)
    if root_ca.certificate is None:
        raise StopFlashing("STOP: patched CA certificate did not parse")
    if client_certificate.certificate is None:
        raise StopFlashing("STOP: patched client certificate did not parse")
    if private_key.private_key is None:
        raise StopFlashing("STOP: patched private key did not parse")

    _require_ca_true(root_ca.certificate, "patched CA")
    _require_key_matches_certificate(
        private_key.private_key,
        client_certificate.certificate,
        "patched",
    )

    if not client_certificate_replaced:
        original_client = _require_field(original, AwsCertsFieldKind.CLIENT_CERTIFICATE)
        if client_certificate.value != original_client.value:
            raise StopFlashing("STOP: client certificate changed unexpectedly")
    if not private_key_replaced:
        original_private_key = _require_field(original, AwsCertsFieldKind.PRIVATE_KEY)
        if private_key.value != original_private_key.value:
            raise StopFlashing("STOP: private key changed unexpectedly")

    if patched.field(AwsCertsFieldKind.HOST) is not None and not patched.host:
        raise StopFlashing("STOP: patched host field is empty")
    if host is not None and patched.host != host.strip():
        raise StopFlashing(
            f"STOP: patched host mismatch: expected {host.strip()!r}, got {patched.host!r}"
        )
    if patched.field(AwsCertsFieldKind.PORT) is not None:
        _validate_port(patched.port)
    if port is not None and patched.port != port:
        raise StopFlashing(f"STOP: patched port mismatch: expected {port}, got {patched.port}")


def _build_patch_plan(
    original: ParsedAwsCerts,
    patched: ParsedAwsCerts,
    original_image: bytes,
    patched_image: bytes,
    payload_size: int,
) -> AwsCertsPatchPlan:
    original_root_ca = _require_field(original, AwsCertsFieldKind.ROOT_CA)
    patched_root_ca = _require_field(patched, AwsCertsFieldKind.ROOT_CA)
    original_client = _require_field(original, AwsCertsFieldKind.CLIENT_CERTIFICATE)
    patched_client = _require_field(patched, AwsCertsFieldKind.CLIENT_CERTIFICATE)
    original_key = _require_field(original, AwsCertsFieldKind.PRIVATE_KEY)
    patched_key = _require_field(patched, AwsCertsFieldKind.PRIVATE_KEY)
    if (
        original_root_ca.certificate is None
        or patched_root_ca.certificate is None
        or original_client.certificate is None
        or patched_client.certificate is None
        or original_key.private_key is None
        or patched_key.private_key is None
    ):
        raise StopFlashing("STOP: cannot build aws_certs patch plan")

    return AwsCertsPatchPlan(
        host_old=original.host,
        host_new=patched.host,
        port_old=original.port,
        port_new=patched.port,
        root_ca_fingerprint_old=certificate_fingerprint(original_root_ca.certificate),
        root_ca_fingerprint_new=certificate_fingerprint(patched_root_ca.certificate),
        client_certificate_fingerprint_old=certificate_fingerprint(
            original_client.certificate
        ),
        client_certificate_fingerprint_new=certificate_fingerprint(patched_client.certificate),
        client_certificate_unchanged=original_client.value == patched_client.value,
        private_key_public_fingerprint_old=private_key_public_fingerprint(
            original_key.private_key
        ),
        private_key_public_fingerprint_new=private_key_public_fingerprint(
            patched_key.private_key
        ),
        private_key_unchanged=original_key.value == patched_key.value,
        final_payload_size=payload_size,
        free_bytes=len(patched_image) - payload_size,
        padding="0xff",
        changed_ranges=_changed_ranges(original_image, patched_image),
    )


def _fields_from_tokens(tokens: list[AwsCertsToken]) -> tuple[AwsCertsField, ...]:
    fields: list[AwsCertsField] = []
    for token in tokens:
        fields.extend(part.field for part in token.parts if part.field is not None)

    return tuple(fields)


def _decode_text_token(token: bytes) -> str:
    try:
        text = token.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise _ParseFailure("text field is not ASCII") from exc

    if not text:
        raise _ParseFailure("empty text field")
    return text


def _is_ascii_whitespace(value: bytes) -> bool:
    return all(byte in b" \t\r\n" for byte in value)


def _certificate_has_ca_true(certificate: x509.Certificate) -> bool:
    try:
        extension = certificate.extensions.get_extension_for_oid(
            ExtensionOID.BASIC_CONSTRAINTS
        )
    except x509.ExtensionNotFound:
        return False

    constraints = extension.value
    return isinstance(constraints, x509.BasicConstraints) and constraints.ca


def _load_one_certificate(pem: bytes, label: str) -> x509.Certificate:
    try:
        certificates = x509.load_pem_x509_certificates(pem)
    except ValueError as exc:
        raise StopFlashing(f"STOP: {label} must be a valid PEM certificate: {exc}") from exc
    if len(certificates) != 1:
        raise StopFlashing(
            f"STOP: {label} must contain exactly one PEM certificate, found "
            f"{len(certificates)}"
        )

    return certificates[0]


def _load_private_key(pem: bytes, label: str) -> Any:
    try:
        return serialization.load_pem_private_key(pem, password=None)
    except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
        raise StopFlashing(
            f"STOP: {label} must be a valid unencrypted PEM private key: {exc}"
        ) from exc


def _require_ca_true(certificate: x509.Certificate, label: str) -> None:
    if not _certificate_has_ca_true(certificate):
        raise StopFlashing(f"STOP: {label} must have basicConstraints CA:TRUE")


def _require_key_matches_certificate(
    private_key: Any,
    certificate: x509.Certificate,
    label: str,
) -> None:
    if not _private_key_matches_certificate(private_key, certificate):
        raise StopFlashing(
            f"STOP: {label} private key does not match client certificate"
        )


def _private_key_matches_certificate(private_key: Any, certificate: x509.Certificate) -> bool:
    return _public_key_der(private_key.public_key()) == _public_key_der(
        certificate.public_key()
    )


def _public_key_der(public_key: Any) -> bytes:
    public_key_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if not isinstance(public_key_der, bytes):
        raise TypeError("public key serialization did not return bytes")

    return public_key_der


def _format_certificate_serial(certificate: x509.Certificate) -> str:
    return f"0x{certificate.serial_number:x}"


def _format_certificate_time(value: Any) -> str:
    formatted = str(value.isoformat(timespec="seconds"))
    if formatted.endswith("+00:00"):
        return formatted[:-6] + "Z"

    return formatted


def _format_public_key(public_key: Any) -> str:
    if isinstance(public_key, rsa.RSAPublicKey):
        return f"RSA {public_key.key_size} bit"
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        return f"EC {public_key.curve.name}"

    return type(public_key).__name__


def _looks_like_port(text: str | None) -> bool:
    if text is None or not text.isdecimal():
        return False

    value = int(text)
    return 1 <= value <= 65535


def _is_valid_host_replacement(text: str | None) -> bool:
    if text is None or not text or len(text) > 253:
        return False
    if ":" in text:
        return False
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        pass
    else:
        return address.version == 4

    if "." not in text:
        return False
    normalized = text.rstrip(".").lower()
    if normalized == "local" or normalized.endswith(".local"):
        return False

    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")
    return all(character in allowed for character in text)


def _host_bytes(host: str) -> bytes:
    stripped = host.strip()
    if not _is_valid_host_replacement(stripped) or "\x00" in stripped:
        raise StopFlashing(f"STOP: invalid host replacement {host!r}")
    try:
        return stripped.encode("ascii")
    except UnicodeEncodeError as exc:
        raise StopFlashing(f"STOP: host must be ASCII: {host!r}") from exc


def _port_bytes(port: int) -> bytes:
    if not 1 <= port <= 65535:
        raise StopFlashing("STOP: port must be in range 1-65535")
    return str(port).encode("ascii")


def _validate_port(port: int | None) -> None:
    if port is None or not 1 <= port <= 65535:
        raise StopFlashing("STOP: port must be a number in range 1-65535")


def _format_like(original: bytes, replacement: bytes) -> bytes:
    if b"\x00" in replacement:
        raise StopFlashing("STOP: replacement contains a null byte")

    stripped = replacement.rstrip(b"\r\n")
    if original.endswith(b"\r\n"):
        return stripped + b"\r\n"
    if original.endswith(b"\n"):
        return stripped + b"\n"

    return stripped


def _required_kinds(parsed: ParsedAwsCerts) -> set[AwsCertsFieldKind]:
    kinds = {
        AwsCertsFieldKind.ROOT_CA,
        AwsCertsFieldKind.CLIENT_CERTIFICATE,
        AwsCertsFieldKind.PRIVATE_KEY,
    }
    if parsed.field(AwsCertsFieldKind.HOST) is not None:
        kinds.add(AwsCertsFieldKind.HOST)
    if parsed.field(AwsCertsFieldKind.PORT) is not None:
        kinds.add(AwsCertsFieldKind.PORT)

    return kinds


def _require_field(parsed: ParsedAwsCerts, kind: AwsCertsFieldKind) -> AwsCertsField:
    field = parsed.field(kind)
    if field is None:
        raise StopFlashing(f"STOP: required aws_certs field missing: {kind.value}")

    return field


def _ensure_payload_fits(payload_size: int, partition_size: int) -> None:
    if payload_size <= partition_size:
        return

    missing = payload_size - partition_size
    raise StopFlashing(
        "STOP: rebuilt aws_certs payload does not fit partition: "
        f"aws_certs partition size is {partition_size} bytes, "
        f"rebuilt payload size is {payload_size} bytes, "
        f"missing {missing} bytes. Use a shorter CA subject or a smaller key type "
        "such as EC P-256 if the firmware is compatible."
    )


def _changed_ranges(before: bytes, after: bytes) -> tuple[ByteRange, ...]:
    if len(before) != len(after):
        raise ValueError("changed ranges require equal-length buffers")

    ranges: list[ByteRange] = []
    start: int | None = None
    for offset, (old_byte, new_byte) in enumerate(zip(before, after, strict=True)):
        if old_byte == new_byte:
            if start is not None:
                ranges.append(ByteRange(start=start, end=offset))
                start = None
            continue
        if start is None:
            start = offset

    if start is not None:
        ranges.append(ByteRange(start=start, end=len(before)))

    return tuple(ranges)


def _format_change(old: object, new: object) -> str:
    if old == new:
        return f"unchanged ({old})"

    return f"{old} -> {new}"
