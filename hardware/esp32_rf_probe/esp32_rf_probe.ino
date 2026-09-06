// esp32_rf_probe — 2.4 GHz RF probe for the RF Root-Cause SLM.
//
// Samples one channel: Wi-Fi scan + a promiscuous capture window + BLE scan,
// then emits one JSON object (see README.md). Normalised by adapters/esp32.py.
//
// ESP32-WROOM: 2.4 GHz only, no spectrum analyser -> spectrum_capable is always
// false downstream. Board package >= 3.0, ArduinoJson >= 7.

#include "config.h"

#include <WiFi.h>
#include <esp_wifi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include <BLEDevice.h>
#include <BLEScan.h>

static const char* FW_VERSION = "0.1.0";

// ---------------------------------------------------------------------------
// promiscuous capture state (written from the RX callback)
// ---------------------------------------------------------------------------
struct Counters {
  volatile uint32_t frames, retry, fcs, beacons, data, mgmt, ctrl;
  volatile int64_t  airtime_us;
  volatile int64_t  nf_sum, rssi_sum;
  volatile uint32_t nf_n;
};
static Counters C;

// unique transmitter MACs seen this window
static uint8_t  uniq[96][6];
static uint32_t uniq_n = 0;

// per-BSSID beacon-IE facts, merged into the scan list at output time
struct BeaconInfo { uint8_t bssid[6]; char country[4]; float min_rate; bool ht; int csa_to; };
static BeaconInfo beacons[32];
static uint32_t   beacons_n = 0;

static void reset_window() {
  memset((void*)&C, 0, sizeof(C));
  uniq_n = 0;
  beacons_n = 0;
}

static bool mac_eq(const uint8_t* a, const uint8_t* b) { return memcmp(a, b, 6) == 0; }

static void note_uniq(const uint8_t* mac) {
  if (mac[0] & 0x01) return;                      // group/broadcast, not a station
  for (uint32_t i = 0; i < uniq_n; i++) if (mac_eq(uniq[i], mac)) return;
  if (uniq_n < sizeof(uniq) / 6) memcpy(uniq[uniq_n++], mac, 6);
}

static BeaconInfo* beacon_slot(const uint8_t* bssid) {
  for (uint32_t i = 0; i < beacons_n; i++) if (mac_eq(beacons[i].bssid, bssid)) return &beacons[i];
  if (beacons_n >= 32) return nullptr;
  BeaconInfo* b = &beacons[beacons_n++];
  memset(b, 0, sizeof(*b)); memcpy(b->bssid, bssid, 6); b->csa_to = -1; b->min_rate = 0;
  return b;
}

static void parse_beacon_ies(const uint8_t* p, uint16_t len, BeaconInfo* b) {
  // mgmt header 24 + fixed params 12 = 36, then tagged IEs
  uint16_t i = 36;
  while (i + 2 <= len) {
    uint8_t tag = p[i], tlen = p[i + 1];
    const uint8_t* d = p + i + 2;
    if (i + 2 + tlen > len) break;
    if (tag == 1 && tlen > 0) {                   // Supported Rates
      float mn = 1e9;
      for (uint8_t k = 0; k < tlen; k++)
        if (d[k] & 0x80) mn = min(mn, (d[k] & 0x7F) * 0.5f);   // basic rate
      if (mn < 1e9) b->min_rate = mn;
    } else if (tag == 7 && tlen >= 2) {           // Country
      b->country[0] = d[0]; b->country[1] = d[1]; b->country[2] = 0;
    } else if (tag == 37 && tlen >= 2) {          // Channel Switch Announcement
      b->csa_to = d[1];
    } else if (tag == 45 || tag == 61) {          // HT Capabilities / Operation
      b->ht = true;
    }
    i += 2 + tlen;
  }
}

