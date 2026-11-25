// Exercise the production HTTP slot commit across power, digest and storage failures.
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
struct String : public std::string {
   using std::string::string;
   using std::string::operator=;
   bool startsWith(const char *prefix) const { return find(prefix) == 0; }
};
constexpr int EEPROM_SETTINGS_ADR = 500;
constexpr int PENDING_IMAGE_ADDRESS = 1332;
constexpr uint8_t PENDING_IMAGE_MARKER = 0x53;
constexpr const char *DOWNLOAD_SLOT_NAME = "download";
enum { DL_OK = 0, DL_NOT_MODIFIED = 1, DL_DIGEST_ERROR = -6, DL_FORMAT_ERROR = -7,
       DL_FLASH_ERROR = -8, RENDER_USB_REQUIRED = -11 };
struct {
   std::array<uint8_t, 2048> bytes{};
   void write(int address, uint8_t value) { bytes[address] = value; }
   uint8_t read(int address) { return bytes[address]; }
} EEPROM;
bool newImageNeedsRender() { return EEPROM.read(PENDING_IMAGE_ADDRESS) == PENDING_IMAGE_MARKER; }
struct {
   bool requireImageDigest = false;
   uint8_t activeSlot = 0;
   String lastModified = "previous";
   String downloadUrl = "source";
} settings;
struct { int rotationPicture = 1; } displaySettings;
struct { void println(const char *) {} } Serial;
struct { void setSleep(bool) {} } WiFi;
bool usb = false;
bool dropDuringConversion = false;
bool previousImage = true;
bool secondaryImageSlotAvailable = true;
bool convertOk = true;
bool commitOk = true;
int writes = 0;
int response = 0;
String activeImageDigest = "previous digest";
String downloadedDigest(44, 'A');
String tempLastModified = "next";
int connections = 0;
bool ensureWifi() { ++connections; return true; }
bool usbCheckConnect() { return usb; }
bool hasValidFlashImage(const char *) { return previousImage; }
uint8_t candidateImageSlot() { return secondaryImageSlotAvailable ? 1-settings.activeSlot : settings.activeSlot; }
const char *imageSlotName(uint8_t slot) { return slot ? "B" : "A"; }
const char *activeImageSlotName() { return imageSlotName(settings.activeSlot); }
int loadImageFromWeb(const String &, const char *) { return response; }
bool processImageFile(const char *, const char *) {
   ++writes;
   if (dropDuringConversion) usb = false;
   return convertOk;
}
bool saveSettingsToFlash(int) { return commitOk; }

// PRODUCTION_SOURCE

void reset() {
   usb = dropDuringConversion = false;
   previousImage = secondaryImageSlotAvailable = convertOk = commitOk = true;
   writes = response = 0;
   downloadedDigest.assign(44, 'A');
   activeImageDigest = "previous digest";
   settings = {};
   EEPROM.bytes.fill(0xff);
}
int main() {
   reset();
   assert(!quartersPending() && !quarterCleanupDue());
#ifdef PANEL_EMERGENCY_CONFIG
   settings.lastModified = "emergency:verified-digest";
   assert(processHttpDownload() == DL_NOT_MODIFIED && connections == 0 && writes == 0);
   settings.lastModified = "";
   EEPROM.write(EMERGENCY_ACTIVE_ADDRESS, EMERGENCY_ACTIVE_MARKER);
   assert(processHttpDownload() == DL_NOT_MODIFIED && connections == 0 && writes == 0);
   EEPROM.write(EMERGENCY_ACTIVE_ADDRESS, 0);
#endif
#ifdef EPD_TYPE_13INCH
   assert(processHttpDownload() == DL_OK && quartersPending());
   assert(settings.activeSlot == 1 && settings.lastModified == "next" && activeImageDigest == downloadedDigest);
   assert(EEPROM.read(QUARTER_ROTATION_ADDRESS) == 1);
   reset();
   usb = dropDuringConversion = true;
   assert(processHttpDownload() == DL_OK && quartersPending());
#else
   assert(processHttpDownload() == RENDER_USB_REQUIRED && writes == 0);
#endif
   reset();
   downloadedDigest.clear();
   assert(processHttpDownload() == RENDER_USB_REQUIRED && writes == 0);
   reset();
   previousImage = false;
   assert(processHttpDownload() == RENDER_USB_REQUIRED && writes == 0);
   reset();
   secondaryImageSlotAvailable = false;
   assert(processHttpDownload() == RENDER_USB_REQUIRED && writes == 0);
   reset();
   response = DL_DIGEST_ERROR;
   assert(processHttpDownload() == DL_DIGEST_ERROR && writes == 0 && settings.activeSlot == 0);
   reset();
   response = DL_NOT_MODIFIED;
   EEPROM.write(QUARTER_PROGRESS_ADDRESS, QUARTER_CLEANUP_DUE);
   assert(processHttpDownload() == DL_NOT_MODIFIED && writes == 0);
   assert(EEPROM.read(QUARTER_PROGRESS_ADDRESS) == QUARTER_CLEANUP_DUE);
   reset();
   usb = true;
   commitOk = false;
   EEPROM.write(QUARTER_PROGRESS_ADDRESS, QUARTER_CLEANUP_DUE);
   assert(processHttpDownload() == DL_FLASH_ERROR && writes == 1 && settings.activeSlot == 0);
   assert(!newImageNeedsRender() && settings.lastModified == "previous" && activeImageDigest == "previous digest");
   assert(EEPROM.read(QUARTER_PROGRESS_ADDRESS) == QUARTER_CLEANUP_DUE);
   reset();
   usb = true;
   convertOk = false;
   assert(processHttpDownload() == DL_FORMAT_ERROR && !newImageNeedsRender() && settings.activeSlot == 0);
   std::puts("PASS: battery download eligibility, USB loss, validation, unchanged source and slot commit rollback.");
}
