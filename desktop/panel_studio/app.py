"""German desktop interface for the offline panel console and epd13 flasher."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QCloseEvent, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from . import __version__
from .firmware import APP_CAPACITY, PROJECT_ROOT, UPLOAD_SPEEDS, FirmwareJob, image_summary
from .protocol import LABELS, PASSWORD_KEYS, import_config, make_config_command, validate_config
from .transport import ConsoleController, available_ports
from .widgets import ConfigEditor, Dashboard, LogViewer, button, label

STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #223138; }
QMainWindow, QDialog, #workspace { background: #f4f6f7; }
#sidebar { background: #19282e; border: none; }
#sidebar QLabel { color: #aebdc3; }
#sidebar QLabel[role='brand'] { color: #f5cc4c; font-size: 18pt; font-weight: 700; }
#sidebar QPushButton { background: transparent; border: none; color: #c9d5da; text-align: left; padding: 15px 12px; border-radius: 7px; }
#sidebar QPushButton:hover { background: #293a41; }
#sidebar QPushButton:checked { background: #f5cc4c; color: #19282e; font-weight: 600; }
QLabel[role='heading'] { font-size: 23pt; font-weight: 650; }
QLabel[role='metric'] { font-size: 25pt; font-weight: 650; }
QLabel[role='caption'] { color: #597079; font-size: 9pt; font-weight: 600; }
QLabel[role='muted'] { color: #647983; }
QLabel[role='note'] { background: #e9f0f1; border-radius: 6px; padding: 12px; color: #38545e; }
#metricCard { background: white; border: 1px solid #dce4e7; border-radius: 10px; }
QPushButton { background: white; border: 1px solid #cad6dc; border-radius: 6px; padding: 9px 13px; }
QPushButton:hover { background: #eaf0f2; border-color: #8aa0ab; }
QPushButton:pressed { background: #d9e3e7; }
QPushButton[primary='true'] { background: #f5cc4c; border-color: #e5bb39; color: #243137; font-weight: 600; }
QPushButton[primary='true']:hover { background: #ffda66; }
QPushButton:disabled { background: #e9eef0; color: #8c9da5; border-color: #dce4e7; }
QLineEdit, QSpinBox, QComboBox { background: white; border: 1px solid #cad6dc; border-radius: 5px; padding: 7px; selection-background-color: #d9b647; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #467d88; }
QLineEdit:disabled, QComboBox:disabled { background: #edf1f3; color: #84969f; }
QComboBox::drop-down { border: none; width: 23px; }
QComboBox::down-arrow, QSpinBox::down-arrow { image: url("__DOWN_ARROW__"); width: 10px; height: 10px; }
QSpinBox::up-arrow { image: url("__UP_ARROW__"); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #e2edf0; selection-color: #223138; }
QGroupBox { border: 1px solid #dce4e7; border-radius: 8px; background: white; margin-top: 15px; padding: 15px 12px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; }
QTreeWidget, QPlainTextEdit { background: white; border: 1px solid #dce4e7; border-radius: 6px; selection-background-color: #d9e9ed; selection-color: #223138; }
QTreeWidget { alternate-background-color: #f6f9fa; }
QTreeWidget::item { padding: 4px; }
QHeaderView::section { background: #edf2f4; padding: 8px; border: none; font-weight: 600; }
QPlainTextEdit[code='true'] { font-family: 'Cascadia Code', Consolas, monospace; font-size: 9pt; padding: 8px; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #e5ecef; padding: 10px 18px; margin-right: 4px; border-radius: 4px; }
QTabBar::tab:selected { background: white; color: #254f59; }
QCheckBox { spacing: 7px; font-weight: 400; }
QCheckBox::indicator { width: 17px; height: 17px; }
QProgressBar { background: #e2e9ec; border: none; border-radius: 5px; min-height: 12px; text-align: center; }
QProgressBar::chunk { background: #3c8995; border-radius: 5px; }
QScrollArea { background: transparent; border: none; }
QToolTip { background: #19282e; color: white; border: none; padding: 7px; }
"""

