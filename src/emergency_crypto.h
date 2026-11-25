#pragma once
#include <mbedtls/pk.h>
#include <mbedtls/sha256.h>

inline bool emergencyHash(EmergencyBytes bytes, uint8_t output[32]) {
   return mbedtls_sha256(bytes.data, bytes.size, output, 0) == 0;
}

inline bool emergencyVerify(EmergencyBytes key, EmergencyBytes message, EmergencyBytes signature) {
   uint8_t hash[32];
   mbedtls_pk_context context;
   mbedtls_pk_init(&context);
   const bool verified = emergencyHash(message, hash) &&
       mbedtls_pk_parse_public_key(&context, key.data, key.size) == 0 &&
       mbedtls_pk_can_do(&context, MBEDTLS_PK_ECDSA) &&
       mbedtls_pk_verify(&context, MBEDTLS_MD_SHA256, hash, sizeof(hash), signature.data, signature.size) == 0;
   mbedtls_pk_free(&context);
   return verified;
}
