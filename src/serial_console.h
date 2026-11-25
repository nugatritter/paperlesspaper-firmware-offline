#pragma once

// Firmware adapter, included by main.cpp after the storage and display helpers.
// Only the setup loop executes commands; no SPI access runs in UART callbacks.
static void serialReply(JsonDocument &reply) {
   reply["protocol"] = 1;
   if (reply.overflowed()) {
      Serial.println("[USB] {\"protocol\":1,\"ok\":false,\"error\":\"Out of memory\"}");
      return;
   }
   String output;
   serializeJson(reply, output);
   Serial.printf("[USB] %s\n", output.c_str());
}

static void serialError(const char *command, const char *message) {
   JsonDocument reply;
   reply["command"] = command;
   reply["ok"] = false;
   reply["error"] = message;
   serialReply(reply);
}

static void appendSerialConfig(JsonObject config) {
   config["wifiSsid"] = wifiSettings.ssid;
   config["wifiPasswordSet"] = !wifiSettings.pss.isEmpty();
   config["downloadUrl"] = settings.downloadUrl;
   config["settingsUrl"] = settings.settingsUrl;
   config["httpAuthUser"] = settings.httpAuthUser;
   config["httpAuthPasswordSet"] = !settings.httpAuthPassword.isEmpty();
   config["timeout"] = settings.timeout;
   config["imageMode"] = settings.imageMode;
   config["autoRotation"] = settings.autoRotation;
   config["manualOrientation"] = settings.manualOrientation;
   config["motionWakeup"] = settings.motionWakeup;
   config["showBatteryWarning"] = settings.showBatteryWarning;
   config["showWifiWarning"] = settings.showWifiWarning;
   config["requireImageDigest"] = settings.requireImageDigest;
   config["chargerMode"] = settings.chargerMode;
}

static void captureSerialStorage() {
   serialStorageSnapshot.clear();
   serialStorageSnapshot["sampledAtUptimeMs"] = millis();
   serialStorageSnapshot["eepromReady"] = eepromReady;
   serialStorageSnapshot["spiffsReady"] = spiffsReady;
   serialStorageSnapshot["serialFlashReady"] = serialFlashReady;
   if (spiffsReady) {
      serialStorageSnapshot["spiffsTotalBytes"] = SPIFFS.totalBytes();
      serialStorageSnapshot["spiffsUsedBytes"] = SPIFFS.usedBytes();
   }
   if (!serialFlashReady) return;
   prepareSpiBusForFlash();
   uint8_t id[5] = {};
   SerialFlash.readID(id);
   char identifier[15];
   snprintf(identifier, sizeof(identifier), "%02X%02X%02X%02X%02X", id[0], id[1], id[2], id[3], id[4]);
   serialStorageSnapshot["jedecId"] = identifier;
   serialStorageSnapshot["capacityBytes"] = SerialFlash.capacity(id);
   serialStorageSnapshot["eraseBlockBytes"] = SerialFlash.blockSize();
   JsonArray slots = serialStorageSnapshot["slots"].to<JsonArray>();
   for (const char *name : {IMAGE_SLOT_A_NAME, IMAGE_SLOT_B_NAME, DOWNLOAD_SLOT_NAME}) {
      JsonObject slot = slots.add<JsonObject>();
      slot["name"] = name;
      SerialFlashFile file = SerialFlash.open(name);
      slot["exists"] = static_cast<bool>(file);
      if (file) {
         slot["allocatedBytes"] = file.size();
         slot["address"] = file.getFlashAddress();
         file.close();
         if (strcmp(name, DOWNLOAD_SLOT_NAME)) slot["imageMarkerValid"] = hasValidFlashImage(name);
      }
   }
}

static void appendRenderDiagnostics(JsonObject output, const RenderJournal &record) {
   output["valid"] = validRenderJournal(record);
   if (!validRenderJournal(record)) return;
   output["attempt"] = record.attempt;
   output["stage"] = renderStageName(record.stage);
   output["needsRecovery"] = renderNeedsRecovery(record);
   output["slot"] = imageSlotName(record.slot);
   output["targetPresentation"] = record.target;
   output["result"] = record.result;
   output["startedAtUptimeMs"] = record.startedMs;
   output["elapsedMsAtCheckpoint"] = record.elapsedMs;
   output["batteryBeforeMv"] = record.batteryBeforeMv;
   output["sampledMinimumBatteryMv"] = record.batteryMinimumMv;
}

