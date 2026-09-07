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
| connected-link RSSI | `WiFi.RSSI()` when `STA_SSID` is set |

Channel utilisation is a coarse estimate (no CCA-busy counter is exposed on the
ESP32); treat it as indicative.

## Build

Arduino IDE or `arduino-cli`, ESP32 board package ≥ 3.0.

Libraries: **ArduinoJson** (≥7). Wi-Fi, `esp_wifi`, BLE, `HTTPClient`, `time.h`
ship with the ESP32 core.

```
cp config.h.example config.h      # then edit config.h
# select your board, e.g. "ESP32 Dev Module", and flash
```

## config.h

| define | meaning |
|---|---|
| `WIFI_SSID` / `WIFI_PASS` | a network to join for SNTP time (and POST). Required — the adapter refuses a snapshot with no real timestamp. |
| `PROBE_CHANNEL` | 1–13, the 2.4 GHz channel to sample |
| `CHANNEL_WIDTH_MHZ` | 20 or 40 |
| `SAMPLE_WINDOW_MS` | promiscuous capture length (2000–5000 typical) |
| `BLE_SCAN_SECONDS` | BLE scan length (2–4) |
| `STA_SSID` (optional) | if set, briefly associate to read link RSSI / mark `same_ess` |
| `BACKEND_URL` (optional) | e.g. `http://192.168.1.50:8000/ingest` — POST each sample; leave empty for Serial-only |
| `SAMPLE_PERIOD_MS` | delay between samples (loop) |

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
# device POSTs to BACKEND_URL, or replay a captured line:
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -d '{"format":"esp32","document": <paste one Serial line> }'
# -> canonical snapshot; feed that to POST /diagnose
```

**Live, in the frontend's "2.4GHz Live Test" tab:** set `BACKEND_URL` in
`config.h` to `http://<backend-host>:8000/live/ingest` instead of `/ingest`.
Every sample the board posts is normalized, diagnosed (same fixed low
temperature as `/diagnose`), and held in an in-memory buffer the frontend
polls via `GET /live/feed`. `/ingest` still exists unchanged for one-off
ingestion (`read_probe.py`, CSV/JSON uploads) that should not show up live.

**Offline (no board):** save Serial lines to a file and run them through
`Esp32Adapter().to_canonical(json.loads(line))` — the adapter has no device
dependency, so the whole path is testable from a recorded capture.
