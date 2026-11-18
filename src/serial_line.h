#pragma once
#include <stddef.h>

// B/b is reserved only at the beginning of a line for existing USB flashers.
// Invalid/oversized lines are discarded through their terminator, including B.
template <size_t Capacity> class SerialLine {
 public:
   enum class Event { None, Line, Bootloader, Invalid };
   Event feed(char value) {
      if (value == '\r' || value == '\n') {
         if (discarding) {
            reset();
            return Event::Invalid;
         }
         if (length == 0)
            return Event::None;
         buffer[length] = '\0';
         length = 0;
         return Event::Line;
      }
      if (discarding)
         return Event::None;
      if (value == '\b' || value == 127) {
         if (length > 0) buffer[--length] = '\0';
         return Event::None;
      }
      if (length == 0 && (value == 'B' || value == 'b'))
         return Event::Bootloader;
      if ((static_cast<unsigned char>(value) < 32 && value != '\t') || length == Capacity) {
         discarding = true;
         return Event::None;
      }
      buffer[length++] = value;
      return Event::None;
   }
   const char *line() const { return buffer; }
   void reset() {
      for (size_t index = 0; index <= Capacity; ++index) buffer[index] = '\0';
      length = 0;
      discarding = false;
   }
 private:
   char buffer[Capacity + 1] = {};
   size_t length = 0;
   bool discarding = false;
};
