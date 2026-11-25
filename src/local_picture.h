// Included by the managed epd13 image service.
#include <qrcode.h>
#include <mbedtls/md.h>

namespace localPicture {
constexpr uint32_t scanWindow = 90000;
static uint8_t secret[16];
static bool requested, issued, ready, active;
static uint32_t visibleSince;
static uint8_t requestedCommand;

static bool draw(bool show) {
   constexpr int scale = 4, version = 3, side = (29 + 8) * scale;
   GFXcanvas1 modules(side, side), background(side, side);
   if (!modules.getBuffer() || !background.getBuffer()) return false;
   background.fillScreen(1);
   modules.fillScreen(0);
   if (show) {
      char payload[37] = "EYB:";
      for (size_t i = 0; i < sizeof(secret); ++i) snprintf(payload + 4 + i*2, 3, "%02X", secret[i]);
      QRCode code;
      uint8_t buffer[qrcode_getBufferSize(version)];
      if (qrcode_initText(&code, buffer, version, ECC_LOW, payload) != 0) return false;
      for (int y = 0; y < code.size; ++y)
         for (int x = 0; x < code.size; ++x)
            if (qrcode_getModule(&code, x, y)) modules.fillRect((4+x)*scale, (4+y)*scale, scale, scale, 1);
   }
   int left = 1200-side-8, top = 1600-side-8;
   const bool rotated = displaySettings.rotationPicture > 0;
   orientImageErrorMasks13(modules, background, rotated, left, top);
   powerSupplyDisplay(true);
   prepareSpiBusForFlash();
   auto image = SerialFlash.open(activeImageSlotName());
   uint32_t offset;
   const bool ok = storedRasterOffset(image, offset) && writeImageErrorRegion13(SPI, image, offset,
           modules, background, left, top, rotated, true, show);
   if (image) image.close();
   powerSupplyDisplay(false);
   return ok;
}

static bool mark(bool visible) {
   Preferences record;
   return record.begin("local-picture", false) && record.putBool("overlay", visible) == sizeof(bool);
}

static void restore() {
   Preferences record;
   if (record.begin("local-picture", true) && record.getBool("overlay", false)) {
      record.end();
      if (draw(false)) mark(false);
   }
}

static bool verify(const uint8_t *packet, size_t length, const uint8_t nonce[32], EmergencyAuthorization &result) {
   if (!ready || millis()-visibleSince >= scanWindow || length != 69 || packet[0] != requestedCommand) return false;
   uint8_t message[32 + sizeof(CLIENT_ID) + 37], expected[32];
   size_t idSize = strlen(CLIENT_ID);
   memcpy(message, nonce, 32);
   memcpy(message+32, CLIENT_ID, idSize);
   memcpy(message+32+idSize, packet, 37);
   auto algorithm = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
   if (!algorithm || mbedtls_md_hmac(algorithm, secret, sizeof(secret), message, 69+idSize, expected)) return false;
   unsigned mismatch = 0;
   for (unsigned i = 0; i < 32; ++i) mismatch |= expected[i] ^ packet[37+i];
   if (mismatch) return false;
   result = {};
   if (requestedCommand == 4) {
      for (size_t i = 1; i < 37; ++i) if (packet[i] != 0) return false;
   }
   result.operation = requestedCommand == 4 ? 2 : 1;
   result.length = emergencyNumber(packet+1, 4);
   memcpy(result.digest, packet+5, 32);
   ready = false;
   memset(secret, 0, sizeof(secret));
   active = true;
   return true;
}
}
