from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from softener_certs_flasher import __version__
from softener_certs_flasher.aws_certs import AwsCertsPatchResult
from softener_certs_flasher.esp import PartitionEntry


def build_manifest(
    *,
    port: str | None,
    port_filter: str | None,
    baud: int,
    device_mac: str,
    flash_size: int,
    partition_table_offset: int,
    aws_certs_partition: PartitionEntry,
    dump_a_path: Path,
    dump_b_path: Path,
    dump_sha256: str,
    original_aws_certs_path: Path,
    patched_aws_certs_path: Path,
    original_aws_certs_sha256: str,
    patched_aws_certs_sha256: str,
    patch_result: AwsCertsPatchResult,
    ca_cert_path: Path,
    ca_key_path: Path | None,
    ca_fingerprint: str,
    server_cert_path: Path | None,
    server_key_path: Path | None,
    server_fingerprint: str | None,
    read_mac_command: list[str],
    read_commands: list[list[str]],
    write_command: list[str] | None,
    verify_command: list[str] | None,
    post_flash_verified: bool,
) -> dict[str, object]:
    plan = patch_result.plan
    return {
        "schema_version": 1,
        "tool": "softener-certs-flasher",
        "tool_version": __version__,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "device": {
            "port": port,
            "port_filter": port_filter,
            "baud": baud,
            "mac": device_mac,
            "flash_size_bytes": flash_size,
        },
        "partition_table": {
            "offset": partition_table_offset,
        },
        "aws_certs_partition": {
            "label": aws_certs_partition.label,
            "type": aws_certs_partition.type,
            "subtype": aws_certs_partition.subtype,
            "offset": aws_certs_partition.offset,
            "size": aws_certs_partition.size,
            "flags": aws_certs_partition.flags,
        },
        "dumps": {
            "first": str(dump_a_path),
            "second": str(dump_b_path),
            "sha256": dump_sha256,
        },
        "aws_certs_images": {
            "original": str(original_aws_certs_path),
            "patched": str(patched_aws_certs_path),
            "original_sha256": original_aws_certs_sha256,
            "patched_sha256": patched_aws_certs_sha256,
        },
        "layout": patch_result.original.layout.value,
        "logical_diff": {
            "host": {"old": plan.host_old, "new": plan.host_new},
            "port": {"old": plan.port_old, "new": plan.port_new},
            "root_ca_fingerprint": {
                "old": plan.root_ca_fingerprint_old,
                "new": plan.root_ca_fingerprint_new,
            },
            "client_certificate_fingerprint": {
                "old": plan.client_certificate_fingerprint_old,
                "new": plan.client_certificate_fingerprint_new,
                "unchanged": plan.client_certificate_unchanged,
            },
            "private_key_public_fingerprint": {
                "old": plan.private_key_public_fingerprint_old,
                "new": plan.private_key_public_fingerprint_new,
                "unchanged": plan.private_key_unchanged,
            },
            "final_payload_size": plan.final_payload_size,
            "free_bytes": plan.free_bytes,
            "padding": plan.padding,
        },
        "changed_ranges": [
            {
                "start": changed_range.start,
                "end": changed_range.end,
                "size": changed_range.size,
            }
            for changed_range in plan.changed_ranges
        ],
        "generated_files": {
            "ca_cert": str(ca_cert_path),
            "ca_key": str(ca_key_path) if ca_key_path is not None else None,
            "server_cert": str(server_cert_path) if server_cert_path is not None else None,
            "server_key": str(server_key_path) if server_key_path is not None else None,
        },
        "generated_certificate_fingerprints": {
            "ca": ca_fingerprint,
            "server": server_fingerprint,
        },
        "commands": {
            "read-mac": read_mac_command,
            "read-flash": read_commands,
            "write-flash": write_command,
            "verify-read": verify_command,
        },
        "post_flash_verified": post_flash_verified,
    }


def manifest_json(manifest: dict[str, object]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"
