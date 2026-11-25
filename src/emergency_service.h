// Included by the managed firmware after the image storage and render functions.
#include "emergency_auth.h"
#include "picture_packet.h"
#include PANEL_EMERGENCY_CONFIG
#include <mutex>
#include <atomic>

#ifdef EPD_TYPE_13INCH
#include "local_picture.h"
#endif

namespace emergency {
constexpr char serviceId[] = "bb7454a0-28d9-4b2b-8cd5-bcf97fa33930";
constexpr char challengeId[] = "bb7454a1-28d9-4b2b-8cd5-bcf97fa33930";
constexpr char transferId[] = "bb7454a2-28d9-4b2b-8cd5-bcf97fa33930";
constexpr char statusId[] = "bb7454a3-28d9-4b2b-8cd5-bcf97fa33930";
constexpr char packedId[] = "bb7454a4-28d9-4b2b-8cd5-bcf97fa33930";
constexpr int generationAddress = 1570;
static_assert(generationAddress + sizeof(uint64_t) <= EMERGENCY_ACTIVE_ADDRESS && EMERGENCY_ACTIVE_ADDRESS < EEPROM_SIZE);
enum State : uint8_t { Idle, Challenge, Receiving, Queued, Committed, Rejected, Processing };
static std::atomic<State> state{Idle};
static std::mutex session;
static NimBLECharacteristic *challengeChar, *transferChar, *packedChar, *statusChar;
static uint16_t owner = BLE_HS_CONN_HANDLE_NONE;
static uint8_t nonce[32];
static EmergencyAuthorization authorization;
static bool running = false;
static uint32_t sessionStart = 0;

static uint64_t generation() {
   uint64_t stored;
   EEPROM.get(generationAddress, stored);
   return stored == UINT64_MAX ? 0 : stored;
}

static bool updateGeneration(uint64_t next) {
   const uint64_t previous = generation();
   if (next <= previous) return true;
   EEPROM.put(generationAddress, next);
   if (EEPROM.commit()) return true;
   EEPROM.put(generationAddress, previous);
   return false;
}

static void rememberGeneration(const String &value) {
   if (value.isEmpty() || value.length() > 19) return;
   uint64_t next = 0;
   for (unsigned i = 0; i < value.length(); ++i) {
      if (value[i] < '0' || value[i] > '9') return;
      next = next * 10 + (value[i] - '0');
   }
   if (next <= INT64_MAX) updateGeneration(next);
}

static bool timeValid() {
#ifdef EPD_TYPE_13INCH
   if (localPicture::active) return millis()-sessionStart < 600000;
#endif
   const auto now = time(nullptr);
   return hasWorkshopClock(workshopTimeAnchor, now) && uint64_t(now) < authorization.expires &&
          generation() <= authorization.generation;
}

static void reject() {
   if (saveFile) saveFile.close();
   state = Rejected;
}

static void startOperation(const uint8_t *data, size_t length) {
   bool local = false;
#ifdef EPD_TYPE_13INCH
   local = localPicture::verify(data, length, nonce, authorization);
#endif
   const auto now = time(nullptr);
   if (!eepromReady || quartersPending() || (!local && (!hasWorkshopClock(workshopTimeAnchor, now) || settings.httpAuthUser.isEmpty() ||
       !authorizeEmergency({data,length}, {emergencyIssuerPublic, sizeof(emergencyIssuerPublic)},
              nonce, settings.httpAuthUser.c_str(), CLIENT_ID, now, generation(), authorization) ||
       !updateGeneration(authorization.generation)))) {
      reject();
      return;
   }
   if (authorization.operation == 2) {
      state = Queued;
      return;
   }
   if (!secondaryImageSlotAvailable || authorization.length != IMG_WIDTH * IMG_HEIGHT / 2 + 118 ||
       !openSlot(DOWNLOAD_SLOT_NAME, downloadSlotSize(), saveFile)) {
      reject();
      return;
   }
   rawSlotBegin(downloadSlotSize());
   state = Receiving;
}

class Connections final : public NimBLEServerCallbacks {
   void onConnect(NimBLEServer *server, NimBLEConnInfo &info) override {
      std::lock_guard<std::mutex> guard(session);
      if (owner != BLE_HS_CONN_HANDLE_NONE || state == Queued || state == Processing || state == Committed) {
         server->disconnect(info.getConnHandle());
         return;
      }
#ifdef EPD_TYPE_13INCH
      localPicture::active = false;
#endif
      owner = info.getConnHandle();
      isBleClientConnected = true;
      esp_fill_random(nonce, sizeof(nonce));
      state = Challenge;
      sessionStart = bleLastActivity = millis();
      server->updateConnParams(owner, 12, 24, 0, 600);
   }
   void onDisconnect(NimBLEServer *, NimBLEConnInfo &info, int) override {
      std::lock_guard<std::mutex> guard(session);
      if (owner != info.getConnHandle()) return;
#ifdef EPD_TYPE_13INCH
      localPicture::requested = false;
      if (state == Challenge && localPicture::ready) {
         localPicture::ready = false;
         memset(localPicture::secret, 0, sizeof(localPicture::secret));
         forceExitSetup = true;
      }
#endif
      owner = BLE_HS_CONN_HANDLE_NONE;
      isBleClientConnected = false;
      lastDisconnectTime = millis();
      if (state == Committed) forceExitSetup = true;
      else if (state != Queued && state != Processing) {
         if (state == Receiving && saveFile) saveFile.close();
         state = Idle;
         if (running) NimBLEDevice::startAdvertising();
      }
   }
};

class Attributes final : public NimBLECharacteristicCallbacks {
   void onRead(NimBLECharacteristic *attribute, NimBLEConnInfo &info) override {
      std::lock_guard<std::mutex> guard(session);
      if (info.getConnHandle() != owner) { attribute->setValue(""); return; }
      if (attribute == challengeChar && state == Challenge) attribute->setValue(nonce, sizeof(nonce));
      else if (attribute == statusChar) {
         uint8_t response = state.load();
#ifdef EPD_TYPE_13INCH
         if (response == Challenge && localPicture::ready) response = 7;
#endif
         attribute->setValue(&response, 1);
      } else attribute->setValue("");
   }
   void onWrite(NimBLECharacteristic *attribute, NimBLEConnInfo &info) override {
      std::lock_guard<std::mutex> guard(session);
      if (info.getConnHandle() != owner || (attribute != transferChar && attribute != packedChar) || state == Processing || state == Queued) return;
      const auto value = attribute->getValue();
      const uint8_t *data = value.data();
      const size_t length = value.size();
      bleLastActivity = millis();
      if (attribute == packedChar && state != Receiving) return;
      if (state == Challenge) {
#ifdef EPD_TYPE_13INCH
         if (length == 1 && (data[0] == 3
#ifdef PANEL_FIXED_IMAGE_CONFIG
             || data[0] == 4
#endif
             ) && buttonWake && millis() < 90000 &&
             !localPicture::issued && secondaryImageSlotAvailable && !quartersPending()) {
            localPicture::requestedCommand = data[0];
            localPicture::requested = true;
            return;
         }
#endif
         startOperation(data, length);
         memset(nonce, 0, sizeof(nonce));
      } else if (state == Receiving) {
         if (!timeValid() || length < 5 || emergencyNumber(data, 4) != rawSlot.written ||
             rawSlot.written >= authorization.length) {
            reject();
            return;
         }
         const size_t remaining = authorization.length - rawSlot.written;
         const uint8_t *payload = data + 4;
         size_t count = length - 4;
         if (attribute == packedChar) {
            static uint8_t expanded[8192];
            count = unpackPictureBlock(payload, count, expanded, std::min(remaining, sizeof(expanded)));
            payload = expanded;
         }
         if (!count || count > remaining || !rawSlotWrite(payload, count)) reject();
         else if (rawSlot.written == authorization.length) state = Queued;
      }
   }
};

static bool commitPicture() {
   char digest[45];
   size_t encoded = 0;
   if (mbedtls_base64_encode((uint8_t*)digest, sizeof(digest), &encoded, authorization.digest, 32) ||
       encoded != 44 || !verifyDownloadedDigest(saveFile, authorization.length, digest)) return false;
   saveFile.seek(0);
   uint8_t header[54];
   const bool completeHeader = saveFile.read(header, sizeof(header)) == sizeof(header);
   const int32_t height = completeHeader ? int32_t(readLe32(header + 22)) : 0;
   bool valid = completeHeader && header[0] == 'B' && header[1] == 'M' &&
                readLe32(header+10) == 118 && readLe32(header+18) == IMG_WIDTH &&
                (height == IMG_HEIGHT || height == -IMG_HEIGHT) && readLe16(header+28) == 4 && readLe32(header+30) == 0;
   saveFile.close();
   const uint8_t target = candidateImageSlot();
   lastDownloadedBytes = authorization.length;
   if (!valid || !processImageFile(DOWNLOAD_SLOT_NAME, imageSlotName(target)) || !timeValid()) {
      Serial.println("[EMERGENCY] Image format, storage or grant validity check failed.");
      return false;
   }
   const auto oldSlot = settings.activeSlot;
   const uint8_t oldOverride = EEPROM.read(EMERGENCY_ACTIVE_ADDRESS);
   const String oldTag = settings.lastModified, oldDigest = activeImageDigest;
   const uint8_t oldPending = EEPROM.read(PENDING_IMAGE_ADDRESS), oldProgress = EEPROM.read(QUARTER_PROGRESS_ADDRESS);
   const uint8_t oldRotation = EEPROM.read(QUARTER_ROTATION_ADDRESS);
   bool segmented = false;
#ifdef EPD_TYPE_13INCH
   segmented = hasValidFlashImage(activeImageSlotName());
#endif
   settings.activeSlot = target;
   digest[44] = 0;
   activeImageDigest = digest;
   settings.lastModified = "emergency:" + activeImageDigest;
   EEPROM.write(EMERGENCY_ACTIVE_ADDRESS, EMERGENCY_ACTIVE_MARKER);
   EEPROM.write(PENDING_IMAGE_ADDRESS, PENDING_IMAGE_MARKER);
   EEPROM.write(QUARTER_PROGRESS_ADDRESS, segmented ? QUARTER_START : 0);
   EEPROM.write(QUARTER_ROTATION_ADDRESS, displaySettings.rotationPicture > 0);
   if (saveSettingsToFlash(EEPROM_SETTINGS_ADR)) return true;
   settings.activeSlot = oldSlot;
   EEPROM.write(EMERGENCY_ACTIVE_ADDRESS, oldOverride);
   settings.lastModified = oldTag;
   activeImageDigest = oldDigest;
   EEPROM.write(PENDING_IMAGE_ADDRESS, oldPending);
   EEPROM.write(QUARTER_PROGRESS_ADDRESS, oldProgress);
   EEPROM.write(QUARTER_ROTATION_ADDRESS, oldRotation);
   saveSettingsToFlash(EEPROM_SETTINGS_ADR);
   return false;
}

static bool releasePicture() {
#if defined(PANEL_FIXED_IMAGE_CONFIG) && defined(EPD_TYPE_13INCH)
   const bool localRelease = localPicture::active;
   const String previousUrl = settings.downloadUrl;
   const auto previousMode = settings.imageMode;
   if (localRelease) {
      settings.downloadUrl = fixedImageUrl;
      settings.imageMode = 1;
   } else
#endif
   if (!emergencyImageActive()) return false;
   const String oldTag = settings.lastModified;
   const uint8_t oldOverride = EEPROM.read(EMERGENCY_ACTIVE_ADDRESS);
   EEPROM.write(EMERGENCY_ACTIVE_ADDRESS, 0);
   settings.lastModified = "";
   if (saveSettingsToFlash(EEPROM_SETTINGS_ADR)) return true;
#if defined(PANEL_FIXED_IMAGE_CONFIG) && defined(EPD_TYPE_13INCH)
   settings.downloadUrl = previousUrl;
   settings.imageMode = previousMode;
#endif
   settings.lastModified = oldTag;
   EEPROM.write(EMERGENCY_ACTIVE_ADDRESS, oldOverride);
   saveSettingsToFlash(EEPROM_SETTINGS_ADR);
   return false;
}

static void poll() {
#ifdef EPD_TYPE_13INCH
   bool show = false, erase = false;
   {
      std::lock_guard<std::mutex> guard(session);
      if (localPicture::requested && !localPicture::issued && state == Challenge) {
         localPicture::requested = false;
         localPicture::issued = true;
         esp_fill_random(localPicture::secret, sizeof(localPicture::secret));
         show = true;
      } else if (localPicture::ready && (state != Challenge || millis()-localPicture::visibleSince >= localPicture::scanWindow)) {
         localPicture::ready = false;
         memset(localPicture::secret, 0, sizeof(localPicture::secret));
         erase = true;
      }
   }
   if (show) {
      const bool ok = localPicture::mark(true) && localPicture::draw(true);
      std::lock_guard<std::mutex> guard(session);
      localPicture::ready = ok && state == Challenge && isBleClientConnected;
      if (!localPicture::ready) forceExitSetup = true;
      localPicture::visibleSince = millis();
      if (!ok) state = Rejected;
   }
   if (erase) localPicture::restore();
#endif
   {
      std::lock_guard<std::mutex> guard(session);
      if (state != Queued) {
         if ((state == Receiving && millis()-bleLastActivity > 30000) ||
             (state == Committed && millis()-bleLastActivity > 10000) ||
             (isBleClientConnected && millis()-sessionStart > 600000)) forceExitSetup = true;
         return;
      }
      state = Processing;
   }
   const bool ok = timeValid() && (authorization.operation == 1 ? commitPicture() : releasePicture());
   std::lock_guard<std::mutex> guard(session);
   if (saveFile) saveFile.close();
   state = ok ? Committed : Rejected;
   Serial.printf("[EMERGENCY] Operation %u %s.\n", authorization.operation, ok ? "committed" : "rejected");
   bleLastActivity = millis();
   if (!isBleClientConnected) forceExitSetup = true;
}

static bool enable(const String &device, bool enabled) {
   if (enabled == running) return true;
   if (!enabled) {
      running = false;
      NimBLEDevice::deinit(true);
      return true;
   }
   static Connections connections;
   static Attributes attributes;
   NimBLEDevice::init(device.c_str());
   NimBLEDevice::setMTU(517);
   auto server = NimBLEDevice::createServer();
   server->setCallbacks(&connections, false);
   auto service = server->createService(serviceId);
   challengeChar = service->createCharacteristic(challengeId, NIMBLE_PROPERTY::READ);
   transferChar = service->createCharacteristic(transferId, NIMBLE_PROPERTY::WRITE);
   packedChar = service->createCharacteristic(packedId, NIMBLE_PROPERTY::WRITE);
   statusChar = service->createCharacteristic(statusId, NIMBLE_PROPERTY::READ);
   for (auto attr : {challengeChar, transferChar, packedChar, statusChar}) attr->setCallbacks(&attributes);
   service->start();
   auto adv = NimBLEDevice::getAdvertising();
   adv->addServiceUUID(serviceId);
   adv->enableScanResponse(true);
   adv->setName(device.c_str());
   running = adv->start();
   return running;
}
}
