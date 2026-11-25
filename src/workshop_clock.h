#pragma once

#include <cstdint>

inline bool workshopEpoch(const char *text, int64_t &epoch) {
   int64_t value = 0;
   for (unsigned i = 0; i < 10; ++i) {
      if (text[i] < '0' || text[i] > '9') return false;
      value = value * 10 + (text[i] - '0');
   }
   if (text[10] || value < 1577836800 || value >= 4102444800LL) return false;
   epoch = value;
   return true;
}

inline bool hasWorkshopClock(int64_t anchor, int64_t current) {
   return anchor >= 1577836800 && current >= anchor && current < 4102444800LL;
}
