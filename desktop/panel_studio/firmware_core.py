"""Platform-independent validation for the fixed epd13 flash layout."""
from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
from pathlib import Path
import re
import struct

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT = "epd13"
APP_CAPACITY = 0x1D0000
UPLOAD_SPEEDS = (115200, 230400, 460800, 921600, 1500000, 2000000)
PARTITIONS = (
    ("nvs", 1, 2, 0x9000, 0x5000, 0),
    ("otadata", 1, 0, 0xE000, 0x2000, 0),
    ("app0", 0, 16, 0x10000, APP_CAPACITY, 0),
    ("app1", 0, 17, 0x1E0000, APP_CAPACITY, 0),
    ("spiffs", 1, 130, 0x3B0000, 0x40000, 0),
    ("coredump", 1, 3, 0x3F0000, 0x10000, 0),
)
FLASH_RANGES = ((0, 0x8000), (0x8000, 0x9000), (0xE000, 0x10000), (0x10000, 0x1E0000))


class WorkflowError(Exception):
    def __init__(self, message: str, exit_code: int = 4):
        super().__init__(message)
        self.exit_code = exit_code


def validate_port_name(port: str) -> str:
    if re.fullmatch(r"COM[1-9][0-9]*", port, re.IGNORECASE):
        return port.upper()
    if port.startswith("/dev/") and len(port) > 5 and not any(ord(char) < 32 for char in port):
        if ".." not in Path(port).parts:
            return port
    raise ValueError("Einen COM-Port oder seriellen Gerätepfad unter /dev/ auswählen.")


def validate_image(data: bytes, *, app: bool) -> str:
    maximum = APP_CAPACITY if app else 0x8000
    minimum = 65536 if app else 64
    if not minimum <= len(data) <= maximum:
        raise WorkflowError("App-/Bootloader-Größe passt nicht in den vorgesehenen Flashbereich.")
    if data[0] != 0xE9 or not 1 <= data[1] <= 16 or struct.unpack_from("<H", data, 12)[0] != 13:
        raise WorkflowError("Kein gültiges ESP32-C6-Image (Header, Segmentanzahl oder Chip-ID).")
    has_app_description = struct.unpack_from("<I", data, 32)[0] == 0xABCD5432
    if app != has_app_description:
        raise WorkflowError("App und Bootloader verwechselt oder App-Beschreibung fehlt.")
    position = 24
    checksum = 0xEF
    for _ in range(data[1]):
        if position + 8 > len(data):
            raise WorkflowError("Abgeschnittener Image-Segmentheader.")
        length = struct.unpack_from("<I", data, position + 4)[0]
        position += 8
        if position + length > len(data):
            raise WorkflowError("Abgeschnittenes Image-Segment.")
        for value in data[position:position + length]:
            checksum ^= value
        position += length
    checksum_offset = position + (15 - position % 16)
    if checksum_offset >= len(data) or data[checksum_offset] != checksum:
        raise WorkflowError("Die Segment-Prüfsumme des Images stimmt nicht.")
    if any(data[position:checksum_offset]):
        raise WorkflowError("Ungültige Image-Auffüllbytes.")
    image_end = checksum_offset + 1
    if data[23] == 1:
        if len(data) != image_end + 32 or hashlib.sha256(data[:image_end]).digest() != data[image_end:]:
            raise WorkflowError("Der angehängte SHA-256-Hash stimmt nicht oder das Image enthält Zusatzdaten.")
    elif data[23] != 0 or len(data) != image_end:
        raise WorkflowError("Ungültiger Hash-Marker oder unerwartete Daten hinter dem Image.")
    return hashlib.sha256(data).hexdigest().upper()


def validate_partition_binary(data: bytes) -> None:
    if len(data) != 0xC00:
        raise WorkflowError("partitions.bin muss genau 3072 Bytes enthalten.")
    entries = []
    found_digest = False
    for offset in range(0, len(data), 32):
        entry = data[offset:offset + 32]
        if entry == b"\xff" * 32:
            if any(value != 0xFF for value in data[offset:]):
                raise WorkflowError("Daten hinter dem Ende der Partitionstabelle.")
            break
        if entry[:16] == b"\xeb\xeb" + b"\xff" * 14:
            if found_digest or hashlib.md5(data[:offset], usedforsecurity=False).digest() != entry[16:]:
                raise WorkflowError("Die MD5-Prüfsumme der Partitionstabelle stimmt nicht.")
            found_digest = True
            continue
        if entry[:2] != b"\xaa\x50" or found_digest:
            raise WorkflowError("Ungültiger Eintrag in der Partitionstabelle.")
        _, kind, subtype, address, size, name, flags = struct.unpack("<HBBII16sI", entry)
        try:
            name = name.split(b"\0", 1)[0].decode("ascii")
        except UnicodeError as error:
            raise WorkflowError("Ungültiger Partitionsname.") from error
        entries.append((name, kind, subtype, address, size, flags))
    if tuple(entries) != PARTITIONS or not found_digest:
        raise WorkflowError("Die Partitionstabelle entspricht nicht dem geschützten epd13-Projektlayout.")


