"""Protocol, UI and transport regression tests. Never access physical serial ports."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, QSettings, Signal

from panel_studio.app import MainWindow, create_application
from panel_studio.firmware import APP_CAPACITY, FirmwareJob, build_arguments, image_summary
from panel_studio.protocol import LineDecoder, export_config, import_config, make_config_command, parse_reply, validate_config
from panel_studio.sample import SAMPLE_DIAGNOSTICS
from panel_studio.transport import ConsoleController, SerialWorker
from panel_studio.widgets import ConfigEditor, Dashboard

APPLICATION = create_application()


def wait_for(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APPLICATION.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for simulated event")


class FakeSerial:
    def __init__(self):
        self.dtr = True
        self.rts = True
        self.port = None
        self.is_open = False
        self.respond = True
        self.writes = []
        self.buffer = bytearray()
        self.lock = threading.Lock()
        self.config = deepcopy(SAMPLE_DIAGNOSTICS["config"])
        self.fail_read = False

    def open(self):
        assert not self.dtr and not self.rts
        self.is_open = True

    def close(self):
        self.is_open = False

    @property
    def in_waiting(self):
        if self.fail_read:
            raise OSError("Simulated cable removal")
        with self.lock:
            return len(self.buffer)

    def inject(self, line):
        with self.lock:
            self.buffer.extend((line + "\r\n").encode("utf-8"))

    def read(self, size):
        with self.lock:
            chunk = bytes(self.buffer[:min(size, 37)])
            del self.buffer[:len(chunk)]
        if not chunk:
            time.sleep(0.005)
        return chunk

    def write(self, data):
        self.writes.append(data)
        if not self.respond:
            return len(data)
        command = data.decode("utf-8").strip()
        if command == "B":
            self.inject("[SYSTEM] Rebooting into ROM Download Bootloader...")
            return len(data)
        name = "CONFIG SET" if command.startswith("CONFIG SET ") else command
        reply = {"protocol": 1, "command": name, "ok": True}
        if name == "CONFIG SET":
            values = json.loads(command[11:])
            validate_config(values)
            for key, value in values.items():
                if key in ("wifiPassword", "httpAuthPassword"):
                    self.config[key + "Set"] = bool(value)
                elif key != "confirmRechargeable":
                    self.config[key] = value
        if name in {"CONFIG GET", "CONFIG SET"}:
            reply["config"] = deepcopy(self.config)
        if name == "DIAG":
            reply = deepcopy(SAMPLE_DIAGNOSTICS)
            reply["config"] = deepcopy(self.config)
        self.inject("[USB] " + json.dumps(reply, ensure_ascii=False))
        return len(data)


class ProtocolTests(unittest.TestCase):
    def test_fragmented_utf8_crlf_and_multiple_lines(self):
        decoder = LineDecoder()
        data = "[MAIN] Größe\r\n[USB] {\"protocol\":1,\"ok\":true}\n".encode("utf-8")
        lines = []
        for value in data:
            lines.extend(decoder.feed(bytes([value])))
        self.assertEqual(lines[0], "[MAIN] Größe")
        self.assertTrue(parse_reply(lines[1])["ok"])

    def test_bounded_serial_stream_recovers(self):
        decoder = LineDecoder(8)
        self.assertEqual(decoder.feed(b"x" * 100), [])
        self.assertLessEqual(len(decoder.buffer), 8)
        lines = decoder.feed(b"\nOK\n")
        self.assertIn("verworfen", lines[0])
        self.assertEqual(lines[1], "OK")

    def test_invalid_replies_are_not_success(self):
        self.assertIsNone(parse_reply("[MAIN] normal log"))
        for line in ('[USB] {bad', '[USB] {"protocol":2,"ok":true}', '[USB] {"protocol":1,"ok":"true"}'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_reply(line)

    def test_all_supported_config_types(self):
        values = export_config(SAMPLE_DIAGNOSTICS["config"])
        validate_config(values)
        self.assertTrue(make_config_command(values).startswith("CONFIG SET {"))

    def test_utf8_bounds_and_strict_types(self):
        validate_config({"wifiSsid": "ä" * 16})
        for values in ({"wifiSsid": "ä" * 17}, {"timeout": True}, {"timeout": 59}, {"timeout": 2592001},
                       {"autoRotation": "false"}, {"manualOrientation": 2}, {"imageMode": -1},
                       {"wifiPassword": "a\x00b"}, {"downloadUrl": "file:///local"}, {"downloadUrl": "https://"},
                       {"unknown": 0}, {"wifiPasswordSet": True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_config(values)

    def test_charge_confirmation_cannot_come_from_import(self):
        with self.assertRaises(ValueError):
            make_config_command({"chargerMode": True})
        values = import_config('{"chargerMode":true,"confirmRechargeable":true}')
        self.assertNotIn("confirmRechargeable", values)
        validate_config({"chargerMode": True, "confirmRechargeable": True})

    def test_export_never_contains_passwords(self):
        values = {"wifiSsid": "Lab", "wifiPassword": "secret", "httpAuthPassword": "secret2", "confirmRechargeable": True}
        self.assertEqual(export_config(values), {"wifiSsid": "Lab"})
        self.assertEqual(import_config('{"config":{"wifiSsid":"Lab","wifiPasswordSet":true}}'), {"wifiSsid": "Lab"})

    def test_flashing_arguments_do_not_rebuild_or_erase_all(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "platformio.ini").touch()
            arguments = build_arguments(project, "flash", "COM10", 921600)
            self.assertIn("flash", arguments)
            self.assertNotIn("build", arguments)
            self.assertNotIn("erase-flash", arguments)
            self.assertNotIn("--port", build_arguments(project, "build"))
            self.assertNotIn("--port", build_arguments(project, "verify"))
            self.assertIn("--manual-bootloader", build_arguments(project, "flash", "COM10", manual_bootloader=True))
            for port in ("/dev/ttyUSB0", "/dev/cu.usbserial-123", "/dev/serial/by-id/usb-panel"):
                self.assertIn(port, build_arguments(project, "flash", port))
            for port in ("", "COM10;exit", "COM0", "$(bad)"):
                with self.assertRaises(ValueError):
                    build_arguments(project, "flash", port)

    def test_image_summary_rejects_wrong_chip_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            artifact = project / ".pio/build/epd13/firmware.bin"
            artifact.parent.mkdir(parents=True)
            data = bytearray(65536)
            data[0] = 0xE9
            struct.pack_into("<H", data, 12, 13)
            struct.pack_into("<I", data, 32, 0xABCD5432)
            artifact.write_bytes(data)
            self.assertNotIn("error", image_summary(project))
            data[12] = 0
            artifact.write_bytes(data)
            self.assertIn("error", image_summary(project))
            artifact.write_bytes(bytes(APP_CAPACITY + 1))
            self.assertIn("error", image_summary(project))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.editor = ConfigEditor()
        self.editor.set_config(deepcopy(SAMPLE_DIAGNOSTICS["config"]))

    def tearDown(self):
        self.editor.deleteLater()
        APPLICATION.processEvents()

    def test_loaded_values_have_no_patch(self):
        self.assertFalse(self.editor.dirty)
        self.assertEqual(self.editor.patch(), {})

    def test_polling_preserves_unsaved_edits(self):
        self.editor.fields["wifiSsid"].setText("Edited")
        self.assertFalse(self.editor.set_config(SAMPLE_DIAGNOSTICS["config"]))
        self.assertEqual(self.editor.patch(), {"wifiSsid": "Edited"})

    def test_password_keep_replace_delete(self):
        field = self.editor.fields["wifiPassword"]
        changes = []
        field.changed.connect(lambda: changes.append(True))
        self.assertNotIn("wifiPassword", self.editor.patch())
        field.mode.setCurrentIndex(1)
        field.edit.setText("BBBBsecret")
        self.assertEqual(len(changes), 2)
        self.assertEqual(self.editor.patch()["wifiPassword"], "BBBBsecret")
        self.assertNotIn("wifiPassword", self.editor.public_values())
        field.mode.setCurrentIndex(2)
        self.assertEqual(self.editor.patch()["wifiPassword"], "")
        self.editor.set_config(SAMPLE_DIAGNOSTICS["config"], force=True)
        self.assertEqual(field.edit.text(), "")

    def test_import_is_staged_and_url_selects_download(self):
        original = deepcopy(SAMPLE_DIAGNOSTICS["config"])
        original["imageMode"] = 0
        self.editor.set_config(original, force=True)
        self.editor.import_values({"downloadUrl": "https://example.com/a.bmp"})
        self.assertEqual(self.editor.patch()["imageMode"], 1)
        self.assertEqual(self.editor.baseline["imageMode"], 0)

    def test_manual_orientation_respects_auto_rotation(self):
        self.editor.fields["autoRotation"].setChecked(True)
        self.assertFalse(self.editor.fields["manualOrientation"].isEnabled())

    def test_action_buttons_emit_without_clicked_boolean(self):
        dashboard = Dashboard()
        requests = []
        dashboard.refresh_requested.connect(lambda: requests.append("DIAG"))
        dashboard.refresh_button.click()
        self.assertEqual(requests, ["DIAG"])
        dashboard.deleteLater()


class FirmwareProcessTests(unittest.TestCase):
    def test_progress_accepts_classic_and_current_esptool_output(self):
        job = FirmwareJob()
        progress = []
        job.progress.connect(progress.append)
        job._emit_line("Writing at 0x00010000... (25 %)")
        job._emit_line("Writing at 0x00020000 [========       ]  62.5%")
        self.assertEqual(progress, [25, 62])
        job.deleteLater()

    def test_real_qprocess_handles_unicode_paths_output_and_failure(self):
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory(prefix="panel studio ü ") as directory:
                project = Path(directory)
                script = project / "test worker.py"
                script.write_text("import sys\nprint('==> Prüfung mit Umlauten')\n"
                                  f"sys.exit({exit_code})\n", encoding="utf-8")
                job = FirmwareJob(project=project)
                output = []
                completed = []
                job.output.connect(output.append)
                job.completed.connect(lambda action, code: completed.append((action, code)))
                with patch("panel_studio.firmware.build_arguments", return_value=[str(script)]):
                    job.start("verify")
                wait_for(lambda: bool(completed), seconds=10)
                self.assertEqual(completed, [("verify", exit_code)])
                self.assertTrue(any("Prüfung" in line for line in output))
                self.assertFalse(job.active)
                job.deleteLater()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.serial = FakeSerial()
        self.controller = ConsoleController(worker_factory=lambda port: SerialWorker(port, lambda **options: self.serial))
        self.logs = []
        self.replies = []
        self.controller.log_received.connect(lambda kind, text: self.logs.append((kind, text)))
        self.controller.reply_received.connect(self.replies.append)
        self.controller.connect_port("TEST-PORT")
        wait_for(lambda: self.controller.state == "ready")

    def tearDown(self):
        self.assertTrue(self.controller.disconnect_port())
        self.controller.deleteLater()
        APPLICATION.processEvents()

    def test_handshake_and_single_outstanding_request(self):
        self.assertEqual(self.serial.writes, [b"DIAG\n"])
        self.serial.respond = False
        self.assertTrue(self.controller.request("CONFIG GET"))
        self.assertFalse(self.controller.request("REBOOT"))

    def test_secret_is_sent_but_never_logged(self):
        self.controller.request(make_config_command({"wifiPassword": "privateBBBB", "timeout": 600}))
        wait_for(lambda: self.controller.state == "ready")
        self.assertTrue(any(b"privateBBBB" in data for data in self.serial.writes))
        self.assertNotIn("privateBBBB", str(self.logs))
        self.assertEqual(self.replies[-1]["config"]["timeout"], 600)

    def test_timeout_does_not_retry_mutations(self):
        self.serial.respond = False
        self.controller.request(make_config_command({"timeout": 600}))
        self.controller.deadline.start(30)
        wait_for(lambda: self.controller.state == "waiting")
        self.assertEqual(len(self.serial.writes), 2)
        self.assertIsNone(self.controller.pending)

    def test_late_wrong_command_does_not_confirm_another_request(self):
        self.serial.respond = False
        self.controller.request("DIAG")
        self.serial.inject('[USB] {"protocol":1,"command":"CONFIG SET","ok":true}')
        wait_for(lambda: any("Verspätete" in text for _, text in self.logs))
        self.assertEqual(self.controller.pending, "DIAG")

    def test_ready_after_reset_restarts_handshake(self):
        self.serial.inject("[MAIN] test mode check...")
        self.serial.inject("[USB] Ready: DIAG")
        wait_for(lambda: len(self.replies) == 2)
        self.assertEqual(self.controller.state, "ready")

    def test_wifi_wait_blocks_other_commands_then_queries(self):
        self.controller.request("WIFI CONNECT")
        wait_for(lambda: self.controller.wifi_wait)
        self.assertFalse(self.controller.request("CONFIG GET"))
        self.controller.wifi_timer.start(20)
        wait_for(lambda: self.controller.state == "ready")
        self.assertEqual(self.serial.writes[-1], b"DIAG\n")

    def test_run_disables_live_ready_state(self):
        self.controller.request("RUN")
        wait_for(lambda: self.controller.state == "sleeping")

    def test_bootloader_command_is_explicit(self):
        self.controller.request("B")
        wait_for(lambda: len(self.serial.writes) == 2)
        self.assertEqual(self.serial.writes[-1], b"\nB")
        self.assertEqual(self.controller.state, "bootloader")

    def test_cable_removal_closes_serial_owner(self):
        self.serial.fail_read = True
        wait_for(lambda: self.controller.worker is None)
        self.assertFalse(self.serial.is_open)


class FakeFirmwareJob(QObject):
    output = Signal(str)
    phase = Signal(str)
    progress = Signal(int)
    completed = Signal(str, int)

    def __init__(self, serial):
        super().__init__()
        self.serial = serial
        self.active = False
        self.calls = []

    def start(self, action, port, baud, manual_bootloader, expected_sha256=""):
        assert not self.serial.is_open, "The GUI must release the port before flashing"
        self.calls.append((action, port, baud, manual_bootloader, expected_sha256))
        self.active = True


class WindowTests(unittest.TestCase):
    def test_flash_releases_port_and_no_automatic_device_write_in_demo(self):
        with tempfile.TemporaryDirectory() as directory, patch("panel_studio.app.available_ports", return_value=[("COM10", "COM10  ·  Test", True)]):
            connection = FakeSerial()
            controller = ConsoleController(worker_factory=lambda port: SerialWorker(port, lambda **options: connection))
            job = FakeFirmwareJob(connection)
            preferences = QSettings(str(Path(directory) / "prefs.ini"), QSettings.Format.IniFormat)
            window = MainWindow(preferences=preferences, controller=controller, firmware_job=job)
            window.live.setChecked(False)
            window.confirm = lambda title, text: True
            window.toggle_connection()
            wait_for(lambda: controller.state == "ready")
            summary = {"path": "firmware.bin", "sha256": "a" * 64, "size": 100000, "modified": 0, "percent": 5}
            with patch("panel_studio.app.image_summary", return_value=summary):
                window.start_firmware("flash")
                self.assertFalse(connection.is_open)
                self.assertEqual(job.calls[0][0:2], ("flash", "COM10"))
                self.assertEqual(job.calls[0][-1], summary["sha256"])
                self.assertFalse(window.connect_button.isEnabled())
                job.active = False
                window.reconnect.setChecked(False)
                job.completed.emit("flash", 0)
            window.close()
            window.deleteLater()
            preview = MainWindow(demo=True, preferences=preferences)
            self.assertIsNone(preview.controller.worker)
            self.assertFalse(preview.flash_button.isEnabled())
            self.assertFalse(preview.connect_button.isEnabled())
            preview.close()
            preview.deleteLater()
            APPLICATION.processEvents()

    def test_timed_out_reload_cannot_discard_edits_on_poll(self):
        with tempfile.TemporaryDirectory() as directory, patch("panel_studio.app.available_ports", return_value=[]):
            settings = QSettings(str(Path(directory) / "prefs.ini"), QSettings.Format.IniFormat)
            window = MainWindow(demo=True, preferences=settings)
            window.config.fields["wifiSsid"].setText("Keep this edit")
            window.force_reload = True
            window.handle_reply(deepcopy(SAMPLE_DIAGNOSTICS))
            self.assertEqual(window.config.fields["wifiSsid"].text(), "Keep this edit")
            window.config.set_config(SAMPLE_DIAGNOSTICS["config"], force=True)
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
