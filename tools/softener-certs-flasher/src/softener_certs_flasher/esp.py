from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import esptool  # type: ignore[import-untyped]
from esptool import cmds as esptool_cmds
from esptool.util import FatalError, NotImplementedInROMError  # type: ignore[import-untyped]

from softener_certs_flasher.errors import StopFlashing

PARTITION_TABLE_OFFSET = 0x8000
PARTITION_TABLE_SIZE = 0x1000
PARTITION_ENTRY_SIZE = 32
PARTITION_MAGIC = b"\xaa\x50"
PARTITION_MD5_MAGIC = b"\xeb\xeb"


@dataclass(frozen=True, slots=True)
class PartitionEntry:
    type: int
    subtype: int
    offset: int
    size: int
    label: str
    flags: int

    @property
    def end(self) -> int:
        return self.offset + self.size


class EsptoolApi(Protocol):
    def connect(
        self,
        *,
        port: str | None,
        baud: int,
        chip: str,
        port_filter: str | None,
    ) -> AbstractContextManager[Any]:
        ...

    def run_stub(self, esp: Any) -> Any:
        ...

    def change_baud(self, esp: Any, baud: int) -> None:
        ...

    def attach_flash(self, esp: Any) -> None:
        ...

    def read_flash(self, esp: Any, address: int, size: int, output_path: Path) -> None:
        ...

    def write_flash(self, esp: Any, address: int, image_path: Path) -> None:
        ...

    def reset_chip(self, esp: Any) -> None:
        ...

    def detect_flash_size_bytes(self, esp: Any) -> int:
        ...


class PackageEsptoolApi:
    @contextmanager
    def connect(
        self,
        *,
        port: str | None,
        baud: int,
        chip: str,
        port_filter: str | None,
    ) -> Iterator[Any]:
        esp = self._connect(port=port, baud=baud, chip=chip, port_filter=port_filter)
        try:
            yield esp
        finally:
            with suppress(Exception):
                esp.__exit__(None, None, None)

    def run_stub(self, esp: Any) -> Any:
        return esptool_cmds.run_stub(esp)

    def change_baud(self, esp: Any, baud: int) -> None:
        try:
            esp.change_baud(baud)
        except NotImplementedInROMError:
            pass

    def attach_flash(self, esp: Any) -> None:
        esptool_cmds.attach_flash(esp)

    def read_flash(self, esp: Any, address: int, size: int, output_path: Path) -> None:
        esptool_cmds.read_flash(esp, address, size, str(output_path))

    def write_flash(self, esp: Any, address: int, image_path: Path) -> None:
        esptool_cmds.write_flash(esp, [(address, str(image_path))])

    def reset_chip(self, esp: Any) -> None:
        esptool_cmds.reset_chip(esp, "hard-reset")

    def detect_flash_size_bytes(self, esp: Any) -> int:
        size = esptool_cmds.detect_flash_size(esp)
        if size is None:
            raise StopFlashing("STOP: esptool could not detect flash size for read-size ALL")

        return int(esptool_cmds.flash_size_bytes(size))

    def _connect(
        self,
        *,
        port: str | None,
        baud: int,
        chip: str,
        port_filter: str | None,
    ) -> Any:
        initial_baud = min(115200, baud)
        last_error: Exception | None = None
        for candidate in self._candidate_ports(port=port, port_filter=port_filter):
            try:
                if chip == "auto":
                    return self._detect_chip(candidate, initial_baud)

                chip_class = esptool.CHIP_DEFS[chip]
                esp = chip_class(candidate, initial_baud)
                esp.connect("default-reset")
                return esp
            except KeyError as exc:
                raise StopFlashing(f"STOP: unsupported ESP chip type: {chip}") from exc
            except (FatalError, OSError) as exc:
                last_error = exc
                if port is not None:
                    raise StopFlashing(f"STOP: esptool failed to connect to {port}: {exc}") from exc

        detail = f": {last_error}" if last_error is not None else ""
        raise StopFlashing(f"STOP: esptool could not connect to any detected serial port{detail}")

    def _candidate_ports(self, *, port: str | None, port_filter: str | None) -> list[str]:
        if port is not None:
            return [port]

        try:
            filters = esptool.parse_port_filters((port_filter,) if port_filter else ())
            ports = esptool.get_port_list(*filters)
        except FatalError as exc:
            raise StopFlashing(f"STOP: esptool port autodetect failed: {exc}") from exc

        if not ports:
            filter_detail = f" matching {port_filter!r}" if port_filter else ""
            raise StopFlashing(f"STOP: no serial ports found{filter_detail}")

        return list(reversed(ports))

    def _detect_chip(self, port: str, initial_baud: int) -> Any:
        return esptool_cmds.detect_chip(port, baud=initial_baud)


