from __future__ import annotations

from pathlib import Path

import pytest

import softener_certs_flasher.cli as cli
from softener_certs_flasher.certs import KeyType
from softener_certs_flasher.cli import RecoveryConfig, WizardConfig, run_recovery, run_wizard
from softener_certs_flasher.errors import StopFlashing
from tests.crypto_helpers import generate_ca_pem_material, generate_pem_material


def test_wizard_reads_flash_twice_patches_writes_manifest_and_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old_ca = generate_ca_pem_material("ca")
    client = generate_pem_material("softener-client")
    aws_certs = _partition(
        _payload(
            b"old.example.com",
            b"8883",
            old_ca.certificate,
            client.key,
            client.certificate,
        ),
        0x4000,
    )
    runner = FakeRunner(_flash_with_aws_certs(aws_certs))
    monkeypatch.setattr(cli, "Esptool", runner.esptool_factory)

    run_wizard(_wizard_config(tmp_path))
    output = capsys.readouterr().out

    assert runner.session_count == 1
    assert runner.read_count == 3
    assert runner.read_mac_count == 1
    assert runner.write_count == 1
    assert (tmp_path / "flash-read-1.bin").exists()
    assert (tmp_path / "flash-read-2.bin").exists()
    assert (tmp_path / "aws_certs_original.bin").exists()
    assert (tmp_path / "aws_certs_patched.bin").exists()
    assert (tmp_path / "softener-gateway.crt").exists()
    assert (tmp_path / "softener-gateway.key").exists()
    manifest = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert '"mac": "aa:bb:cc:dd:ee:ff"' in manifest
    assert '"read-mac": [' in manifest
    assert '"post_flash_verified": true' in manifest
    assert '"host": {' in manifest
    assert "softener-gateway.home.arpa" in manifest
    assert "softener-gateway.crt" in manifest
    assert "softener-gateway.key" in manifest
    assert "softener-server.crt" not in manifest
    assert "softener-server.key" not in manifest
    assert "changed ranges" not in output
    assert "fingerprint" not in output
    assert "serial:" in output
    assert "issuer:" in output
    assert "subject:" in output
    assert "validity:" in output
    assert "- new root CA:" in output
    assert "- device certificate: unchanged; left intact" in output
    assert "- device private key: unchanged; left intact" in output


def test_wizard_allows_esptool_port_autodetect_with_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aws_certs = _sample_aws_certs()
    runner = FakeRunner(
        _flash_with_aws_certs(aws_certs),
        expected_port=None,
        expected_port_filter="vid=0x10c4",
    )
    monkeypatch.setattr(cli, "Esptool", runner.esptool_factory)

    run_wizard(_wizard_config(tmp_path, port=None, port_filter="vid=0x10c4"))

    manifest = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert '"port": null' in manifest
    assert '"port_filter": "vid=0x10c4"' in manifest


