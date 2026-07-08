from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cryptography import x509

from softener_certs_flasher.aws_certs import (
    AwsCertsFieldKind,
    ParsedAwsCerts,
    format_certificate_summary,
    format_patch_plan,
    format_private_key_summary,
    parse_aws_certs,
    patch_aws_certs,
)
from softener_certs_flasher.certs import (
    CertificateMaterial,
    KeyType,
    generate_certificate_material,
    load_ca_material,
)
from softener_certs_flasher.errors import StopFlashing
from softener_certs_flasher.esp import (
    PARTITION_TABLE_OFFSET,
    Esptool,
    find_partition,
    normalize_mac,
    parse_partition_table,
)
from softener_certs_flasher.manifest import build_manifest, manifest_json
from softener_certs_flasher.util import sha256_bytes, sha256_file, write_bytes, write_text

DEFAULT_BAUD = 460800
DEFAULT_PARTITION_LABEL = "aws_certs"
DEFAULT_CA_COMMON_NAME = "Softener Local Root CA"
DEFAULT_VALID_DAYS = 3650


@dataclass(frozen=True, slots=True)
class WizardConfig:
    port: str | None
    port_filter: str | None
    baud: int
    esptool: str
    chip: str
    read_size: int | str
    output_dir: Path
    force: bool
    partition_table_offset: int
    partition_label: str
    host: str | None
    port_replacement: int | None
    ca_cert_path: Path | None
    ca_key_path: Path | None
    key_type: KeyType
    ca_common_name: str
    server_common_name: str | None
    valid_days: int
    flash: bool | None
    yes: bool


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    manifest_path: Path
    image_path: Path | None
    port: str | None
    port_filter: str | None
    baud: int | None
    esptool: str
    chip: str
    yes: bool


@dataclass(frozen=True, slots=True)
class CaSelection:
    ca_cert_pem: bytes
    ca_cert_path: Path
    ca_key_path: Path | None
    ca_fingerprint: str
    server_cert_path: Path | None
    server_key_path: Path | None
    server_fingerprint: str | None


CommandConfig = WizardConfig | RecoveryConfig


