"""Explicitly synthetic data used only in preview mode and UI tests."""

SAMPLE_DIAGNOSTICS = {
    "protocol": 1, "command": "DIAG", "ok": True,
    "firmware": {"version": "0.1.0f", "variant": "offline", "build": "DEMO",
                 "deviceId": "epd13-DEMO", "sdk": "ESP-IDF", "appSlot": "app0"},
    "system": {"uptimeMs": 42300, "resetReason": 1, "wakeup": "button",
               "chip": "ESP32-C6", "cpuMHz": 160, "chipTemperatureC": 29.4,
               "batteryMillivolts": 5120, "usbConnected": True, "charging": False,
               "freeHeapBytes": 91648, "minimumFreeHeapBytes": 78240, "failedUpdates": 0},
    "network": {"connected": True, "ssid": "Panel-Lab", "ip": "192.0.2.42", "rssiDbm": -58,
                "channel": 6, "bleConnected": False},
    "display": {"physicalWidth": 1600, "physicalHeight": 1200, "rasterWidth": 1200, "rasterHeight": 1600,
                "textRotation": 0, "pictureRotation": 0, "activeImageSlot": "tmp_b.bmp", "secondarySlotAvailable": True},
    "storageAtBoot": {"sampledAtUptimeMs": 900, "eepromReady": True, "serialFlashReady": True,
                      "capacityBytes": 16777216, "eraseBlockBytes": 65536},
    "lastCompletedUpdate": {"valid": True, "httpStatus": 304, "downloadResult": 1,
                            "renderResult": 0, "downloadMs": 580, "renderMs": 25},
    "config": {"wifiSsid": "Panel-Lab", "wifiPasswordSet": True, "downloadUrl": "http://192.0.2.10/panel.bmp",
               "settingsUrl": "", "httpAuthUser": "", "httpAuthPasswordSet": False, "timeout": 900,
               "imageMode": 1, "autoRotation": False, "manualOrientation": 0, "motionWakeup": False,
               "showBatteryWarning": True, "showWifiWarning": True, "requireImageDigest": False, "chargerMode": False},
}
