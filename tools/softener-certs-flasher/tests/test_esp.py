from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from softener_certs_flasher.errors import StopFlashing
from softener_certs_flasher.esp import (
    Esptool,
    PackageEsptoolApi,
    find_partition,
    normalize_mac,
    parse_partition_table,
)


def test_parse_partition_table_finds_aws_certs() -> None:
    flash = bytearray(b"\xff" * 0x20000)
    flash[0x8000 : 0x8020] = _entry("nvs", 0x01, 0x02, 0x9000, 0x6000)
    flash[0x8020 : 0x8040] = _entry("aws_certs", 0x40, 0x00, 0x10000, 0x4000)

    entries = parse_partition_table(bytes(flash))
    partition = find_partition(entries, "aws_certs", flash_size=len(flash))

    assert partition.label == "aws_certs"
    assert partition.offset == 0x10000
    assert partition.size == 0x4000


def test_find_partition_rejects_partition_outside_flash() -> None:
    flash = bytearray(b"\xff" * 0x20000)
    flash[0x8000 : 0x8020] = _entry("aws_certs", 0x40, 0x00, 0x1F000, 0x4000)

    entries = parse_partition_table(bytes(flash))

    with pytest.raises(StopFlashing, match="exceeds flash dump size"):
        find_partition(entries, "aws_certs", flash_size=len(flash))


def test_normalize_mac_accepts_compact_mac() -> None:
    assert normalize_mac("aabbccddeeff") == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_rejects_invalid_mac() -> None:
    with pytest.raises(StopFlashing, match="invalid MAC address format"):
        normalize_mac("no mac here")


def test_esptool_session_uses_one_connection_and_records_hyphenated_commands(
    tmp_path: Path,
) -> None:
    api = RecordingApi()
    esptool = Esptool(
        port=None,
        baud=460800,
        executable="esptool",
        chip="auto",
        port_filter="vid=0x10c4",
        api=api,
    )

    with esptool.session() as session:
        mac, read_mac_command = session.read_mac()
        read_flash_command = session.read_flash(0, "ALL", tmp_path / "flash.bin")
        write_flash_command = session.write_flash(0x10000, tmp_path / "flash.bin")

    assert mac == "aa:bb:cc:dd:ee:ff"
    assert "--port" not in read_flash_command
    assert read_flash_command[:6] == [
        "esptool",
        "--chip",
        "auto",
        "--port-filter",
        "vid=0x10c4",
        "--baud",
    ]
    assert read_mac_command[-1] == "read-mac"
    assert read_flash_command[-4] == "read-flash"
    assert write_flash_command[-3] == "write-flash"
    assert (tmp_path / "flash.bin").read_bytes() == b"\xa5" * api.flash_size
    assert api.calls == [
        ("connect", None, 460800, "auto", "vid=0x10c4"),
        ("run-stub",),
        ("change-baud", 460800),
        ("attach-flash",),
        ("detect-flash-size",),
        ("read-flash", 0, api.flash_size, tmp_path / "flash.bin"),
        ("write-flash", 0x10000, tmp_path / "flash.bin"),
        ("reset-chip",),
    ]


def test_package_api_connects_at_rom_baud_before_speed_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, int]] = []

    def fake_detect_chip(port: str, initial_baud: int) -> FakeEsp:
        calls.append(("detect-chip", port, initial_baud))
        return FakeEsp()

    api = PackageEsptoolApi()
    monkeypatch.setattr(api, "_detect_chip", fake_detect_chip)
    with api.connect(port="/dev/ttyUSB0", baud=460800, chip="auto", port_filter=None):
        pass

    assert calls == [("detect-chip", "/dev/ttyUSB0", 115200)]


class FakeEsp:
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read_mac(self, mac_type: str) -> tuple[int, int, int, int, int, int]:
        assert mac_type == "BASE_MAC"
        return (0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF)


class RecordingApi:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.flash_size = 32

    @contextmanager
    def connect(
        self,
        *,
        port: str | None,
        baud: int,
        chip: str,
        port_filter: str | None,
    ) -> Iterator[FakeEsp]:
        self.calls.append(("connect", port, baud, chip, port_filter))
        yield FakeEsp()

    def run_stub(self, esp: Any) -> Any:
        self.calls.append(("run-stub",))
        return esp

    def change_baud(self, esp: Any, baud: int) -> None:
        self.calls.append(("change-baud", baud))

    def attach_flash(self, esp: Any) -> None:
        self.calls.append(("attach-flash",))

    def read_flash(self, esp: Any, address: int, size: int, output_path: Path) -> None:
        self.calls.append(("read-flash", address, size, output_path))
        output_path.write_bytes(b"\xa5" * size)

    def write_flash(self, esp: Any, address: int, image_path: Path) -> None:
        self.calls.append(("write-flash", address, image_path))

    def reset_chip(self, esp: Any) -> None:
        self.calls.append(("reset-chip",))

    def detect_flash_size_bytes(self, esp: Any) -> int:
        self.calls.append(("detect-flash-size",))
        return self.flash_size


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
