// Host checks for the production partial-overlay implementation with simulated hardware.
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "render_journal.h"

using std::min;
using std::max;
constexpr int LOW = 0;
constexpr int HIGH = 1;
constexpr int CS_EPD_PIN = 20;
constexpr int EPD_CS_S = 19;
constexpr int BUSY_PIN = 18;
constexpr int MSBFIRST = 1;
constexpr int SPI_MODE0 = 0;
constexpr int DISPLAY_SPI_SPEED = 20000000;
int chipLevel[21];
uint32_t elapsedMs;
uint32_t busyUntil;
bool panelTouched;
bool hangRefresh;
bool refreshStarted;
int powerOffCalls;

struct Command {
   bool master;
   bool slave;
   std::vector<uint8_t> bytes;
};
std::vector<Command> commands;
void digitalWrite(int pin, int value) { chipLevel[pin] = value; }
int digitalRead(int) { return ((hangRefresh && refreshStarted) || elapsedMs < busyUntil) ? LOW : HIGH; }
void delay(uint32_t ms) { elapsedMs += ms; }
uint32_t millis() { return elapsedMs; }
void noteRenderStage(RenderStage) {}
void renderHeartbeat(const void *) { delay(1); }
struct SerialMock {
   std::string messages;
   void println(const char *message) { messages += std::string(message) + "\n"; }
   template <typename... Args> void printf(const char *format, Args... args) {
      char message[300];
      std::snprintf(message, sizeof(message), format, args...);
      messages += message;
   }
} Serial;
struct SPISettings { SPISettings(int, int, int) {} };
struct SPIClass {
   void beginTransaction(SPISettings) { commands.push_back({false, false, {}}); panelTouched = true; }
   void transfer(uint8_t value) {
      auto &command = commands.back();
      command.master = chipLevel[CS_EPD_PIN] == LOW;
      command.slave = chipLevel[EPD_CS_S] == LOW;
      assert(command.master || command.slave);
      command.bytes.push_back(value);
   }
   void endTransaction() {
      assert(chipLevel[CS_EPD_PIN] == HIGH && chipLevel[EPD_CS_S] == HIGH);
      if (commands.back().bytes.front() == 0x12) {
         refreshStarted = true;
         busyUntil = elapsedMs + 40;
      }
   }
} spi;
bool streamingStrips = false;
struct SerialFlashFile {
   std::vector<uint8_t> data;
   uint32_t position = 0;
   bool shortRead = false;
   void seek(uint32_t offset) { assert(!panelTouched || streamingStrips); position = offset; }
   uint32_t read(uint8_t *destination, uint32_t count) {
      assert(!panelTouched || streamingStrips);
      assert(chipLevel[CS_EPD_PIN] == HIGH && chipLevel[EPD_CS_S] == HIGH);
      if (shortRead || position + count > data.size())
         return 0;
      std::memcpy(destination, data.data() + position, count);
      position += count;
      return count;
   }
};
struct GFXcanvas1 {
   int canvasWidth, canvasHeight;
   std::vector<uint8_t> data;
   GFXcanvas1(int width, int height) : canvasWidth(width), canvasHeight(height), data(width * height) {}
   int width() const { return canvasWidth; }
   int height() const { return canvasHeight; }
   bool getPixel(int x, int y) const {
      return x >= 0 && y >= 0 && x < width() && y < height() && data[y * width() + x];
   }
   void drawPixel(int x, int y, int color) { data[y * width() + x] = color; }
   void fillRect(int x, int y, int width, int height, int color) {
      for (int row = y; row < y + height; row++)
         for (int column = x; column < x + width; column++)
            drawPixel(column, row, color);
   }
};
struct ImageWrite { int x, y, width, height; std::vector<uint8_t> pixels; };
struct DisplayMock {
   std::vector<ImageWrite> writes;
   void enableQuickRefresh(int, bool enabled) { assert(!enabled); panelTouched = true; }
   void init(int) { panelTouched = true; }
   void writeImage(const uint8_t *pixels, int x, int y, int width, int height) {
      assert((x % 4) == 0 && width >= 16 && (width % 4) == 0 && (y % 2) == 0 && (height % 2) == 0);
      writes.push_back({x, y, width, height, {pixels, pixels + width * height / 2}});
   }
   void powerOff() { assert(digitalRead(BUSY_PIN) == HIGH); powerOffCalls++; }
} display;
// The runner inserts the actual production function bodies here, without hardware includes.
// PRODUCTION_SOURCE