def test_recovery_flash_restores_original_for_matching_mac(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aws_certs = _sample_aws_certs()
    runner = FakeRunner(_flash_with_aws_certs(aws_certs))
    monkeypatch.setattr(cli, "Esptool", runner.esptool_factory)
    run_wizard(_wizard_config(tmp_path))
    assert bytes(runner.flash[0x10000 : 0x10000 + len(aws_certs)]) != aws_certs

    run_recovery(_recovery_config(tmp_path))

    assert runner.session_count == 2
    assert runner.read_mac_count == 2
    assert runner.write_count == 2
    assert bytes(runner.flash[0x10000 : 0x10000 + len(aws_certs)]) == aws_certs


def test_recovery_flash_rejects_mac_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aws_certs = _sample_aws_certs()
    backup_runner = FakeRunner(_flash_with_aws_certs(aws_certs), mac="aa:bb:cc:dd:ee:ff")
    monkeypatch.setattr(cli, "Esptool", backup_runner.esptool_factory)
    run_wizard(_wizard_config(tmp_path))

    recovery_runner = FakeRunner(bytes(backup_runner.flash), mac="11:22:33:44:55:66")
    monkeypatch.setattr(cli, "Esptool", recovery_runner.esptool_factory)
    with pytest.raises(StopFlashing, match="recovery MAC mismatch"):
        run_recovery(_recovery_config(tmp_path))

    assert recovery_runner.session_count == 1
    assert recovery_runner.read_mac_count == 1
    assert recovery_runner.write_count == 0


class FakeRunner:
    def __init__(
        self,
        flash: bytes,
        *,
        mac: str = "aa:bb:cc:dd:ee:ff",
        expected_port: str | None = "/dev/ttyUSB0",
        expected_port_filter: str | None = None,
    ) -> None:
        self.flash = bytearray(flash)
        self.mac = mac
        self.expected_port = expected_port
        self.expected_port_filter = expected_port_filter
        self.session_count = 0
        self.read_mac_count = 0
        self.read_count = 0
        self.write_count = 0

    def esptool_factory(
        self,
        port: str | None,
        baud: int,
        executable: str,
        chip: str,
        port_filter: str | None = None,
    ) -> FakeRunner:
        assert port == self.expected_port
        assert port_filter == self.expected_port_filter
        assert baud == 460800
        assert executable == "esptool"
        assert chip == "auto"
        return self

    def session(self) -> FakeRunner:
        self.session_count += 1
        return self

    def __enter__(self) -> FakeRunner:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read_mac(self) -> tuple[str, list[str]]:
        self.read_mac_count += 1
        return self.mac, ["fake-esptool", "read-mac"]

    def read_flash(self, address: int, size: int | str, output_path: Path) -> list[str]:
        self.read_count += 1
        if size == "ALL":
            data = bytes(self.flash[address:])
        else:
            assert isinstance(size, int)
            data = bytes(self.flash[address : address + size])
        output_path.write_bytes(data)
        return ["fake-esptool", "read-flash", hex(address), str(size), str(output_path)]

    def write_flash(self, address: int, image_path: Path) -> list[str]:
        self.write_count += 1
        image = image_path.read_bytes()
        self.flash[address : address + len(image)] = image
        return ["fake-esptool", "write-flash", hex(address), str(image_path)]


def _wizard_config(
    tmp_path: Path,
    *,
    port: str | None = "/dev/ttyUSB0",
    port_filter: str | None = None,
) -> WizardConfig:
    return WizardConfig(
        port=port,
        port_filter=port_filter,
        baud=460800,
        esptool="esptool",
        chip="auto",
        read_size="ALL",
        output_dir=tmp_path,
        force=False,
        partition_table_offset=0x8000,
        partition_label="aws_certs",
        host="softener-gateway.home.arpa",
        port_replacement=8883,
        ca_cert_path=None,
        ca_key_path=None,
        key_type=KeyType.EC_P256,
        ca_common_name="Softener Test CA",
        server_common_name=None,
        valid_days=30,
        flash=True,
        yes=True,
    )


def _recovery_config(tmp_path: Path) -> RecoveryConfig:
    return RecoveryConfig(
        manifest_path=tmp_path / "manifest.json",
        image_path=None,
        port="/dev/ttyUSB0",
        port_filter=None,
        baud=460800,
        esptool="esptool",
        chip="auto",
        yes=True,
    )


def _sample_aws_certs() -> bytes:
    old_ca = generate_ca_pem_material("ca")
    client = generate_pem_material("softener-client")
    return _partition(
        _payload(
            b"old.example.com",
            b"8883",
            old_ca.certificate,
            client.key,
            client.certificate,
        ),
        0x4000,
    )


def _flash_with_aws_certs(aws_certs: bytes) -> bytes:
    flash = bytearray(b"\xff" * 0x20000)
    flash[0x8000 : 0x8020] = _entry("aws_certs", 0x40, 0x00, 0x10000, len(aws_certs))
    flash[0x10000 : 0x10000 + len(aws_certs)] = aws_certs
    return bytes(flash)


def _payload(*fields: bytes) -> bytes:
    return b"".join(
        field if field.endswith(b"\n") else field + b"\n" for field in fields
    )


def _partition(payload: bytes, size: int) -> bytes:
    assert len(payload) <= size
    return payload + b"\xff" * (size - len(payload))


def _entry(label: str, type_: int, subtype: int, offset: int, size: int) -> bytes:
    raw = bytearray(b"\x00" * 32)
    raw[0:2] = b"\xaa\x50"
    raw[2] = type_
    raw[3] = subtype
    raw[4:8] = offset.to_bytes(4, "little")
    raw[8:12] = size.to_bytes(4, "little")
    raw[12:28] = label.encode("ascii").ljust(16, b"\x00")
    raw[28:32] = (0).to_bytes(4, "little")
    return bytes(raw)
