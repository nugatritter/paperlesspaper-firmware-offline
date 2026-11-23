// Exercise production render journaling and presentation recovery through simulated power loss.
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include "render_journal.h"
using std::min;
using String = std::string;
constexpr uint8_t DISPLAY_PICTURE = 0;
constexpr uint8_t DISPLAY_ERROR_TEXT = 2;
constexpr uint8_t DISPLAY_ERROR_OVERLAY = 4;
constexpr int EEPROM_DISPLAY_CONTENT_ADR = 230;
constexpr int EEPROM_SIZE = 2048;
constexpr int FAILSAVE_TIMER = 180;
constexpr int BUSY_PIN = 18;
uint8_t desiredPresentation;
uint8_t renderedPresentation;
bool renderPending;
bool panelReady;
bool eepromReady;
bool renderJournalStorageOk;
bool renderMonitoring;
uint32_t elapsedMs;
uint32_t lastRenderHeartbeat;
uint32_t lastRenderStatusLog;
int lastRenderLoggedVoltage;
int lastRenderBusyLevel;
RenderJournal renderJournal;
RenderJournal renderJournalAtBoot;
int renderResult;
int partialCalls;
int fullCalls;
int crcReads;
int batteryMv = 5350;
int batterySamples = 0;
bool interruptRender;
struct PowerCut {};
struct { bool chargerMode; uint8_t activeSlot; } settings;
struct { int vddValue; } systemData;
struct {
   std::array<uint8_t, EEPROM_SIZE> memory{}, persisted{};
   bool failCommit = false;
   int commits = 0;
   template<class T> void get(int address, T &value) { std::memcpy(&value, memory.data() + address, sizeof(T)); }
   template<class T> void put(int address, const T &value) { std::memcpy(memory.data() + address, &value, sizeof(T)); }
   void write(int address, uint8_t value) { memory[address] = value; }
   uint8_t read(int address) { return memory[address]; }
   bool commit() {
      if (failCommit) return false;
      persisted = memory;
      commits++;
      return true;
   }
} EEPROM;
struct {
   int logCount = 0;
   void println(const char *) { logCount++; }
   template<typename... Args> void printf(const char *, Args...) { logCount++; }
} Serial;
struct { struct { void setBusyCallback(void (*)(const void *), const void *) {} } epd2; } display;
struct { template<typename... Args> void once_ms(Args...) {} } tickerFailsave;
void timeoutFailsafe(int) {}
void ledBlink(int, bool) {}
void chargeMode(bool) {}
int readVDD(bool, bool = true) { batterySamples++; return batteryMv; }
int digitalRead(int) { return panelReady ? 1 : 0; }
uint32_t millis() { return elapsedMs; }
void delay(uint32_t ms) { elapsedMs += ms; }
void logImageSlotCrc(const char *) { crcReads++; }
bool waitDisplayComplete(bool) { return panelReady; }
int performRender() {
   noteRenderStage(RenderStage::Streaming);
   noteRenderStage(RenderStage::Refreshing);
   elapsedMs += 1500;
   renderHeartbeat(nullptr);
   if (interruptRender) throw PowerCut{};
   return renderResult;
}
int setImageFromFS(const String &) { fullCalls++; return performRender(); }
int restoreImageErrorOverlay(const String &) { partialCalls++; return performRender(); }

// PRODUCTION_SOURCE

