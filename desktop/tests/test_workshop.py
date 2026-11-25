import json
import unittest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from panel_studio.workshop import Workshop


class Console(QObject):
    reply_received = Signal(dict)
    state_changed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.state = "ready"
        self.worker = object()
        self.requests = []

    def request(self, command):
        self.requests.append(command)
        return True


class WorkshopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.console = Console()
        self.page = Workshop(self.console)
        self.addCleanup(self.page.close)
        self.page.server.setText("https://lab.example/app")
        self.page.label_id.setText("P-17")
        self.page.orders.addItem("BL-01", {"order":{"beamline":"BL-01","location":"A","model":"epd13"}})
        self.diagnosis = {"command":"DIAG","ok":True,
                          "firmware":{"deviceId":"epd13-test","version":"test","managedOrigin":"https://lab.example"},
                          "display":{"physicalWidth":1600,"physicalHeight":1200}}
        self.calls = []

        def post(action, data, finished, **options):
            self.calls.append((action, data, options))
            if action == "reserve":
                finished({"panel":"P-17","beamline":"BL-01","location":"A"})
            else:
                finished({"username":"P-17","password":"test-device-value"})
        self.page.post = post

    def test_scanned_identity_and_fresh_usb_diagnosis_before_secret_transfer(self):
        self.page.read_usb("issue")
        self.console.reply_received.emit(self.diagnosis)
        self.assertEqual([call[0] for call in self.calls], ["reserve", "issue"])
        self.assertEqual(self.calls[0][1]["hardware"], "epd13-test")
        self.assertEqual(self.console.requests, ["DIAG","DIAG"])
        self.console.reply_received.emit(self.diagnosis)
        values = json.loads(self.console.requests[-1].removeprefix("CONFIG SET "))
        self.assertEqual(values["httpAuthUser"], "P-17")
        self.assertTrue(values["requireImageDigest"])
        self.assertIsNone(self.page.pending_credentials)
        self.assertNotIn(values["httpAuthPassword"], self.page.result.text())
        self.console.reply_received.emit({"command":"CONFIG SET","saved":True})
        self.assertTrue(self.page.form.isEnabled())

    def test_cold_managed_panel_gets_workshop_time_before_credentials(self):
        fw = self.diagnosis["firmware"]
        self.page.read_usb("issue")
        self.console.reply_received.emit({**self.diagnosis, "firmware": {**fw, "clockTrusted": False}})
        self.assertRegex(self.console.requests[-1], r"^CLOCK SET [0-9]{10}$")
        self.assertFalse(self.calls)
        self.console.reply_received.emit({"command": "CLOCK SET", "ok": True})
        self.assertEqual(self.console.requests[-1], "DIAG")
        self.console.reply_received.emit({**self.diagnosis, "firmware": {**fw, "clockTrusted": True}})
        self.assertEqual([call[0] for call in self.calls], ["reserve", "issue"])

    def test_wrong_origin_and_replaced_hardware_stop_transfer(self):
        self.page.read_usb("issue")
        self.console.reply_received.emit({**self.diagnosis,"firmware":{**self.diagnosis["firmware"],"managedOrigin":"https://other.example"}})
        self.assertFalse(self.calls)
        self.page.read_usb("issue")
        self.console.reply_received.emit(self.diagnosis)
        self.console.reply_received.emit({**self.diagnosis,"firmware":{**self.diagnosis["firmware"],"deviceId":"other"}})
        self.assertTrue(all(command == "DIAG" for command in self.console.requests))
        self.assertIsNone(self.page.pending_credentials)
