"""Run the repository's verified Windows build/flash workflow without a shell."""
from __future__ import annotations

import codecs
import hashlib
import os
from pathlib import Path
import re
import shutil
import struct

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_CAPACITY = 0x1D0000
UPLOAD_SPEEDS = (115200, 230400, 460800, 921600, 1500000, 2000000)


def build_arguments(project: Path, action: str, port: str = "", baud: int = 921600,
                    manual_bootloader: bool = False) -> list[str]:
    if action not in {"build", "verify", "flash"}:
        raise ValueError("Unbekannter Firmware-Vorgang.")
    script = project / "build.ps1"
    if not script.is_file():
        raise ValueError(f"Build-Skript fehlt: {script}")
    arguments = ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    if action in {"verify", "flash"}:
        arguments.append("-VerifyOnly")
    if action == "flash":
        if not re.fullmatch(r"COM[1-9][0-9]*", port, re.IGNORECASE):
            raise ValueError("Für diesen Windows-Flasher einen COM-Port auswählen.")
        if baud not in UPLOAD_SPEEDS:
            raise ValueError("Ungültige Upload-Geschwindigkeit.")
        arguments += ["-Upload", "-Port", port.upper(), "-UploadBaud", str(baud), "-BootloaderTimeout", "120"]
        if manual_bootloader:
            arguments.append("-NoAutoBootloader")
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


class FirmwareJob(QObject):
    output = Signal(str)
    phase = Signal(str)
    progress = Signal(int)
    completed = Signal(str, int)

    def __init__(self, parent=None, project: Path = PROJECT_ROOT):
        super().__init__(parent)
        self.project = project
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.active = False
        self.action = ""
        self.buffer = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def start(self, action: str, port: str = "", baud: int = 921600, manual_bootloader: bool = False) -> None:
        if self.active:
            raise ValueError("Es läuft bereits ein Firmware-Vorgang.")
        if os.name != "nt":
            raise ValueError("Build und Flashen verwenden build.ps1 und sind in dieser GUI unter Windows verfügbar.")
        executable = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if not executable:
            raise ValueError("PowerShell wurde nicht gefunden.")
        arguments = build_arguments(self.project, action, port, baud, manual_bootloader)
        self.buffer = ""
        self.decoder.reset()
        self.action = action
        self.active = True
        self.process.setWorkingDirectory(str(self.project))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUTF8", "1")
        self.process.setProcessEnvironment(environment)
        self.progress.emit(-1)
        self.phase.emit({"build": "Firmware wird gebaut …", "verify": "Image wird geprüft …", "flash": "Imageprüfung und USB-Übertragung …"}[action])
        self.process.start(executable, arguments)

    def _emit_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        self.output.emit(line)
        if line.startswith("==>") or "[HINWEIS]" in line or "Reset-Knopf" in line:
            self.phase.emit(line.removeprefix("==>").strip())
        match = re.search(r"(?:Writing|Wrote).*?\(\s*(\d+)\s*%\s*\)", line, re.IGNORECASE)
        if match:
            self.progress.emit(min(100, int(match.group(1))))

    def _read(self) -> None:
        self.buffer += self.decoder.decode(bytes(self.process.readAllStandardOutput())).replace("\r", "\n")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._emit_line(line)
        if len(self.buffer) > 65536:
            self._emit_line(self.buffer[:65536])
            self.buffer = ""

    def _finish(self, exit_code: int) -> None:
        if not self.active:
            return
        self._read()
        self.buffer += self.decoder.decode(b"", final=True)
        self._emit_line(self.buffer)
        self.buffer = ""
        self.active = False
        self.progress.emit(100 if exit_code == 0 else 0)
        self.completed.emit(self.action, exit_code)

    def _finished(self, exit_code: int, status) -> None:
        self._finish(exit_code if status == QProcess.ExitStatus.NormalExit else -1)

    def _error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.output.emit(self.process.errorString())
            self._finish(-1)