def main(argv: Sequence[str] | None = None) -> None:
    try:
        config = parse_args(argv)
        if isinstance(config, RecoveryConfig):
            run_recovery(config)
        else:
            run_wizard(config)
    except StopFlashing as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    except FileExistsError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except OSError as exc:
        print(f"STOP: filesystem error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def parse_args(argv: Sequence[str] | None = None) -> CommandConfig:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"recover", "recovery", "restore"}:
        return _parse_recovery_args(args[1:])

    return _parse_wizard_args(args)


def _parse_wizard_args(argv: Sequence[str]) -> WizardConfig:
    parser = argparse.ArgumentParser(
        prog="softener-certs-flasher",
        description="Wizard for patching and flashing a Softener aws_certs partition.",
        epilog="Recovery: softener-certs-flasher recover path/to/manifest.json",
    )
    parser.add_argument(
        "--port",
        help="Serial port, for example /dev/ttyUSB0 or COM5. Omit for esptool autodetect.",
    )
    parser.add_argument(
        "--port-filter",
        help=(
            "Serial port autodetect filter passed to esptool, for example "
            "vid=0x10c4, pid=0xea60, name=USB, or serial=ABC."
        ),
    )
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument(
        "--esptool",
        default="esptool",
        help=(
            "Executable name recorded in manifest command equivalents; "
            "flashing uses the Python API."
        ),
    )
    parser.add_argument("--chip", default="auto")
    parser.add_argument(
        "--read-size",
        default="ALL",
        help="Full flash read size for esptool read-flash. Use ALL or a value like 4MB.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("softener-certs-flasher-output"),
    )
    parser.add_argument("--force", action="store_true", help="Overwrite output artifacts.")
    parser.add_argument(
        "--partition-table-offset",
        type=_parse_int,
        default=PARTITION_TABLE_OFFSET,
    )
    parser.add_argument("--partition-label", default=DEFAULT_PARTITION_LABEL)
    parser.add_argument("--host", help="Replacement MQTT/AWS endpoint host.")
    parser.add_argument("--mqtt-port", dest="port_replacement", type=int)
    parser.add_argument("--ca-cert", type=Path, help="Existing replacement CA PEM.")
    parser.add_argument("--ca-key", type=Path, help="Existing CA private key PEM to archive.")
    parser.add_argument(
        "--key-type",
        choices=[key_type.value for key_type in KeyType],
        default=KeyType.RSA_2048.value,
        help="Key type used when generating local CA and server certificate.",
    )
    parser.add_argument("--ca-common-name", default=DEFAULT_CA_COMMON_NAME)
    parser.add_argument("--server-common-name")
    parser.add_argument("--valid-days", type=int, default=DEFAULT_VALID_DAYS)
    parser.add_argument("--yes", action="store_true", help="Accept confirmations.")
    flash_group = parser.add_mutually_exclusive_group()
    flash_group.add_argument("--flash", dest="flash", action="store_true")
    flash_group.add_argument("--no-flash", dest="flash", action="store_false")
    parser.set_defaults(flash=None)

    args = parser.parse_args(argv)
    return WizardConfig(
        port=args.port,
        port_filter=args.port_filter,
        baud=args.baud,
        esptool=args.esptool,
        chip=args.chip,
        read_size=_parse_read_size(args.read_size),
        output_dir=args.output_dir,
        force=args.force,
        partition_table_offset=args.partition_table_offset,
        partition_label=args.partition_label,
        host=args.host,
        port_replacement=args.port_replacement,
        ca_cert_path=args.ca_cert,
        ca_key_path=args.ca_key,
        key_type=KeyType(args.key_type),
        ca_common_name=args.ca_common_name,
        server_common_name=args.server_common_name,
        valid_days=args.valid_days,
        flash=args.flash,
        yes=args.yes,
    )


def _parse_recovery_args(argv: Sequence[str]) -> RecoveryConfig:
    parser = argparse.ArgumentParser(
        prog="softener-certs-flasher recover",
        description="Restore aws_certs_original.bin from a softener-certs-flasher manifest.",
    )
    parser.add_argument("manifest", type=Path, help="Path to the backup manifest.json.")
    parser.add_argument(
        "--image",
        type=Path,
        help="Optional recovery image. Defaults to aws_certs_original.bin from the manifest.",
    )
    parser.add_argument("--port", help="Serial port. Omit for esptool autodetect.")
    parser.add_argument(
        "--port-filter",
        help=(
            "Serial port autodetect filter passed to esptool, for example "
            "vid=0x10c4, pid=0xea60, name=USB, or serial=ABC."
        ),
    )
    parser.add_argument("--baud", type=int, help="Serial baud. Defaults to the manifest baud.")
    parser.add_argument(
        "--esptool",
        default="esptool",
        help=(
            "Executable name recorded in manifest command equivalents; "
            "flashing uses the Python API."
        ),
    )
    parser.add_argument("--chip", default="auto")
    parser.add_argument("--yes", action="store_true", help="Accept recovery confirmation.")

    args = parser.parse_args(argv)
    return RecoveryConfig(
        manifest_path=args.manifest,
        image_path=args.image,
        port=args.port,
        port_filter=args.port_filter,
        baud=args.baud,
        esptool=args.esptool,
        chip=args.chip,
        yes=args.yes,
    )


def run_wizard(config: WizardConfig) -> None:
    _prepare_output_dir(config.output_dir, force=config.force)
    esptool = Esptool(
        port=config.port,
        baud=config.baud,
        executable=config.esptool,
        chip=config.chip,
        port_filter=config.port_filter,
    )

    with esptool.session() as esp_session:
        print("Reading device MAC...")
        device_mac, read_mac_command = esp_session.read_mac()
        print(f"Device MAC: {device_mac}")

        dump_a_path = config.output_dir / "flash-read-1.bin"
        dump_b_path = config.output_dir / "flash-read-2.bin"
        print("Reading full flash, pass 1...")
        read_command_a = esp_session.read_flash(0, config.read_size, dump_a_path)
        print("Reading full flash, pass 2...")
        read_command_b = esp_session.read_flash(0, config.read_size, dump_b_path)

        dump_a = dump_a_path.read_bytes()
        dump_b = dump_b_path.read_bytes()
        if dump_a != dump_b:
            raise StopFlashing(
                "STOP: double flash read mismatch: "
                f"first sha256={sha256_bytes(dump_a)}, second sha256={sha256_bytes(dump_b)}"
            )

        # dump_a_path.hardlink_to("flash-read.bin")
        # dump_a_path.unlink()
        # dump_b_path.unlink()

        dump_sha256 = sha256_bytes(dump_a)
        print(f"Double flash read verified: sha256={dump_sha256}")

        partition_entries = parse_partition_table(
            dump_a,
            table_offset=config.partition_table_offset,
        )
        aws_certs_partition = find_partition(
            partition_entries,
            config.partition_label,
            flash_size=len(dump_a),
        )
        print(
            "Found aws_certs partition: "
            f"offset=0x{aws_certs_partition.offset:x}, size={aws_certs_partition.size} bytes"
        )

        original_aws_certs = dump_a[aws_certs_partition.offset : aws_certs_partition.end]
        original_aws_certs_path = config.output_dir / "aws_certs_original.bin"
        write_bytes(original_aws_certs_path, original_aws_certs, overwrite=config.force)

        parsed = parse_aws_certs(original_aws_certs)
        if parsed.error is not None:
            raise StopFlashing(f"STOP: {parsed.error}")
        print(_format_parsed_summary(parsed))

        host = config.host
        if parsed.field(AwsCertsFieldKind.HOST) is not None and host is None:
            host = _prompt_value("Replacement endpoint host", default=parsed.host)
        port = config.port_replacement
        if parsed.field(AwsCertsFieldKind.PORT) is not None and port is None:
            port = int(_prompt_value("Replacement endpoint port", default=str(parsed.port)))

        ca_selection = _prepare_ca(config, host=host)
        patch_result = patch_aws_certs(
            original_aws_certs,
            new_ca_pem=ca_selection.ca_cert_pem,
            host=host,
            port=port,
        )

        patched_aws_certs_path = config.output_dir / "aws_certs_patched.bin"
        write_bytes(patched_aws_certs_path, patch_result.image, overwrite=config.force)
        print(format_patch_plan(patch_result))

        manifest_path = config.output_dir / "manifest.json"
        manifest = build_manifest(
            port=config.port,
            port_filter=config.port_filter,
            baud=config.baud,
            device_mac=device_mac,
            flash_size=len(dump_a),
            partition_table_offset=config.partition_table_offset,
            aws_certs_partition=aws_certs_partition,
            dump_a_path=dump_a_path,
            dump_b_path=dump_b_path,
            dump_sha256=dump_sha256,
            original_aws_certs_path=original_aws_certs_path,
            patched_aws_certs_path=patched_aws_certs_path,
            original_aws_certs_sha256=sha256_bytes(original_aws_certs),
            patched_aws_certs_sha256=sha256_bytes(patch_result.image),
            patch_result=patch_result,
            ca_cert_path=ca_selection.ca_cert_path,
            ca_key_path=ca_selection.ca_key_path,
            ca_fingerprint=ca_selection.ca_fingerprint,
            server_cert_path=ca_selection.server_cert_path,
            server_key_path=ca_selection.server_key_path,
            server_fingerprint=ca_selection.server_fingerprint,
            read_mac_command=read_mac_command,
            read_commands=[read_command_a, read_command_b],
            write_command=None,
            verify_command=None,
            post_flash_verified=False,
        )
        write_text(manifest_path, manifest_json(manifest), overwrite=True)

        should_flash = _should_flash(config)
        if not should_flash:
            print(f"Prepared artifacts without flashing. Manifest: {manifest_path}")
            return

        if not config.yes and not _confirm("Write patched aws_certs to device now?", default=False):
            print(f"Flash skipped. Manifest: {manifest_path}")
            return

        print("Writing patched aws_certs partition...")
        write_command = esp_session.write_flash(aws_certs_partition.offset, patched_aws_certs_path)
        verify_path = config.output_dir / "aws_certs_after_flash.bin"
        print("Reading aws_certs back for verification...")
        verify_command = esp_session.read_flash(
            aws_certs_partition.offset,
            aws_certs_partition.size,
            verify_path,
        )
        verified = verify_path.read_bytes() == patch_result.image
        if not verified:
            manifest["commands"] = {
                "read-mac": read_mac_command,
                "read-flash": [read_command_a, read_command_b],
                "write-flash": write_command,
                "verify-read": verify_command,
            }
            write_text(manifest_path, manifest_json(manifest), overwrite=True)
            raise StopFlashing(
                "STOP: post-flash aws_certs verification failed: "
                f"expected sha256={sha256_bytes(patch_result.image)}, "
                f"read sha256={sha256_file(verify_path)}"
            )

        manifest = build_manifest(
            port=config.port,
            port_filter=config.port_filter,
            baud=config.baud,
            device_mac=device_mac,
            flash_size=len(dump_a),
            partition_table_offset=config.partition_table_offset,
            aws_certs_partition=aws_certs_partition,
            dump_a_path=dump_a_path,
            dump_b_path=dump_b_path,
            dump_sha256=dump_sha256,
            original_aws_certs_path=original_aws_certs_path,
            patched_aws_certs_path=patched_aws_certs_path,
            original_aws_certs_sha256=sha256_bytes(original_aws_certs),
            patched_aws_certs_sha256=sha256_bytes(patch_result.image),
            patch_result=patch_result,
            ca_cert_path=ca_selection.ca_cert_path,
            ca_key_path=ca_selection.ca_key_path,
            ca_fingerprint=ca_selection.ca_fingerprint,
            server_cert_path=ca_selection.server_cert_path,
            server_key_path=ca_selection.server_key_path,
            server_fingerprint=ca_selection.server_fingerprint,
            read_mac_command=read_mac_command,
            read_commands=[read_command_a, read_command_b],
            write_command=write_command,
            verify_command=verify_command,
            post_flash_verified=True,
        )
        write_text(manifest_path, manifest_json(manifest), overwrite=True)
        print(f"Flash verified. Manifest: {manifest_path}")


def run_recovery(config: RecoveryConfig) -> None:
    manifest = _load_manifest(config.manifest_path)
    device = _manifest_object(manifest, "device")
    expected_mac = normalize_mac(_manifest_str(device, "mac", "device.mac"))
    baud = config.baud
    if baud is None:
        baud = _manifest_int(device, "baud", "device.baud")

    partition = _manifest_object(manifest, "aws_certs_partition")
    partition_offset = _manifest_int(partition, "offset", "aws_certs_partition.offset")
    partition_size = _manifest_int(partition, "size", "aws_certs_partition.size")
    image_path = config.image_path or _manifest_original_image_path(config.manifest_path, manifest)
    image = image_path.read_bytes()
    image_sha256 = sha256_bytes(image)
    original_sha256 = _manifest_original_sha256(manifest)
    if image_sha256 != original_sha256:
        raise StopFlashing(
            "STOP: recovery image sha256 mismatch: "
            f"manifest original_sha256={original_sha256}, image sha256={image_sha256}"
        )
    if len(image) != partition_size:
        raise StopFlashing(
            "STOP: recovery image size mismatch: "
            f"manifest size={partition_size} bytes, image size={len(image)} bytes"
        )

    esptool = Esptool(
        port=config.port,
        baud=baud,
        executable=config.esptool,
        chip=config.chip,
        port_filter=config.port_filter,
    )
    with esptool.session() as esp_session:
        print("Reading device MAC...")
        current_mac, _ = esp_session.read_mac()
        print(f"Device MAC: {current_mac}")
        if current_mac != expected_mac:
            raise StopFlashing(
                "STOP: recovery MAC mismatch: "
                f"manifest device.mac={expected_mac}, connected device.mac={current_mac}"
            )

        if not config.yes and not _confirm(
            "Restore original aws_certs to this device now?",
            default=False,
        ):
            print("Recovery flash skipped.")
            return

        print("Writing original aws_certs partition...")
        esp_session.write_flash(partition_offset, image_path)
        verify_path = config.manifest_path.parent / "aws_certs_after_recovery.bin"
        print("Reading aws_certs back for recovery verification...")
        esp_session.read_flash(partition_offset, partition_size, verify_path)
        verified = verify_path.read_bytes() == image
        if not verified:
            raise StopFlashing(
                "STOP: recovery aws_certs verification failed: "
                f"expected sha256={image_sha256}, read sha256={sha256_file(verify_path)}"
            )

        print("Recovery flash verified.")


def _load_manifest(manifest_path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StopFlashing(f"STOP: invalid recovery manifest JSON: {exc}") from exc

    if not isinstance(loaded, dict):
        raise StopFlashing("STOP: recovery manifest root must be a JSON object")

    return cast(dict[str, object], loaded)


def _manifest_object(container: dict[str, object], key: str) -> dict[str, object]:
    value = container.get(key)
    if not isinstance(value, dict):
        raise StopFlashing(f"STOP: recovery manifest is missing object {key}")

    return cast(dict[str, object], value)


def _manifest_str(container: dict[str, object], key: str, path: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise StopFlashing(f"STOP: recovery manifest is missing string {path}")

    return value


def _manifest_int(container: dict[str, object], key: str, path: str) -> int:
    value = container.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise StopFlashing(f"STOP: recovery manifest is missing integer {path}")

    return value


def _manifest_original_sha256(manifest: dict[str, object]) -> str:
    images = _manifest_object(manifest, "aws_certs_images")
    return _manifest_str(images, "original_sha256", "aws_certs_images.original_sha256")


def _manifest_original_image_path(manifest_path: Path, manifest: dict[str, object]) -> Path:
    images = _manifest_object(manifest, "aws_certs_images")
    value = images.get("original")
    if value is None:
        return manifest_path.parent / "aws_certs_original.bin"
    if not isinstance(value, str) or not value:
        raise StopFlashing("STOP: recovery manifest has invalid aws_certs_images.original")

    return _resolve_manifest_artifact_path(manifest_path, value)


def _resolve_manifest_artifact_path(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path

    candidates = (
        path,
        manifest_path.parent / path,
        manifest_path.parent / path.name,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return manifest_path.parent / path.name


def _prepare_ca(config: WizardConfig, *, host: str | None) -> CaSelection:
    if config.ca_cert_path is not None:
        ca_key_pem = config.ca_key_path.read_bytes() if config.ca_key_path is not None else None
        ca_cert_pem, ca_fingerprint = load_ca_material(
            config.ca_cert_path.read_bytes(),
            ca_key_pem,
        )
        ca_cert_path = config.output_dir / "replacement-root-ca.crt"
        write_bytes(ca_cert_path, ca_cert_pem, overwrite=config.force)
        ca_key_path: Path | None = None
        if ca_key_pem is not None:
            ca_key_path = config.output_dir / "replacement-root-ca.key"
            write_bytes(ca_key_path, ca_key_pem, overwrite=config.force)
            ca_key_path.chmod(0o600)
        ca_certificate = _load_display_certificate(ca_cert_pem, "replacement CA")
        print("Using replacement CA:")
        print(format_certificate_summary("replacement root CA", ca_certificate))
        return CaSelection(
            ca_cert_pem=ca_cert_pem,
            ca_cert_path=ca_cert_path,
            ca_key_path=ca_key_path,
            ca_fingerprint=ca_fingerprint,
            server_cert_path=None,
            server_key_path=None,
            server_fingerprint=None,
        )

    if host is None:
        host = _prompt_required("Server certificate DNS/IP SAN")
    server_common_name = config.server_common_name or host
    material = generate_certificate_material(
        host=host,
        ca_common_name=config.ca_common_name,
        server_common_name=server_common_name,
        key_type=config.key_type,
        valid_days=config.valid_days,
    )
    return _write_generated_material(config, material)


def _write_generated_material(config: WizardConfig, material: CertificateMaterial) -> CaSelection:
    ca_cert_path = config.output_dir / "softener-local-ca.crt"
    ca_key_path = config.output_dir / "softener-local-ca.key"
    server_cert_path = config.output_dir / "softener-gateway.crt"
    server_key_path = config.output_dir / "softener-gateway.key"
    write_bytes(ca_cert_path, material.ca_cert_pem, overwrite=config.force)
    write_bytes(ca_key_path, material.ca_key_pem, overwrite=config.force)
    write_bytes(server_cert_path, material.server_cert_pem, overwrite=config.force)
    write_bytes(server_key_path, material.server_key_pem, overwrite=config.force)
    ca_key_path.chmod(0o600)
    server_key_path.chmod(0o600)
    ca_certificate = _load_display_certificate(material.ca_cert_pem, "generated CA")
    server_certificate = _load_display_certificate(
        material.server_cert_pem,
        "generated server certificate",
    )
    print("Generated local CA:")
    print(format_certificate_summary("local root CA", ca_certificate))
    print("Generated server certificate:")
    print(format_certificate_summary("server certificate", server_certificate))
    return CaSelection(
        ca_cert_pem=material.ca_cert_pem,
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
        ca_fingerprint=material.ca_fingerprint,
        server_cert_path=server_cert_path,
        server_key_path=server_key_path,
        server_fingerprint=material.server_fingerprint,
    )


def _format_parsed_summary(parsed: ParsedAwsCerts) -> str:
    root_ca = parsed.field(AwsCertsFieldKind.ROOT_CA)
    client_certificate = parsed.field(AwsCertsFieldKind.CLIENT_CERTIFICATE)
    private_key = parsed.field(AwsCertsFieldKind.PRIVATE_KEY)
    if (
        root_ca is None
        or root_ca.certificate is None
        or client_certificate is None
        or client_certificate.certificate is None
        or private_key is None
        or private_key.private_key is None
    ):
        raise StopFlashing("STOP: parsed aws_certs is missing required material")

    return "\n".join(
        [
            f"Parsed aws_certs payload format: {parsed.layout.value}",
            f"- host: {parsed.host}",
            f"- port: {parsed.port}",
            *format_certificate_summary("current root CA", root_ca.certificate).splitlines(),
            *format_certificate_summary(
                "device certificate",
                client_certificate.certificate,
            ).splitlines(),
            *format_private_key_summary(
                "device private key",
                private_key.private_key,
                certificate=client_certificate.certificate,
            ).splitlines(),
            f"- current payload size: {parsed.payload_size} bytes",
            f"- partition size: {parsed.partition_size} bytes",
            f"- free bytes: {parsed.partition_size - parsed.payload_size} bytes",
        ]
    )


def _load_display_certificate(pem: bytes, label: str) -> x509.Certificate:
    try:
        certificates = x509.load_pem_x509_certificates(pem)
    except ValueError as exc:
        raise StopFlashing(f"STOP: {label} did not parse: {exc}") from exc
    if len(certificates) != 1:
        raise StopFlashing(
            f"STOP: {label} must contain exactly one certificate, found {len(certificates)}"
        )

    return certificates[0]


def _prepare_output_dir(output_dir: Path, *, force: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise StopFlashing(f"STOP: output directory {output_dir} is not empty; use --force")

    output_dir.mkdir(parents=True, exist_ok=True)


def _should_flash(config: WizardConfig) -> bool:
    if config.flash is not None:
        return config.flash
    if config.yes:
        return False

    return _confirm("Flash patched aws_certs to the device?", default=False)


def _confirm(prompt: str, *, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix} ").strip().lower()
    if not answer:
        return default

    return answer in {"y", "yes", "t", "tak"}


def _prompt_required(prompt: str) -> str:
    while True:
        value = input(f"{prompt}: ").strip()
        if value:
            return value


def _prompt_value(prompt: str, *, default: str | None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if value:
        return value
    if default is not None:
        return default

    return _prompt_required(prompt)


def _parse_read_size(value: str) -> int | str:
    if value.upper() == "ALL":
        return "ALL"

    return _parse_int(value)


def _parse_int(value: str) -> int:
    normalized = value.strip().lower()
    multiplier = 1
    if normalized.endswith("kb"):
        multiplier = 1024
        normalized = normalized[:-2]
    elif normalized.endswith("mb"):
        multiplier = 1024 * 1024
        normalized = normalized[:-2]
    return int(normalized, 0) * multiplier
