#include "epaper_partial_13.h"

#ifdef EPD_TYPE_13INCH

#include "epaper_display.h"
#include <memory>
#include <new>

namespace {

constexpr int PANEL_WIDTH = 1200;
constexpr int PANEL_HEIGHT = 1600;
constexpr int CONTROLLER_WIDTH = PANEL_WIDTH / 2;

struct Region {
   int x;
   int y;
   int width;
   int height;
};

// writeImage() expects the GxEPD2 palette, which differs from both the saved raster and panel SPI codes.
constexpr uint8_t DRIVER_COLOR[7] = {0, 3, 2, 4, 1, 5, 1};

bool readRegion(SerialFlashFile &image, uint32_t imageOffset, const Region &region,
                bool rotate180, uint8_t *pixels) {
   const int rowBytes = region.width / 2;
   const int sourceX = rotate180 ? PANEL_WIDTH - region.x - region.width : region.x;
   for (int row = 0; row < region.height; row++) {
      const int sourceY = rotate180 ? PANEL_HEIGHT - 1 - region.y - row : region.y + row;
      image.seek(imageOffset + sourceY * (PANEL_WIDTH / 2) + sourceX / 2);
      uint8_t *destination = pixels + row * rowBytes;
      if (image.read(destination, rowBytes) != static_cast<uint32_t>(rowBytes))
         return false;
      if (rotate180) {
         for (int byte = 0; byte < (rowBytes + 1) / 2; byte++) {
            const uint8_t first = destination[byte];
            const uint8_t last = destination[rowBytes - 1 - byte];
            destination[byte] = (last << 4) | (last >> 4);
            destination[rowBytes - 1 - byte] = (first << 4) | (first >> 4);
         }
      }
      for (int byte = 0; byte < rowBytes; byte++) {
         const uint8_t high = destination[byte] >> 4;
         const uint8_t low = destination[byte] & 0x0F;
         if (high >= 7 || low >= 7 || high == 4 || low == 4)
            return false;
         destination[byte] = (DRIVER_COLOR[high] << 4) | DRIVER_COLOR[low];
      }
   }
   return true;
}

void writeCommand(SPIClass &spi, bool master, bool slave, uint8_t command,
                  const uint8_t *data = nullptr, size_t length = 0) {
   spi.beginTransaction(SPISettings(DISPLAY_SPI_SPEED, MSBFIRST, SPI_MODE0));
   digitalWrite(CS_EPD_PIN, master ? LOW : HIGH);
   digitalWrite(EPD_CS_S, slave ? LOW : HIGH);
   spi.transfer(command);
   for (size_t index = 0; index < length; index++)
      spi.transfer(data[index]);
   digitalWrite(CS_EPD_PIN, HIGH);
   digitalWrite(EPD_CS_S, HIGH);
   spi.endTransaction();
}

void armRegion(SPIClass &spi, int half, const Region &region) {
   const uint8_t mode[] = {0x49, 0x55, 0x13, 0x5D, 0x05, 0x10};
   const uint16_t left = (region.x - half * CONTROLLER_WIDTH) * 2;
   const uint16_t right = left + region.width * 2 - 1;
   const uint16_t top = region.y / 2;
   const uint16_t bottom = (region.y + region.height) / 2 - 1;
   const uint8_t window[] = {
       uint8_t(left >> 8), uint8_t(left), uint8_t(right >> 8), uint8_t(right),
       uint8_t(top >> 8), uint8_t(top), uint8_t(bottom >> 8), uint8_t(bottom), 0x01};
   writeCommand(spi, half == 0, half == 1, 0xF0, mode, sizeof(mode));
   writeCommand(spi, half == 0, half == 1, 0x83, window, sizeof(window));
}

bool waitReady(uint32_t timeoutMs, const char *stage) {
   delay(2);
   const uint32_t start = millis();
   while (digitalRead(BUSY_PIN) == LOW) {
      if (millis() - start >= timeoutMs) {
         Serial.printf("[EPD] Partial refresh timeout: %s\n", stage);
         return false;
      }
      delay(1);
   }
   return true;
}

} // namespace

bool padImageErrorBackground13(GFXcanvas1 &textMask, GFXcanvas1 &backgroundMask) {
   int left = textMask.width();
   int top = textMask.height();
   int right = 0;
   int bottom = 0;
   bool hasText = false;
   for (int y = 0; y < textMask.height(); y++) {
      for (int x = 0; x < textMask.width(); x++) {
         if (backgroundMask.getPixel(x, y)) {
            left = min(left, x);
            top = min(top, y);
            right = max(right, x + 1);
            bottom = max(bottom, y + 1);
         }
         if (textMask.getPixel(x, y)) {
            hasText = true;
            left = min(left, x - 4);
            top = min(top, y - 8);
            right = max(right, x + 5);
            bottom = max(bottom, y + 9);
         }
      }
   }
   if (!hasText || left < 0 || top < 0 || right > textMask.width() || bottom > textMask.height())
      return false;
   // Keep the old backing area inside the new window so recovery also removes older overlays.
   backgroundMask.fillRect(left, top, right - left, bottom - top, 1);
   return true;
}

