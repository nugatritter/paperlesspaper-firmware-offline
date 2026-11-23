"""Presentation widgets; hardware and subprocess ownership stay in controllers."""
from __future__ import annotations

from collections import deque
from datetime import datetime
import json
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .protocol import LABELS, PASSWORD_KEYS, STRING_LIMITS, export_config, validate_config, reset_description, render_description


def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if role:
        widget.setProperty("role", role)
    return widget


def button(text: str, callback=None, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        widget.setProperty("primary", True)
    if callback is not None:
        widget.clicked.connect(lambda checked=False: callback())
    return widget


class MetricCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.addWidget(label(title, "caption"))
        self.value = label("—", "metric")
        self.detail = label("Noch keine Messung", "muted", True)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def update_value(self, value: str, detail: str) -> None:
        self.value.setText(value)
        self.detail.setText(detail)


class PowerCard(MetricCard):
    def __init__(self):
        super().__init__("VERSORGUNG")
        self.history = deque(maxlen=3)
        self.history_label = label("", "muted", True)
        self.layout().addWidget(self.history_label)
        self.reset()

    def reset(self):
        self.history.clear()
        self.history_label.clear()
        self.awaiting_boot_voltage = False
        self.pause_requested = False
        self.charge_status = ""
        self.source = ""
        self.received_at = ""
        self.update_value("—", "Noch keine Messung")

    def show_details(self):
        details = [self.source, self.charge_status, self.received_at]
        self.detail.setText("\n".join(filter(None, details)))

    def set_voltage(self, millivolts, received_at):
        voltage = f"{millivolts / 1000:.3f} V".replace(".", ",")
        self.value.setText(voltage)
        self.received_at = f"Spannung empfangen um {received_at}"
        return voltage

    def observe_line(self, kind, line):
        if kind != "RX":
            return
        if "ESP-ROM:" in line or line.startswith("[MAIN] test mode check"):
            self.awaiting_boot_voltage = True
            self.pause_requested = False
            self.charge_status = ""
            self.source = ""
        elif line == "[POWER] Pausing charging for the display update.":
            self.pause_requested = True
            return
        elif line.startswith("[CHARGE]"):
            states = {
                "[CHARGE] on - Charger ON": "Akkus werden geladen",
                "[CHARGE] on - Charger DONE": "Laden freigegeben · kein aktiver Ladevorgang",
                "[CHARGE] off - Charge OFF": "Laden für Bildaufbau pausiert" if self.pause_requested else "Ladefunktion aus",
            }
            if line not in states:
                return
            self.charge_status = states[line]
            self.pause_requested = False
        else:
            sample = re.fullmatch(r"\[BAT\] ADC Raw: [\d.]+ -> VDD: (\d{1,5}) mV", line)
            render = re.match(r"\[(?:IMAGE|EPD)\] Render (?:begin|waiting): .*?\bbattery=(\d{1,5}) mV\b", line)
            if not (sample or render):
                return
            received_at = datetime.now().strftime("%H:%M:%S")
            voltage = self.set_voltage(int((sample or render).group(1)), received_at)
            if sample and self.awaiting_boot_voltage:
                self.history.append(f"{received_at}  {voltage}")
                self.history_label.setText("Beim Aufwachen\n" + "\n".join(self.history))
            self.awaiting_boot_voltage = False
        self.show_details()

    def observe_diagnostics(self, system, config):
        voltage = system.get("batteryMillivolts")
        if isinstance(voltage, (int, float)):
            self.set_voltage(voltage, datetime.now().strftime("%H:%M:%S"))
        if isinstance(system.get("usbConnected"), bool):
            self.source = "USB verbunden" if system["usbConnected"] else "Batteriebetrieb"
        if system.get("charging") is True:
            self.charge_status = "Akkus werden geladen"
        elif config.get("chargerMode") is False:
            self.charge_status = "Ladefunktion aus"
        elif system.get("charging") is False:
            self.charge_status = "Kein aktiver Ladevorgang"
        self.show_details()


class Dashboard(QWidget):
    refresh_requested = Signal()
    export_requested = Signal()

    def __init__(self):
        super().__init__()
        self.snapshot = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        self.sample_label = label("Für aktuelle Messwerte „Jetzt abfragen“ wählen.", "muted", True)
        actions.addWidget(self.sample_label, 1)
        self.refresh_button = button("Jetzt abfragen", self.refresh_requested.emit, True)
        self.export_button = button("JSON exportieren", self.export_requested.emit)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        layout.addWidget(label("„Jetzt abfragen“ öffnet die USB-Diagnosesitzung und verzögert den nächsten automatischen Bildabruf.", "muted", True))
        cards = QGridLayout()
        self.power_card = PowerCard()
        self.cards = {
            "device": MetricCard("GERÄT"), "battery": self.power_card,
            "wifi": MetricCard("WLAN"), "memory": MetricCard("FREIER HEAP"),
        }
        for column, card in enumerate(self.cards.values()):
            cards.addWidget(card, 0, column)
            cards.setColumnStretch(column, 1)
        layout.addLayout(cards)
        self.reset_label = label("Noch kein Reset-Grund abgefragt.", "note", True)
        self.render_label = label("Noch kein Renderstatus abgefragt.", "note", True)
        layout.addWidget(self.reset_label)
        layout.addWidget(self.render_label)
        self.update_label = label("Die Diagnose zeigt Firmwarezustände. Sichtbare Pixel werden nicht zurückgelesen.", "note", True)
        layout.addWidget(self.update_label)
        tabs = QTabWidget()
        details = QWidget()
        details_layout = QVBoxLayout(details)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Diagnose durchsuchen … z. B. heap, rotation, http")
        self.search.textChanged.connect(self.filter_tree)
        details_layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Eigenschaft", "Wert"])
        self.tree.setColumnWidth(0, 330)
        self.tree.setAlternatingRowColors(True)
        details_layout.addWidget(self.tree)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setProperty("code", True)
        tabs.addTab(details, "Alle Diagnosewerte")
        tabs.addTab(self.raw, "JSON")
        layout.addWidget(tabs, 1)

    def clear(self) -> None:
        self.snapshot = {}
        self.tree.clear()
        self.raw.clear()
        self.sample_label.setText("Noch keine Diagnose für diese Verbindung.")
        self.reset_label.setText("Noch kein Reset-Grund abgefragt.")
        self.render_label.setText("Noch kein Renderstatus abgefragt.")
        self.update_label.setText("Noch kein erhaltener Bildzyklus.")
        self.power_card.reset()
        for card in self.cards.values():
            card.update_value("—", "Noch keine Messung")

    def display_snapshot(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        firmware = snapshot.get("firmware", {})
        system = snapshot.get("system", {})
        network = snapshot.get("network", {})
        display = snapshot.get("display", {})
        self.reset_label.setText("Letzter Neustart: " + reset_description(system))
        self.render_label.setText(render_description(snapshot))
        width, height = display.get("physicalWidth", "?"), display.get("physicalHeight", "?")
        self.cards["device"].update_value("13,3″" if width == 1600 else ("7″" if width == 800 else "Panel"),
                                          f"{width} × {height} · Firmware {firmware.get('version', '—')}")
        self.power_card.observe_diagnostics(system, snapshot.get("config", {}))
        self.cards["wifi"].update_value(f"{network.get('rssiDbm', '—')} dBm" if network.get("connected") else "Offline",
                                        str(network.get("ip", "Keine WLAN-Verbindung")))
        free_heap = system.get("freeHeapBytes")
        self.cards["memory"].update_value(f"{free_heap / 1024:.1f} KiB" if isinstance(free_heap, (int, float)) else "—",
                                          f"Minimum: {system.get('minimumFreeHeapBytes', '—')} Bytes")
        self.sample_label.setText(f"{firmware.get('deviceId', 'Panel')}  ·  Abgefragt um {datetime.now():%H:%M:%S}")
        update = snapshot.get("lastCompletedUpdate", {})
        if update.get("valid"):
            self.update_label.setText(f"Letzter erhaltener Bildzyklus: HTTP {update.get('httpStatus', '—')} · "
                                      f"Download {update.get('downloadMs', '—')} ms · Rendering {update.get('renderMs', '—')} ms · "
                                      f"Ergebnisse {update.get('downloadResult', '—')} / {update.get('renderResult', '—')}")
        else:
            self.update_label.setText("Noch kein erhaltener Bildzyklus. Speicherwerte unter storageAtBoot stammen vom Start.")
        self.raw.setPlainText(json.dumps(snapshot, ensure_ascii=False, indent=2))
        self.tree.clear()

        def add(parent, key, value):
            item = QTreeWidgetItem(parent, [str(key), "" if isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)])
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    add(item, child_key, child_value)
            elif isinstance(value, list):
                for index, child_value in enumerate(value):
                    add(item, index, child_value)

        for key, value in snapshot.items():
            add(self.tree, key, value)
        self.tree.expandToDepth(0)
        self.filter_tree(self.search.text())

    def filter_tree(self, query: str) -> None:
        query = query.casefold()

        def visit(item, parent_matches=False):
            matches = parent_matches or not query or query in (item.text(0) + " " + item.text(1)).casefold()
            child_matches = [visit(item.child(index), matches) for index in range(item.childCount())]
            visible = matches or any(child_matches)
            item.setHidden(not visible)
            if query and any(child_matches):
                item.setExpanded(True)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))


