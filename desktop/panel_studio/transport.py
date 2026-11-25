"""One serial owner and one outstanding protocol request at a time."""
from __future__ import annotations

import queue
import threading

import serial
from serial.tools import list_ports
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .protocol import LineDecoder, command_name, parse_reply, safe_command_label
from .schedule import CycleSchedule


def available_ports() -> list[tuple[str, str, bool]]:
    result = []
    for port in list_ports.comports():
        likely_panel = (port.vid, port.pid) == (0x10C4, 0xEA60) or port.vid == 0x303A
        result.append((port.device, f"{port.device}  ·  {port.description}", likely_panel))
    return sorted(result, key=lambda item: (not item[2], item[0]))


class SerialWorker(QThread):
    opened = Signal()
    line_received = Signal(str)
    failed = Signal(str)

    def __init__(self, port: str, serial_factory=serial.Serial):
        super().__init__()
        self.port = port
        self.serial_factory = serial_factory
        self.outgoing: queue.Queue[bytes] = queue.Queue()
        self.stop_requested = threading.Event()

    def send(self, data: bytes) -> None:
        self.outgoing.put(data)

    def stop(self) -> None:
        self.stop_requested.set()

    def run(self) -> None:
        connection = None
        try:
            connection = self.serial_factory(port=None, baudrate=115200, timeout=0.05, write_timeout=1)
            connection.dtr = False
            connection.rts = False
            connection.port = self.port
            connection.open()
            self.opened.emit()
            decoder = LineDecoder()
            while not self.stop_requested.is_set():
                try:
                    data = self.outgoing.get_nowait()
                except queue.Empty:
                    data = None
                if data is not None:
                    if connection.write(data) != len(data):
                        raise serial.SerialTimeoutException("Befehl wurde nicht vollständig übertragen.")
                chunk = connection.read(min(max(connection.in_waiting, 1), 8192))
                for line in decoder.feed(chunk):
                    self.line_received.emit(line)
        except (serial.SerialException, OSError, ValueError) as error:
            self.failed.emit(str(error))
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (OSError, serial.SerialException):
                    pass