uint8_t sourceColor(int x, int y) {
   constexpr uint8_t palette[] = {0, 1, 2, 3, 5, 6};
   return palette[(x + x / 5 + y * 3) % 6];
}
uint8_t driverColor(uint8_t source) {
   switch (source) {
   case 0: return 0;
   case 1: return 3;
   case 2: return 2;
   case 3: return 4;
   case 5: return 5;
   case 6: return 1;
   default: assert(false); return 0;
   }
}
void reset() {
   std::fill(chipLevel, chipLevel + 21, HIGH);
   elapsedMs = busyUntil = 0;
   panelTouched = hangRefresh = refreshStarted = false;
   powerOffCalls = 0;
   commands.clear();
   display.writes.clear();
   Serial.messages.clear();
}
SerialFlashFile imageFixture(int offset) {
   SerialFlashFile image;
   image.data.resize(offset + 960000, 0xFF);
   for (int y = 0; y < 1600; y++)
      for (int x = 0; x < 1200; x += 2)
         image.data[offset + y * 600 + x / 2] = (sourceColor(x, y) << 4) | sourceColor(x + 1, y);
   return image;
}
void checkPixels(const ImageWrite &write, bool rotated, int maskLeft, GFXcanvas1 &text, GFXcanvas1 &background, bool overlay,
                 int maskTop = 24) {
   for (int y = 0; y < write.height; y++) {
      for (int x = 0; x < write.width; x++) {
         const int panelX = write.x + x, panelY = write.y + y;
         uint8_t expected = driverColor(sourceColor(rotated ? 1199 - panelX : panelX, rotated ? 1599 - panelY : panelY));
         if (overlay && background.getPixel(panelX - maskLeft, panelY - maskTop)) expected = 1;
         if (overlay && text.getPixel(panelX - maskLeft, panelY - maskTop)) expected = 0;
         const uint8_t packed = write.pixels[y * write.width / 2 + x / 2];
         assert(expected == ((x & 1) ? packed & 15 : packed >> 4));
      }
   }
}
int main() {
   int cases = 0;
   for (bool showOverlay : {false, true}) for (bool rotated : {false, true})
   for (int offset : {0, 118}) for (int maskLeft : {24, 1112}) {
      reset();
      auto image = imageFixture(offset);
      GFXcanvas1 text(64, 640), background(64, 640);
      background.fillRect(12, 8, 32, 564, 1);
      background.drawPixel(20, 20, 0);
      text.drawPixel(14, 10, 1);
      assert(writeImageErrorRegion13(spi, image, offset, text, background, maskLeft, 24, rotated, true, showOverlay, false));
      assert(display.writes.size() == 2);
      assert(display.writes[0].x == maskLeft + 12 && display.writes[0].y == 32);
      assert(display.writes[0].pixels.size() == 9024 && display.writes[1].pixels.size() == 16);
      checkPixels(display.writes[0], rotated, maskLeft, text, background, showOverlay);
      checkPixels(display.writes[1], rotated, maskLeft, text, background, false);
      assert(commands.size() == 7);
      for (int index : {0, 2}) assert(commands[index].bytes == std::vector<uint8_t>({0xF0, 0x49, 0x55, 0x13, 0x5D, 0x05, 0x10}));
      for (int index : {1, 3}) {
         const auto &bytes = commands[index].bytes;
         assert(bytes.size() == 10 && bytes[0] == 0x83 && bytes[9] == 1);
         const int left = (bytes[1] << 8) | bytes[2], right = (bytes[3] << 8) | bytes[4];
         assert(left % 8 == 0 && right % 8 == 7 && right - left + 1 >= 32);
      }
      assert(commands[4].bytes == std::vector<uint8_t>({0x04}));
      assert(commands[5].master && commands[5].slave && commands[5].bytes == std::vector<uint8_t>({0x12, 1}));
      assert(commands[6].bytes == std::vector<uint8_t>({0x83, 0, 0, 0, 0, 0, 0, 0, 0, 0}));
      assert(powerOffCalls == 1);
      cases++;
   }
   for (int failure : {0, 1, 2, 3}) {
      reset();
      auto image = imageFixture(0);
      GFXcanvas1 text(64, 640), background(64, 640);
      if (failure != 0) background.fillRect(12, 8, 32, 564, 1);
      if (failure == 1) image.shortRead = true;
      if (failure == 2) std::fill(image.data.begin(), image.data.end(), 0x44);
      if (failure == 3) hangRefresh = true;
      assert(!writeImageErrorRegion13(spi, image, 0, text, background, 1112, 24, false, true, true, false));
      if (failure != 3) assert(!panelTouched && commands.empty());
      else assert(elapsedMs >= 60000 && Serial.messages.find("complete.") == std::string::npos);
      cases++;
   }
   reset();
   auto image = imageFixture(0);
   GFXcanvas1 text(64, 640), background(64, 640);
   background.drawPixel(13, 9, 1);
   assert(writeImageErrorRegion13(spi, image, 0, text, background, 1112, 24, false, false, true, false));
   assert(display.writes[0].width == 16 && display.writes[0].height == 2);
   assert(commands.size() == 4 && !refreshStarted && powerOffCalls == 0);
   cases++;
   reset();
   SerialFlashFile missingImage;
   text.drawPixel(13, 9, 1);
   assert(writeImageErrorRegion13(spi, missingImage, 0, text, background, 1112, 24, false, true, true, true));
   assert(display.writes.size() == 2 && display.writes[0].width == 16 && display.writes[0].height == 2);
   assert(display.writes[1].pixels == std::vector<uint8_t>(16, 0x11));
   assert(commands[5].bytes == std::vector<uint8_t>({0x12, 1}));
   cases++;
   for (int paddingCase : {0, 1, 2}) {
      GFXcanvas1 glyphs(64, 640), backing(64, 640);
      if (paddingCase == 0) {
         glyphs.fillRect(16, 24, 24, 552, 1);
         backing.fillRect(12, 8, 32, 564, 1);
         assert(padImageErrorBackground13(glyphs, backing));
         assert(backing.getPixel(12, 8) && backing.getPixel(43, 583));
         assert(!backing.getPixel(44, 583) && !backing.getPixel(43, 584));
         reset();
         assert(writeImageErrorRegion13(spi, image, 0, glyphs, backing, 1112, 24, false, true, false, false));
         assert(display.writes[0].y == 32 && display.writes[0].height == 576);
         checkPixels(display.writes[0], false, 1112, glyphs, backing, false);
      }
      else {
         if (paddingCase == 1) glyphs.drawPixel(63, 24, 1);
         assert(!padImageErrorBackground13(glyphs, backing));
      }
      cases++;
   }
   // manualOrientation 1 streams the picture turned by 180 degrees: the overlay must turn with it
   // and appear at the same corner of the picture, i.e. the opposite corner of the panel.
   for (bool rotated : {false, true}) for (bool showOverlay : {true, false}) {
      GFXcanvas1 glyphs(64, 640), backing(64, 640);
      backing.fillRect(12, 8, 32, 564, 1);
      glyphs.drawPixel(14, 10, 1);
      int maskLeft = 1112, maskTop = 24;
      orientImageErrorMasks13(glyphs, backing, rotated, maskLeft, maskTop);
      if (rotated) {
         assert(maskLeft == 24 && maskTop == 936);
         assert(glyphs.getPixel(49, 629) && !glyphs.getPixel(14, 10));
         assert(backing.getPixel(20, 68) && backing.getPixel(51, 631));
         assert(!backing.getPixel(19, 68) && !backing.getPixel(20, 67) && !backing.getPixel(52, 631) && !backing.getPixel(51, 632));
      }
      else {
         assert(maskLeft == 1112 && maskTop == 24 && glyphs.getPixel(14, 10) && backing.getPixel(12, 8));
      }
      reset();
      auto rotatedImage = imageFixture(0);
      assert(writeImageErrorRegion13(spi, rotatedImage, 0, glyphs, backing, maskLeft, maskTop, rotated, true, showOverlay, false));
      const ImageWrite &write = display.writes[0];
      checkPixels(write, rotated, maskLeft, glyphs, backing, showOverlay, maskTop);
      // The glyph pixel sits at the picture's own position: panel point mapped through the 180-degree turn.
      const int glyphX = rotated ? 1199 - (1112 + 14) : 1112 + 14;
      const int glyphY = rotated ? 1599 - (24 + 10) : 24 + 10;
      assert(glyphX >= write.x && glyphX < write.x + write.width && glyphY >= write.y && glyphY < write.y + write.height);
      const uint8_t packed = write.pixels[(glyphY - write.y) * write.width / 2 + (glyphX - write.x) / 2];
      const uint8_t value = ((glyphX - write.x) & 1) ? packed & 15 : packed >> 4;
      assert(value == (showOverlay ? 0 : driverColor(sourceColor(rotated ? 1199 - glyphX : glyphX, rotated ? 1599 - glyphY : glyphY))));
      cases++;
   }
   streamingStrips = true;
   for (bool rotated : {false, true}) {
      auto candidate = imageFixture(118);
      SerialFlashFile previous;
      previous.data.assign(960000, 0x66);
      GFXcanvas1 empty(1, 1);
      for (unsigned quarter = 0; quarter < 4; ++quarter) {
         reset();
         assert(writeImageQuarter13(spi, candidate, 118, previous, 0, rotated, quarter));
         assert(display.writes.size() == 51);
         for (int strip = 0; strip < 50; ++strip) {
            auto &write = display.writes[strip];
            assert(write.width == 600 && write.height == 16 && write.x == int(quarter % 2) * 600 &&
                   write.y == int(quarter / 2) * 800 + strip * 16);
            checkPixels(write, rotated, 0, empty, empty, false);
         }
         const auto &companion = display.writes.back();
         assert(companion.width == 16 && companion.height == 2);
         if (quarter % 2) checkPixels(companion, rotated, 0, empty, empty, false);
         else assert(companion.pixels == std::vector<uint8_t>(16, 0x11));
         assert(commands[5].bytes == std::vector<uint8_t>({0x12, 1}) && powerOffCalls == 1);
         cases++;
      }
      reset();
      assert(!writeImageQuarter13(spi, candidate, 118, previous, 0, rotated, 4) && commands.empty());
      candidate.shortRead = true;
      assert(!writeImageQuarter13(spi, candidate, 118, previous, 0, rotated, 0) && !refreshStarted);
   }
   std::printf("PASS: %d partial-window cases (overlays, four quarters, palette, rotation, padding, SPI order and failures).\n", cases);
}
