#pragma once
#include <ArduinoJson.h>
#include <cstring>

// Validate the entire patch before changing RAM or persistent settings.
// Constants match the existing EEPROM layout and remote settings protocol.
inline const char *validateSerialConfig(JsonVariantConst input) {
   if (!input.is<JsonObjectConst>() || input.as<JsonObjectConst>().size() == 0)
      return "Expected a nonempty JSON object";
   for (JsonPairConst entry : input.as<JsonObjectConst>()) {
      const char *key = entry.key().c_str();
      JsonVariantConst value = entry.value();
      size_t limit = 0;
      bool url = false;
      if (!strcmp(key, "wifiSsid")) limit = 32;
      else if (!strcmp(key, "wifiPassword")) limit = 64;
      else if (!strcmp(key, "httpAuthUser") || !strcmp(key, "httpAuthPassword")) limit = 128;
      else if (!strcmp(key, "downloadUrl") || !strcmp(key, "settingsUrl")) { limit = 128; url = true; }
      else if (!strcmp(key, "timeout")) {
         if (!value.is<int>() || value.as<int>() < 60 || value.as<int>() > 2592000)
            return "timeout must be an integer from 60 to 2592000 seconds";
      }
      else if (!strcmp(key, "imageMode") || !strcmp(key, "manualOrientation")) {
         if (!value.is<int>() || value.as<int>() < 0 || value.as<int>() > 1)
            return "imageMode and manualOrientation must be 0 or 1";
      }
      else if (!strcmp(key, "autoRotation") || !strcmp(key, "motionWakeup") ||
               !strcmp(key, "showBatteryWarning") || !strcmp(key, "showWifiWarning") ||
               !strcmp(key, "requireImageDigest") || !strcmp(key, "chargerMode") ||
               !strcmp(key, "confirmRechargeable")) {
         if (!value.is<bool>()) return "Boolean settings require true or false";
      }
      else return "Unknown or read-only configuration key";
      if (limit) {
         if (!value.is<const char *>()) return "String setting requires a JSON string";
         const JsonString text = value.as<JsonString>();
         if (text.size() > limit) return "String exceeds the EEPROM field capacity";
         for (size_t index = 0; index < text.size(); ++index)
            if (static_cast<unsigned char>(text.c_str()[index]) < 32 || text.c_str()[index] == 127)
               return "Control characters are not allowed in settings";
         if (url && text.size()) {
            const char *address = text.c_str();
            const size_t prefix = !strncmp(address, "https://", 8) ? 8 : (!strncmp(address, "http://", 7) ? 7 : 0);
            if (!prefix || text.size() <= prefix || address[prefix] == '/' || strchr(address, ' '))
               return "URL must have an http:// or https:// host, or be empty";
         }
      }
   }
#ifdef PANEL_TRUST_CONFIG
   if (input["requireImageDigest"].is<bool>() && !input["requireImageDigest"].as<bool>())
      return "Managed panels require an image digest";
#endif
   if (input["chargerMode"].as<bool>() && !input["confirmRechargeable"].as<bool>())
      return "Enabling charging requires confirmRechargeable:true (rechargeable batteries only)";
   return nullptr;
}

class SerialJsonInput {
 public:
   explicit SerialJsonInput(const char *text) : cursor(text) {}
   int read() { return *cursor ? static_cast<unsigned char>(*cursor++) : -1; }
   size_t readBytes(char *output, size_t length) {
      size_t count = 0;
      while (count < length && *cursor) output[count++] = *cursor++;
      return count;
   }
   bool hasTrailingData() const {
      const char *remaining = cursor;
      while (*remaining == ' ' || *remaining == '\t' || *remaining == '\r' || *remaining == '\n') ++remaining;
      return *remaining != '\0';
   }
 private:
   const char *cursor;
};

inline const char *parseSerialConfig(JsonDocument &document, const char *text) {
   SerialJsonInput input(text);
   const auto error = deserializeJson(document, input, DeserializationOption::NestingLimit(3));
   if (error || input.hasTrailingData()) return "Expected exactly one valid JSON object";
   return validateSerialConfig(document.as<JsonVariantConst>());
}
