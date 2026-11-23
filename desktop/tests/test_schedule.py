"""Wakeup estimates must follow observed sleep, never infer success from elapsed time."""
from datetime import datetime
import unittest

from panel_studio.schedule import CycleSchedule


class CycleScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 23, 12, 0, 0).timestamp()
        self.schedule = CycleSchedule(clock=lambda: self.now)

    def test_diagnostics_and_session_end_do_not_start_countdown(self):
        self.schedule.observe_reply({"ok": True, "command": "DIAG", "system": {"sleepPredictionSeconds": 900}, "config": {"timeout": 900}})
        self.schedule.observe_line("[USB] Session ended: USB disconnected or idle timeout")
        self.assertIn("noch nicht abschätzbar", self.schedule.description(connected=True))

    def test_actual_sleep_duration_overrides_configured_interval(self):
        self.schedule.observe_reply({"ok": True, "command": "DIAG", "config": {"timeout": 3600}})
        self.schedule.observe_line("[MAIN] Going to Sleep for 60 seconds (MotionWake: 0)")
        self.assertIn("23.11. 12:01:00", self.schedule.description(connected=True))
        self.now += 15
        self.assertIn("00:00:45", self.schedule.description(connected=True))
        self.now += 120
        self.assertIn("Start noch nicht bestätigt", self.schedule.description(connected=True))
        self.assertNotIn("in -", self.schedule.description(connected=True))

    def test_estimate_survives_disconnect_but_is_marked_unconfirmed(self):
        self.schedule.observe_line("[MAIN] Going to Sleep for 60 seconds")
        self.now += 20
        text = self.schedule.description(connected=False)
        self.assertIn("00:00:40", text)
        self.assertIn("USB getrennt", text)
        self.assertIn("unbestätigt", text)

    def test_new_boot_or_observed_activity_discards_old_deadline(self):
        for line in ("ESP-ROM:esp32c6-20220919", "DESP-ROM:esp32c6-20220919",
                     "[WAKE] Got Timer Wakeup", "[USB] Ready: DIAG",
                     "[DL] Download Image file: http://example.com/", "[IMAGE] Render begin: attempt=9"):
            with self.subTest(line=line):
                self.schedule.observe_line("[MAIN] Going to Sleep for 900 seconds")
                self.schedule.observe_line(line)
                self.assertIn("noch nicht abschätzbar", self.schedule.description(connected=True))

    def test_no_timer_and_soft_sleep_do_not_predict_automatic_wakeup(self):
        for seconds in (0, -1):
            self.schedule.observe_line(f"[MAIN] Going to Sleep for {seconds} seconds (MotionWake: 0)")
            self.assertIn("kein automatischer Timerstart", self.schedule.description(connected=True))
        self.schedule.observe_line("[MAIN] Going to Sleep for 60 seconds")
        self.schedule.observe_line("[SLEEP] enter soft sleep")
        self.assertIn("kein automatischer Timerstart", self.schedule.description(connected=True))
        self.schedule.reset()
        self.schedule.observe_reply({"ok": True, "command": "DIAG", "system": {"sleepDisabled": True}})
        self.schedule.observe_line("[MAIN] Going to Sleep for 60 seconds (MotionWake: 1)")
        self.assertIn("kein automatischer Timerstart", self.schedule.description(connected=True))
        self.assertNotIn("Bewegung", self.schedule.description(connected=True))

    def test_motion_and_multiday_sleep_are_explicit(self):
        self.schedule.observe_line("[MAIN] Going to Sleep for 90061 seconds (MotionWake: 1)")
        text = self.schedule.description(connected=True)
        self.assertIn("24.11. 13:01:01", text)
        self.assertIn("1 T 01:01:01", text)
        self.assertIn("Bewegung kann früher aufwecken", text)

    def test_successful_manual_command_clears_estimate_and_new_sleep_reschedules(self):
        for command in ("RUN", "FORCE REFRESH IMAGE", "REBOOT"):
            with self.subTest(command=command):
                self.schedule.observe_line("[MAIN] Going to Sleep for 900 seconds")
                self.schedule.observe_reply({"ok": True, "command": command})
                self.assertIn("noch nicht abschätzbar", self.schedule.description(connected=True))
                self.schedule.observe_line("[MAIN] Going to Sleep for 120 seconds")
                self.assertIn("00:02:00", self.schedule.description(connected=True))


if __name__ == "__main__":
    unittest.main()
