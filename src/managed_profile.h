#pragma once

#include "serial_config.h"
#include <cstdint>

struct ManagedProfile {
   uint32_t revision;
   int interval;
   bool motionWakeup;
};

inline bool parseManagedProfile(const char *text, size_t length, uint32_t previousRevision, ManagedProfile &profile) {
   if (strlen(text) != length) return false;
   JsonDocument document;
   SerialJsonInput input(text);
   if (deserializeJson(document, input, DeserializationOption::NestingLimit(2)) || input.hasTrailingData()) return false;
   JsonObjectConst fields = document.as<JsonObjectConst>();
   if (fields.size() != 3 || !fields["revision"].is<uint32_t>() || !fields["timeout"].is<int>() ||
       !fields["motionWakeup"].is<bool>()) return false;
   uint32_t revision = fields["revision"].as<uint32_t>();
   int interval = fields["timeout"].as<int>();
   if (revision == UINT32_MAX || revision <= previousRevision || interval < 60 || interval > 2592000) return false;
   profile = {revision, interval, fields["motionWakeup"].as<bool>()};
   return true;
}
