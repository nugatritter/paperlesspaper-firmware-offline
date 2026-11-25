#pragma once

#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ctime>
#include <sys/time.h>
#include "workshop_clock.h"

// The managed build supplies a DNS name, port and one public root certificate.
#include PANEL_TRUST_CONFIG
#ifdef PANEL_FIXED_IMAGE_CONFIG
#include PANEL_FIXED_IMAGE_CONFIG
#endif

// Deep sleep retains both the RTC timebase and this witness. A cold boot needs fresh workshop time.
static RTC_DATA_ATTR int64_t workshopTimeAnchor = 0;

static bool setWorkshopClock(const char *input) {
   int64_t epoch;
   if (!workshopEpoch(input, epoch)) return false;
   const int64_t current = time(nullptr);
   if (hasWorkshopClock(workshopTimeAnchor, current) && epoch <= current) {
      // Allow USB delivery latency without moving a trusted clock backwards.
      return current - epoch <= 3;
   }
   const timeval value{static_cast<time_t>(epoch), 0};
   if (settimeofday(&value, nullptr) != 0) return false;
   workshopTimeAnchor = epoch;
   return true;
}

static String panelOrigin() {
   String origin = String("https://") + panelHost;
   if (panelPort != 443) origin += ":" + String(panelPort);
   return origin;
}

static bool allowedPanelUrl(const String &url) {
   if (!url.startsWith(panelOrigin() + "/")) return false;
   for (size_t i = 0; i < url.length(); ++i) {
      const char c = url[i];
      if (static_cast<unsigned char>(c) <= 32 || c == 127 || c == '\\' || c == '#') return false;
   }
   return true;
}

static int64_t dateValue(int year, int month, int day, int hour, int minute, int second) {
   return (((((int64_t(year) * 100 + month) * 100 + day) * 100 + hour) * 100 + minute) * 100 + second);
}

static int64_t dateValue(const mbedtls_x509_time &date) {
   return dateValue(date.year, date.mon, date.day, date.hour, date.min, date.sec);
}

static bool validAt(const mbedtls_x509_crt *chain, int64_t now) {
   if (!chain) return false;
   for (; chain; chain = chain->next) {
      if (dateValue(chain->valid_from) > now || now > dateValue(chain->valid_to)) return false;
   }
   return true;
}

class PanelSecureClient : public WiFiClientSecure {
public:
#ifdef PANEL_FIXED_IMAGE_CONFIG
   bool fixedImage = false;
#endif
   int connect(const char *host, uint16_t port, int32_t timeout) override {
#ifdef PANEL_FIXED_IMAGE_CONFIG
      if (fixedImage) {
         if (strcmp(host, fixedImageHost) != 0 || port != fixedImagePort) return 0;
         setHandshakeTimeout((timeout + 999) / 1000);
         IPAddress address;
         if (!address.fromString(host) ||
             !WiFiClientSecure::connect(address, port, "eYellowboard", fixedImageRoot, nullptr, nullptr)) return 0;
         uint8_t fingerprint[32];
         if (getFingerprintSHA256(fingerprint) && !memcmp(fingerprint, fixedImageFingerprint, sizeof(fingerprint))) return 1;
         stop();
         return 0;
      }
#endif
      if (strcmp(host, panelHost) != 0 || port != panelPort) return 0;
      const time_t clock = time(nullptr);
      if (!hasWorkshopClock(workshopTimeAnchor, clock)) return 0;
      struct tm utc;
      if (!gmtime_r(&clock, &utc)) return 0;
      const int64_t now = dateValue(utc.tm_year + 1900, utc.tm_mon + 1, utc.tm_mday,
                                    utc.tm_hour, utc.tm_min, utc.tm_sec);
      // The prebuilt SDK omits certificate time checking. Check the root and
      // presented chain before HTTPClient can send any request headers.
      mbedtls_x509_crt root;
      mbedtls_x509_crt_init(&root);
      const bool trustedTime = mbedtls_x509_crt_parse(&root, (const uint8_t *)panelRoot,
                                                      strlen(panelRoot) + 1) == 0 && validAt(&root, now);
      mbedtls_x509_crt_free(&root);
      if (!trustedTime) return 0;
      setHandshakeTimeout((timeout + 999) / 1000);
#ifdef PANEL_TLS_LAB_ADDRESS
      int connected = WiFiClientSecure::connect(PANEL_TLS_LAB_ADDRESS, port, host, panelRoot, nullptr, nullptr);
#else
      int connected = WiFiClientSecure::connect(host, port, panelRoot, nullptr, nullptr);
#endif
      if (connected && !validAt(getPeerCertificate(), now)) {
         Serial.println("[TLS] Peer certificate outside validity period");
         stop();
         return 0;
      }
      return connected;
   }
};

static bool beginPanelRequest(HTTPClient &http, PanelSecureClient &client, const String &url) {
   http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
   return allowedPanelUrl(url) && http.begin(client, url);
}

static int getPanelResponse(HTTPClient &http) {
   for (unsigned redirects = 0; redirects <= 3; ++redirects) {
      const int status = http.GET();
      if (status != 301 && status != 302 && status != 303 && status != 307 && status != 308) return status;
      String location = http.getLocation();
      if (location.startsWith("/") && !location.startsWith("//")) location = panelOrigin() + location;
      if (redirects == 3 || !allowedPanelUrl(location)) return HTTPC_ERROR_CONNECTION_REFUSED;
      if (!http.setURL(location)) return HTTPC_ERROR_CONNECTION_REFUSED;
   }
   return HTTPC_ERROR_CONNECTION_REFUSED;
}
