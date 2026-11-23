#pragma once
#include <esp_system.h>

inline const char *resetReasonName(esp_reset_reason_t reason) {
   switch (reason) {
   case ESP_RST_POWERON: return "POWERON";
   case ESP_RST_EXT: return "EXTERNAL_PIN";
   case ESP_RST_SW: return "SOFTWARE";
   case ESP_RST_PANIC: return "PANIC";
   case ESP_RST_INT_WDT: return "INTERRUPT_WATCHDOG";
   case ESP_RST_TASK_WDT: return "TASK_WATCHDOG";
   case ESP_RST_WDT: return "WATCHDOG";
   case ESP_RST_DEEPSLEEP: return "DEEP_SLEEP";
   case ESP_RST_BROWNOUT: return "BROWNOUT";
   case ESP_RST_SDIO: return "SDIO";
   case ESP_RST_USB: return "USB";
   case ESP_RST_JTAG: return "JTAG";
   case ESP_RST_EFUSE: return "EFUSE";
   case ESP_RST_PWR_GLITCH: return "POWER_GLITCH";
   case ESP_RST_CPU_LOCKUP: return "CPU_LOCKUP";
   default: return "UNKNOWN";
   }
}
