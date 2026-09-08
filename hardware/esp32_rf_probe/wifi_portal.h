// wifi_portal — on-device captive-portal WiFi + backend setup.
//
// Replaces compile-time WIFI_SSID/WIFI_PASS/BACKEND_URL in config.h with a
// runtime flow: connect using NVS-stored credentials, or (first boot, no
// stored credentials, or BOOT button held at power-on) host a temporary
// "RF-Probe-Setup-XXXX" access point serving a setup page — scan nearby
// networks, pick one, enter its password, set the backend host/port/path,
// and toggle HTTPS. Saving writes to NVS and reboots into normal operation.
//
// The setup page itself is login-gated (HTTP Basic Auth, default admin/admin,
// changeable from the same page — router-style, like a fresh D-Link/TP-Link
// admin panel) since the setup AP is necessarily open. Holding BOOT for 10s+
// factory-resets (wipes WiFi creds AND the admin login back to admin/admin)
// so a mistyped new admin password can never permanently lock the portal.
//
// wifiPortal::begin() blocks until WiFi is connected (retrying the portal
// indefinitely on first-time setup, or with a 5-minute portal timeout before
// retrying stored credentials if a previously-working network is just
// transiently unreachable). Call it once from setup(); read wifiPortal::config()
// afterwards for the backend host/port/path/https settings.
//
// wifiPortal::pollForReconfigure(), called periodically from loop(), reopens
// the setup portal on demand (a plain BOOT press while already running
// normally -- no reboot needed) so the setup page stays reachable without
// making the board broadcast an open AP continuously. That was a deliberate
// choice over a permanent AP+STA setup network: an always-open, unauthenticated
// hotspot broadcasting nonstop is a bigger attack surface than one that only
// exists for the brief window after a deliberate physical button press, and
// running AP+STA concurrently forces the AP onto the same channel as the RF
// sampling, interrupting anyone connected to it every sampling cycle.
#pragma once

#include <Arduino.h>
#include <WiFi.h>

struct WifiPortalConfig {
  String backendHost;   // empty means "no backend configured" (Serial-only)
  uint16_t backendPort = 8000;
  String backendPath = "/live/ingest";
  bool https = false;
};

namespace wifiPortal {
  bool begin();
  const WifiPortalConfig& config();
  void pollForReconfigure();
}

// Shared with esp32_rf_probe.ino (which uses it to tag scanned APs in the
// sample JSON) and the portal page (which uses it to badge/warn on Open
// networks) -- one definition instead of two copies drifting apart.
inline const char* auth_name(wifi_auth_mode_t a) {
  switch (a) {
    case WIFI_AUTH_OPEN: return "open";
    case WIFI_AUTH_WEP: return "wep";
    case WIFI_AUTH_WPA_PSK: return "wpa";
    case WIFI_AUTH_WPA2_PSK: case WIFI_AUTH_WPA_WPA2_PSK: case WIFI_AUTH_WPA2_ENTERPRISE: return "wpa2";
    case WIFI_AUTH_WPA3_PSK: case WIFI_AUTH_WPA2_WPA3_PSK: return "wpa3";
#ifdef WIFI_AUTH_OWE
    case WIFI_AUTH_OWE: return "owe";
#endif
    default: return "wpa2";
  }
}