// coarse per-frame airtime: 20 us preamble + bytes at an assumed rate
static int64_t airtime_estimate(const wifi_pkt_rx_ctrl_t& rx) {
  float mbps = 6.0f;                              // conservative OFDM floor
  if (rx.sig_mode == 0) mbps = (rx.rate <= 3) ? 2.0f : 11.0f;   // 11b
  else if (rx.mcs >= 4) mbps = 39.0f;
  else mbps = 13.0f;
  return (int64_t)(20 + (rx.sig_len * 8.0f) / mbps);
}

static void IRAM_ATTR rx_cb(void* buf, wifi_promiscuous_pkt_type_t type) {
  auto* pkt = (wifi_promiscuous_pkt_t*)buf;
  const wifi_pkt_rx_ctrl_t& rx = pkt->rx_ctrl;
  const uint8_t* p = pkt->payload;

  C.frames++;
  C.nf_sum += rx.noise_floor; C.nf_n++;
  C.rssi_sum += rx.rssi;
  C.airtime_us += airtime_estimate(rx);
  if (rx.rx_state != 0) { C.fcs++; return; }      // FCS error — header may be junk

  uint8_t ftype = (p[0] >> 2) & 0x3, subtype = (p[0] >> 4) & 0xF;
  if (p[1] & 0x08) C.retry++;

  if (ftype == 0) {                               // management
    C.mgmt++;
    const uint8_t* sa = p + 10;
    if (subtype == 8) {                            // beacon
      C.beacons++;
      BeaconInfo* b = beacon_slot(p + 16);         // addr3 = BSSID
      if (b) parse_beacon_ies(p, rx.sig_len, b);
    } else {
      note_uniq(sa);
    }
  } else if (ftype == 1) {                        // control
    C.ctrl++;
  } else if (ftype == 2) {                        // data
    C.data++;
    note_uniq(p + 10);                             // addr2
  }
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
static void mac_str(const uint8_t* m, char* out) {
  sprintf(out, "%02x:%02x:%02x:%02x:%02x:%02x", m[0], m[1], m[2], m[3], m[4], m[5]);
}

static const char* auth_name(wifi_auth_mode_t a) {
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

static bool iso_now(char* out, size_t n) {
  time_t t = time(nullptr);
  if (t < 1700000000) return false;              // SNTP not synced yet
  struct tm g; gmtime_r(&t, &g);
  strftime(out, n, "%Y-%m-%dT%H:%M:%SZ", &g);
  return true;
}

// ---------------------------------------------------------------------------
// one sample
// ---------------------------------------------------------------------------
static void sample_and_report() {
  char ts[32];
  if (!iso_now(ts, sizeof(ts))) { Serial.println("{\"error\":\"no SNTP time yet\"}"); return; }

  // 1. Wi-Fi scan (station mode)
  int n = WiFi.scanNetworks(false, true, false, 250, PROBE_CHANNEL);

  // 2. promiscuous window on PROBE_CHANNEL
  reset_window();
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(&rx_cb);
  esp_wifi_set_channel(PROBE_CHANNEL, CHANNEL_WIDTH_MHZ == 40 ? WIFI_SECOND_CHAN_ABOVE : WIFI_SECOND_CHAN_NONE);
  delay(SAMPLE_WINDOW_MS);
  esp_wifi_set_promiscuous(false);

  // 3. BLE scan
  int ble = 0, ble_strongest = -127;
  BLEScanResults* r = BLEDevice::getScan()->start(BLE_SCAN_SECONDS, false);
  if (r) {
    ble = r->getCount();
    for (int i = 0; i < ble; i++) ble_strongest = max(ble_strongest, r->getDevice(i).getRSSI());
  }
  BLEDevice::getScan()->clearResults();

  // 4. assemble JSON
  JsonDocument doc;
  doc["probe"] = "esp32-rf-probe";
  doc["fw_version"] = FW_VERSION;
  doc["collected_at"] = ts;
  doc["channel"] = PROBE_CHANNEL;
  doc["channel_width_mhz"] = CHANNEL_WIDTH_MHZ;
  doc["sample_window_ms"] = SAMPLE_WINDOW_MS;

  JsonArray scan = doc["scan"].to<JsonArray>();
  for (int i = 0; i < n && i < 30; i++) {
    JsonObject ap = scan.add<JsonObject>();
    uint8_t* b = WiFi.BSSID(i);
    char bs[18]; mac_str(b, bs);
    ap["bssid"] = bs;
    ap["ssid"] = WiFi.SSID(i);
    ap["channel"] = WiFi.channel(i);
    ap["rssi"] = WiFi.RSSI(i);
    ap["auth"] = auth_name(WiFi.encryptionType(i));
    for (uint32_t k = 0; k < beacons_n; k++) {
      if (!mac_eq(beacons[k].bssid, b)) continue;
      if (beacons[k].country[0]) ap["country"] = beacons[k].country;
      if (beacons[k].min_rate > 0) ap["min_rate_mbps"] = beacons[k].min_rate;
      ap["ht"] = beacons[k].ht;
      if (beacons[k].csa_to >= 0) ap["csa_to"] = beacons[k].csa_to;
    }
  }
  WiFi.scanDelete();

  JsonObject sniff = doc["sniff"].to<JsonObject>();
  sniff["frames_total"] = C.frames;
  sniff["frames_retry"] = C.retry;
  sniff["frames_fcs_error"] = C.fcs;
  sniff["beacons"] = C.beacons;
  sniff["data_frames"] = C.data;
  sniff["mgmt_frames"] = C.mgmt;
  sniff["ctrl_frames"] = C.ctrl;
  sniff["airtime_us"] = (long)C.airtime_us;
  if (C.nf_n) sniff["noise_floor_dbm_avg"] = (float)C.nf_sum / C.nf_n;
  if (C.frames) sniff["rssi_dbm_avg"] = (float)C.rssi_sum / C.frames;
  sniff["unique_tx"] = uniq_n;
  JsonArray st = sniff["stations"].to<JsonArray>();
  for (uint32_t i = 0; i < uniq_n && i < 20; i++) { char s[18]; mac_str(uniq[i], s); st.add(s); }

  JsonObject bt = doc["bt"].to<JsonObject>();
  bt["ble_devices"] = ble;
  bt["classic_devices"] = 0;                      // classic BT inquiry not run
  if (ble_strongest > -127) bt["strongest_rssi"] = ble_strongest;

#ifdef STA_SSID
  JsonObject sta = doc["sta"].to<JsonObject>();
  sta["connected"] = WiFi.isConnected();
  if (WiFi.isConnected()) {
    char bs[18]; mac_str(WiFi.BSSID(), bs);
    sta["bssid"] = bs; sta["ssid"] = WiFi.SSID();
    sta["rssi"] = WiFi.RSSI(); sta["channel"] = WiFi.channel();
  }
#endif

  // 5. output
  serializeJson(doc, Serial);
  Serial.println();

#ifdef BACKEND_URL
  if (WiFi.isConnected()) {
    JsonDocument env;
    env["format"] = "esp32";
    env["document"] = doc;
    String body; serializeJson(env, body);
    HTTPClient http;
    http.begin(BACKEND_URL);
    http.addHeader("Content-Type", "application/json");
    int code = http.POST(body);
    Serial.printf("POST %s -> %d\n", BACKEND_URL, code);
    http.end();
  }
#endif
}

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("wifi");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print("."); }
  Serial.println(WiFi.status() == WL_CONNECTED ? " ok" : " (no join — SNTP will fail)");

  configTime(0, 0, "pool.ntp.org", "time.google.com");
  for (int i = 0; i < 20 && time(nullptr) < 1700000000; i++) delay(500);

#ifndef STA_SSID
  WiFi.disconnect(true, false);                   // keep radio, drop association
  WiFi.mode(WIFI_STA);
#endif

  BLEDevice::init("");
  BLEDevice::getScan()->setActiveScan(false);
}

void loop() {
  sample_and_report();
  delay(SAMPLE_PERIOD_MS);
}
