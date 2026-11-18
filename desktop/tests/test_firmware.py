"""Firmware validation and orchestration tests; all hardware access is simulated."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from panel_studio import firmware_cli as workflow
from panel_studio.firmware_core import (
    APP_CAPACITY, PARTITIONS, WorkflowError, flash_arguments, prepare_images,
    stage_images, validate_image, validate_partition_binary, validate_partition_csv,
)


def make_image(app=True):
    header = bytearray(24)
    header[0:2] = bytes((0xE9, 1))
    struct.pack_into("<H", header, 12, 13)
    header[23] = 1
    payload = bytearray(65536 if app else 128)
    if app:
        struct.pack_into("<I", payload, 0, 0xABCD5432)
    data = header + struct.pack("<II", 0x42000000, len(payload)) + payload
    checksum = 0xEF
    for value in payload:
        checksum ^= value
    data += bytes(15 - len(data) % 16) + bytes((checksum,))
    return bytes(data + hashlib.sha256(data).digest())


def make_partitions(entries=PARTITIONS):
    data = b"".join(struct.pack("<HBBII16sI", 0x50AA, kind, subtype, address, size, name.encode(), flags)
                    for name, kind, subtype, address, size, flags in entries)
    data += b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(data, usedforsecurity=False).digest()
    return data.ljust(0xC00, b"\xff")


class ImageTests(unittest.TestCase):
    def test_valid_images_and_corrupt_checksum_digest_chip_or_type(self):
        data = make_image()
        self.assertEqual(validate_image(data, app=True), hashlib.sha256(data).hexdigest().upper())
        validate_image(make_image(False), app=False)
        for offset in (12, 32, 40, len(data) - 33, len(data) - 1):
            corrupt = bytearray(data)
            corrupt[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(WorkflowError):
                validate_image(corrupt, app=True)
        for corrupt in (data[:-1], data + b"x", data.ljust(APP_CAPACITY + 1, b"\0")):
            with self.assertRaises(WorkflowError):
                validate_image(corrupt, app=True)
        with self.assertRaises(WorkflowError):
            validate_image(data, app=False)

    def test_partition_layout_and_digest_are_both_enforced(self):
        data = make_partitions()
        validate_partition_binary(data)
        corrupt = bytearray(data)
        corrupt[32] ^= 1
        with self.assertRaises(WorkflowError):
            validate_partition_binary(corrupt)
        entries = list(PARTITIONS)
        entries[4] = ("spiffs", 1, 130, 0x3C0000, 0x30000, 0)
        with self.assertRaises(WorkflowError):
            validate_partition_binary(make_partitions(entries))

    def test_partition_csv_accepts_comments_but_rejects_moved_certificates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.csv"
            source = "# Comment\n   \n" + (workflow.PROJECT_ROOT / "part.csv").read_text()
            path.write_text(source)
            validate_partition_csv(path)
            path.write_text(source.replace("0x3B0000", "0x3C0000"))
            with self.assertRaises(WorkflowError):
                validate_partition_csv(path)


class ProjectTests(unittest.TestCase):
    def test_inherited_epd13_settings_are_required_even_when_default_is_epd7(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "part.csv").write_bytes((workflow.PROJECT_ROOT / "part.csv").read_bytes())
            source = ("[platformio]\ndefault_envs = epd7\n"
                      "[env]\nboard = esp32-c6-devkitm-1\nframework = arduino\nboard_build.partitions = part.csv\n"
                      "[env:epd13]\nbuild_flags = -DEPD_TYPE_13INCH\n"
                      "[env:epd7]\nbuild_flags = -DEPD_TYPE_7INCH\n")
            path = project / "platformio.ini"
            original_directory = Path.cwd()
            try:
                os.chdir(project)
                path.write_text(source)
                workflow.validate_project(project)
                for incorrect in (source.replace("-DEPD_TYPE_13INCH", "-DEPD_TYPE_7INCH"),
                                  source.replace("esp32-c6-devkitm-1", "esp32dev"),
                                  source.replace("part.csv", "other.csv")):
                    path.write_text(incorrect)
                    with self.assertRaises(WorkflowError):
                        workflow.validate_project(project)
            finally:
                os.chdir(original_directory)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.project = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="panel ü ")))
        self.build = self.project / ".pio/build/epd13"
        self.build.mkdir(parents=True)
        (self.build / "firmware.bin").write_bytes(make_image())
        (self.build / "bootloader.bin").write_bytes(make_image(False))
        (self.build / "partitions.bin").write_bytes(make_partitions())
        self.ota = self.project / "boot_app0.bin"
        self.ota.write_bytes(b"\xff" * 8192)
        self.stack.enter_context(patch.object(workflow, "validate_project"))
        self.stack.enter_context(patch.object(workflow, "ota_image_path", return_value=self.ota))
        self.serial = self.stack.enter_context(patch("serial.Serial", side_effect=AssertionError("Unexpected serial access")))
        self.ports = self.stack.enter_context(patch("serial.tools.list_ports.comports", side_effect=AssertionError("Unexpected port scan")))
        self.report = Mock()
        self.arguments = SimpleNamespace(action="verify", expected_sha256="", port="/dev/ttyUSB0", baud=921600,
                                         manual_bootloader=False, bootloader_timeout=5)

    def test_verify_never_accesses_ports_and_calls_real_image_info_interface(self):
        with patch.object(workflow, "run_tool", return_value=(0, "valid")) as tool:
            workflow.execute(self.arguments, self.project, self.report)
        self.assertEqual(tool.call_count, 2)
        for call in tool.call_args_list:
            self.assertEqual(call.args[0], "esptool")
            self.assertEqual(call.args[1][:3], ["--chip", "esp32c6", "image-info"])
        self.serial.assert_not_called()
        self.ports.assert_not_called()

    def test_corrupt_or_unconfirmed_images_abort_before_any_tool_or_port(self):
        self.arguments.action = "flash"
        for mismatch in (True, False):
            self.arguments.expected_sha256 = "0" * 64 if mismatch else ""
            if not mismatch:
                (self.build / "firmware.bin").write_bytes(b"x" * 65536)
            with patch.object(workflow, "run_tool") as tool, self.assertRaises(WorkflowError):
                workflow.execute(self.arguments, self.project, self.report)
            tool.assert_not_called()
        self.serial.assert_not_called()
        self.ports.assert_not_called()

    def test_esptool_invalid_with_zero_exit_still_aborts(self):
        self.arguments.action = "flash"
        with patch.object(workflow, "run_tool", return_value=(0, "Validation hash: (invalid!)")):
            with self.assertRaises(WorkflowError):
                workflow.execute(self.arguments, self.project, self.report)
        self.ports.assert_not_called()

    def test_failed_build_cannot_continue_or_flash(self):
        self.arguments.action = "build"
        with patch.object(workflow.shutil, "which", return_value="git"), \
                patch.object(workflow, "run_tool", return_value=(1, "failed")) as tool:
            with self.assertRaises(WorkflowError) as result:
                workflow.execute(self.arguments, self.project, self.report)
        self.assertEqual(result.exception.exit_code, 3)
        self.assertEqual(tool.call_args.args[0], "platformio")
        self.assertEqual(tool.call_args.args[1][-2:], ["--environment", "epd13"])
        self.ports.assert_not_called()

    def test_flash_uses_snapshot_even_if_original_changes_and_requires_four_hashes(self):
        self.arguments.action = "flash"
        original = (self.build / "firmware.bin").read_bytes()
        staged_paths = []

        def tool(module, arguments, project, report):
            if "image-info" in arguments:
                return 0, "valid"
            self.assertEqual(module, "esptool")
            pairs = arguments[-8:]
            self.assertEqual(pairs[::2], ["0x0", "0x8000", "0xe000", "0x10000"])
            staged_paths.extend(Path(path) for path in pairs[1::2])
            self.assertEqual(staged_paths[-1].read_bytes(), original)
            self.assertNotIn("erase-flash", arguments)
            return 0, "Hash of data verified.\n" * 4

        with patch.object(workflow, "validate_port", return_value="/dev/ttyUSB0"), \
                patch.object(workflow, "enter_bootloader", side_effect=lambda *args: (self.build / "firmware.bin").write_bytes(b"changed")), \
                patch.object(workflow, "run_tool", side_effect=tool):
            workflow.execute(self.arguments, self.project, self.report)
        self.assertTrue(all(not path.exists() for path in staged_paths))

    def test_flash_failure_or_missing_hashes_never_retries(self):
        self.arguments.action = "flash"
        for result in ((6, "failure"), (0, "Hash of data verified.\n" * 3)):
            with patch.object(workflow, "validate_port", return_value="COM10"), \
                    patch.object(workflow, "enter_bootloader"), \
                    patch.object(workflow, "run_tool", side_effect=[(0, "valid"), (0, "valid"), result]) as tool:
                with self.assertRaises(WorkflowError) as caught:
                    workflow.execute(self.arguments, self.project, self.report)
                self.assertEqual(caught.exception.exit_code, 6)
                self.assertEqual(tool.call_count, 3)

    def test_changed_staged_files_cannot_be_written(self):
        images = prepare_images(self.build, self.ota)
        with tempfile.TemporaryDirectory() as directory:
            staged = stage_images(images, Path(directory))
            flash_arguments("/dev/cu.usbserial-123", 921600, staged)
            staged[-1][1].write_bytes(b"tampered")
            with self.assertRaises(WorkflowError):
                flash_arguments("COM10", 921600, staged)

    def test_serial_reader_is_closed_before_bootloader_probe(self):
        connection = Mock()
        connection.in_waiting = 20
        connection.read.return_value = b"ROM Download Bootloader"
        connection.is_open = False
        connection.open.side_effect = lambda: setattr(connection, "is_open", True)
        connection.close.side_effect = lambda: setattr(connection, "is_open", False)
        self.serial.side_effect = None
        self.serial.return_value = connection

        def probe(*args):
            self.assertFalse(connection.is_open)
            return connection.close.called

        with patch.object(workflow, "probe_bootloader", side_effect=probe), patch.object(workflow.time, "sleep"):
            workflow.enter_bootloader(self.project, "COM10", False, 5, self.report)
        self.assertFalse(connection.dtr)
        self.assertFalse(connection.rts)
        connection.write.assert_called_with(b"\nB")
        connection.close.assert_called_once()

    def test_manual_bootloader_failure_does_not_send_commands(self):
        with patch.object(workflow, "probe_bootloader", return_value=False):
            with self.assertRaises(WorkflowError) as result:
                workflow.enter_bootloader(self.project, "COM10", True, 5, self.report)
        self.assertEqual(result.exception.exit_code, 7)
        self.serial.assert_not_called()

    def test_port_detection_rejects_wrong_usb_device(self):
        self.ports.side_effect = None
        self.ports.return_value = [SimpleNamespace(device="/dev/ttyUSB0", vid=0x1234, pid=1, description="Other")]
        with self.assertRaises(WorkflowError):
            workflow.validate_port("/dev/ttyUSB0", self.report)
        self.ports.return_value[0].vid = 0x10C4
        self.ports.return_value[0].pid = 0xEA60
        self.assertEqual(workflow.validate_port("/dev/ttyUSB0", self.report), "/dev/ttyUSB0")

    def test_macos_native_cp2102n_port_is_accepted(self):
        from panel_studio.transport import available_ports

        self.ports.side_effect = None
        self.ports.return_value = [SimpleNamespace(device="/dev/cu.usbserial-10", vid=4292, pid=60000,
                                                  description="CP2102N USB to UART Bridge Controller")]
        self.assertEqual(workflow.validate_port("/dev/cu.usbserial-10", self.report), "/dev/cu.usbserial-10")
        self.assertEqual(available_ports()[0][::2], ("/dev/cu.usbserial-10", True))
        self.serial.assert_not_called()

    def test_project_lock_prevents_second_run_and_releases_after_error(self):
        with self.assertRaisesRegex(RuntimeError, "test failure"):
            with workflow.project_lock(self.project):
                with self.assertRaises(WorkflowError):
                    with workflow.project_lock(self.project):
                        self.fail("Second lock succeeded")
                raise RuntimeError("test failure")
        with workflow.project_lock(self.project):
            pass


if __name__ == "__main__":
    unittest.main()
