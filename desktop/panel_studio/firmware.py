"""Run the Python firmware workflow asynchronously without a shell."""
from __future__ import annotations

import codecs
from pathlib import Path
import re
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from .firmware_core import APP_CAPACITY, PROJECT_ROOT, UPLOAD_SPEEDS, image_summary, validate_port_name


def build_arguments(project: Path, action: str, port: str = "", baud: int = 921600,
                    manual_bootloader: bool = False, expected_sha256: str = "") -> list[str]:
    if action not in {"build", "verify", "flash"}:
        raise ValueError("Unbekannter Firmware-Vorgang.")
    if not (project / "platformio.ini").is_file():
        raise ValueError(f"PlatformIO-Projekt fehlt: {project}")
    arguments = ["-u", "-m", "panel_studio.firmware_cli", action, "--project", str(project.resolve())]
    if action == "flash":
        port = validate_port_name(port)
        if baud not in UPLOAD_SPEEDS:
            raise ValueError("Ungültige Upload-Geschwindigkeit.")
        arguments += ["--port", port, "--baud", str(baud), "--bootloader-timeout", "120"]
        if manual_bootloader:
            arguments.append("--manual-bootloader")
        if expected_sha256:
            if not re.fullmatch("[0-9a-fA-F]{64}", expected_sha256):
                raise ValueError("Ungültiger SHA-256 für die Image-Bestätigung.")
            arguments += ["--expected-sha256", expected_sha256]
    return arguments


def python_executable() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    return str(executable)


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

    def start(self, action: str, port: str = "", baud: int = 921600, manual_bootloader: bool = False,
              expected_sha256: str = "") -> None:
        if self.active:
            raise ValueError("Es läuft bereits ein Firmware-Vorgang.")
        arguments = build_arguments(self.project, action, port, baud, manual_bootloader, expected_sha256)
        self.buffer = ""
        self.decoder.reset()
        self.action = action
        self.active = True
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUTF8", "1")
        self.process.setProcessEnvironment(environment)
        self.progress.emit(-1)
        self.phase.emit({"build": "Firmware wird gebaut …", "verify": "Image wird geprüft …", "flash": "Imageprüfung und USB-Übertragung …"}[action])
        self.process.start(python_executable(), arguments)

    def _emit_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        self.output.emit(line)
        if line.startswith("==>") or "[HINWEIS]" in line or "Reset-Knopf" in line:
            self.phase.emit(line.removeprefix("==>").strip())
        match = re.search(r"(?:Writing|Wrote).*?(\d+(?:\.\d+)?)\s*%", line, re.IGNORECASE)
        if match:
            self.progress.emit(min(100, round(float(match.group(1)))))

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
