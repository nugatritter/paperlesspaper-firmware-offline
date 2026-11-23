"""Estimate timer wakeup from observed firmware messages, without polling the panel."""
from __future__ import annotations

from datetime import datetime
import math
import re
import time


class CycleSchedule:
    def __init__(self, clock=None):
        self.clock = clock or time.time
        self.reset()

    def reset(self) -> None:
        self.last_received_at: float | None = None
        self.next_cycle_at: float | None = None
        self.sleep_seconds: int | None = None
        self.sleep_disabled = False
        self.motion_wakeup = False

    def clear_estimate(self) -> None:
        self.next_cycle_at = None
        self.sleep_seconds = None
        self.motion_wakeup = False

    def observe_line(self, line: str) -> None:
        if "ESP-ROM:" in line or "[MAIN] test mode check" in line or "[WAKE]" in line:
            self.reset()
        elif any(marker in line for marker in (
            "[USB] Ready:", "[DL] Download Image file:", "[IMAGE] Render begin:",
            "[IMAGE] Forced refresh requested;", "[EPD] Render stage:",
        )):
            self.clear_estimate()
        self.last_received_at = self.clock()
        match = re.search(r"\[MAIN\] Going to Sleep for (-?\d{1,10}) seconds(?: \(MotionWake: ([01])\))?", line)
        if match:
            self.sleep_seconds = max(0, int(match.group(1))) if not self.sleep_disabled else 0
            self.motion_wakeup = not self.sleep_disabled and match.group(2) == "1"
            self.next_cycle_at = self.clock() + self.sleep_seconds if self.sleep_seconds else None
        elif "[SLEEP] enter soft sleep" in line:
            self.sleep_disabled = True
            self.sleep_seconds = 0
            self.next_cycle_at = None
            self.motion_wakeup = False

    def observe_reply(self, reply: dict) -> None:
        if not reply.get("ok"):
            return
        if reply.get("command") == "DIAG":
            self.sleep_disabled = reply.get("system", {}).get("sleepDisabled", False) is True
            self.clear_estimate()
        elif reply.get("command") in {"RUN", "FORCE REFRESH IMAGE", "REBOOT"}:
            self.clear_estimate()

    def description(self, *, connected: bool) -> str:
        if self.sleep_seconds is None:
            text = "Nächster Bildzyklus: noch nicht abschätzbar."
            if self.last_received_at is not None:
                received = datetime.fromtimestamp(self.last_received_at).strftime("%H:%M:%S")
                text += f" Letzter Empfang um {received}."
            return text
        if self.next_cycle_at is None:
            text = "Nächster Bildzyklus: kein automatischer Timerstart angekündigt."
        else:
            expected = datetime.fromtimestamp(self.next_cycle_at).strftime("%d.%m. %H:%M:%S")
            remaining = math.ceil(self.next_cycle_at - self.clock())
            if remaining > 0:
                days, seconds = divmod(remaining, 86400)
                hours, seconds = divmod(seconds, 3600)
                minutes, seconds = divmod(seconds, 60)
                countdown = (f"{days} T " if days else "") + f"{hours:02}:{minutes:02}:{seconds:02}"
                text = f"Nächster Bildzyklus: ca. {expected} · in {countdown} (geschätzt)."
            else:
                text = f"Nächster Bildzyklus: erwartet seit ca. {expected} · Start noch nicht bestätigt."
        if self.motion_wakeup:
            text += " Bewegung kann früher aufwecken."
        if not connected:
            text += " USB getrennt; Schätzung unbestätigt."
        return text