static void appendSerialDiagnostics(JsonDocument &reply) {
   JsonObject firmware = reply["firmware"].to<JsonObject>();
   firmware["version"] = SOFTWARE_VERSION;
#ifdef PANEL_TRUST_CONFIG
   firmware["managedOrigin"] = panelOrigin();
   const auto now = time(nullptr);
   firmware["clockTrusted"] = hasWorkshopClock(workshopTimeAnchor, now);
   if (hasWorkshopClock(workshopTimeAnchor, now)) firmware["utcEpoch"] = int64_t(now);
#endif
#ifdef PANEL_QUARTER_TRIAL
   firmware["quarterTrial"] = true;
   QuarterTrialRecord trial;
   EEPROM.get(QUARTER_TRIAL_ADDRESS, trial);
   if (trial.attempt && trial.attempt != UINT32_MAX && trial.completed <= 4) {
      auto report = reply["quarterTrial"].to<JsonObject>();
      report["attempt"] = trial.attempt;
      report["completed"] = trial.completed;
      report["usbSeen"] = trial.usbSeen;
      for (unsigned index = 0; index < 4; ++index) {
         report["elapsedMs"][index] = trial.elapsedMs[index];
         report["minimumMv"][index] = trial.minimumMv[index];
      }
   }
#endif
   firmware["variant"] = "offline";
   firmware["build"] = __DATE__ " " __TIME__;
   firmware["sdk"] = ESP.getSdkVersion();
   firmware["deviceId"] = CLIENT_ID;
   const esp_partition_t *app = esp_ota_get_running_partition();
   if (app) {
      firmware["appSlot"] = app->label;
      firmware["appAddress"] = app->address;
      firmware["appCapacityBytes"] = app->size;
   }
   firmware["sketchBytes"] = ESP.getSketchSize();
   JsonObject system = reply["system"].to<JsonObject>();
   system["uptimeMs"] = millis();
   system["resetReason"] = static_cast<int>(esp_reset_reason());
   system["resetReasonName"] = resetReasonName(esp_reset_reason());
   system["wakeupCause"] = static_cast<int>(esp_sleep_get_wakeup_cause());
   const char *wakeNames[] = {"reset", "power-on-or-reset-pin", "motion", "timer"};
   system["wakeup"] = wakeNames[static_cast<unsigned>(systemData.wakeupCause) % 4];
   system["chip"] = ESP.getChipModel();
   system["chipRevision"] = ESP.getChipRevision();
   system["cpuMHz"] = ESP.getCpuFreqMHz();
   system["chipTemperatureC"] = temperatureRead();
   system["heapBytes"] = ESP.getHeapSize();
   system["freeHeapBytes"] = ESP.getFreeHeap();
   system["minimumFreeHeapBytes"] = ESP.getMinFreeHeap();
   system["largestFreeBlockBytes"] = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
   system["internalFlashBytes"] = ESP.getFlashChipSize();
   system["batteryMillivolts"] = systemData.vddValue;
   system["usbConnected"] = systemData.usbConnected;
   system["charging"] = systemData.charging;
   system["sleepPredictionSeconds"] = systemData.sleepPrediction;
   system["failedUpdates"] = failedUpdates;
   system["sleepDisabled"] = settings.sleepDisabled;
   JsonObject network = reply["network"].to<JsonObject>();
   network["status"] = static_cast<int>(WiFi.status());
   network["connected"] = WiFi.status() == WL_CONNECTED;
   network["mac"] = WiFi.macAddress();
   if (WiFi.status() == WL_CONNECTED) {
      network["ssid"] = WiFi.SSID();
      network["ip"] = WiFi.localIP().toString();
      network["gateway"] = WiFi.gatewayIP().toString();
      network["subnet"] = WiFi.subnetMask().toString();
      network["dns"] = WiFi.dnsIP().toString();
      network["rssiDbm"] = WiFi.RSSI();
      network["channel"] = WiFi.channel();
   }
   network["connectionPending"] = wifiSettings.isDeployWifi;
   network["bleConnected"] = isBleClientConnected;
   network["bleReceivedBytes"] = bleBytesReceived;
   network["bleCrc32"] = bleFinalFlashCrc;
   JsonObject panel = reply["display"].to<JsonObject>();
   panel["physicalWidth"] = EPD_WIDTH;
   panel["physicalHeight"] = EPD_HEIGHT;
   panel["rasterWidth"] = IMG_WIDTH;
   panel["rasterHeight"] = IMG_HEIGHT;
   panel["textRotation"] = displaySettings.rotationText;
   panel["pictureRotation"] = displaySettings.rotationPicture;
   panel["quickRefresh"] = displaySettings.quickRefresh;
   panel["quickRefreshDisabledByDriver"] = displaySettings.globalQuickRefreshDisable;
   panel["powerOn"] = systemData.displayPowerOn;
   panel["busyPinLevel"] = digitalRead(BUSY_PIN);
   panel["storedPresentation"] = displayContent();
   panel["activeImageSlot"] = activeImageSlotName();
   panel["secondarySlotAvailable"] = secondaryImageSlotAvailable;
   panel["imageValidator"] = settings.lastModified;
#ifdef PANEL_EMERGENCY_CONFIG
   panel["emergencyActive"] = emergencyImageActive();
#endif
   panel["settingsValidator"] = settings.settingsLastModified;
   JsonObject render = reply["render"].to<JsonObject>();
#ifdef EPD_TYPE_13INCH
   render["quartersCompleted"] = quartersPending() ? EEPROM.read(QUARTER_PROGRESS_ADDRESS) - QUARTER_START :
                                 (quarterCleanupDue() ? 4 : 0);
   render["quartersPending"] = quartersPending();
   render["usbCleanupDue"] = quarterCleanupDue();
#endif
   render["storageOk"] = renderJournalStorageOk;
   render["active"] = renderMonitoring;
   render["needsRecovery"] = renderNeedsRecovery(renderJournal);
   render["interruptedAtBoot"] = renderNeedsRecovery(renderJournalAtBoot) &&
                                  renderJournalAtBoot.stage != RenderStage::Failed;
   appendRenderDiagnostics(render["lastAttempt"].to<JsonObject>(), renderJournal);
   appendRenderDiagnostics(render["atBoot"].to<JsonObject>(), renderJournalAtBoot);
   reply["storageAtBoot"] = serialStorageSnapshot.as<JsonObjectConst>();
   nvs_stats_t stats = {};
   if (nvs_get_stats(nullptr, &stats) == ESP_OK) {
      reply["nvs"]["usedEntries"] = stats.used_entries;
      reply["nvs"]["freeEntries"] = stats.free_entries;
      reply["nvs"]["totalEntries"] = stats.total_entries;
   }
   JsonObject update = reply["lastCompletedUpdate"].to<JsonObject>();
   update["valid"] = lastUpdateDiagnostics.valid;
   if (lastUpdateDiagnostics.valid) {
      update["downloadResult"] = lastUpdateDiagnostics.downloadResult;
      update["renderResult"] = lastUpdateDiagnostics.renderResult;
      update["httpStatus"] = lastUpdateDiagnostics.httpStatus;
      update["downloadedBytes"] = lastUpdateDiagnostics.downloadedBytes;
      update["downloadMs"] = lastUpdateDiagnostics.downloadMs;
      update["renderMs"] = lastUpdateDiagnostics.renderMs;
   }
   appendSerialConfig(reply["config"].to<JsonObject>());
}