@dataclass(frozen=True, slots=True)
class Esptool:
    port: str | None
    baud: int
    executable: str = "esptool"
    chip: str = "auto"
    port_filter: str | None = None
    api: EsptoolApi = field(default_factory=PackageEsptoolApi)

    def session(self, *, reset_on_exit: bool = True) -> EsptoolSession:
        return EsptoolSession(self, reset_on_exit=reset_on_exit)

    def read_mac(self) -> tuple[str, list[str]]:
        with self.session() as session:
            return session.read_mac()

    def read_flash(self, address: int, size: int | str, output_path: Path) -> list[str]:
        with self.session() as session:
            return session.read_flash(address, size, output_path)

    def write_flash(self, address: int, image_path: Path) -> list[str]:
        with self.session() as session:
            return session.write_flash(address, image_path)

    def _base_command(self) -> list[str]:
        command = [
            self.executable,
            "--chip",
            self.chip,
        ]
        if self.port is not None:
            command.extend(["--port", self.port])
        if self.port_filter is not None:
            command.extend(["--port-filter", self.port_filter])
        command.extend(["--baud", str(self.baud)])
        return command


class EsptoolSession:
    def __init__(self, esptool: Esptool, *, reset_on_exit: bool) -> None:
        self._esptool = esptool
        self._reset_on_exit = reset_on_exit
        self._connection: AbstractContextManager[Any] | None = None
        self._esp: Any | None = None
        self._detected_flash_size: int | None = None

    def __enter__(self) -> EsptoolSession:
        self._connection = self._esptool.api.connect(
            port=self._esptool.port,
            baud=self._esptool.baud,
            chip=self._esptool.chip,
            port_filter=self._esptool.port_filter,
        )
        try:
            esp = self._connection.__enter__()
            self._esp = self._esptool.api.run_stub(esp)
            if self._esptool.baud > 115200:
                self._esptool.api.change_baud(self._esp, self._esptool.baud)
            self._esptool.api.attach_flash(self._esp)
        except Exception:
            self._close_connection()
            raise

        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._reset_on_exit and self._esp is not None:
            with suppress(Exception):
                self._esptool.api.reset_chip(self._esp)
        self._close_connection()

    def read_mac(self) -> tuple[str, list[str]]:
        command = self._esptool._base_command() + ["read-mac"]
        try:
            mac = _format_mac(self._require_esp().read_mac("BASE_MAC"))
        except FatalError as exc:
            raise StopFlashing(f"STOP: esptool read-mac failed: {exc}") from exc

        return mac, command

    def read_flash(self, address: int, size: int | str, output_path: Path) -> list[str]:
        command = self._esptool._base_command() + [
            "read-flash",
            hex(address),
            str(size),
            str(output_path),
        ]
        try:
            self._esptool.api.read_flash(
                self._require_esp(),
                address,
                self._resolve_read_size(size),
                output_path,
            )
        except FatalError as exc:
            raise StopFlashing(f"STOP: esptool read-flash failed: {exc}") from exc

        return command

    def write_flash(self, address: int, image_path: Path) -> list[str]:
        command = self._base_command() + [
            "--before",
            "default-reset",
            "--after",
            "hard-reset",
            "write-flash",
            hex(address),
            str(image_path),
        ]
        try:
            self._esptool.api.write_flash(self._require_esp(), address, image_path)
        except FatalError as exc:
            raise StopFlashing(f"STOP: esptool write-flash failed: {exc}") from exc

        return command

    def _base_command(self) -> list[str]:
        return self._esptool._base_command()

    def _resolve_read_size(self, size: int | str) -> int:
        if isinstance(size, int):
            return size
        if size.upper() == "ALL":
            if self._detected_flash_size is None:
                self._detected_flash_size = self._esptool.api.detect_flash_size_bytes(
                    self._require_esp()
                )
            return self._detected_flash_size

        raise StopFlashing(f"STOP: invalid read-flash size: {size!r}")

    def _require_esp(self) -> Any:
        if self._esp is None:
            raise StopFlashing("STOP: esptool session is not connected")

        return self._esp

    def _close_connection(self) -> None:
        if self._connection is None:
            return
        with suppress(Exception):
            self._connection.__exit__(None, None, None)
        self._connection = None


