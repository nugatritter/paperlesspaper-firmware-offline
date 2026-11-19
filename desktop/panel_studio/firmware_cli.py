"""Headless PlatformIO/esptool workflow shared by the desktop GUI and terminal."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .firmware_core import (
    APP_CAPACITY, ENVIRONMENT, PROJECT_ROOT, UPLOAD_SPEEDS, WorkflowError,
    flash_arguments, prepare_images, stage_images, validate_partition_csv, validate_port_name,
)


class Reporter:
    def __init__(self, path: Path):
        self.path = path
        self.file = path.open("w", encoding="utf-8", buffering=1)

    def __call__(self, message: str):
        print(message, flush=True)
        self.file.write(message + "\n")


def validate_build_dependencies():
    """Check filesystem APIs required by the configured ESP32 platform."""
    import importlib

    required = (
        ("littlefs", ("LittleFS",), "littlefs-python"),
        ("fatfs", (
            "Partition", "RamDisk", "create_extended_partition",
            "create_esp32_wl_image", "calculate_esp32_wl_overhead",
            "is_esp32_wl_image", "extract_fat_from_esp32_wl",
        ), "fatfs-ng"),
        ("fatfs.partition_extended", ("PartitionExtended",), "fatfs-ng"),
        ("fatfs.wrapper", ("pyf_mkfs", "PY_FR_OK"), "fatfs-ng"),
    )
    for module_name, attributes, package in required:
        try:
            module = importlib.import_module(module_name)
            missing = [name for name in attributes if not hasattr(module, name)]
            if missing:
                raise ImportError("Fehlende Funktionen: " + ", ".join(missing))
        except Exception as error:
            command = subprocess.list2cmdline([
                sys.executable, "-m", "pip", "install", "-r",
                str(Path(__file__).resolve().parents[1] / "requirements.txt"),
            ])
            raise WorkflowError(
                f"Build-Abhängigkeit {package} fehlt oder ist inkompatibel "
                f"({module_name}): {error}. "
                f"Abhängigkeiten mit demselben Python installieren: {command}. "
                "Bei FatFS-Konflikten konkurrierende Pakete fatfs/fatfs-python "
                "aus dieser Umgebung entfernen und fatfs-ng neu installieren.",
                2,
            ) from error


def child_options(project: Path) -> dict:
    environment = os.environ.copy()
    environment.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1",
                       PLATFORMIO_SETTING_ENABLE_TELEMETRY="No", NO_COLOR="1", TERM="dumb")
    options = {"cwd": str(project), "env": environment, "encoding": "utf-8", "errors": "replace"}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return options


def run_tool(module: str, arguments: list[str], project: Path, report, *, probe: bool = False) -> tuple[int, str]:
    command = [sys.executable, "-u", "-m", module, *arguments]
    if probe:
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=8, **child_options(project))
            return result.returncode, result.stdout
        except subprocess.TimeoutExpired:
            return 1, "Bootloader-Abfrage ohne Antwort."
    report("$ " + subprocess.list2cmdline(command))
    tail = ""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **child_options(project)) as process:
        try:
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    report(line)
                    tail = (tail + line + "\n")[-262144:]
            return process.wait(), tail
        except BaseException:
            process.terminate()
            process.wait()
            raise


@contextmanager
def project_lock(project: Path):
    path = project / ".pio/build-epd13.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("a+b")
    except OSError as error:
        raise WorkflowError("Ein anderer Build-/Flashlauf hält die Projektsperre.", 2) from error
    with handle:
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise WorkflowError("Ein anderer Build-/Flashlauf ist bereits aktiv.", 2) from error
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    # Keep the inode on POSIX so concurrent openers always lock the same file.


def validate_project(project: Path):
    from platformio.project.config import ProjectConfig

    config = ProjectConfig.get_instance(str(project / "platformio.ini"))
    section = f"env:{ENVIRONMENT}"
    flags = " ".join(config.get(section, "build_flags", []))
    if (config.get(section, "board", "") != "esp32-c6-devkitm-1"
            or config.get(section, "framework", []) != ["arduino"]
            or not re.search(r"(?:^|\s)-DEPD_TYPE_13INCH(?:\s|$|=1(?:\s|$))", flags)
            or "EPD_TYPE_7INCH" in flags
            or any("EPD_TYPE" in flag for flag in config.get(section, "build_unflags", []))):
        raise WorkflowError("epd13 muss ESP32-C6, Arduino und ausschließlich EPD_TYPE_13INCH verwenden.", 2)
    if config.get(section, "board_build.partitions", "") != "part.csv":
        raise WorkflowError("epd13 muss die Projekt-Partitionstabelle part.csv verwenden.", 2)
    if Path(config.get("platformio", "build_dir")).resolve() != (project / ".pio/build").resolve():
        raise WorkflowError("Panel Studio erwartet die Builddateien unter .pio/build.", 2)
    validate_partition_csv(project / "part.csv")
    return config


def ota_image_path(config) -> Path:
    from platformio.package.manager.platform import PlatformPackageManager
    from platformio.package.manager.tool import ToolPackageManager
    from platformio.package.meta import PackageSpec

    # Read installed metadata without importing platform.py, which can install
    # Python dependencies even when PlatformFactory receives autoinstall=False.
    platform = PlatformPackageManager(config.get("platformio", "platforms_dir")).get_package(
        config.get(f"env:{ENVIRONMENT}", "platform"))
    if not platform:
        raise WorkflowError("Die konfigurierte PlatformIO-Plattform fehlt. Zuerst Firmware bauen.", 2)
    manifest = json.loads((Path(platform.path) / "platform.json").read_text(encoding="utf-8"))
    name = "framework-arduinoespressif32"
    settings = manifest["packages"][name]
    spec = PackageSpec(owner=settings.get("owner"), name=name, requirements=settings.get("version"))
    for override in config.get(f"env:{ENVIRONMENT}", "platform_packages", []):
        candidate = PackageSpec(override)
        if candidate.name == name:
            spec = candidate
    package = ToolPackageManager(config.get("platformio", "packages_dir")).get_package(spec)
    if package is None:
        raise WorkflowError("Das Arduino-Framework fehlt. Zuerst Firmware bauen.", 2)
    return Path(package.path) / "tools/partitions/boot_app0.bin"


def validate_port(port: str, report) -> str:
    from serial.tools.list_ports import comports

    port = validate_port_name(port)
    ports = list(comports(include_links=True))
    selected = next((item for item in ports if os.path.normcase(os.path.realpath(item.device))
                     == os.path.normcase(os.path.realpath(port))), None)
    if selected is None:
        available = ", ".join(item.device for item in ports) or "keine"
        raise WorkflowError(f"Port {port} nicht gefunden. Verfügbare Ports: {available}. USB-Datenkabel und Treiber prüfen.", 5)
    if selected.vid is not None and not (selected.vid == 0x303A or (selected.vid, selected.pid) == (0x10C4, 0xEA60)):
        raise WorkflowError(f"{port} gehört nicht zu einer CP210x-Brücke oder einem ESP32-USB-Gerät.", 5)
    report(f"Port: {port} · {selected.description}")
    if selected.vid is None:
        report("[HINWEIS] Keine USB-Kennung verfügbar; der ESP32-C6 wird vor dem Schreiben durch esptool geprüft.")
    return port


def probe_bootloader(project: Path, port: str, report) -> bool:
    code, output = run_tool("esptool", ["--chip", "esp32c6", "--port", port, "--baud", "115200",
                            "--before", "no-reset", "--after", "no-reset", "--connect-attempts", "1", "read-mac"],
                            project, report, probe=True)
    if code == 0:
        report(output.strip())
        return True
    if "Wrong --chip" in output or "not ESP32-C6" in output:
        raise WorkflowError("Das angeschlossene Gerät ist kein ESP32-C6. " + output.strip(), 5)
    if "PermissionError" in output or "Permission denied" in output or "Access is denied" in output:
        raise WorkflowError("Kein Zugriff auf den Port. Andere serielle Programme schließen; unter Linux Geräteberechtigungen prüfen.", 5)
    return False


def enter_bootloader(project: Path, port: str, manual: bool, timeout: int, report):
    import serial

    report("==> ROM-Bootloader prüfen")
    if probe_bootloader(project, port, report):
        return
    if manual:
        raise WorkflowError("Kein ESP32-C6-ROM-Bootloader erreichbar. Boot-Knopf halten, Reset kurz drücken, Boot-Knopf loslassen.", 7)
    report("==> Bootloader anfordern. Falls das Panel schläft, jetzt den großen Reset-Knopf einmal drücken.")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1)
        connection.dtr = False
        connection.rts = False
        connection.port = port
        try:
            connection.open()
            serial_text = ""
            next_request = 0
            listen_until = min(deadline, time.monotonic() + 5)
            while time.monotonic() < listen_until:
                now = time.monotonic()
                if now >= next_request:
                    connection.write(b"\nB")
                    connection.flush()
                    next_request = now + 0.35
                chunk = connection.read(min(max(connection.in_waiting, 1), 4096))
                if chunk:
                    serial_text = (serial_text + chunk.decode("utf-8", "replace"))[-8192:]
                    if re.search(r"waiting for download|DOWNLOAD\(|ROM Download Bootloader|Bootloader command 'B' received", serial_text):
                        time.sleep(0.25)
                        break
        except (OSError, serial.SerialException) as error:
            raise WorkflowError(f"Serieller Zugriff fehlgeschlagen: {error}. Port freigeben und USB-Berechtigungen prüfen.", 5) from error
        finally:
            connection.close()
        # The reader must release the port before esptool opens it.
        if probe_bootloader(project, port, report):
            return
    raise WorkflowError("Bootloader nicht erreicht. Bei älterer Firmware Boot-Knopf halten, Reset drücken und Boot-Knopf loslassen; danach 'Bereits im Bootloader' wählen.", 7)


def execute(arguments, project: Path, report):
    report("==> Projektkonfiguration prüfen")
    config = validate_project(project)
    if arguments.action == "build":
        validate_build_dependencies()
    for package in ("platformio", "esptool", "pyserial"):
        report(f"{package}: {version(package)}")
    if arguments.action == "build":
        if not shutil.which("git"):
            raise WorkflowError("Git fehlt im PATH. Git installieren und Panel Studio neu starten.", 2)
        report("==> Firmware mit PlatformIO bauen · epd13")
        code, _ = run_tool("platformio", ["run", "--project-dir", str(project), "--environment", ENVIRONMENT], project, report)
        if code != 0:
            raise WorkflowError(f"PlatformIO-Build fehlgeschlagen (Exit {code}). Details stehen im Log.", 3)
    report("==> Flashdateien und Prüfsummen prüfen")
    images = prepare_images(project / ".pio/build/epd13", ota_image_path(config), arguments.expected_sha256)
    app = images[-1]
    report(f"App: {len(app.data):,} Bytes · {len(app.data) / APP_CAPACITY:.1%} der Partition · {(APP_CAPACITY - len(app.data)) / 1024:.1f} KiB frei")
    if len(app.data) > APP_CAPACITY * 0.95:
        report("[WARNUNG] Die App-Partition ist zu über 95 % belegt.")
    for image in images:
        report(f"{image.name} @ {image.address:#x} · SHA-256: {image.sha256}")
    with tempfile.TemporaryDirectory(prefix="panel-studio-", dir=project / ".pio") as directory:
        staged = stage_images(images, Path(directory))
        for _, path, _ in (staged[0], staged[-1]):
            code, output = run_tool("esptool", ["--chip", "esp32c6", "image-info", str(path)], project, report)
            if code != 0 or re.search(r"\binvalid\b", output, re.IGNORECASE):
                raise WorkflowError(f"esptool hat {path.name} nicht als gültiges ESP32-C6-Image bestätigt.")
        report("==> Imageprüfung erfolgreich")
        if arguments.action != "flash":
            return
        port = validate_port(arguments.port, report)
        enter_bootloader(project, port, arguments.manual_bootloader, arguments.bootloader_timeout, report)
        command = flash_arguments(port, arguments.baud, staged)
        report("==> Geprüfte Flashdateien übertragen")
        code, output = run_tool("esptool", command, project, report)
        if code != 0:
            raise WorkflowError(f"esptool-Übertragung fehlgeschlagen (Exit {code}). Kein automatischer Neuversuch.", 6)
        if output.count("Hash of data verified") != len(staged):
            raise WorkflowError("esptool meldet nicht für alle vier Dateien eine erfolgreiche Hashprüfung. Übertragung nicht bestätigt.", 6)
        report("==> Übertragung und vier Hashprüfungen erfolgreich. Falls das Panel nicht startet, Reset drücken.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Panel Studio · epd13 · PlatformIO/esptool")
    parser.add_argument("action", choices=("build", "verify", "flash"))
    parser.add_argument("--project", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--port", default="")
    parser.add_argument("--baud", type=int, choices=UPLOAD_SPEEDS, default=921600)
    parser.add_argument("--manual-bootloader", action="store_true")
    parser.add_argument("--bootloader-timeout", type=int, default=120)
    parser.add_argument("--expected-sha256", default="")
    arguments = parser.parse_args(argv)
    if not 5 <= arguments.bootloader_timeout <= 600:
        parser.error("--bootloader-timeout must be between 5 and 600 seconds")
    if arguments.expected_sha256 and not re.fullmatch("[0-9a-fA-F]{64}", arguments.expected_sha256):
        parser.error("--expected-sha256 must contain 64 hexadecimal characters")
    if arguments.action == "flash":
        try:
            arguments.port = validate_port_name(arguments.port)
        except ValueError as error:
            parser.error(str(error))
    project = arguments.project.resolve()
    if not (project / "platformio.ini").is_file():
        print(f"[FEHLER] platformio.ini fehlt: {project}", flush=True)
        return 2
    report = None
    original_directory = Path.cwd()
    try:
        os.chdir(project)
        with project_lock(project):
            log_directory = project / ".pio/logs"
            log_directory.mkdir(parents=True, exist_ok=True)
            report = Reporter(log_directory / f"panel-studio-{arguments.action}-{datetime.now():%Y%m%d-%H%M%S-%f}.log")
            report(f"Log: {report.path}")
            execute(arguments, project, report)
            report("[OK] Vorgang erfolgreich.")
        return 0
    except KeyboardInterrupt:
        (report or print)("[FEHLER] Vorgang abgebrochen. Bei unterbrochener Übertragung Bootloader und Image erneut prüfen.")
        return 130
    except Exception as error:
        message = str(error)
        if isinstance(error, ImportError):
            message += " · Startskript erneut ausführen oder pip install -r desktop/requirements.txt verwenden."
        (report or print)(f"[FEHLER] {message}")
        return error.exit_code if isinstance(error, WorkflowError) else 2
    finally:
        if report:
            report.file.close()
        os.chdir(original_directory)


if __name__ == "__main__":
    sys.exit(main())

