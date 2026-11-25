"""Verify the production authorization parser with independent P-256 test keys."""
from pathlib import Path
import os
import shlex
import struct
import subprocess
import tempfile
from hashlib import sha256

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

root = Path(__file__).resolve().parents[1]
crypto = """
#include <openssl/evp.h>
#include <openssl/x509.h>
inline bool emergencyHash(EmergencyBytes bytes, uint8_t out[32]) {
    return EVP_Digest(bytes.data, bytes.size, out, nullptr, EVP_sha256(), nullptr) == 1;
}
inline bool emergencyVerify(EmergencyBytes key, EmergencyBytes message, EmergencyBytes signature) {
    auto publicKey = d2i_PUBKEY(nullptr, &key.data, key.size);
    auto context = EVP_MD_CTX_new();
    bool ok = publicKey && context &&
        EVP_DigestVerifyInit(context, nullptr, EVP_sha256(), nullptr, publicKey) == 1 &&
        EVP_DigestVerify(context, signature.data, signature.size, message.data, message.size) == 1;
    EVP_MD_CTX_free(context);
    EVP_PKEY_free(publicKey);
    return ok;
}
"""
harness = """
#include <iterator>
#include <fstream>
#include <vector>
#include <cstdlib>
static std::vector<uint8_t> load(const char *path) {
   std::ifstream input(path, std::ios::binary);
   return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}
int main(int argc, char **argv) {
   if (argc != 9) return 2;
   auto packet = load(argv[1]), issuer = load(argv[2]), nonce = load(argv[3]);
   EmergencyAuthorization authorization;
   bool ok = authorizeEmergency({packet.data(),packet.size()}, {issuer.data(),issuer.size()}, nonce.data(),
                                 argv[4], argv[5], std::stoull(argv[6]), std::stoull(argv[7]), authorization);
   return (ok ? authorization.operation : 0) == std::atoi(argv[8]) ? 0 : 1;
}
"""
source = (root/'src/emergency_auth.h').read_text().replace('#pragma once', '').replace('#include "emergency_crypto.h"', crypto)
issuer = ec.generate_private_key(ec.SECP256R1())
phone = ec.generate_private_key(ec.SECP256R1())
foreign = ec.generate_private_key(ec.SECP256R1())
now = 1_790_000_000
nonce = os.urandom(32)


def public(key):
    return key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def field(value):
    return bytes([len(value)])+value


def signed(key, message):
    return field(key.sign(message, ec.ECDSA(hashes.SHA256())))


def envelope(op=1, since=now, until=now+60, phone_signer=phone, signer=issuer, digest=None):
    grant = (b'EYB-EMERGENCY-IMAGE-1'+os.urandom(16)+struct.pack('>QQQ', since, until, 5)
             +field(b'P-1')+field(b'epd13-test')+field(public(phone)))
    action = bytes([op])+struct.pack('>I', 960118 if op == 1 else 0)+(digest if digest is not None else
            (bytes(32) if op == 2 else sha256(b'picture').digest()))
    proof = b'EYB-PHONE-PROOF-1'+nonce+sha256(grant).digest()+action
    return action+struct.pack('>H', len(grant))+grant+signed(signer,grant)+signed(phone_signer,proof)


with tempfile.TemporaryDirectory() as name:
    directory=Path(name)
    cpp=directory/'verify.cpp'
    cpp.write_text(source+harness)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','openssl'],text=True))
    exe=directory/'verify'
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-Wall','-Wextra','-Werror',str(cpp),*flags,'-o',str(exe)],check=True)
    keyfile, noncefile, packetfile = (directory/x for x in ('key','nonce','packet'))
    keyfile.write_bytes(public(issuer))
    valid=envelope()
    def verify(data, expected=0, challenge=nonce, asset='P-1', device='epd13-test', clock=now, generation=5):
        packetfile.write_bytes(data)
        noncefile.write_bytes(challenge)
        subprocess.run([exe,packetfile,keyfile,noncefile,asset,device,str(clock),str(generation),str(expected)],check=True)
    verify(valid,1)
    verify(envelope(op=2),2)
    verify(valid,challenge=os.urandom(32))
    verify(valid,asset='P-2')
    verify(valid,device='epd13-other')
    verify(valid,generation=6)
    verify(valid,clock=now+60)
    verify(valid,clock=now-1)
    verify(envelope(until=now+7*86400+1))
    verify(envelope(phone_signer=foreign))
    verify(envelope(signer=foreign))
    verify(envelope(op=2,digest=os.urandom(32)))
    for offset in (0, 3, 5, 38, len(valid)-1):
        changed=bytearray(valid)
        changed[offset]^=1
        verify(changed)
    for cut in (0, 1, 36, 38, 100, len(valid)-1):
        verify(valid[:cut])
    verify(valid+b'x')
    print('PASS scoped image and release, replay, expiry, revocation, wrong handset/issuer, malformed requests')

# Compile the exact BLE BMP admission check against both row orders used by the regular importer.
service = (root/"src/emergency_service.h").read_text()
predicate = service[service.index("   const bool completeHeader"):service.index("   saveFile.close();", service.index("   const bool completeHeader"))]
main = (root/"src/main.cpp").read_text()
endian = main[main.index("static uint16_t readLe16("):main.index("// Uncompressed BMP with")]
bmp_test = """
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
constexpr int IMG_WIDTH=1200, IMG_HEIGHT=1600;
struct {
  uint8_t bytes[54]{};
  size_t length=54;
  size_t read(uint8_t *out, size_t count) { memcpy(out,bytes,count); return length; }
} saveFile;
""" + endian + """
bool admitted() {
   uint8_t header[54];
""" + predicate + """
   return valid;
}
int main(int argc, char **argv) {
   assert(argc == 2);
   auto file = fopen(argv[1], "rb");
   assert(file && fread(saveFile.bytes, 1, 54, file) == 54);
   fclose(file);
   assert(admitted());
   const uint32_t reverse = 0u - readLe32(saveFile.bytes+22);
   for (int i=0; i<4; ++i) saveFile.bytes[22+i] = reverse >> (8*i);
   assert(admitted());
   saveFile.length = 53; assert(!admitted());
   saveFile.length = 54; saveFile.bytes[28] = 24; assert(!admitted());
   return 0;
}
"""
with tempfile.TemporaryDirectory() as name:
    directory = Path(name)
    cpp = directory/"bmp.cpp"
    cpp.write_text(bmp_test)
    exe = directory/"bmp"
    subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    str(cpp), "-o", str(exe)], check=True)
    # The fixture is the native bottom-up BMP from the project bench, without phone or grant data.
    import struct
    fixture = directory/"native.bmp"
    header = bytearray(54)
    header[:2] = b"BM"
    struct.pack_into("<IIiiHHI", header, 10, 118, 40, 1200, 1600, 1, 4, 0)
    fixture.write_bytes(header)
    subprocess.run([exe, fixture], check=True)
    print("PASS emergency BMP admission for bottom-up and top-down frames")