void reset(uint8_t presentation = DISPLAY_ERROR_OVERLAY) {
   EEPROM = {};
   EEPROM.write(EEPROM_DISPLAY_CONTENT_ADR, presentation);
   EEPROM.commit();
   renderedPresentation = desiredPresentation = presentation;
   renderPending = renderMonitoring = interruptRender = false;
   panelReady = eepromReady = renderJournalStorageOk = true;
   renderResult = partialCalls = fullCalls = crcReads = 0;
   renderJournal = renderJournalAtBoot = {};
   settings = {true, 0};
   batteryMv = 5350;
   batterySamples = 0;
   elapsedMs = 100;
}
void reboot() {
   EEPROM.memory = EEPROM.persisted;
   renderMonitoring = false;
   loadRenderJournal();
   renderedPresentation = EEPROM.read(EEPROM_DISPLAY_CONTENT_ADR);
   renderPending = renderNeedsRecovery(renderJournal);
   interruptRender = false;
}
void checkCalls(bool partialRequested) {
#ifdef EPD_TYPE_13INCH
   const bool partialExpected = partialRequested;
#else
   (void)partialRequested;
   const bool partialExpected = false;
#endif
   assert(partialCalls == (partialExpected ? 1 : 0));
   assert(fullCalls == (partialExpected ? 0 : 1));
}
int main() {
   reset();
   assert(showStoredImage("slot", true) == 0);
   checkCalls(true);
   assert(!renderPending && renderedPresentation == DISPLAY_PICTURE);
   assert(EEPROM.read(EEPROM_DISPLAY_CONTENT_ADR) == DISPLAY_PICTURE);
   reboot();
   assert(!renderPending && renderJournal.stage == RenderStage::Complete);
   assert(renderJournal.batteryMinimumMv == 5350);

   reset();
   assert(showStoredImage("new-slot", false) == 0);
   checkCalls(false);
   reset(DISPLAY_ERROR_TEXT);
   assert(showStoredImage("slot", true) == 0);
   checkCalls(false);

   // Unchanged HTTP success must fully redraw after an interrupted refresh, even if the
   // previous completed presentation was an overlay and would normally use a small window.
   for (const uint8_t previous : {DISPLAY_PICTURE, DISPLAY_ERROR_OVERLAY}) {
      reset(previous);
      interruptRender = true;
      try { showStoredImage("slot"); assert(false); } catch (const PowerCut &) {}
      reboot();
      assert(renderPending && renderJournalAtBoot.stage == RenderStage::Refreshing);
      assert(EEPROM.read(EEPROM_DISPLAY_CONTENT_ADR) == previous);
      partialCalls = fullCalls = 0;
      assert(showStoredImage("slot", true) == 0);
      checkCalls(false);
      reboot();
      assert(!renderPending && renderJournal.stage == RenderStage::Complete);
   }

   for (const bool busyTimeout : {false, true}) {
      reset();
      if (busyTimeout) panelReady = false;
      else renderResult = -1;
      assert(showStoredImage("slot", true) == -1);
      assert(renderPending && renderedPresentation == DISPLAY_ERROR_OVERLAY);
      reboot();
      assert(renderPending && renderJournal.stage == RenderStage::Failed);
      assert(EEPROM.read(EEPROM_DISPLAY_CONTENT_ADR) == DISPLAY_ERROR_OVERLAY);
   }

   reset();
   EEPROM.failCommit = true;
   assert(showStoredImage("slot") == -1);
   assert(fullCalls == 0 && partialCalls == 0 && !renderJournalStorageOk);

   reset();
   EEPROM.memory.fill(0xff);
   loadRenderJournal();
   assert(!validRenderJournal(renderJournal) && !renderNeedsRecovery(renderJournal));

   reset();
   assert(beginImageRender(DISPLAY_PICTURE));
   renderHeartbeat(nullptr);
   const int initialLogs = Serial.logCount;
   const int initialCommits = EEPROM.commits;
   for (int second = 1; second <= 9; second++) {
      elapsedMs = renderJournal.startedMs + second * 1000;
      renderHeartbeat(nullptr);
   }
   assert(Serial.logCount == initialLogs && batterySamples == 10);
   elapsedMs = renderJournal.startedMs + 10000;
   renderHeartbeat(nullptr);
   assert(Serial.logCount == initialLogs + 1);
   batteryMv -= 499;
   elapsedMs += 1000;
   renderHeartbeat(nullptr);
   assert(Serial.logCount == initialLogs + 1);
   batteryMv -= 1;
   elapsedMs += 1000;
   renderHeartbeat(nullptr);
   assert(Serial.logCount == initialLogs + 2 && renderJournal.batteryMinimumMv == 4850);
   panelReady = false;
   renderHeartbeat(nullptr);
   assert(Serial.logCount == initialLogs + 3);
   assert(EEPROM.commits == initialCommits);
   std::puts("PASS: persistent render recovery, completion, failure, power-cut and quiet telemetry cases.");
}