def normalize_mac(value: str) -> str:
    compact = value.strip().lower().replace(":", "").replace("-", "")
    if re.fullmatch(r"[0-9a-f]{12}", compact) is None:
        raise StopFlashing(f"STOP: invalid MAC address format: {value!r}")

    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def _format_mac(mac: Sequence[int] | None) -> str:
    if mac is None or len(mac) != 6:
        raise StopFlashing("STOP: esptool API did not report a base MAC address")

    return ":".join(f"{part:02x}" for part in mac)


def parse_partition_table(
    flash_image: bytes,
    *,
    table_offset: int = PARTITION_TABLE_OFFSET,
    table_size: int = PARTITION_TABLE_SIZE,
) -> tuple[PartitionEntry, ...]:
    if table_offset < 0 or table_size <= 0:
        raise StopFlashing("STOP: invalid partition table offset or size")
    if table_offset + table_size > len(flash_image):
        raise StopFlashing(
            "STOP: partition table is outside flash dump: "
            f"offset=0x{table_offset:x}, size=0x{table_size:x}, "
            f"flash_size=0x{len(flash_image):x}"
        )

    table = flash_image[table_offset : table_offset + table_size]
    entries: list[PartitionEntry] = []

    for entry_offset in range(0, len(table), PARTITION_ENTRY_SIZE):
        raw = table[entry_offset : entry_offset + PARTITION_ENTRY_SIZE]
        if len(raw) < PARTITION_ENTRY_SIZE:
            break
        if raw == b"\xff" * PARTITION_ENTRY_SIZE:
            break
        if raw.startswith(PARTITION_MD5_MAGIC):
            break
        if not raw.startswith(PARTITION_MAGIC):
            if entries:
                break
            raise StopFlashing(
                "STOP: partition table does not start with ESP partition magic "
                f"at offset 0x{table_offset:x}"
            )

        label = raw[12:28].split(b"\x00", 1)[0].decode("ascii", errors="strict")
        entries.append(
            PartitionEntry(
                type=raw[2],
                subtype=raw[3],
                offset=int.from_bytes(raw[4:8], "little"),
                size=int.from_bytes(raw[8:12], "little"),
                label=label,
                flags=int.from_bytes(raw[28:32], "little"),
            )
        )

    if not entries:
        raise StopFlashing("STOP: no ESP partition entries found")

    return tuple(entries)


def find_partition(
    entries: tuple[PartitionEntry, ...],
    label: str,
    *,
    flash_size: int,
) -> PartitionEntry:
    matches = [entry for entry in entries if entry.label == label]
    if not matches:
        labels = ", ".join(entry.label for entry in entries)
        raise StopFlashing(f"STOP: partition {label!r} not found; available labels: {labels}")
    if len(matches) > 1:
        raise StopFlashing(f"STOP: partition label {label!r} is ambiguous")

    partition = matches[0]
    if partition.offset < 0 or partition.size <= 0:
        raise StopFlashing(f"STOP: partition {label!r} has invalid offset/size")
    if partition.end > flash_size:
        raise StopFlashing(
            f"STOP: partition {label!r} exceeds flash dump size: "
            f"offset=0x{partition.offset:x}, size=0x{partition.size:x}, "
            f"flash_size=0x{flash_size:x}"
        )

    return partition
