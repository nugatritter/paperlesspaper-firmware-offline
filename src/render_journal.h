#pragma once
#include <cstdint>

enum class RenderStage : uint8_t { None, Preparing, Streaming, Refreshing, Complete, Failed };

// Stored in the EEPROM blob, so a power loss cannot turn an unfinished render into success.
struct RenderJournal {
   uint32_t magic = 0;
   uint32_t attempt = 0;
   uint32_t startedMs = 0;
   uint32_t elapsedMs = 0;
   uint16_t batteryBeforeMv = 0;
   uint16_t batteryMinimumMv = 0;
   int16_t result = 0;
   uint8_t target = 0;
   uint8_t slot = 0;
   RenderStage stage = RenderStage::None;
   uint8_t reserved[3] = {};
};
static_assert(sizeof(RenderJournal) == 28, "Keep the persistent render record layout stable");
constexpr uint32_t RENDER_JOURNAL_MAGIC = 0x45595231;
constexpr int RENDER_JOURNAL_ADDRESS = 1340; // Settings currently end at byte 1331.

inline bool validRenderJournal(const RenderJournal &record) {
   return record.magic == RENDER_JOURNAL_MAGIC && record.stage >= RenderStage::Preparing &&
          record.stage <= RenderStage::Failed && record.slot <= 1 && record.target <= 6;
}

inline bool renderNeedsRecovery(const RenderJournal &record) {
   return validRenderJournal(record) && record.stage != RenderStage::Complete;
}

inline const char *renderStageName(RenderStage stage) {
   switch (stage) {
   case RenderStage::Preparing: return "preparing";
   case RenderStage::Streaming: return "streaming";
   case RenderStage::Refreshing: return "refreshing";
   case RenderStage::Complete: return "complete";
   case RenderStage::Failed: return "failed";
   default: return "none";
   }
}

void noteRenderStage(RenderStage stage);
void renderHeartbeat(const void *context);
