# esp32_rf_probe

Turns an **ESP32-WROOM (38-pin, 2.4 GHz Wi-Fi + BT)** into an RF measurement
probe for this project. It samples one 2.4 GHz channel and emits a JSON object
that `adapters/esp32.py` normalizes into a canonical snapshot.

## What it measures (and what it can't)

The ESP32-WROOM is 2.4 GHz only and has **no spectrum-analysis hardware**, so
every snapshot is `radio.band = "2.4GHz"` and
`analysis_context.spectrum_capable = false`. Within that it is a real source for:

| Signal | How |
|---|---|
| neighbouring APs (BSSID, channel, RSSI, SSID, auth) | `WiFi.scanNetworks()` |
| co / adjacent-channel neighbour counts | computed from the scan |
| noise floor (dBm) | `rx_ctrl.noise_floor`, averaged over sniffed frames |
| retry rate, FCS-error rate | retry bit / rx_state over sniffed frames |
| channel utilisation (approx) | Σ estimated frame airtime ÷ window |
| regulatory domain, min basic rate, CSA / channel-change | beacon Information Elements (country=7, rates=1, CSA=37) |
| non-Wi-Fi interference | **BLE scan** → `{type: "bluetooth"}` device-presence hint |
| connected-link RSSI | `WiFi.RSSI()` whenever the board is associated (always, unless it deliberately drops the link in Serial-only mode — see "Setup portal" below) |

Channel utilisation is a coarse estimate (no CCA-busy counter is exposed on the
ESP32); treat it as indicative.

## Build

Arduino IDE or `arduino-cli`, ESP32 board package ≥ 3.0.

Libraries: **ArduinoJson** (≥7). Everything else — Wi-Fi, `esp_wifi`, BLE,
`HTTPClient`, `WiFiClientSecure`, `WebServer`, `DNSServer`, `Preferences`,
`time.h` — ships with the ESP32 core; no other external library needed for
the setup portal.

```
cp config.h.example config.h      # then edit config.h (sampling params only — see below)
# select your board, e.g. "ESP32 Dev Module", and flash
```

## config.h

WiFi network, backend address, and the HTTPS toggle are **not** in
`config.h` — they're set at runtime through the on-device setup portal (see
"Setup portal" below). This file only controls what to sample:

| define | meaning |
|---|---|
| `PROBE_CHANNEL` | 1–13, the 2.4 GHz channel to sample |
| `CHANNEL_WIDTH_MHZ` | 20 or 40 |
| `SAMPLE_WINDOW_MS` | promiscuous capture length (2000–5000 typical) |
| `BLE_SCAN_SECONDS` | BLE scan length (2–4) |
| `SAMPLE_PERIOD_MS` | delay between samples (loop) |

**If you have a board flashed with an older version of this firmware:** its
compile-time `WIFI_SSID`/`WIFI_PASS`/`BACKEND_URL`/`STA_SSID` are gone after
this update — reflash, then go through the setup portal once. There's no
dual-path migration; maintaining both would add real complexity for no
lasting benefit once the portal exists.

## Setup portal

On first boot (empty NVS) — or anytime you hold the **BOOT** button (GPIO0
on essentially every ESP32-WROOM dev board) while powering on or resetting —
the board opens its own temporary access point, **`RF-Probe-Setup-XXXX`**
(open network; `XXXX` is the last 4 hex digits of its MAC, so multiple
probes don't collide). Connect to it — most phones/laptops will pop the
setup page automatically (captive-portal detection); otherwise browse to
`http://192.168.4.1/`.

**The page itself requires a login** — HTTP Basic Auth, default
**`admin` / `admin`** on a fresh board, exactly like a factory-default
D-Link/TP-Link admin panel. Change it from the same page under "Admin
username" / "New admin password" (leave the password field blank to keep it
unchanged). This login is separate from the WiFi password above — it only
protects the setup page, not your actual network. Since the setup AP is
necessarily open (nothing to authenticate against before it's configured),
this login is a courtesy against a passerby casually opening the page during
your setup window, not a defense against someone already using tools to
snoop that same open AP — same posture a real router's first-boot admin
panel has.

**If you change the admin password and it gets locked out somehow** (typo,
forgotten change): hold BOOT for **10+ seconds** at power-on/reset — this
does a full factory reset (wipes the WiFi credentials *and* the admin login
back to `admin`/`admin`), not just a "reopen the portal" like a short tap. A
short BOOT tap reopens the portal but still requires whatever admin login is
currently stored.

The page lists nearby networks with an auth badge (colour-coded — red for
Open, green for WPA2/WPA3) so you can see at a glance which one is
unencrypted; picking an Open network shows an inline warning. Fill in:

- The network's SSID/password (or type one manually if it didn't show up in
  the scan). Previously-saved values (except passwords, which are never
  echoed back) are pre-filled if you're revisiting the portal.
- The backend's host, port, and path (defaults `8000` / `/live/ingest`).
  **Must be the backend machine's actual LAN IP, never `localhost`** — from
  the board's own network stack, `localhost` means the board itself, not the
  PC running the backend. Find the PC's IP with `ipconfig`.
- **"Encrypt traffic to backend (HTTPS)"** — see the next section.

Saving writes everything to NVS and reboots the board into normal operation.
If it can't join the saved network within ~20s (wrong password, AP out of
range, etc.), it automatically reopens the setup portal so you can fix it —
no need to remember the BOOT-button trick for that specific failure mode.