static bool applySerialConfig(JsonObjectConst patch) {
   const Settings previous = settings;
   const String previousSsid = wifiSettings.ssid;
   const String previousPassword = wifiSettings.pss;
   uint8_t previousEeprom[EEPROM_SIZE];
   for (size_t index = 0; index < sizeof(previousEeprom); ++index) previousEeprom[index] = EEPROM.read(index);
   if (patch["wifiSsid"].is<const char *>()) wifiSettings.ssid = patch["wifiSsid"].as<String>();
   if (patch["wifiPassword"].is<const char *>()) wifiSettings.pss = patch["wifiPassword"].as<String>();
   if (patch["downloadUrl"].is<const char *>()) {
      settings.downloadUrl = patch["downloadUrl"].as<String>();
      if (!settings.downloadUrl.isEmpty()) settings.imageMode = 1;
   }
   if (patch["settingsUrl"].is<const char *>()) settings.settingsUrl = patch["settingsUrl"].as<String>();
   if (patch["httpAuthUser"].is<const char *>()) settings.httpAuthUser = patch["httpAuthUser"].as<String>();
   if (patch["httpAuthPassword"].is<const char *>()) settings.httpAuthPassword = patch["httpAuthPassword"].as<String>();
   if (patch["timeout"].is<int>()) settings.timeout = patch["timeout"].as<int>();
   if (patch["imageMode"].is<int>()) settings.imageMode = patch["imageMode"].as<int>();
   if (patch["manualOrientation"].is<int>()) settings.manualOrientation = patch["manualOrientation"].as<int>();
   if (patch["autoRotation"].is<bool>()) settings.autoRotation = patch["autoRotation"].as<bool>();
   if (patch["motionWakeup"].is<bool>()) settings.motionWakeup = patch["motionWakeup"].as<bool>();
   if (patch["showBatteryWarning"].is<bool>()) settings.showBatteryWarning = patch["showBatteryWarning"].as<bool>();
   if (patch["showWifiWarning"].is<bool>()) settings.showWifiWarning = patch["showWifiWarning"].as<bool>();
   if (patch["requireImageDigest"].is<bool>()) settings.requireImageDigest = patch["requireImageDigest"].as<bool>();
   if (patch["chargerMode"].is<bool>()) settings.chargerMode = patch["chargerMode"].as<bool>();
   const bool credentialsChanged = settings.httpAuthUser != previous.httpAuthUser || settings.httpAuthPassword != previous.httpAuthPassword;
   const bool orientationChanged = settings.manualOrientation != previous.manualOrientation || settings.autoRotation != previous.autoRotation;
   bool invalidateSource = settings.downloadUrl != previous.downloadUrl || credentialsChanged || orientationChanged ||
                           (settings.requireImageDigest && !previous.requireImageDigest);
#ifdef PANEL_EMERGENCY_CONFIG
   invalidateSource &= !emergencyImageActive();
#endif
   if (invalidateSource) settings.lastModified = "";
   if (settings.settingsUrl != previous.settingsUrl || credentialsChanged) settings.settingsLastModified = "";
   writeStringToFlash(wifiSettings.ssid.c_str(), 0, MAX_WIFI_SSID_LEN, false);
   writeStringToFlash(wifiSettings.pss.c_str(), 40, MAX_WIFI_PASS_LEN, false);
   writeIntToFlash(settings.timeout, 210, false);
   if (!saveSettingsToFlash(EEPROM_SETTINGS_ADR)) {
      settings = previous;
      wifiSettings.ssid = previousSsid;
      wifiSettings.pss = previousPassword;
      for (size_t index = 0; index < sizeof(previousEeprom); ++index) EEPROM.write(index, previousEeprom[index]);
      return false;
   }
   if (settings.timeout != previous.timeout) systemData.newSleepTimeSet = true;
   if (orientationChanged) {
      settings.forceDownload = true;
      bleImageApplied = false;
   }
   if (!settings.autoRotation) displaySetRotation(settings.manualOrientation);
   if (wifiSettings.ssid != previousSsid || wifiSettings.pss != previousPassword) WiFi.disconnect();
   if (settings.chargerMode != previous.chargerMode) chargeMode(settings.chargerMode);
   return true;
}

