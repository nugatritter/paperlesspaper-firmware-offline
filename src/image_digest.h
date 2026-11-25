#pragma once

#include <stddef.h>
#include <string.h>

enum class ImageDigestResult { Missing, Invalid, Present };

inline bool digestKeyChar(char c) {
   return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '*';
}

inline int digestBase64Value(char c) {
   if (c >= 'A' && c <= 'Z') return c - 'A';
   if (c >= 'a' && c <= 'z') return c - 'a' + 26;
   if (c >= '0' && c <= '9') return c - '0' + 52;
   return c == '+' ? 62 : c == '/' ? 63 : -1;
}

// Parse the byte-sequence dictionary emitted by an RFC 9530 image publisher.
inline ImageDigestResult readImageDigest(const char *field, char expected[45]) {
   expected[0] = 0;
   if (!*field) return ImageDigestResult::Missing;
   if (strlen(field) > 512) return ImageDigestResult::Invalid;
   const char *p = field;
   for (;;) {
      while (*p == ' ' || *p == '\t') ++p;
      const char *key = p;
      if (!((*p >= 'a' && *p <= 'z') || *p == '*')) return ImageDigestResult::Invalid;
      while (digestKeyChar(*p)) ++p;
      const bool sha256 = p-key == 7 && !memcmp(key,"sha-256",7);
      if (*p++ != '=' || *p++ != ':') return ImageDigestResult::Invalid;
      const char *encoded = p;
      while (digestBase64Value(*p) >= 0) ++p;
      const size_t digits = p-encoded;
      while (*p == '=') ++p;
      const size_t length = p-encoded;
      if (!digits || length % 4 || length-digits > 2 || *p++ != ':') return ImageDigestResult::Invalid;
      if (sha256) {
         if (*expected || length != 44 || digits != 43 || (digestBase64Value(encoded[42]) & 3))
            return ImageDigestResult::Invalid;
         memcpy(expected,encoded,44);
         expected[44] = 0;
      }
      while (*p == ' ' || *p == '\t') ++p;
      if (!*p) break;
      if (*p++ != ',') return ImageDigestResult::Invalid;
   }
   return *expected ? ImageDigestResult::Present : ImageDigestResult::Missing;
}
