#include "serial_line.h"
#include "serial_config.h"
#include <cassert>
#include <iostream>
#include <string>

static bool valid(const std::string &json) {
   JsonDocument document;
   return parseSerialConfig(document, json.c_str()) == nullptr;
}

int main() {
   SerialLine<128> input;
   using Event = SerialLine<128>::Event;
   assert(input.feed('B') == Event::Bootloader);
   assert(input.feed('b') == Event::Bootloader);
   const std::string command = "CONFIG SET {\"wifiPassword\":\"BBBBbb\\\"123\"}";
   for (char value : command) assert(input.feed(value) == Event::None);
   assert(input.feed('\r') == Event::Line);
   assert(command == input.line());
   assert(input.feed('\n') == Event::None);
   input.reset();
   for (int index = 0; index < 129; ++index) assert(input.feed('X') == Event::None);
   assert(input.feed('B') == Event::None);
   assert(input.feed('\n') == Event::Invalid);
   assert(input.feed('D') == Event::None);
   assert(input.feed('\0') == Event::None);
   assert(input.feed('B') == Event::None);
   assert(input.feed('\n') == Event::Invalid);
   for (char value : std::string("DIAX\bG\n")) input.feed(value);
   assert(std::string(input.line()) == "DIAG");
   input.reset();
   for (int index = 0; index < 128; ++index) assert(input.feed('X') == Event::None);
   assert(input.feed('\n') == Event::Line);
   assert(std::string(input.line()).size() == 128);
   assert(valid(R"({"timeout":60,"manualOrientation":1,"autoRotation":false})"));
   assert(valid(R"({"timeout":2592000,"downloadUrl":"https://host/image.bmp"})"));
   assert(valid(R"({"wifiPassword":"","downloadUrl":""})"));
   assert(valid(R"({"chargerMode":true,"confirmRechargeable":true})"));
   assert(valid("{\"timeout\":60} \t"));
   assert(!valid("{\"timeout\":60}junk"));
   assert(!valid("{\"timeout\":60}{\"timeout\":120}"));
   for (const char *json : {"{}", "[]", "null", R"({"timeout":59})", R"({"timeout":2592001})",
                           R"({"timeout":"60"})", R"({"timeout":60.5})", R"({"autoRotation":1})",
                           R"({"imageMode":2})", R"({"manualOrientation":-1})", R"({"wifiSsid":null})",
                           R"({"chargerMode":true})", R"({"chargerMode":true,"confirmRechargeable":false})",
                           R"({"downloadUrl":"file:///secret"})", R"({"downloadUrl":"https://"})",
                           R"({"wifiPassword":"before\u0000after"})", R"({"wifiPassword":"a\nb"})",
                           R"({"timeout":60,"unknown":true})", R"({"sleepDisabled":true})"}) assert(!valid(json));
   assert(valid("{\"wifiSsid\":\"" + std::string(32, 'a') + "\"}"));
   assert(!valid("{\"wifiSsid\":\"" + std::string(33, 'a') + "\"}"));
   assert(valid("{\"wifiPassword\":\"" + std::string(64, 'b') + "\"}"));
   assert(!valid("{\"wifiPassword\":\"" + std::string(65, 'b') + "\"}"));
   assert(!valid("{\"httpAuthPassword\":\"" + std::string(129, 'b') + "\"}"));
   std::cout << "Serial parser and configuration validation passed\n";
}