static void handleSerialCommand(const char *line) {
   String command(line);
   command.trim();
   if (command.isEmpty()) return;
   if (!serialConsoleReady) { serialError("INPUT", "Not ready; wait for [USB] Ready"); return; }
   if (!systemData.usbConnected) { serialError("INPUT", "USB power required"); return; }
   if (isBleClientConnected || bleFile || fwUpdateInProgress || applyPending || applyInProgress || fwRebootPending) {
      serialError("INPUT", "Busy; disconnect the BLE client and finish pending transfers first");
      return;
   }
   serialConsoleActive = true;
   if (wifiSettings.bleInitOk) NimBLEDevice::stopAdvertising();
   serialConsoleActivity = millis();
   JsonDocument reply;
   reply["ok"] = true;
   if (command == "HELP") {
      reply["command"] = "HELP";
      reply["commands"] = "HELP | DIAG | CONFIG GET | CONFIG SET {JSON} | WIFI CONNECT | RUN | FORCE REFRESH IMAGE | REBOOT | B";
#ifdef PANEL_TRUST_CONFIG
      reply["workshopCommands"] = "CLOCK SET <UTC Unix seconds> | MAINTENANCE RESET CONFIRM";
#endif
      reply["writableKeys"] = "wifiSsid,wifiPassword,downloadUrl,settingsUrl,httpAuthUser,httpAuthPassword,timeout,imageMode,autoRotation,manualOrientation,motionWakeup,showBatteryWarning,showWifiWarning,requireImageDigest,chargerMode,confirmRechargeable";
      reply["maxLineBytes"] = 2048;
      reply["idleTimeoutSeconds"] = SETUP_IDLE_TIMEOUT;
   }
   else if (command == "DIAG") {
      reply["command"] = "DIAG";
      appendSerialDiagnostics(reply);
   }
   else if (command == "CONFIG GET") {
      reply["command"] = "CONFIG GET";
      appendSerialConfig(reply["config"].to<JsonObject>());
   }
   else if (command.startsWith("CONFIG SET ")) {
      JsonDocument patch;
      const char *validation = parseSerialConfig(patch, command.c_str() + 11);
      if (validation) { serialError("CONFIG SET", validation); return; }
#ifdef PANEL_TRUST_CONFIG
      for (const char *key : {"downloadUrl", "settingsUrl"}) {
         if (patch[key].is<const char *>() && strlen(patch[key].as<const char *>()) &&
             !allowedPanelUrl(patch[key].as<String>())) {
            serialError("CONFIG SET", "Managed URL must use the configured HTTPS origin");
            return;
         }
      }
#endif
      if (!eepromReady) { serialError("CONFIG SET", "EEPROM is unavailable"); return; }
      if (!applySerialConfig(patch.as<JsonObjectConst>())) { serialError("CONFIG SET", "Saving EEPROM failed"); return; }
      reply["command"] = "CONFIG SET";
      reply["saved"] = true;
      reply["apply"] = "Use WIFI CONNECT to connect; RUN to update the display and sleep";
      appendSerialConfig(reply["config"].to<JsonObject>());
   }
   else if (command == "WIFI CONNECT") {
      if (wifiSettings.ssid.isEmpty()) { serialError("WIFI CONNECT", "Configure wifiSsid first"); return; }
      wifiSettings.isDeployWifi = true;
      reply["command"] = "WIFI CONNECT";
      reply["pending"] = true;
   }
   else if (command == "FORCE REFRESH IMAGE") {
      reply["command"] = command;
      serialReply(reply);
      Serial.flush();
      serialConsoleActive = false;
      forceStoredImageRefresh = true;
      forceExitSetup = true;
      return;
   }
#ifdef PANEL_TRUST_CONFIG
   else if (command.startsWith("CLOCK SET ")) {
      if (!usbCheckConnect() || !setWorkshopClock(command.c_str() + 10)) {
         serialError("CLOCK SET", "Workshop USB and a valid non-decreasing UTC time required");
         return;
      }
      reply["command"] = "CLOCK SET";
      reply["utcEpoch"] = int64_t(time(nullptr));
   }
   else if (command == "MAINTENANCE RESET CONFIRM") {
      if (!eepromReady || !usbCheckConnect()) { serialError("RESET", "Workshop USB required"); return; }
      if (!resetAll(true)) { serialError("RESET", "Reset failed"); return; }
      reply["command"] = "RESET";
      serialReply(reply);
      Serial.flush();
      ESP.restart();
      return;
   }
#endif
#ifdef PANEL_QUARTER_TRIAL
   else if (command == "TRIAL QUARTERS") {
      if (!usbCheckConnect() || !eepromReady || !secondaryImageSlotAvailable ||
          newImageNeedsRender() || displayContent() != DISPLAY_PICTURE || renderNeedsRecovery(renderJournal)) {
         serialError("TRIAL QUARTERS", "Two slots and a completed reference picture required");
         return;
      }
      reply["command"] = command;
      serialReply(reply);
      Serial.flush();
      runQuarterTrial();
      gotToDeepSleep(600, false, false);
      return;
   }
#endif
   else if (command == "RUN" || command == "REBOOT") {
      reply["command"] = command;
      serialReply(reply);
      Serial.flush();
      serialConsoleActive = false;
      if (command == "REBOOT") ESP.restart();
      forceExitSetup = true;
      return;
   }
   else { serialError("INPUT", "Unknown command; use HELP (uppercase)"); return; }
   serialReply(reply);
}
