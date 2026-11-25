#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

struct EmergencyBytes {
   const uint8_t *data;
   size_t size;

   bool take(size_t count, EmergencyBytes &part) {
      if (count > size) return false;
      part = {data, count};
      data += count;
      size -= count;
      return true;
   }

   bool byteField(EmergencyBytes &field) {
      if (!size) return false;
      const unsigned count = *data++;
      --size;
      return count && take(count, field);
   }

   bool matches(const char *text) const {
      return size == strlen(text) && memcmp(data, text, size) == 0;
   }
};

inline uint64_t emergencyNumber(const uint8_t *data, unsigned size) {
   uint64_t result = 0;
   while (size--) result = result * 256 + *data++;
   return result;
}

#include "emergency_crypto.h"

struct EmergencyAuthorization {
   uint8_t operation = 0;
   uint32_t length = 0;
   uint8_t digest[32]{};
   uint64_t expires = 0;
   uint64_t generation = 0;
};

inline bool authorizeEmergency(EmergencyBytes packet, EmergencyBytes issuer, const uint8_t nonce[32],
                               const char *panel, const char *hardware, uint64_t now, uint64_t floor,
                               EmergencyAuthorization &authorization) {
   constexpr char scope[] = "EYB-EMERGENCY-IMAGE-1";
   constexpr char proof[] = "EYB-PHONE-PROOF-1";
   EmergencyBytes operation{}, grantSize{}, grant{}, issuerSignature{}, phoneSignature{};
   if (!packet.take(37, operation) || !packet.take(2, grantSize) ||
       !packet.take(emergencyNumber(grantSize.data, 2), grant) || !packet.byteField(issuerSignature) ||
       !packet.byteField(phoneSignature) || packet.size || !emergencyVerify(issuer, grant, issuerSignature)) return false;
   const uint8_t op = operation.data[0];
   const uint32_t size = emergencyNumber(operation.data + 1, 4);
   const uint8_t zero[32] = {};
   if ((op != 1 && op != 2) || (op == 1 && !size) ||
       (op == 2 && (size || memcmp(operation.data + 5, zero, 32)))) return false;
   EmergencyBytes cursor = grant, domain{}, metadata{}, asset{}, device{}, phone{};
   if (!cursor.take(sizeof(scope)-1, domain) || !domain.matches(scope) || !cursor.take(40, metadata) ||
       !cursor.byteField(asset) || !asset.matches(panel) || !cursor.byteField(device) || !device.matches(hardware) ||
       !cursor.byteField(phone) || cursor.size) return false;
   const uint64_t from = emergencyNumber(metadata.data + 16, 8);
   const uint64_t until = emergencyNumber(metadata.data + 24, 8);
   const uint64_t generation = emergencyNumber(metadata.data + 32, 8);
   if (now < from || now >= until || until <= from || until-from > 7*86400 || generation < floor) return false;
   uint8_t binding[sizeof(proof)-1 + 32 + 32 + 37];
   uint8_t *out = binding;
   memcpy(out, proof, sizeof(proof)-1);
   out += sizeof(proof)-1;
   memcpy(out, nonce, 32);
   out += 32;
   if (!emergencyHash(grant, out)) return false;
   memcpy(out + 32, operation.data, operation.size);
   if (!emergencyVerify(phone, {binding, sizeof(binding)}, phoneSignature)) return false;
   authorization.operation = op;
   authorization.length = size;
   memcpy(authorization.digest, operation.data + 5, 32);
   authorization.expires = until;
   authorization.generation = generation;
   return true;
}
