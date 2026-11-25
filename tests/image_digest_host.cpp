#include "../src/image_digest.h"
#include <cassert>
#include <string>

int main() {
   char expected[45] = {};
   const std::string value = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
   const std::string sha = "sha-256=:" + value + ":";
   assert(readImageDigest(sha.c_str(), expected) == ImageDigestResult::Present);
   assert(value == expected);
   assert(readImageDigest(("other=:AQID:, " + sha).c_str(), expected) == ImageDigestResult::Present);
   assert(readImageDigest("", expected) == ImageDigestResult::Missing);
   assert(readImageDigest("other=:AQID:", expected) == ImageDigestResult::Missing);
   for (const auto &invalid : {sha+",", sha+","+sha, sha.substr(0,sha.size()-1),
                               std::string("sha-256=:abc:"), std::string("sha-256=::::"),
                               "sha-256=:" + std::string(42,'A')+"B=:"})
      assert(readImageDigest(invalid.c_str(), expected) == ImageDigestResult::Invalid);
}