**Reconfiguring later, once it's already running normally:** a brief BOOT
press (no reboot, no holding the whole time) drops it straight back into the
setup portal — login still required, existing WiFi/backend settings kept
unless you change and save them. If you don't submit anything within 5
minutes it gives up and reconnects with whatever was already stored,
resuming normal sampling automatically. This is deliberately *not* a
permanently-broadcasting access point: the setup AP only exists for the
brief window you actually asked for, rather than the device continuously
hosting an open, unauthenticated hotspot in the background — and running the
AP and the sampling STA link at once would force both onto the same radio
channel, interrupting anyone connected to the AP every sampling cycle.

The backend also needs to actually be listening where the board can reach
it: `uvicorn backend.main:app --reload` alone binds `127.0.0.1` (loopback
only, invisible to the board). Start it with `--host 0.0.0.0`, and allow it
through Windows Firewall on Private networks if prompted. After each sample
the board prints `POST <url> -> <code>` on Serial — `200` means delivered;
anything else (including no line at all) means it never reached the backend,
and the fix is in your network/portal settings, not the backend.

## HTTPS to the backend

Toggling "Encrypt traffic to backend" makes the board connect over
`WiFiClientSecure` with certificate verification disabled
(`setInsecure()`) — there's no certificate authority here, so the board
trusts whatever cert the backend presents. Generate one for local testing:

```
pip install -r requirements-dev.txt   # adds `cryptography`
python hardware/esp32_rf_probe/generate_dev_cert.py --host <backend LAN IP>
uvicorn backend.main:app --host 0.0.0.0 --port 8000 \
  --ssl-keyfile .local/certs/key.pem --ssl-certfile .local/certs/cert.pem
```

**What this does and doesn't protect against:** it encrypts the probe's
payload against passive eavesdropping on the WiFi network — the concern with
an open/unencrypted AP. It does **not** authenticate the backend, so it
won't stop an active attacker on the same network presenting a different
certificate. That's a deliberate, disclosed tradeoff for a local dev/lab
tool with no PKI infrastructure, not a claim of full transport security.
`hardware/read_probe.py --insecure` makes the same tradeoff for desktop-side
testing against the same self-signed cert.

## Network placement

If you're running several of these probes, consider putting them on their
own small subnet (a `/27` — 32 addresses, 30 usable — is generally plenty)
rather than the flat main LAN, and let DHCP assign addresses within it. This
is a router/network-infrastructure decision, not something the firmware
enforces — it doesn't do static IP configuration by design (DHCP only).

## Output JSON

One object per sample, on Serial at 115200 and/or POSTed as
`{"format":"esp32","document": <this object>}`:

```json
{
  "probe": "esp32-rf-probe",
  "fw_version": "0.1.0",
  "collected_at": "2026-03-01T12:00:00Z",
  "channel": 6,
  "channel_width_mhz": 20,
  "sample_window_ms": 3000,
  "scan": [
    {"bssid":"aa:bb:cc:dd:ee:ff","ssid":"corp","channel":6,"rssi":-58,
     "auth":"wpa2","country":"GB","min_rate_mbps":1,"ht":true,"csa_to":null}
  ],
  "sniff": {
    "frames_total":1840,"frames_retry":210,"frames_fcs_error":55,
    "beacons":320,"data_frames":900,"mgmt_frames":400,"ctrl_frames":540,
    "airtime_us":1650000,"noise_floor_dbm_avg":-88.5,"rssi_dbm_avg":-70.2,
    "unique_tx":14,"stations":["11:22:33:44:55:66"]
  },
  "bt": {"ble_devices":6,"classic_devices":0,"strongest_rssi":-55},
  "sta": {"connected":true,"bssid":"aa:bb:cc:dd:ee:ff","ssid":"corp","rssi":-63,"channel":6}
}
```

MAC addresses (`bssid`, `stations`) are pseudonymised **at the adapter
boundary**, not on the device — real MACs never enter training data or logs.

## Use it

**With the backend running:**
```
# device POSTs to whatever host/port/path you set in the setup portal, or
# replay a captured line yourself:
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -d '{"format":"esp32","document": <paste one Serial line> }'
# -> canonical snapshot; feed that to POST /diagnose
```

**Live, in the frontend's "2.4GHz Live Test" tab:** in the setup portal, set
the path to `/live/ingest` instead of `/ingest` (the default). Every sample
the board posts is normalized, diagnosed (same fixed low temperature as
`/diagnose`), and held in an in-memory buffer the frontend polls via
`GET /live/feed`. `/ingest` still exists unchanged for one-off ingestion
(`read_probe.py`, CSV/JSON uploads) that should not show up live.

**No board at all:** the Live Test tab has a "Load demo samples" button that
calls `POST /live/demo`, which replays `hardware/sample_capture.jsonl` — 6
real recorded probe captures, each engineered so exactly one (or,
deliberately, two at once) RF-24-* cause becomes assertion-eligible — through
the identical adapter → diagnose → buffer path a real board would use. Demo
samples carry `source: "demo"` in the feed so they're never confused with a
real board's `source: "probe"` samples; the two can coexist in the same
buffer. The same file also works from a terminal, printing each diagnosis
instead of one line per POST:
`python hardware/read_probe.py --replay hardware/sample_capture.jsonl --once`
(drop `--once` to walk all 6), or `--live` to push them into the tab instead.
See the comment block at the top of `sample_capture.jsonl` for what each line
demonstrates and why RF-24-004/005 can't be reached this way. If the backend
is running HTTPS (see "HTTPS to the backend" above), add `--insecure` and
point `--backend` at the `https://` URL.

**Offline (no board):** save Serial lines to a file and run them through
`Esp32Adapter().to_canonical(json.loads(line))` — the adapter has no device
dependency, so the whole path is testable from a recorded capture.
