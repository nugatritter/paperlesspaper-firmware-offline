// Exercise the production presentation transition with simulated display completion and EEPROM.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>

using String = std::string;
constexpr uint8_t DISPLAY_PICTURE = 0;
constexpr uint8_t DISPLAY_ERROR_TEXT = 2;
constexpr uint8_t DISPLAY_ERROR_OVERLAY = 4;
uint8_t desiredPresentation;
uint8_t renderedPresentation;
uint8_t storedPresentation;
bool renderPending;
bool panelReady;
int renderResult;
int partialCalls;
int fullCalls;
int crcReads;
int commits;
struct { void println(const char *) {} } Serial;
void logImageSlotCrc(const char *) { crcReads++; }
int setImageFromFS(const String &) { fullCalls++; return renderResult; }
int restoreImageErrorOverlay(const String &) { partialCalls++; return renderResult; }
bool waitDisplayComplete(bool) { return panelReady; }
void setDisplayContent(uint8_t state) { storedPresentation = state; commits++; }

// PRODUCTION_SOURCE

void reset(uint8_t presentation = DISPLAY_ERROR_OVERLAY) {
   storedPresentation = renderedPresentation = desiredPresentation = presentation;
   renderPending = false;
   panelReady = true;
   renderResult = partialCalls = fullCalls = crcReads = commits = 0;
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
   assert(crcReads == (partialExpected ? 0 : 1));
}
int main() {
   // Both HTTP 304 and HTTP 200 with a matching validator arrive as sourceUnchanged=true.
   reset();
   assert(showStoredImage("slot", true) == 0);
   checkCalls(true);
   assert(!renderPending && renderedPresentation == DISPLAY_PICTURE && storedPresentation == DISPLAY_PICTURE);
   assert(commits == 1);

   // A newly committed image must receive a complete render even when an overlay was present.
   reset();
   assert(showStoredImage("new-slot", false) == 0);
   checkCalls(false);

   // The legacy full-screen error cannot be cleared by restoring just a text rectangle.
   reset(DISPLAY_ERROR_TEXT);
   assert(showStoredImage("slot", true) == 0);
   checkCalls(false);

   reset();
   renderPending = true;
   assert(showStoredImage("slot", true) == 0);
   checkCalls(true);
   assert(!renderPending);

   // A failed restore must keep the persistent overlay marker and allow a later retry.
   reset();
   renderResult = -1;
   assert(showStoredImage("slot", true) == -1);
   checkCalls(true);
   assert(renderPending && desiredPresentation == DISPLAY_PICTURE);
   assert(renderedPresentation == DISPLAY_ERROR_OVERLAY && storedPresentation == DISPLAY_ERROR_OVERLAY && commits == 0);

   reset();
   panelReady = false;
   assert(showStoredImage("slot", true) == -1);
   assert(renderPending && storedPresentation == DISPLAY_ERROR_OVERLAY && commits == 0);

   // BLE APPLY and other explicit renders do not claim that their source is unchanged.
   reset();
   assert(showStoredImage("slot") == 0);
   checkCalls(false);
   std::puts("PASS: 7 presentation recovery cases.");
}