PAGE_INFO = [
    ("Überblick", "Status und vollständige Diagnose Ihres Panels"),
    ("Einstellungen", "Verbindung, Bildquelle und Anzeige konfigurieren"),
    ("Firmware", "Projekt-Firmware für das 13,3-Zoll-Panel bauen, prüfen und übertragen"),
    ("Konsole", "Befehle ausführen und serielle Rückmeldungen verfolgen"),
]


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.GlobalColor.darkCyan)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, 64, 64, 12, 12)
    painter.setPen(Qt.GlobalColor.yellow)
    painter.setFont(QFont("Segoe UI", 35, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "e")
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self, *, demo=False, preferences=None, controller=None, firmware_job=None):
        super().__init__()
        self.demo = demo
        self.preferences = preferences or QSettings("eYellowBoard", "Panel Studio")
        self.controller = controller or ConsoleController(self)
        self.firmware_job = firmware_job or FirmwareJob(self)
        self.force_reload = False
        self.flash_port = ""
        self.setWindowTitle("eYellowBoard · Panel Studio")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1060, 720)
        self.resize(1320, 900)
        root = QWidget()
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(205)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 30, 18, 20)
        side.addWidget(label("eYellowBoard", "brand"))
        side.addWidget(label("PANEL STUDIO", "caption"))
        side.addSpacing(38)
        self.nav_buttons = []
        for index, (title, _) in enumerate(PAGE_INFO):
            item = button(f"0{index + 1}   {title}", lambda checked=False, page=index: self.select_page(page))
            item.setCheckable(True)
            side.addWidget(item)
            self.nav_buttons.append(item)
        side.addStretch()
        side.addWidget(label("USB · 115200 Baud\nOffline-Firmware", "", True))
        guide = button("Anleitung öffnen", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(PROJECT_ROOT / "desktop/README.md"))))
        side.addWidget(guide)
        side.addWidget(label(f"Version {__version__}", "caption"))
        shell.addWidget(sidebar)
        workspace = QWidget()
        workspace.setObjectName("workspace")
        body = QVBoxLayout(workspace)
        body.setContentsMargins(28, 24, 28, 20)
        body.setSpacing(15)
        self.heading = label("", "heading")
        self.subtitle = label("", "muted")
        body.addWidget(self.heading)
        body.addWidget(self.subtitle)
        connection = QHBoxLayout()
        self.ports = QComboBox()
        self.ports.setEditable(True)
        self.ports.setMinimumWidth(260)
        self.ports.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ports.setToolTip("Port auswählen oder eingeben: COM10, /dev/ttyUSB0 oder /dev/cu.usbserial-…")
        self.ports.lineEdit().setPlaceholderText("Seriellen Port auswählen")
        self.scan_button = button("Ports suchen", self.scan_ports)
        self.connect_button = button("Verbinden", self.toggle_connection, True)
        self.live = QCheckBox("Live-Diagnose · 15 s")
        self.live.setToolTip("Hält die USB-Sitzung offen, solange die Konsole bereit ist.")
        self.live.setChecked(self.preferences.value("live", True, type=bool))
        connection.addWidget(self.ports, 1)
        connection.addWidget(self.scan_button)
        connection.addWidget(self.connect_button)
        connection.addWidget(self.live)
        body.addLayout(connection)
        self.status_label = label("Nicht verbunden · USB anschließen, verbinden und einmal Reset drücken.", "note", True)
        body.addWidget(self.status_label)
        self.pages = QStackedWidget()
        self.dashboard = Dashboard()
        self.config = ConfigEditor()
        self.log = LogViewer()
        self.pages.addWidget(self.dashboard)
        self.pages.addWidget(self.config)
        self.pages.addWidget(self._firmware_page())
        self.pages.addWidget(self._console_page())
        body.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        self.wifi_button = button("WLAN verbinden", lambda: self.send("WIFI CONNECT"))
        self.run_button = button("Bild aktualisieren und schlafen", lambda: self.confirm_command("RUN"))
        self.reboot_button = button("Neustart", lambda: self.confirm_command("REBOOT"))
        footer.addWidget(self.wifi_button)
        footer.addWidget(self.run_button)
        footer.addStretch()
        footer.addWidget(self.reboot_button)
        body.addLayout(footer)
        shell.addWidget(workspace, 1)
        self.setCentralWidget(root)
        self.controller.state_changed.connect(self.connection_changed)
        self.controller.log_received.connect(self.log.append)
        self.controller.reply_received.connect(self.handle_reply)
        self.controller.problem.connect(self.show_problem)
        self.dashboard.refresh_requested.connect(lambda: self.send("DIAG"))
        self.dashboard.export_requested.connect(self.export_diagnostics)
        self.config.save_requested.connect(self.save_config)
        self.config.reload_requested.connect(self.reload_config)
        self.config.import_requested.connect(self.import_settings)
        self.config.export_requested.connect(self.export_settings)
        self.config.changed.connect(self.update_controls)
        self.log.export_requested.connect(self.export_log)
        self.firmware_job.output.connect(self.firmware_output)
        self.firmware_job.phase.connect(self.firmware_phase.setText)
        self.firmware_job.progress.connect(self.update_progress)
        self.firmware_job.completed.connect(self.firmware_finished)
        self.ports.currentTextChanged.connect(self.update_controls)
        self.poll = QTimer(self)
        self.poll.setInterval(15000)
        self.poll.timeout.connect(self.poll_diagnostics)
        self.poll.start()
        self.select_page(0)
        self.scan_ports()
        self.refresh_artifact()
        if self.demo:
            self.load_demo()
        self.update_controls()

    def _console_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.command = QComboBox()
        self.command.addItems(["HELP", "DIAG", "CONFIG GET", "WIFI CONNECT", "RUN", "REBOOT", "B"])
        self.command.setToolTip("CONFIG SET ist über das geprüfte Einstellungsformular verfügbar.")
        self.command_button = button("Befehl senden", self.send_selected, True)
        row.addWidget(self.command)
        row.addWidget(self.command_button)
        row.addWidget(label("Konfigurationswerte werden beim Senden nicht ins Log geschrieben.", "muted", True), 1)
        layout.addLayout(row)
        layout.addWidget(self.log, 1)
        return page

    def _firmware_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Ziel: epd13 · ESP32-C6 · 13,3 Zoll", "caption"))
        box = QGroupBox("Aktuelles Projekt-Image")
        info = QVBoxLayout(box)
        self.image_label = label("", "", True)
        self.image_hash = QLineEdit()
        self.image_hash.setReadOnly(True)
        self.image_hash.setPlaceholderText("SHA-256 nach dem Build")
        self.image_hash.setToolTip("SHA-256 der lokalen firmware.bin")
        self.image_usage = QProgressBar()
        self.image_usage.setRange(0, 100)
        info.addWidget(self.image_label)
        info.addWidget(self.image_hash)
        info.addWidget(self.image_usage)
        layout.addWidget(box)
        options = QHBoxLayout()
        options.addWidget(label("Upload-Baudrate"))
        self.upload_speed = QComboBox()
        for speed in UPLOAD_SPEEDS:
            self.upload_speed.addItem(f"{speed:,}".replace(",", "."), speed)
        saved_speed = self.preferences.value("uploadBaud", 921600, type=int)
        self.upload_speed.setCurrentIndex(max(0, self.upload_speed.findData(saved_speed)))
        self.manual_boot = QCheckBox("Bereits im Bootloader")
        self.manual_boot.setToolTip("Überspringt das automatische Senden von B. Nur verwenden, wenn der ROM-Bootloader bereits aktiv ist.")
        self.reconnect = QCheckBox("Danach USB verbinden")
        self.reconnect.setChecked(True)
        options.addWidget(self.upload_speed)
        options.addWidget(self.manual_boot)
        options.addWidget(self.reconnect)
        options.addStretch()
        layout.addLayout(options)
        actions = QHBoxLayout()
        self.build_button = button("1  Firmware bauen", lambda: self.start_firmware("build"))
        self.verify_button = button("2  Image prüfen", lambda: self.start_firmware("verify"))
        self.flash_button = button("3  Auf Panel flashen", lambda: self.start_firmware("flash"), True)
        self.artifact_button = button("Datei aktualisieren", self.refresh_artifact)
        for item in (self.build_button, self.verify_button, self.flash_button, self.artifact_button):
            actions.addWidget(item)
        actions.addStretch()
        layout.addLayout(actions)
        self.firmware_phase = label("Bereit. Flashen verwendet das vorhandene Image ohne erneuten Build.", "note", True)
        layout.addWidget(self.firmware_phase)
        self.firmware_progress = QProgressBar()
        self.firmware_progress.setRange(0, 100)
        self.firmware_progress.setValue(0)
        layout.addWidget(self.firmware_progress)
        self.firmware_log = QPlainTextEdit()
        self.firmware_log.setReadOnly(True)
        self.firmware_log.setProperty("code", True)
        self.firmware_log.document().setMaximumBlockCount(5000)
        layout.addWidget(self.firmware_log, 1)
        layout.addWidget(label("Der Flasher prüft Image und Zielport. Falls er dazu auffordert, den großen Reset-Knopf einmal drücken. "
                               "Während der Übertragung USB angeschlossen lassen. Der Zertifikatsspeicher wird nicht beschrieben.", "muted", True))
        return page

    def select_page(self, index):
        self.pages.setCurrentIndex(index)
        self.heading.setText(PAGE_INFO[index][0])
        self.subtitle.setText(PAGE_INFO[index][1])
        for position, item in enumerate(self.nav_buttons):
            item.setChecked(position == index)

    def selected_port(self) -> str:
        text = self.ports.currentText().strip()
        return text.split("  ·  ", 1)[0].strip()

    def scan_ports(self):
        current = self.selected_port() or self.preferences.value("port", "", type=str)
        self.ports.clear()
        try:
            ports = available_ports()
        except OSError as error:
            self.show_problem(str(error))
            ports = []
        for port, description, likely_panel in ports:
            self.ports.addItem(description + ("  [Panel-Kandidat]" if likely_panel else ""), port)
        chosen = self.ports.findData(current)
        if chosen >= 0:
            self.ports.setCurrentIndex(chosen)
        elif current:
            self.ports.setEditText(current)
        elif not ports:
            self.ports.setEditText("COM10" if os.name == "nt" else "")
        if hasattr(self, "flash_button"):
            self.update_controls()

    def discard_edits(self, action: str) -> bool:
        if not self.config.dirty:
            return True
        return QMessageBox.question(self, "Ungespeicherte Änderungen", f"{action}\n\nUngespeicherte Änderungen verwerfen?",
                                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def toggle_connection(self):
        if self.controller.worker is not None:
            if self.controller.pending and not self.confirm("Befehl läuft", "Die Antwort steht noch aus. Trotzdem die USB-Verbindung schließen?"):
                return
            self.controller.disconnect_port()
            return
        if not self.discard_edits("Eine neue USB-Verbindung öffnen."):
            return
        port = self.selected_port()
        if not port:
            self.show_problem("Bitte einen seriellen Port auswählen.")
            return
        self.dashboard.clear()
        self.config.clear()
        self.controller.connect_port(port)

    def connection_changed(self, state, message):
        self.status_label.setText(message)
        self.update_controls()

    def update_controls(self):
        busy_job = self.firmware_job.active
        connected = self.controller.worker is not None
        ready = self.controller.state == "ready" and not busy_job and not self.demo
        can_query = self.controller.connected and self.controller.pending is None and not self.controller.wifi_wait and not busy_job and not self.demo
        self.ports.setEnabled(not connected and not busy_job and not self.demo)
        self.scan_button.setEnabled(not connected and not busy_job and not self.demo)
        self.connect_button.setEnabled(not busy_job and not self.demo)
        self.connect_button.setText("Trennen" if connected else "Verbinden")
        self.live.setEnabled(not self.demo)
        self.dashboard.refresh_button.setEnabled(can_query)
        self.dashboard.export_button.setEnabled(bool(self.dashboard.snapshot))
        self.config.reload_button.setEnabled(can_query)
        self.config.save_button.setEnabled(ready and self.config.dirty)
        self.config.form_content.setEnabled(self.controller.pending != "CONFIG SET" and not busy_job)
        self.config.import_button.setEnabled(bool(self.config.baseline) and not busy_job)
        self.config.export_button.setEnabled(bool(self.config.baseline))
        self.command_button.setEnabled(can_query)
        for item in (self.wifi_button, self.run_button, self.reboot_button):
            item.setEnabled(ready)
        can_build = not busy_job and not self.demo
        self.build_button.setEnabled(can_build)
        artifact_exists = (PROJECT_ROOT / ".pio/build/epd13/firmware.bin").is_file()
        self.verify_button.setEnabled(can_build and artifact_exists)
        is_wrong_panel = self.dashboard.snapshot.get("display", {}).get("physicalWidth") == 800
        self.flash_button.setEnabled(can_build and artifact_exists and bool(self.selected_port()) and not is_wrong_panel)
        self.flash_button.setToolTip("Dieser Firmwareablauf ist ausschließlich für epd13." if is_wrong_panel else "Prüft und überträgt das vorhandene Projekt-Image mit esptool.")
        for item in (self.upload_speed, self.manual_boot, self.reconnect, self.artifact_button):
            item.setEnabled(not busy_job)

    def send(self, command: str):
        if self.demo or self.firmware_job.active:
            return
        if not self.controller.request(command):
            self.show_problem("USB ist noch nicht bereit oder ein anderer Befehl läuft.")

    def send_selected(self):
        command = self.command.currentText()
        if command in {"RUN", "REBOOT", "B"}:
            self.confirm_command(command)
        elif command == "CONFIG GET":
            self.reload_config()
        else:
            self.send(command)

    def confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def confirm_command(self, command: str):
        descriptions = {
            "RUN": "Gespeicherte Einstellungen verwenden, das Bild aktualisieren und anschließend schlafen?",
            "REBOOT": "Das Panel jetzt neu starten?",
            "B": "Das Panel in den ROM-Bootloader versetzen? Zum Start der Firmware ist anschließend ggf. Reset nötig.",
        }
        if self.config.dirty:
            self.show_problem("Zuerst die Formularänderungen speichern oder über „Neu auslesen“ verwerfen.")
            self.select_page(1)
            return
        if self.confirm(command, descriptions[command]):
            self.send(command)

    def poll_diagnostics(self):
        if self.live.isChecked() and self.controller.state == "ready" and not self.firmware_job.active and not self.demo and QApplication.activeModalWidget() is None:
            self.send("DIAG")

    def handle_reply(self, reply: dict):
        command = reply.get("command")
        if command == "DIAG":
            self.dashboard.display_snapshot(reply)
        if command in {"DIAG", "CONFIG GET", "CONFIG SET"} and isinstance(reply.get("config"), dict):
            self.config.set_config(reply["config"], force=(self.force_reload and command == "CONFIG GET") or command == "CONFIG SET")
            if command == "CONFIG GET":
                self.force_reload = False
        if command == "CONFIG SET":
            self.status_label.setText("Einstellungen gespeichert. „WLAN verbinden“ prüft die Verbindung; „Bild aktualisieren“ wendet die Anzeige an.")
        if command == "HELP":
            self.select_page(3)
            self.log.category.setCurrentText("Alle")
            self.log.append("SYSTEM", str(reply.get("commands", "Befehlsliste empfangen.")))
        self.update_controls()

    def show_problem(self, message: str):
        if hasattr(self, "status_label"):
            self.status_label.setText(message)
        if hasattr(self, "log"):
            self.log.append("SYSTEM", message)

    def reload_config(self):
        if not self.discard_edits("Einstellungen erneut vom Panel auslesen."):
            return
        self.force_reload = True
        self.send("CONFIG GET")

    def save_config(self):
        try:
            patch = self.config.patch()
            validate_config(patch, require_confirmation=False)
        except ValueError as error:
            self.show_problem(str(error))
            return
        review = []
        for key, value in patch.items():
            text = ("ersetzen" if value else "löschen") if key in PASSWORD_KEYS else str(value)
            review.append(f"{LABELS.get(key, key)}: {text}")
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Änderungen speichern")
        dialog.setText("Diese Einstellungen dauerhaft auf dem Panel speichern?")
        dialog.setInformativeText("\n".join(review))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if patch.get("chargerMode"):
            confirmation = QCheckBox("Ich bestätige: Es sind geeignete wiederaufladbare Akkus eingelegt.")
            dialog.setCheckBox(confirmation)
            dialog.button(QMessageBox.StandardButton.Save).setEnabled(False)
            confirmation.toggled.connect(dialog.button(QMessageBox.StandardButton.Save).setEnabled)
        if dialog.exec() != QMessageBox.StandardButton.Save:
            return
        if patch.get("chargerMode"):
            patch["confirmRechargeable"] = True
        try:
            self.send(make_config_command(patch))
        except ValueError as error:
            self.show_problem(str(error))

    def save_json(self, title, filename, values):
        path, _ = QFileDialog.getSaveFileName(self, title, filename, "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except OSError as error:
                self.show_problem(str(error))

    def export_diagnostics(self):
        self.save_json("Diagnose exportieren", "panel-diagnose.json", self.dashboard.snapshot)

    def export_settings(self):
        self.save_json("Einstellungen ohne Passwörter exportieren", "panel-konfiguration.json", self.config.public_values())

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Konfiguration importieren", "", "JSON (*.json)")
        if not path:
            return
        try:
            if Path(path).stat().st_size > 65536:
                raise ValueError("Die Konfigurationsdatei ist zu groß (maximal 64 KiB).")
            values = import_config(Path(path).read_text(encoding="utf-8-sig"))
            self.config.import_values(values)
            self.status_label.setText("Import als Formularänderung übernommen. Zum Übertragen „Änderungen speichern“ wählen.")
        except (OSError, ValueError, UnicodeError) as error:
            self.show_problem(str(error))

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Log exportieren", "panel-studio.log", "Log (*.log);;Text (*.txt)")
        if path:
            try:
                Path(path).write_text(self.log.export_text(), encoding="utf-8")
            except OSError as error:
                self.show_problem(str(error))

    def refresh_artifact(self):
        try:
            info = image_summary()
        except OSError as error:
            info = {"error": str(error), "path": str(PROJECT_ROOT)}
        self.artifact = info
        if "error" in info:
            self.image_label.setText(f"{info['error']}\n{info['path']}")
        else:
            self.image_label.setText(f"{info['path']}\n{info['size']:,} Bytes · "
                                     f"{(APP_CAPACITY - info['size']) / 1024:.1f} KiB frei · "
                                     f"Stand {datetime.fromtimestamp(info['modified']):%d.%m.%Y %H:%M:%S}")
        self.image_hash.setText(info.get("sha256", ""))
        percent = info.get("percent", 0)
        self.image_usage.setValue(round(percent))
        self.image_usage.setFormat(f"{percent:.1f} % der App-Partition")
        if hasattr(self, "wifi_button"):
            self.update_controls()

    def start_firmware(self, action: str):
        if self.demo or self.firmware_job.active:
            return
        port = self.selected_port()
        if action == "flash":
            self.refresh_artifact()
            if "error" in self.artifact:
                self.show_problem(self.artifact["error"])
                return
            if self.dashboard.snapshot.get("display", {}).get("physicalWidth") == 800:
                self.show_problem("Das gewählte Image ist für epd13, das verbundene Panel meldet epd7.")
                return
            if self.config.dirty or self.controller.pending or self.controller.wifi_wait:
                self.show_problem("Vor dem Flashen offene Befehle abschließen und Formularänderungen speichern oder verwerfen.")
                return
            if not self.confirm("Firmware auf Panel flashen", f"Ziel: {port} · 13,3-Zoll-Panel (epd13)\n"
                                f"Image: {self.artifact['path']}\nSHA-256: {self.artifact['sha256']}\n\n"
                                "Das vorhandene Image wird geprüft und übertragen. Ist dies das gewünschte Zielgerät?"):
                return
            self.flash_port = port
            if not self.controller.disconnect_port():
                return
        self.firmware_log.clear()
        self.select_page(2)
        try:
            self.firmware_job.start(action, port, self.upload_speed.currentData(), self.manual_boot.isChecked(),
                                    expected_sha256=self.artifact["sha256"] if action == "flash" else "")
        except ValueError as error:
            self.show_problem(str(error))
        self.update_controls()

    def firmware_output(self, text: str):
        self.firmware_log.appendPlainText(text)
        self.log.append("BUILD", text)

    def update_progress(self, value: int):
        self.firmware_progress.setRange(0, 0 if value < 0 else 100)
        if value >= 0:
            self.firmware_progress.setValue(value)

    def firmware_finished(self, action: str, exit_code: int):
        if exit_code == 0:
            message = {"build": "Firmware gebaut und geprüft.", "verify": "Imageprüfung erfolgreich.",
                       "flash": "Übertragung erfolgreich. Falls nötig einmal Reset drücken, um die Firmware zu starten."}[action]
        else:
            message = f"Vorgang fehlgeschlagen (Exitcode {exit_code}). Details und Hinweise stehen im Log."
        self.firmware_phase.setText(message)
        self.status_label.setText(message)
        self.refresh_artifact()
        if action == "flash" and exit_code == 0 and self.reconnect.isChecked():
            self.dashboard.clear()
            self.config.clear()
            self.controller.connect_port(self.flash_port)
        self.update_controls()

    def closeEvent(self, event: QCloseEvent):
        if self.firmware_job.active:
            QMessageBox.information(self, "Firmware-Vorgang läuft", "Bitte den Build oder die Übertragung abschließen lassen. "
                                     "Das Fenster bleibt bedienbar; der laufende Prozess wird beim Schließen nicht unterbrochen.")
            event.ignore()
            return
        if not self.discard_edits("Panel Studio schließen."):
            event.ignore()
            return
        if self.controller.pending and not self.confirm("Befehl läuft", "Die Antwort steht noch aus. Trotzdem schließen?"):
            event.ignore()
            return
        if not self.controller.disconnect_port():
            event.ignore()
            return
        if not self.demo:
            self.preferences.setValue("port", self.selected_port())
            self.preferences.setValue("live", self.live.isChecked())
            self.preferences.setValue("uploadBaud", self.upload_speed.currentData())
        event.accept()

    def load_demo(self):
        from .sample import SAMPLE_DIAGNOSTICS
        self.dashboard.display_snapshot(SAMPLE_DIAGNOSTICS)
        self.config.set_config(SAMPLE_DIAGNOSTICS["config"])
        self.status_label.setText("VORSCHAU · Beispieldaten · Kein Gerät verbunden · Übertragung deaktiviert")
        self.log.append("SYSTEM", "Vorschaumodus: keine serielle Verbindung und kein Flashen.")
        self.log.append("RX", "[USB] Ready: HELP, DIAG, CONFIG GET, CONFIG SET {JSON}, WIFI CONNECT, RUN, REBOOT")


def create_application() -> QApplication:
    application = QApplication.instance() or QApplication([])
    # Qt's offscreen backend on Windows does not enumerate the system font database.
    if application.platformName() == "offscreen" and os.name == "nt":
        font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
            QFontDatabase.addApplicationFont(str(font_directory / name))
    application.setApplicationName("Panel Studio")
    application.setOrganizationName("eYellowBoard")
    # The stylesheet uses dark text. Give unstyled controls and dialogs the same
    # light palette instead of inheriting dark Windows backgrounds or accents.
    application.styleHints().setColorScheme(Qt.ColorScheme.Light)
    application.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f4f6f7",
        QPalette.ColorRole.WindowText: "#223138",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f6f9fa",
        QPalette.ColorRole.Text: "#223138",
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#223138",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: "#d9e9ed",
        QPalette.ColorRole.HighlightedText: "#223138",
        QPalette.ColorRole.Accent: "#3c8995",
        QPalette.ColorRole.ToolTipBase: "#19282e",
        QPalette.ColorRole.ToolTipText: "#ffffff",
        QPalette.ColorRole.Link: "#256573",
        QPalette.ColorRole.LinkVisited: "#5c527d",
        QPalette.ColorRole.PlaceholderText: "#647983",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#edf2f4",
        QPalette.ColorRole.Mid: "#cad6dc",
        QPalette.ColorRole.Dark: "#84969f",
        QPalette.ColorRole.Shadow: "#526b75",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#70858e"))
    application.setPalette(palette)
    assets = Path(__file__).resolve().parent / "assets"
    application.setStyleSheet(STYLE.replace("__DOWN_ARROW__", (assets / "down.svg").as_posix())
                              .replace("__UP_ARROW__", (assets / "up.svg").as_posix()))
    application.setFont(QFont("Segoe UI", 10))
    return application