class ConsoleController(QObject):
    state_changed = Signal(str, str)
    log_received = Signal(str, str)
    reply_received = Signal(dict)
    problem = Signal(str)

    def __init__(self, parent=None, worker_factory=SerialWorker):
        super().__init__(parent)
        self.worker_factory = worker_factory
        self.worker: SerialWorker | None = None
        self.port = ""
        self.state = "disconnected"
        self.pending: str | None = None
        self.wifi_wait = False
        self.update_in_progress = False
        self.cycle_schedule = CycleSchedule()
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)
        self.wifi_timer = QTimer(self)
        self.wifi_timer.setSingleShot(True)
        self.wifi_timer.timeout.connect(self._wifi_complete)

    @property
    def connected(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _set_state(self, state: str, message: str) -> None:
        self.state = state
        self.state_changed.emit(state, message)

    def connect_port(self, port: str) -> None:
        if self.worker is not None:
            raise RuntimeError("Die bisherige Verbindung muss zuerst geschlossen werden.")
        self.port = port
        self.cycle_schedule.reset()
        worker = self.worker_factory(port)
        self.worker = worker
        worker.opened.connect(lambda: self._opened(worker))
        worker.line_received.connect(lambda line: self._line(worker, line))
        worker.failed.connect(lambda message: self._failed(worker, message))
        worker.finished.connect(lambda: self._finished(worker))
        self._set_state("opening", f"Öffne {port} …")
        worker.start()

    def disconnect_port(self) -> bool:
        self.deadline.stop()
        self.wifi_timer.stop()
        self.pending = None
        self.wifi_wait = False
        self.update_in_progress = False
        worker = self.worker
        if worker is not None:
            worker.stop()
            if not worker.wait(2000):
                self.problem.emit("Der serielle Port wird noch geschlossen. Bitte kurz warten.")
                return False
            self.worker = None
            worker.deleteLater()
        self._set_state("disconnected", "Nicht verbunden")
        return True

    def request(self, command: str) -> bool:
        if not self.connected or self.state in {"opening", "updating"} or self.pending or self.wifi_wait:
            return False
        if command == "B":
            if self.state != "ready":
                self.problem.emit("Für diesen Befehl zuerst das Panel aufwecken und DIAG abfragen. Der Flasher kann alternativ selbst auf Reset warten.")
                return False
            self.worker.send(b"\nB")
            self.cycle_schedule.clear_estimate()
            self.log_received.emit("TX", "B · ROM-Bootloader anfordern")
            self._set_state("bootloader", "Bootloader angefordert. Falls nötig einmal Reset drücken.")
            return True
        if command_name(command) not in {"DIAG", "HELP", "CONFIG GET", "CONFIG SET", "CLOCK SET", "WIFI CONNECT", "RUN", "FORCE REFRESH IMAGE", "REBOOT"}:
            raise ValueError("Unbekannter Konsolenbefehl.")
        if "\n" in command or "\r" in command or len(command.encode("utf-8")) > 2048:
            raise ValueError("Ungültige Befehlszeile.")
        self.pending = command_name(command)
        self.worker.send((command + "\n").encode("utf-8"))
        self.log_received.emit("TX", safe_command_label(command))
        self._set_state("busy", f"{self.pending} …")
        self.deadline.start(8000 if self.pending == "CONFIG SET" else 5000)
        return True

    def _opened(self, worker) -> None:
        if worker is not self.worker:
            return
        self._set_state("waiting", "Mithören aktiv · warte auf die nächste Panelmeldung.")
        self.log_received.emit("SYSTEM", f"{self.port} geöffnet · 115200 Baud · DTR/RTS aus")

    def _line(self, worker, line: str) -> None:
        if worker is not self.worker:
            return
        self.cycle_schedule.observe_line(line)
        kind = "JSON" if line.startswith("[USB] {") else "RX"
        try:
            reply = parse_reply(line)
        except ValueError as error:
            self.log_received.emit(kind, line)
            self.log_received.emit("SYSTEM", str(error))
            return
        if reply is not None:
            self.cycle_schedule.observe_reply(reply)
        self.log_received.emit(kind, line)
        if "ESP-ROM:" in line:
            if self.update_in_progress:
                self.problem.emit("Neustart während des Bildablaufs; ein erfolgreicher Abschluss wurde nicht bestätigt. Reset-Grund und Renderstatus in der Diagnose prüfen.")
            self.update_in_progress = False
            self.deadline.stop()
            self.pending = None
            self._set_state("waiting", "Panel startet neu.")
        if "[WAKE] Got Timer Wakeup" in line:
            self._set_state("waiting", "Panel durch Timer aufgewacht.")
        if "[MAIN] Setup Mode Completed or Timeout" in line or "[USB] Session ended:" in line:
            self.update_in_progress = True
            self._set_state("updating", "Setup beendet · Bildzyklus läuft.")
        if "[DL] Download Image file:" in line:
            self.update_in_progress = True
            self._set_state("updating", "Bildabruf vom Server läuft.")
        if "[IMAGE] Render begin:" in line or "[EPD] Render stage:" in line or "[EPD] Render waiting:" in line:
            self.update_in_progress = True
            self._set_state("updating", "Bildaufbau läuft. Bitte Taster und USB-Verbindung unverändert lassen.")
        if "[MAIN] End of Update" in line:
            self.update_in_progress = False
        if "[USB] Ready:" in line:
            if self.pending is None:
                self._set_state("ready", "USB-Konsole bereit · Mithören aktiv.")
            return
        if "[MAIN] test mode check" in line:
            self.deadline.stop()
            self.pending = None
            self.wifi_wait = False
            self.wifi_timer.stop()
            self._set_state("waiting", "Panel startet. Warte auf USB-Konsole …")
        if "[MAIN] Going to Sleep" in line:
            self.update_in_progress = False
            self.deadline.stop()
            self.wifi_timer.stop()
            self.wifi_wait = False
            self.pending = None
            self._set_state("sleeping", "Panel schläft · Mithören aktiv.")
        if "ROM Download Bootloader" in line or "waiting for download" in line:
            self.deadline.stop()
            self.wifi_timer.stop()
            self.wifi_wait = False
            self.pending = None
            self._set_state("bootloader", "ROM-Bootloader aktiv")
        if reply is None:
            return
        response_name = reply.get("command")
        if self.pending is None or (response_name != self.pending and not (not reply["ok"] and response_name in (None, "INPUT"))):
            self.log_received.emit("SYSTEM", "Verspätete oder unerwartete Antwort; keine Aktion bestätigt.")
            return
        completed = self.pending
        self.pending = None
        self.deadline.stop()
        if not reply["ok"]:
            self._set_state("waiting", str(reply.get("error", "Befehl abgelehnt")))
            self.problem.emit(str(reply.get("error", "Das Panel hat den Befehl abgelehnt.")))
            return
        if completed == "RUN":
            self.update_in_progress = True
            self._set_state("updating", "Bildablauf läuft; anschließend schläft das Panel.")
        elif completed == "FORCE REFRESH IMAGE":
            self.update_in_progress = True
            self._set_state("updating", "Gespeichertes Bild wird neu aufgebaut. Bitte Taster und USB unverändert lassen.")
        elif completed == "REBOOT":
            self._set_state("waiting", "Neustart bestätigt. Warte auf USB-Konsole …")
        elif completed == "WIFI CONNECT":
            self.wifi_wait = True
            self._set_state("busy", "WLAN-Verbindung wird geprüft (bis zu 12 Sekunden) …")
            self.wifi_timer.start(12000)
        else:
            self._set_state("ready", f"{self.port} · USB-Konsole bereit")
        self.reply_received.emit(reply)

    def _wifi_complete(self) -> None:
        self.wifi_wait = False
        self.request("DIAG")

    def _timeout(self) -> None:
        command = self.pending
        self.pending = None
        message = "Keine Antwort. Panel ggf. aufwecken und Diagnose erneut abfragen."
        if command == "CONFIG SET":
            message = "Speicherbestätigung fehlt. Vor erneutem Speichern Einstellungen neu auslesen."
        self._set_state("waiting", message)
        self.problem.emit(message)

    def _failed(self, worker, message: str) -> None:
        if worker is self.worker:
            details = f"USB-Verbindung fehlgeschlagen: {message}"
            if self.update_in_progress:
                details += " · Abschluss des Bildablaufs unbekannt. Das Panel kann noch arbeiten. Nach Wiederverbindung Diagnose prüfen."
            self.problem.emit(details)

    def _finished(self, worker) -> None:
        if worker is not self.worker:
            return
        self.worker = None
        self.update_in_progress = False
        self.deadline.stop()
        self.wifi_timer.stop()
        self.pending = None
        self.wifi_wait = False
        self._set_state("disconnected", "Verbindung getrennt. Kabel und Port prüfen.")
        worker.deleteLater()