def validate_partition_csv(path: Path) -> None:
    types = {"app": 0, "data": 1}
    subtypes = {"nvs": 2, "ota": 0, "ota_0": 16, "ota_1": 17, "spiffs": 130, "coredump": 3}

    def number(value):
        value = value.strip()
        multiplier = {"K": 1024, "M": 1024 * 1024}.get(value[-1:].upper(), 1)
        return int(value[:-1] if multiplier != 1 else value, 0) * multiplier

    try:
        entries = []
        for row in csv.reader(path.read_text(encoding="utf-8-sig").splitlines()):
            if not row or row[0].lstrip().startswith("#"):
                continue
            row = [value.strip() for value in row]
            name, kind, subtype, address, size = row[:5]
            flags = row[5] if len(row) > 5 else ""
            entries.append((name, types[kind], subtypes[subtype], number(address), number(size), 0 if not flags else int(flags, 0)))
        if tuple(entries) != PARTITIONS:
            raise ValueError("layout mismatch")
    except (KeyError, ValueError, OSError, UnicodeError) as error:
        raise WorkflowError("part.csv entspricht nicht dem unterstützten epd13-Layout. Kein Flashen mit geänderter Speicheraufteilung.") from error


@dataclass(frozen=True)
class FlashImage:
    name: str
    address: int
    data: bytes
    sha256: str


def prepare_images(build_directory: Path, ota_path: Path, expected_sha256: str = "") -> tuple[FlashImage, ...]:
    images = []
    for name, address, path in (
        ("bootloader.bin", 0, build_directory / "bootloader.bin"),
        ("partitions.bin", 0x8000, build_directory / "partitions.bin"),
        ("boot_app0.bin", 0xE000, ota_path),
        ("firmware.bin", 0x10000, build_directory / "firmware.bin"),
    ):
        try:
            if path.stat().st_size > APP_CAPACITY:
                raise WorkflowError(f"{name} ist zu groß.")
            data = path.read_bytes()
        except OSError as error:
            raise WorkflowError(f"{name} fehlt oder ist nicht lesbar: {path}. Zuerst epd13 bauen.") from error
        if name in {"firmware.bin", "bootloader.bin"}:
            validate_image(data, app=name == "firmware.bin")
        elif name == "partitions.bin":
            validate_partition_binary(data)
        elif len(data) != 8192:
            raise WorkflowError("boot_app0.bin muss genau 8192 Bytes enthalten.")
        erased_end = (address + len(data) + 4095) // 4096 * 4096
        if not any(address == start and erased_end <= end for start, end in FLASH_RANGES):
            raise WorkflowError("Flashbereich würde geschützten Speicher überschreiben.")
        digest = hashlib.sha256(data).hexdigest().upper()
        if name == "firmware.bin" and expected_sha256 and digest != expected_sha256.upper():
            raise WorkflowError("Das App-Image wurde seit der GUI-Bestätigung verändert. Bitte erneut prüfen und bestätigen.")
        images.append(FlashImage(name, address, data, digest))
    return tuple(images)


def stage_images(images: tuple[FlashImage, ...], directory: Path) -> list[tuple[int, Path, str]]:
    staged = []
    for image in images:
        path = directory / image.name
        path.write_bytes(image.data)
        staged.append((image.address, path, image.sha256))
    return staged


def flash_arguments(port: str, baud: int, staged: list[tuple[int, Path, str]]) -> list[str]:
    port = validate_port_name(port)
    if baud not in UPLOAD_SPEEDS:
        raise ValueError("Ungültige Upload-Baudrate.")
    if [address for address, _, _ in staged] != [start for start, _ in FLASH_RANGES]:
        raise WorkflowError("Unvollständiger oder unerwarteter Flashplan.")
    arguments = ["--chip", "esp32c6", "--port", port, "--baud", str(baud),
                 "--before", "no-reset", "--after", "hard-reset", "--connect-attempts", "1",
                 "write-flash", "--compress", "--flash-mode", "keep", "--flash-freq", "keep", "--flash-size", "keep"]
    for address, path, digest in staged:
        if hashlib.sha256(path.read_bytes()).hexdigest().upper() != digest:
            raise WorkflowError("Eine geprüfte Flashdatei wurde verändert. Übertragung abgebrochen.")
        arguments += [hex(address), str(path)]
    return arguments


def image_summary(project: Path = PROJECT_ROOT) -> dict:
    path = project / ".pio/build/epd13/firmware.bin"
    if not path.is_file():
        return {"path": str(path), "error": "Noch kein Image vorhanden. Zuerst die Firmware bauen."}
    size = path.stat().st_size
    if not 65536 <= size <= APP_CAPACITY:
        return {"path": str(path), "size": size, "error": "Die Image-Größe passt nicht in die App-Partition."}
    data = path.read_bytes()
    valid_header = data[0] == 0xE9 and struct.unpack_from("<H", data, 12)[0] == 13
    valid_app = struct.unpack_from("<I", data, 32)[0] == 0xABCD5432
    result = {"path": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest().upper(),
              "modified": path.stat().st_mtime, "percent": len(data) / APP_CAPACITY * 100}
    if not valid_header or not valid_app:
        result["error"] = "Kein plausibles ESP32-C6-App-Image. Vollständige Prüfung erforderlich."
    return result
