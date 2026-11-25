"""Pure protocol and configuration helpers, independent of Qt and serial hardware."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

MAX_COMMAND_BYTES = 2048
STRING_LIMITS = {
    "wifiSsid": 32, "wifiPassword": 64, "downloadUrl": 128,
    "settingsUrl": 128, "httpAuthUser": 128, "httpAuthPassword": 128,
}
BOOLEAN_KEYS = {
    "autoRotation", "motionWakeup", "showBatteryWarning", "showWifiWarning",
    "requireImageDigest", "chargerMode", "confirmRechargeable",
}
INTEGER_LIMITS = {"timeout": (60, 2592000), "imageMode": (0, 1), "manualOrientation": (0, 1)}
PASSWORD_KEYS = {"wifiPassword", "httpAuthPassword"}
READ_ONLY_KEYS = {"wifiPasswordSet", "httpAuthPasswordSet"}
CONFIG_KEYS = set(STRING_LIMITS) | BOOLEAN_KEYS | set(INTEGER_LIMITS)
LABELS = {
    "wifiSsid": "WLAN-Name (SSID)", "wifiPassword": "WLAN-Passwort",
    "downloadUrl": "Bild-URL", "settingsUrl": "Remote-Konfiguration (URL)",
    "httpAuthUser": "HTTP-Benutzername", "httpAuthPassword": "HTTP-Passwort",
    "timeout": "Aktualisierungsintervall", "imageMode": "Bildquelle",
    "autoRotation": "Automatische Ausrichtung", "manualOrientation": "Manuelle Ausrichtung",
    "motionWakeup": "Bei Bewegung aufwachen", "showBatteryWarning": "Batteriewarnung anzeigen",
    "showWifiWarning": "Verbindungswarnung anzeigen", "requireImageDigest": "Bild-Digest verlangen",
    "chargerMode": "Akkus laden", "confirmRechargeable": "Akkus bestätigt",
}

RESET_REASONS = {
    0: "UNKNOWN", 1: "POWERON", 2: "EXTERNAL_PIN", 3: "SOFTWARE", 4: "PANIC",
    5: "INTERRUPT_WATCHDOG", 6: "TASK_WATCHDOG", 7: "WATCHDOG", 8: "DEEP_SLEEP",
    9: "BROWNOUT", 10: "SDIO", 11: "USB", 12: "JTAG", 13: "EFUSE",
    14: "POWER_GLITCH", 15: "CPU_LOCKUP",
}


def reset_description(system: dict) -> str:
    reason = system.get("resetReasonName") or RESET_REASONS.get(system.get("resetReason"), "UNKNOWN")
    descriptions = {
        "POWERON": "Einschalten oder Reset-Pin; Tastendruck und Versorgungsunterbrechung sind nicht unterscheidbar",
        "BROWNOUT": "Unterspannung am ESP32 erkannt",
        "POWER_GLITCH": "Störung der Versorgung erkannt",
        "SOFTWARE": "Software-Neustart", "DEEP_SLEEP": "Aufwachen aus Deep Sleep",
        "PANIC": "Firmware-Absturz", "TASK_WATCHDOG": "Task-Watchdog",
        "INTERRUPT_WATCHDOG": "Interrupt-Watchdog", "WATCHDOG": "Watchdog",
    }
    return f"{reason}: {descriptions.get(reason, 'Reset-Grund nicht näher eingegrenzt')}"


def render_description(snapshot: dict) -> str:
    render = snapshot.get("render", {})
    if render.get("storageOk") is False:
        return "Renderstatus konnte nicht zuverlässig gespeichert werden. Abschluss unbestätigt."
    attempt = render.get("lastAttempt", {})
    if not attempt.get("valid"):
        return "Kein dauerhafter Renderstatus vorhanden. Ein vollständiges Bild ist damit nicht bestätigt."
    stage = attempt.get("stage", "unknown")
    if stage == "complete" and not render.get("needsRecovery"):
        return f"Bildaufbau von der Firmware abgeschlossen · {attempt.get('elapsedMsAtCheckpoint', '—')} ms. Sichtbare Pixel werden nicht geprüft."
    phases = {"preparing": "Vorbereitung", "streaming": "Bildübertragung", "refreshing": "Panel-Refresh", "failed": "Fehler"}
    phase = phases.get(stage, stage)
    if render.get("interruptedAtBoot"):
        return f"Beim Neustart war der Bildaufbau unvollständig. Letzte gespeicherte Phase: {phase}. Vollständiger Neuaufbau erforderlich."
    return f"Bildaufbau nicht abgeschlossen · Phase: {phase}."


def parse_reply(line: str) -> dict[str, Any] | None:
    if not line.startswith("[USB] {"):
        return None
    try:
        reply = json.loads(line[6:])
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError("Unvollständige oder ungültige JSON-Antwort vom Panel.") from error
    if not isinstance(reply, dict) or type(reply.get("protocol")) is not int or reply["protocol"] != 1:
        raise ValueError("Diese Version des USB-Protokolls wird nicht unterstützt.")
    if type(reply.get("ok")) is not bool:
        raise ValueError("Die Panel-Antwort enthält keinen gültigen Erfolgsstatus.")
    return reply


def validate_config(values: dict[str, Any], *, require_confirmation: bool = True) -> None:
    if not isinstance(values, dict) or not values:
        raise ValueError("Bitte mindestens eine Einstellung ändern.")
    for key, value in values.items():
        label = LABELS.get(key, key)
        if key in STRING_LIMITS:
            if not isinstance(value, str):
                raise ValueError(f"{label}: Text erwartet.")
            try:
                size = len(value.encode("utf-8"))
            except UnicodeEncodeError as error:
                raise ValueError(f"{label}: ungültiges Unicode-Zeichen.") from error
            if size > STRING_LIMITS[key] or any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError(f"{label}: höchstens {STRING_LIMITS[key]} UTF-8-Bytes, keine Steuerzeichen.")
            if key.endswith("Url") and value:
                try:
                    parsed = urlsplit(value)
                    valid = parsed.scheme in ("http", "https") and bool(parsed.hostname) and " " not in value
                except ValueError:
                    valid = False
                if not valid:
                    raise ValueError(f"{label}: vollständige http://- oder https://-Adresse eingeben.")
        elif key in BOOLEAN_KEYS:
            if type(value) is not bool:
                raise ValueError(f"{label}: true oder false erwartet.")
        elif key in INTEGER_LIMITS:
            lower, upper = INTEGER_LIMITS[key]
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{label}: ganze Zahl von {lower} bis {upper} erwartet.")
        else:
            raise ValueError(f"Unbekannte oder schreibgeschützte Einstellung: {key}")
    if require_confirmation and values.get("chargerMode") and not values.get("confirmRechargeable"):
        raise ValueError("Das Laden muss für eingelegte wiederaufladbare Akkus ausdrücklich bestätigt werden.")


def make_config_command(values: dict[str, Any]) -> str:
    validate_config(values)
    command = "CONFIG SET " + json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
        raise ValueError("Die Konfiguration überschreitet das Limit von 2048 Bytes pro Befehl.")
    return command


def command_name(command: str) -> str:
    for name in ("CONFIG SET", "CLOCK SET"):
        if command.startswith(name + " "):
            return name
    return command


def safe_command_label(command: str) -> str:
    if command.startswith("CONFIG SET "):
        return "CONFIG SET · Werte ausgeblendet"
    return command


def export_config(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items()
            if key in CONFIG_KEYS - PASSWORD_KEYS - {"confirmRechargeable"}}


def import_config(text: str) -> dict[str, Any]:
    try:
        values = json.loads(text)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError("Die Datei enthält kein gültiges JSON.") from error
    if isinstance(values, dict) and "config" in values:
        values = values["config"]
    if not isinstance(values, dict):
        raise ValueError("Ein JSON-Objekt mit Konfigurationswerten wird erwartet.")
    values = {key: value for key, value in values.items() if key not in READ_ONLY_KEYS}
    # A file can never stand in for the user's live charging confirmation.
    values.pop("confirmRechargeable", None)
    validate_config(values, require_confirmation=False)
    return values


class LineDecoder:
    """Keep fragmented UTF-8 intact; bound memory even for a broken serial stream."""
    def __init__(self, maximum: int = 65536):
        self.buffer = bytearray()
        self.maximum = maximum
        self.discarding = False

    def feed(self, chunk: bytes) -> list[str]:
        lines = []
        for value in chunk:
            if value in (10, 13):
                if self.discarding:
                    lines.append("[GUI] Überlange serielle Zeile verworfen.")
                elif self.buffer:
                    lines.append(self.buffer.decode("utf-8", errors="replace"))
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                if len(self.buffer) >= self.maximum:
                    self.buffer.clear()
                    self.discarding = True
                else:
                    self.buffer.append(value)
        return lines