class PasswordField(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        self.mode.addItems(["Beibehalten", "Ersetzen", "Löschen"])
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setEnabled(False)
        self.edit.setPlaceholderText("Nicht auslesbar")
        self.show = button("Zeigen")
        self.show.setCheckable(True)
        self.show.setMaximumWidth(65)
        self.show.toggled.connect(lambda checked: self.edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        row.addWidget(self.mode)
        row.addWidget(self.edit, 1)
        row.addWidget(self.show)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.edit.textChanged.connect(lambda text: self.changed.emit())

    def _mode_changed(self) -> None:
        self.edit.setEnabled(self.mode.currentIndex() == 1)
        self.changed.emit()

    def reset(self, is_set=False) -> None:
        self.mode.setCurrentIndex(0)
        self.edit.clear()
        self.show.setChecked(False)
        self.edit.setPlaceholderText("Gespeichert" if is_set else "Nicht gesetzt")

    def patch_value(self) -> str | None:
        if self.mode.currentIndex() == 0:
            return None
        return self.edit.text() if self.mode.currentIndex() == 1 else ""


class ConfigEditor(QWidget):
    changed = Signal()
    save_requested = Signal()
    reload_requested = Signal()
    import_requested = Signal()
    export_requested = Signal()

    def __init__(self):
        super().__init__()
        self.baseline: dict = {}
        self.loading = False
        self.fields: dict[str, QWidget] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        self.message = label("Zuerst mit dem Panel verbinden und Einstellungen auslesen.", "muted", True)
        actions.addWidget(self.message, 1)
        self.reload_button = button("Neu auslesen", self.reload_requested.emit)
        self.import_button = button("Importieren", self.import_requested.emit)
        self.export_button = button("Exportieren", self.export_requested.emit)
        actions.addWidget(self.reload_button)
        actions.addWidget(self.import_button)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.form_content = content
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 8, 0, 8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        def group(title, keys, row, column):
            box = QGroupBox(title)
            form = QFormLayout(box)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            form.setVerticalSpacing(9)
            for key in keys:
                field = self._field(key)
                self.fields[key] = field
                form.addRow(LABELS[key], field)
            grid.addWidget(box, row, column)

        group("WLAN", ["wifiSsid", "wifiPassword"], 0, 0)
        group("Bild und Ausrichtung", ["imageMode", "timeout", "autoRotation", "manualOrientation"], 0, 1)
        group("Bildserver", ["downloadUrl", "httpAuthUser", "httpAuthPassword", "settingsUrl"], 1, 0)
        group("Verhalten und Energie", ["motionWakeup", "showBatteryWarning", "showWifiWarning", "requireImageDigest", "chargerMode"], 1, 1)
        grid.setRowStretch(2, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        footer = QHBoxLayout()
        footer.addWidget(label("Speichern übernimmt die Werte dauerhaft. „Bild aktualisieren“ startet den Bildablauf; „Forced refresh image“ rendert das gespeicherte Bild ohne Serverabruf.", "muted", True), 1)
        self.save_button = button("Änderungen speichern", self.save_requested.emit, True)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)
        self.fields["autoRotation"].toggled.connect(self._rotation_changed)
        self.fields["downloadUrl"].textEdited.connect(self._url_edited)
        self._rotation_changed()

    def _field(self, key):
        if key in PASSWORD_KEYS:
            field = PasswordField()
            field.changed.connect(self._changed)
        elif key in STRING_LIMITS:
            field = QLineEdit()
            field.setToolTip(f"Maximal {STRING_LIMITS[key]} UTF-8-Bytes; leer löscht den Wert.")
            if key.endswith("Url"):
                field.setPlaceholderText("https://…" if key == "downloadUrl" else "Optional · leer deaktiviert Fernkonfiguration")
            field.textChanged.connect(self._changed)
        elif key == "timeout":
            field = QSpinBox()
            field.setRange(60, 2592000)
            field.setValue(3600)
            field.setSuffix(" Sekunden")
            field.valueChanged.connect(self._changed)
            field.setToolTip("60 Sekunden bis 30 Tage. 900 = 15 Minuten; 3600 = 1 Stunde.")
        elif key in {"imageMode", "manualOrientation"}:
            field = QComboBox()
            if key == "imageMode":
                field.addItem("Gespeichertes BLE-Bild", 0)
                field.addItem("Bild von URL herunterladen", 1)
            else:
                field.addItem("Standard-Landschaftslage", 0)
                field.addItem("Gegenüberliegende Landschaftslage (180°)", 1)
            field.currentIndexChanged.connect(self._changed)
        else:
            field = QCheckBox("Aktiviert")
            field.toggled.connect(self._changed)
            if key == "chargerMode":
                field.setText("Nur für wiederaufladbare Akkus")
            if key == "requireImageDigest":
                field.setToolTip("Der Bildserver muss den von der Firmware erwarteten Integritätsnachweis liefern.")
        return field

    def _changed(self) -> None:
        if not self.loading:
            self.message.setText("Ungespeicherte Änderungen" if self.dirty else "Einstellungen entsprechen dem zuletzt gelesenen Stand.")
            self.changed.emit()

    def _rotation_changed(self) -> None:
        self.fields["manualOrientation"].setEnabled(not self.fields["autoRotation"].isChecked())

    def _url_edited(self, text) -> None:
        if text:
            self.fields["imageMode"].setCurrentIndex(1)

    def values(self) -> dict:
        result = {}
        for key, field in self.fields.items():
            if isinstance(field, PasswordField):
                value = field.patch_value()
                if value is not None:
                    result[key] = value
            elif isinstance(field, QCheckBox):
                result[key] = field.isChecked()
            elif isinstance(field, QComboBox):
                result[key] = field.currentData()
            elif isinstance(field, QSpinBox):
                result[key] = field.value()
            else:
                result[key] = field.text()
        return result

    def patch(self) -> dict:
        values = self.values()
        patch = {key: value for key, value in values.items() if key in PASSWORD_KEYS or value != self.baseline.get(key)}
        if "downloadUrl" in patch and patch["downloadUrl"]:
            patch["imageMode"] = values["imageMode"]
        return patch

    @property
    def dirty(self) -> bool:
        return bool(self.baseline) and bool(self.patch())

    def clear(self) -> None:
        self.baseline = {}
        self.loading = True
        for field in self.fields.values():
            if isinstance(field, PasswordField):
                field.reset()
            elif isinstance(field, QLineEdit):
                field.clear()
            elif isinstance(field, QCheckBox):
                field.setChecked(False)
            elif isinstance(field, QComboBox):
                field.setCurrentIndex(0)
            elif isinstance(field, QSpinBox):
                field.setValue(3600)
        self.loading = False
        self.message.setText("Noch keine Einstellungen für diese Verbindung geladen.")
        self.changed.emit()

    def set_config(self, values: dict, force=False) -> bool:
        if self.dirty and not force:
            return False
        self.loading = True
        self.baseline = dict(values)
        self._set_values(values)
        for key in PASSWORD_KEYS:
            self.fields[key].reset(bool(values.get(key + "Set")))
        self.loading = False
        self.message.setText("Einstellungen geladen. Passwörter bleiben beim Speichern unverändert, solange nicht anders gewählt.")
        self.changed.emit()
        return True

    def _set_values(self, values: dict) -> None:
        for key, value in values.items():
            field = self.fields.get(key)
            if isinstance(field, PasswordField):
                field.mode.setCurrentIndex(1 if value else 2)
                field.edit.setText(value)
            elif isinstance(field, QCheckBox):
                field.setChecked(bool(value))
            elif isinstance(field, QComboBox):
                field.setCurrentIndex(field.findData(value))
            elif isinstance(field, QSpinBox):
                field.setValue(value)
            elif isinstance(field, QLineEdit):
                field.setText(value)
        self._rotation_changed()

    def import_values(self, values: dict) -> None:
        if not self.baseline:
            raise ValueError("Vor einem Import zuerst die Einstellungen des Zielpanels auslesen.")
        validate_config(values, require_confirmation=False)
        self.loading = True
        self._set_values(values)
        if values.get("downloadUrl") and "imageMode" not in values:
            self.fields["imageMode"].setCurrentIndex(1)
        self.loading = False
        self._changed()

    def public_values(self) -> dict:
        return export_config(self.values())


class LogViewer(QWidget):
    export_requested = Signal()

    def __init__(self):
        super().__init__()
        self.entries: deque[tuple[str, str]] = deque(maxlen=5000)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItems(["Alle", "RX", "TX", "JSON", "SYSTEM", "BUILD"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Log filtern …")
        self.follow = QCheckBox("Zum Ende scrollen")
        self.follow.setChecked(True)
        tools.addWidget(self.category)
        tools.addWidget(self.search, 1)
        tools.addWidget(self.follow)
        tools.addWidget(button("Exportieren", self.export_requested.emit))
        tools.addWidget(button("Leeren", self.clear))
        layout.addLayout(tools)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setProperty("code", True)
        self.text.document().setMaximumBlockCount(5000)
        layout.addWidget(self.text, 1)
        self.category.currentTextChanged.connect(self.rebuild)
        self.search.textChanged.connect(self.rebuild)

    def matches(self, category, text) -> bool:
        return (self.category.currentText() in ("Alle", category) and self.search.text().casefold() in text.casefold())

    def append(self, category: str, message: str) -> None:
        text = f"{datetime.now():%H:%M:%S}  {category:6}  {message}"
        self.entries.append((category, text))
        if self.matches(category, text):
            scrollbar = self.text.verticalScrollBar()
            previous = scrollbar.value()
            self.text.appendPlainText(text)
            scrollbar.setValue(scrollbar.maximum() if self.follow.isChecked() else previous)

    def rebuild(self) -> None:
        self.text.setPlainText("\n".join(text for category, text in self.entries if self.matches(category, text)))

    def clear(self) -> None:
        self.entries.clear()
        self.text.clear()

    def export_text(self) -> str:
        return "\n".join(text for _, text in self.entries) + "\n"
