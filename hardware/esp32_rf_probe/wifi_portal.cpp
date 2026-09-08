#include "wifi_portal.h"

#include <DNSServer.h>
#include <Preferences.h>
#include <WebServer.h>

namespace {

constexpr int BOOT_BUTTON_PIN = 0;                      // standard on ESP32-WROOM dev boards, active-low
constexpr uint32_t STA_CONNECT_TIMEOUT_MS = 20000;
constexpr uint32_t PORTAL_RETRY_TIMEOUT_MS = 5UL * 60 * 1000;  // retry stored creds if nobody reconfigures
constexpr byte DNS_PORT = 53;
constexpr int MAX_SCAN_ROWS = 32;

Preferences prefs;
WifiPortalConfig g_config;
WebServer server(80);
DNSServer dnsServer;

String apName() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char suffix[5];
  snprintf(suffix, sizeof(suffix), "%02X%02X", mac[4], mac[5]);
  return String("RF-Probe-Setup-") + suffix;
}

// SSIDs come from nearby radios, not from us -- escape before embedding in
// the portal page so a maliciously-named neighbour AP can't inject HTML/JS
// into the setup page rendered on the person configuring this device.
String htmlEscape(const String& s) {
  String out;
  out.reserve(s.length());
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '&') out += "&amp;";
    else if (c == '"') out += "&quot;";
    else if (c == '<') out += "&lt;";
    else if (c == '>') out += "&gt;";
    else out += c;
  }
  return out;
}

String networkListHtml() {
  int n = WiFi.scanNetworks();
  if (n <= 0) {
    return "<p class=\"muted\">No networks found — scan again or enter one manually below.</p>";
  }

  struct Seen { String ssid; int32_t rssi; wifi_auth_mode_t auth; };
  static Seen seen[MAX_SCAN_ROWS];
  int seenN = 0;
  for (int i = 0; i < n; i++) {
    String ssid = WiFi.SSID(i);
    if (ssid.isEmpty()) continue;
    int idx = -1;
    for (int j = 0; j < seenN; j++) {
      if (seen[j].ssid == ssid) { idx = j; break; }
    }
    if (idx < 0 && seenN < MAX_SCAN_ROWS) {
      idx = seenN++;
      seen[idx] = {ssid, WiFi.RSSI(i), WiFi.encryptionType(i)};
    } else if (idx >= 0 && WiFi.RSSI(i) > seen[idx].rssi) {
      seen[idx].rssi = WiFi.RSSI(i);
      seen[idx].auth = WiFi.encryptionType(i);
    }
  }

  String out = "<div class=\"nets\">";
  for (int i = 0; i < seenN; i++) {
    bool open = seen[i].auth == WIFI_AUTH_OPEN;
    String esc = htmlEscape(seen[i].ssid);
    out += "<label class=\"net\" data-open=\"" + String(open ? "1" : "0") + "\">";
    out += "<input type=\"radio\" name=\"ssid_pick\" value=\"" + esc + "\" "
           "onclick=\"document.getElementById('ssid').value=this.value;"
           "document.getElementById('openWarn').style.display=this.parentElement.dataset.open==='1'?'block':'none';\">";
    out += "<span class=\"ssid\">" + esc + "</span>";
    out += String("<span class=\"badge ") + (open ? "badge-open" : "badge-secure") + "\">" +
           auth_name(seen[i].auth) + "</span>";
    out += "<span class=\"rssi\">" + String(seen[i].rssi) + " dBm</span></label>";
  }
  out += "</div>";
  WiFi.scanDelete();
  return out;
}

String portalPage() {
  String page =
    "<!doctype html><html><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    "<title>RF Probe Setup</title><style>"
    "body{font-family:system-ui,sans-serif;max-width:480px;margin:24px auto;padding:0 16px;background:#0f172a;color:#e2e8f0}"
    "h1{font-size:1.25rem}"
    ".card{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:16px}"
    ".net{display:flex;align-items:center;gap:8px;padding:8px 4px;border-bottom:1px solid #334155;cursor:pointer}"
    ".net:last-child{border-bottom:none}"
    ".ssid{flex:1}"
    ".badge{font-size:0.7rem;padding:2px 8px;border-radius:999px;font-weight:600}"
    ".badge-open{background:#7f1d1d;color:#fecaca}"
    ".badge-secure{background:#14532d;color:#bbf7d0}"
    ".rssi{font-size:0.75rem;color:#94a3b8}"
    ".muted{color:#94a3b8;font-size:0.85rem}"
    "label.field{display:block;margin:10px 0 4px;font-size:0.85rem;color:#cbd5e1}"
    "input[type=text],input[type=password],input[type=number]{width:100%;box-sizing:border-box;padding:8px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0}"
    "button{width:100%;padding:10px;border-radius:8px;border:none;background:#2563eb;color:white;font-weight:600;margin-top:16px;cursor:pointer}"
    ".warn{background:#7f1d1d;color:#fecaca;padding:10px;border-radius:8px;margin-top:8px;display:none}"
    ".https-note{font-size:0.75rem;color:#94a3b8;margin-top:6px}"
    ".checkline{display:flex;align-items:center;gap:8px;margin-top:12px}"
    "</style></head><body>"
    "<h1>RF Probe Setup</h1>"
    "<form action=\"/save\" method=\"POST\">"
    "<div class=\"card\">"
    "<p class=\"muted\">Pick your WiFi network (tap to fill it in below), or enter one manually.</p>";

  page += networkListHtml();
  page +=
    "<label class=\"field\">Network name (SSID)</label>"
    "<input type=\"text\" id=\"ssid\" name=\"ssid\" required>"
    "<label class=\"field\">Password</label>"
    "<input type=\"password\" name=\"pass\">"
    "<div id=\"openWarn\" class=\"warn\">This network has no password — anyone nearby can read its "
    "traffic. Turn on &quot;Encrypt traffic to backend&quot; below to at least protect this probe's data.</div>"
    "</div>"
    "<div class=\"card\">"
    "<label class=\"field\">Backend host (this machine's LAN IP — not &quot;localhost&quot;)</label>"
    "<input type=\"text\" name=\"host\" placeholder=\"192.168.1.50\" required>"
    "<label class=\"field\">Backend port</label>"
    "<input type=\"number\" name=\"port\" value=\"8000\" required>"
    "<label class=\"field\">Path</label>"
    "<input type=\"text\" name=\"path\" value=\"/live/ingest\" required>"
    "<div class=\"checkline\">"
    "<input type=\"checkbox\" id=\"https\" name=\"https\" value=\"1\">"
    "<label for=\"https\">Encrypt traffic to backend (HTTPS)</label>"
    "</div>"
    "<p class=\"https-note\">Requires the backend running with --ssl-keyfile/--ssl-certfile "
    "(see generate_dev_cert.py). Encrypts against eavesdropping on this WiFi network; does not "
    "verify the backend's identity (self-signed development certificate).</p>"
    "</div>"
    "<button type=\"submit\">Save &amp; connect</button>"
    "</form></body></html>";
  return page;
}

