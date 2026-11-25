#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Decode a complete, independent PackBits payload before writing any flash.
inline size_t unpackPictureBlock(const uint8_t *input, size_t length, uint8_t *output, size_t capacity) {
   size_t written = 0;
   while (length) {
      const uint8_t control = *input++;
      --length;
      if (control == 128) return 0;
      const bool literal = control < 128;
      const size_t count = literal ? control + 1 : 257 - control;
      const size_t consumed = literal ? count : 1;
      if (count > capacity - written || consumed > length) return 0;
      if (literal) memcpy(output + written, input, count);
      else memset(output + written, *input, count);
      input += consumed;
      length -= consumed;
      written += count;
   }
   return written;
}
