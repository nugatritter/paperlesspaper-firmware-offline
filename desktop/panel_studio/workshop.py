"""Workshop inventory, USB reservations and on-site proof confirmation."""
from __future__ import annotations

import base64
import csv
import json
import re
import time
from urllib.parse import urlsplit

from .protocol import make_config_command
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget)


class Workshop(QWidget):
    def __init__(self, controller, demo=False):
        super().__init__()
        self.controller = controller
        self.demo = demo
        self.network = QNetworkAccessManager(self)
        self.preview_token = ""
        self.waiting_for_usb = None
        self.inflight = None
        self.pending_credentials = None
        self.saving_credentials = False
        self.after_clock = None
        layout = QVBoxLayout(self)
        self.form = QWidget()
        form = QFormLayout(self.form)
        self.server = QLineEdit()
        self.server.setPlaceholderText("https://dienst.institut.de/panel-management")
        self.user = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.orders = QComboBox()
        self.label_id = QLineEdit()
        self.location = QLineEdit()
        self.proof = QLineEdit()
        self.proof.setMaxLength(6)
        for title, field in (("Verwaltungsdienst", self.server), ("Werkstattkonto", self.user),
                             ("Passwort", self.password), ("Auftrag", self.orders),
                             ("Panel-ID vom QR-Etikett", self.label_id), ("Montageort vor Ort", self.location),
                             ("Code vom Prüfschild", self.proof)):
            form.addRow(title, field)
        layout.addWidget(self.form)
        for actions in [(("Arbeitsliste öffnen", self.preview), ("Vorschau übernehmen", self.apply)),
                        (("USB-Gerät inventarisieren", lambda: self.read_usb("inventory")),
                         ("Gerät reservieren", lambda: self.read_usb("reserve"))),
                        (("Gerätekonto einrichten", lambda: self.read_usb("issue")),
                         ("Zweitschlüssel übertragen", lambda: self.read_usb("rotate"))),
                        (("Werkstattzeit über USB übertragen", lambda: self.set_clock()),),
                        (("Standort aktivieren", self.activate), ("Reservierung aufheben", self.cancel))]:
            row = QHBoxLayout()
            for title, action in actions:
                button = QPushButton(title, self.form)
                button.clicked.connect(action)
                row.addWidget(button)
            form.addRow(row)
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        layout.addStretch()
        for field in (self.server, self.user, self.password):
            field.textChanged.connect(self.reset_session)
        self.controller.reply_received.connect(self.usb_reply)
        self.controller.state_changed.connect(self.usb_state_changed)
        self.setEnabled(not demo)

    def reset_session(self):
        self.preview_token = ""
        self.orders.clear()
        self.pending_credentials = None
        self.network.deleteLater()
        self.network = QNetworkAccessManager(self)

    def post(self, action, payload, completed, *, access_panel=None):
        base = QUrl(self.server.text().strip())
        if (base.scheme() != "https" or not base.host() or base.userInfo() or base.hasQuery() or
                base.hasFragment() or not self.user.text() or ":" in self.user.text() or not self.password.text()):
            self.result.setText("HTTPS-Dienst, Werkstattkonto und Passwort eingeben.")
            return
        if self.demo or self.inflight is not None:
            return
        route = f"access/{access_panel}/{action}" if access_panel else "workshop/" + action
        base.setPath(base.path().rstrip("/") + "/api/admin/" + route)
        request = QNetworkRequest(base)
        request.setTransferTimeout(20000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        credentials = (self.user.text() + ":" + self.password.text()).encode()
        request.setRawHeader(b"Authorization", b"Basic " + base64.b64encode(credentials))
        request.setRawHeader(b"X-Panel-Admin", b"1")
        request.setRawHeader(b"Content-Type", b"application/json")
        reply = self.network.post(request, json.dumps(payload).encode())
        self.inflight = reply
        self.form.setEnabled(False)

        def finished():
            self.inflight = None
            self.form.setEnabled(True)
            try:
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if status != 200:
                    self.result.setText(f"Aufruf fehlgeschlagen (HTTP {status}). " + (
                        "Auftrag, Reservierung und Eingaben prüfen." if status == 409 else reply.errorString()))
                    return
                completed(json.loads(bytes(reply.readAll())))
            except (KeyError, ValueError, TypeError):
                self.result.setText("Die Antwort des Verwaltungsdienstes ist ungültig.")
            finally:
                reply.deleteLater()
        reply.finished.connect(finished)

    def preview(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Arbeitsliste", "", "Arbeitslisten (*.csv *.json)")
        if not filename:
            return
        try:
            path = Path(filename)
            if path.stat().st_size > 65536:
                raise ValueError("Die Arbeitsliste überschreitet 64 KiB.")
            with path.open(encoding="utf-8-sig", newline="") as stream:
                entries = list(csv.DictReader(stream)) if path.suffix.lower() == ".csv" else json.load(stream)["orders"]
            if not entries or any(set(item) != {"beamline", "location", "model"} for item in entries):
                raise ValueError("Erwartete Spalten: beamline, location, model.")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.result.setText(str(error))
            return
        self.orders.clear()
        self.preview_token = ""

        def display(data):
            self.preview_token = data["token"]
            for item in data["orders"]:
                order = item["order"]
                self.orders.addItem(f"{order['beamline']} · {order['location']} · {order['model']}", item)
            self.result.setText("\n".join(f"{item['order']['beamline']}: {item['state']}" +
                                          (f" · belegt mit {item['activePanel']}" if item.get("activePanel") else "")
                                          for item in data["orders"]))
        self.post("preview", {"orders": entries}, display)

    def apply(self):
        if not self.preview_token:
            self.result.setText("Zuerst die Arbeitsliste öffnen und die Vorschau prüfen.")
            return
        def applied(_):
            self.preview_token = ""
            self.result.setText("Arbeitsliste übernommen.")
        self.post("apply", {"token": self.preview_token}, applied)

    def panel_id(self):
        panel = self.label_id.text().strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", panel):
            return panel
        self.result.setText("Die öffentliche Panel-ID vom QR-Etikett einlesen.")
        return None

    def read_usb(self, action):
        panel = self.panel_id()
        order = self.orders.currentData()
        if not panel:
            return
        if action != "inventory" and not order:
            self.result.setText("Zuerst den Auftrag aus der Arbeitsliste auswählen.")
            return
        if self.controller.state != "ready" or not self.controller.request("DIAG"):
            self.result.setText("Panel über USB verbinden und auf die Gerätebereitschaft warten.")
            return
        self.waiting_for_usb = (action, panel, order)
        self.form.setEnabled(False)
        self.result.setText("Gerätekennung wird am Werkstattport ausgelesen.")

    def usb_state_changed(self, state, _message):
        if state not in {"disconnected", "opening", "waiting", "updating", "sleeping", "bootloader"}:
            return
        self.pending_credentials = None
        if self.after_clock is not None:
            self.after_clock = None
            self.form.setEnabled(True)
            self.result.setText("USB-Zeitabgleich unterbrochen. Werkstattzeit erneut übertragen.")
        if self.saving_credentials:
            self.saving_credentials = False
            self.form.setEnabled(True)
            self.result.setText("USB-Bestätigung fehlt. Vor erneutem Schlüsselwechsel den Gerätestand prüfen.")
        if self.waiting_for_usb:
            self.waiting_for_usb = None
            self.form.setEnabled(True)
            self.result.setText("USB-Lesung unterbrochen. Gerät erneut verbinden und Auftrag wieder öffnen.")

    def set_clock(self, resume=None):
        if self.controller.state != "ready" or not self.controller.request(f"CLOCK SET {int(time.time())}"):
            self.result.setText("Verwaltetes Panel über USB verbinden und auf Gerätebereitschaft warten.")
            return
        self.after_clock = resume or ()
        self.form.setEnabled(False)

    def usb_reply(self, data):
        if self.after_clock is not None and data.get("command") == "CLOCK SET":
            resume = self.after_clock
            self.after_clock = None
            self.form.setEnabled(True)
            self.result.setText("Gerätezeit mit der Werkstattuhr abgeglichen.")
            if resume and self.controller.request("DIAG"):
                self.waiting_for_usb = resume
                self.form.setEnabled(False)
            return
        if self.saving_credentials and data.get("command") == "CONFIG SET":
            self.saving_credentials = False
            self.form.setEnabled(True)
            self.result.setText("Gerätekonto und persönliche Dienst-URLs über USB gespeichert.")
        if not self.waiting_for_usb or data.get("command") != "DIAG":
            return
        action, panel, item = self.waiting_for_usb
        self.waiting_for_usb = None
        self.form.setEnabled(True)
        fw = data.get("firmware", {})
        display = data.get("display", {})
        model = {(1600, 1200): "epd13", (800, 480): "epd7"}.get((display.get("physicalWidth"), display.get("physicalHeight")))
        if not data.get("ok") or not model or not fw.get("deviceId") or not fw.get("version"):
            self.result.setText("Unvollständige Gerätekennung in der USB-Diagnose.")
            return
        payload = dict(panel=panel, hardware=fw["deviceId"], model=model)
        if action == "write_credentials":
            credentials = self.pending_credentials
            self.pending_credentials = None
            if not credentials or credentials[0] != fw["deviceId"] or credentials[1] != panel:
                self.result.setText("Das Gerät am USB-Port hat gewechselt. Zugang erneut vorbereiten.")
                return
            _, _, values = credentials
            try:
                command = make_config_command(values)
            except ValueError as error:
                self.result.setText(str(error))
                return
            self.saving_credentials = self.controller.request(command)
            self.form.setEnabled(not self.saving_credentials)
            if not self.saving_credentials:
                self.result.setText("USB-Schreiben konnte nicht gestartet werden.")
            return
        if action in {"issue", "rotate", "issue_after_clock", "rotate_after_clock"}:
            base = self.server.text().strip().rstrip("/")
            url = urlsplit(base)
            origin = f"{url.scheme}://{url.netloc}"
            if fw.get("managedOrigin") != origin or url.scheme != "https":
                self.result.setText("Die verwaltete Firmware muss dem HTTPS-Ursprung der Verwaltung vertrauen.")
                return
            if fw.get("clockTrusted") is False:
                if action.endswith("_after_clock"):
                    self.result.setText("Die USB-Diagnose bestätigt die Werkstattzeit noch nicht.")
                else:
                    self.set_clock((action + "_after_clock", panel, item))
                return
            action = action.removesuffix("_after_clock")
            values = dict(downloadUrl=base + "/api/panel/me/image", settingsUrl=base + "/api/panel/me/settings",
                          imageMode=1, requireImageDigest=True, httpAuthUser=panel)
            try:
                make_config_command(values)
            except ValueError as error:
                self.result.setText(str(error))
                return
            worker = self.controller.worker
            def issued(result):
                if self.controller.worker is not worker or self.controller.state != "ready" or result["username"] != panel:
                    self.result.setText("USB-Gerät gewechselt. Ausgabe prüfen und Zugang erneut vorbereiten.")
                    return
                values["httpAuthPassword"] = result["password"]
                self.pending_credentials = (fw["deviceId"], panel, values)
                if not self.controller.request("DIAG"):
                    self.pending_credentials = None
                    self.result.setText("USB-Diagnose zur Schlüsselübergabe fehlgeschlagen.")
                    return
                self.waiting_for_usb = ("write_credentials", panel, item)
                self.form.setEnabled(False)
            def reserved(_):
                if self.controller.worker is worker and self.controller.state == "ready":
                    self.post(action, {}, issued, access_panel=panel)
                else:
                    self.result.setText("USB-Verbindung prüfen und die Reservierung erneut öffnen.")
            self.post("reserve", dict(payload, beamline=item["order"]["beamline"],
                                      previousPanel=item.get("activePanel")), reserved)
            return
        if action == "inventory":
            payload["firmware"] = fw["version"]
        else:
            payload.update(beamline=item["order"]["beamline"], previousPanel=item.get("activePanel"))
        self.post(action, payload, lambda result: self.result.setText(
            f"{panel} mit USB-Kennung {fw['deviceId']} inventarisiert." if action == "inventory" else
            f"{panel} für {result['beamline']} am Standort {result['location']} reserviert."))

    def activate(self):
        panel, item = self.panel_id(), self.orders.currentData()
        if not panel or not item or not self.location.text().strip() or not re.fullmatch("[0-9]{6}", self.proof.text()):
            self.result.setText("Etikett scannen, Auftrag auswählen, Standort und sechsstelligen Prüfcode eingeben.")
            return
        if QMessageBox.question(self, "Standort aktivieren", f"{panel} am Standort {self.location.text()} für "
                                f"{item['order']['beamline']} aktivieren?") != QMessageBox.StandardButton.Yes:
            return
        self.post("activate", dict(panel=panel, beamline=item["order"]["beamline"], location=self.location.text().strip(),
                                   code=self.proof.text()), lambda _: self.result.setText(f"{panel} am Standort aktiviert."))
        self.proof.clear()

    def cancel(self):
        panel, item = self.panel_id(), self.orders.currentData()
        if panel and item and QMessageBox.question(self, "Reservierung aufheben",
                 f"Reservierung für {panel} und {item['order']['beamline']} aufheben?") == QMessageBox.StandardButton.Yes:
            self.post("cancel", dict(panel=panel, beamline=item["order"]["beamline"]),
                      lambda _: self.result.setText("Reservierung aufgehoben."))