bool writeImageErrorRegion13(SPIClass &spi, SerialFlashFile &image, uint32_t imageOffset,
                            GFXcanvas1 &textMask, GFXcanvas1 &backgroundMask,
                            int maskLeft, int maskTop, bool rotate180, bool doRefresh, bool showOverlay) {
   int left = textMask.width();
   int top = textMask.height();
   int right = 0;
   int bottom = 0;
   for (int y = 0; y < textMask.height(); y++) {
      for (int x = 0; x < textMask.width(); x++) {
         if (textMask.getPixel(x, y) || backgroundMask.getPixel(x, y)) {
            left = min(left, x);
            top = min(top, y);
            right = max(right, x + 1);
            bottom = max(bottom, y + 1);
         }
      }
   }
   if (left >= right || top >= bottom)
      return false;
   left = (maskLeft + left) & ~3;
   top = (maskTop + top) & ~1;
   right = (maskLeft + right + 3) & ~3;
   bottom = (maskTop + bottom + 1) & ~1;
   if (right - left < 16)
      right = left + 16;
   if (left < 0 || top < 0 || right > PANEL_WIDTH || bottom > PANEL_HEIGHT ||
       left / CONTROLLER_WIDTH != (right - 1) / CONTROLLER_WIDTH) {
      Serial.println("[EPD] Error region exceeds one controller; partial update rejected.");
      return false;
   }

   const Region region{left, top, right - left, bottom - top};
   const int half = left / CONTROLLER_WIDTH;
   // Both ICs must complete DRF. The other half needs a valid minimum 16x2 window.
   const Region companion{(1 - half) * CONTROLLER_WIDTH, 0, 16, 2};
   const size_t byteCount = region.width * region.height / 2;
   std::unique_ptr<uint8_t[]> pixels(new (std::nothrow) uint8_t[byteCount]);
   uint8_t companionPixels[16];
   if (!pixels || !readRegion(image, imageOffset, region, rotate180, pixels.get()) ||
       !readRegion(image, imageOffset, companion, rotate180, companionPixels)) {
      Serial.println("[EPD] Could not prepare partial image data.");
      return false;
   }
   for (int y = 0; showOverlay && y < region.height; y++) {
      for (int x = 0; x < region.width; x++) {
         const int maskX = region.x + x - maskLeft;
         const int maskY = region.y + y - maskTop;
         const bool text = textMask.getPixel(maskX, maskY);
         if (!text && !backgroundMask.getPixel(maskX, maskY))
            continue;
         uint8_t &packed = pixels[y * (region.width / 2) + x / 2];
         const uint8_t color = text ? 0 : 1;
         packed = x & 1 ? (packed & 0xF0) | color : (packed & 0x0F) | (color << 4);
      }
   }

   // Finish every flash read before selecting a panel IC on the shared SPI bus.
   display.enableQuickRefresh(0, false);
   display.init(115200);
   display.writeImage(pixels.get(), region.x, region.y, region.width, region.height);
   display.writeImage(companionPixels, companion.x, companion.y, companion.width, companion.height);
   armRegion(spi, half, region);
   armRegion(spi, 1 - half, companion);
   Serial.printf("[EPD] Partial overlay %s: x=%d y=%d w=%d h=%d bytes=%u; companion=16x2; DRF=0x01\n",
                 showOverlay ? "show" : "restore", region.x, region.y, region.width, region.height, unsigned(byteCount));
   if (!doRefresh)
      return true;

   writeCommand(spi, true, true, 0x04);
   if (!waitReady(10000, "power on"))
      return false;
   delay(30);
   const uint8_t refreshMode = 0x01;
   writeCommand(spi, true, true, 0x12, &refreshMode, 1);
   if (!waitReady(60000, "ink update"))
      return false;
   display.powerOff();
   if (!waitReady(10000, "power off"))
      return false;
   delay(300);
   const uint8_t disabledWindow[9] = {};
   writeCommand(spi, true, true, 0x83, disabledWindow, sizeof(disabledWindow));
   Serial.printf("[EPD] Partial overlay %s complete.\n", showOverlay ? "show" : "restore");
   return true;
}

#endif