void handleRoot() {
  server.send(200, "text/html", portalPage());
}

void handleSave() {
  String ssid = server.arg("ssid");
  if (ssid.isEmpty()) {
    server.send(400, "text/plain", "SSID is required");
    return;
  }
  String pass = server.arg("pass");
  String host = server.arg("host");
  long portArg = server.arg("port").toInt();
  String path = server.arg("path");
  bool https = server.hasArg("https");

  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.putString("host", host);
  prefs.putUShort("port", portArg > 0 && portArg <= 65535 ? (uint16_t)portArg : 8000);
  prefs.putString("path", path.isEmpty() ? "/live/ingest" : path);
  prefs.putBool("https", https);
  prefs.putBool("cfgd", true);

  server.send(200, "text/html",
    "<html><body style='font-family:sans-serif;text-align:center;margin-top:40px;"
    "background:#0f172a;color:#e2e8f0'>"
    "<h2>Saved</h2><p>Rebooting and joining your network…</p></body></html>");
  delay(1000);
  ESP.restart();
}

void handleNotFound() {
  // Captive-portal trick: send every unknown path back to the setup page so
  // phones/laptops auto-pop it instead of the user having to know the AP's IP.
  server.sendHeader("Location", String("http://") + WiFi.softAPIP().toString() + "/", true);
  server.send(302, "text/plain", "");
}

// Runs the AP + captive portal. `timeoutMs == 0` blocks forever (first-time
// setup — nothing to fall back to). A non-zero timeout returns if nobody
// saves new settings in that window, so a transient outage on an
// already-working network doesn't strand the device in setup mode forever.
// A successful Save calls ESP.restart() from inside handleSave(), so the
// "normal" way out of this function on first-time setup is a reboot, not a
// return.
void runPortal(uint32_t timeoutMs) {
  WiFi.mode(WIFI_AP);
  WiFi.softAP(apName().c_str());
  IPAddress apIP = WiFi.softAPIP();
  dnsServer.start(DNS_PORT, "*", apIP);

  server.on("/", HTTP_GET, handleRoot);
  server.on("/save", HTTP_POST, handleSave);
  server.onNotFound(handleNotFound);
  server.begin();

  Serial.printf("setup portal: join WiFi \"%s\" then open http://%s/\n",
                apName().c_str(), apIP.toString().c_str());

  uint32_t start = millis();
  while (timeoutMs == 0 || millis() - start < timeoutMs) {
    dnsServer.processNextRequest();
    server.handleClient();
    delay(2);
  }

  server.stop();
  dnsServer.stop();
  WiFi.softAPdisconnect(true);
}

}  // namespace

namespace wifiPortal {

bool begin() {
  prefs.begin("rfprobe", false);

  pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);
  bool forceSetup = digitalRead(BOOT_BUTTON_PIN) == LOW;

  if (!prefs.getBool("cfgd", false) || forceSetup) {
    runPortal(0);  // blocks; only exits via ESP.restart() in handleSave()
  }

  while (true) {
    String ssid = prefs.getString("ssid", "");
    String pass = prefs.getString("pass", "");
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), pass.c_str());
    Serial.printf("joining \"%s\"", ssid.c_str());
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < STA_CONNECT_TIMEOUT_MS) {
      delay(500);
      Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.println(" ok");
      g_config.backendHost = prefs.getString("host", "");
      g_config.backendPort = prefs.getUShort("port", 8000);
      g_config.backendPath = prefs.getString("path", "/live/ingest");
      g_config.https = prefs.getBool("https", false);
      return true;
    }
    Serial.println(" failed — reopening setup portal");
    runPortal(PORTAL_RETRY_TIMEOUT_MS);  // returns on timeout; retry the stored creds
  }
}

const WifiPortalConfig& config() { return g_config; }

}  // namespace wifiPortal
