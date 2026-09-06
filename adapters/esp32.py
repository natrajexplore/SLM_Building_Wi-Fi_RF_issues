"""ESP32 RF probe adapter: `hardware/esp32_rf_probe` JSON -> canonical snapshot.

The ESP32-WROOM is a 2.4 GHz-only Wi-Fi + BT radio with no spectrum-analysis
hardware, so every snapshot it produces carries `radio.band = "2.4GHz"` and
`analysis_context.spectrum_capable = false`. Within that limit it is a genuine
measurement source for the RF-24-* causes: co/adjacent-channel interference,
legacy rates, cell overlap, and non-Wi-Fi (Bluetooth) interference.

Raw JSON shape the firmware emits (one object per sample) is documented in
`hardware/esp32_rf_probe/README.md`. This adapter maps it; it does not talk to
the device. Feed it a live capture or a recorded one identically:

    from adapters.esp32 import Esp32Adapter
    snapshot = Esp32Adapter().to_canonical(json.loads(line_from_serial))
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from adapters.base import Adapter, ContractViolation

# 2.4 GHz channels within this many channel-numbers of the primary overlap it
# (channels are 5 MHz apart, a 20 MHz channel spans ~4).
_ADJACENT_SPAN = 4


class Esp32Adapter(Adapter):
    name = "esp32_rf_probe"

    def _translate(self, raw: Any) -> dict:
        if not isinstance(raw, dict):
            raise ContractViolation(
                f"{self.name}._translate expects one probe JSON object, got {type(raw).__name__}"
            )

        collected_at = raw.get("collected_at")
        if not isinstance(collected_at, str) or "T" not in collected_at:
            raise ContractViolation(
                f"{self.name}: probe JSON needs `collected_at` as an RFC3339 timestamp "
                "(the firmware syncs time over SNTP). Refusing to invent one."
            )

        channel = _require_int(raw, "channel", self.name)
        width = _require_int(raw, "channel_width_mhz", self.name)
        scan = raw.get("scan") or []
        sniff = raw.get("sniff") or {}
        bt = raw.get("bt") or {}
        sta = raw.get("sta") or {}
        window_ms = raw.get("sample_window_ms")

        snapshot: dict[str, Any] = {
            "snapshot_id": raw.get("snapshot_id") or f"esp32-{collected_at}-ch{channel}",
            "timestamp": collected_at,
            "radio": {
                "band": "2.4GHz", "channel": channel,
                "channel_width_mhz": width, "admin_state": "enabled",
            },
            "rf_metrics": {},
            "analysis_context": {
                "spectrum_capable": False,          # no FFT hardware — always false
                "neighbor_scan_available": bool(scan),
                "client_detail_available": bool(sniff.get("stations")),
            },
        }

        if isinstance(window_ms, (int, float)) and window_ms > 0:
            snapshot["analysis_context"]["observation_window_minutes"] = round(window_ms / 60000, 3)

        self._rf_metrics(snapshot["rf_metrics"], channel, scan, sniff, window_ms, sta)
        self._radio_from_beacons(snapshot["radio"], scan)
        self._capabilities(snapshot, scan, sta)
        self._neighbors(snapshot, scan, sta)
        self._clients(snapshot, sniff, sta)
        self._events(snapshot, scan, collected_at)
        self._non_wifi(snapshot, bt)

        return snapshot

    # -- rf_metrics --------------------------------------------------------

    def _rf_metrics(self, m: dict, channel, scan, sniff, window_ms, sta) -> None:
        own_bssid = str(sta.get("bssid") or "").lower()
        on_channel = [a for a in scan if a.get("channel") == channel and str(a.get("bssid", "")).lower() != own_bssid]
        adjacent = [
            a for a in scan
            if a.get("channel") not in (None, channel)
            and abs(a["channel"] - channel) <= _ADJACENT_SPAN
        ]
        m["co_channel_neighbors"] = len(on_channel)
        m["adjacent_channel_neighbors"] = len(adjacent)

        rssis = [a["rssi"] for a in scan if isinstance(a.get("rssi"), (int, float))]
        if rssis:
            m["strongest_neighbor_rssi_dbm"] = float(max(rssis))

        nf = sniff.get("noise_floor_dbm_avg")
        if isinstance(nf, (int, float)):
            m["noise_floor_dbm"] = round(float(nf), 1)

        total = sniff.get("frames_total")
        if isinstance(total, int) and total > 0:
            m["retry_rate_pct"] = _pct(sniff.get("frames_retry", 0), total)
            fcs = sniff.get("frames_fcs_error", 0)
            if isinstance(fcs, int):
                m["crc_error_rate_pct"] = _pct(fcs, total + fcs)

        airtime = sniff.get("airtime_us")
        if isinstance(airtime, (int, float)) and isinstance(window_ms, (int, float)) and window_ms > 0:
            m["channel_utilization_pct"] = round(min(100.0, max(0.0, airtime / (window_ms * 1000) * 100)), 1)

    # -- radio / capabilities from beacon IEs -----------------------------

    def _radio_from_beacons(self, radio: dict, scan) -> None:
        countries = Counter(a["country"] for a in scan if a.get("country"))
        if countries:
            radio["regulatory_domain"] = countries.most_common(1)[0][0]

    def _capabilities(self, snapshot: dict, scan, sta) -> None:
        caps: dict[str, Any] = {}
        rates = [a["min_rate_mbps"] for a in scan if isinstance(a.get("min_rate_mbps"), (int, float))]
        if rates:
            caps["min_data_rate_mbps"] = float(min(rates))
        auths = {str(a.get("auth", "")).lower() for a in scan}
        if auths and auths <= {"wpa3", "owe"} and "" not in auths:
            caps["wpa3_enforced"] = True
        elif any(x in auths for x in ("wpa2", "wpa", "wep", "open")):
            caps["wpa3_enforced"] = False
        if caps:
            snapshot["capabilities"] = caps

    # -- arrays ----------------------------------------------------------

    def _neighbors(self, snapshot: dict, scan, sta) -> None:
        own_ssid = str(sta.get("ssid") or "")
        neighbors = []
        for ap in scan:
            if not ap.get("bssid"):
                continue
            n: dict[str, Any] = {"bss_ref": str(ap["bssid"])}  # pseudonymised by to_canonical
            if isinstance(ap.get("channel"), int):
                n["channel"] = ap["channel"]
            if isinstance(ap.get("rssi"), (int, float)):
                n["rssi_dbm"] = float(ap["rssi"])
            if own_ssid:
                n["same_ess"] = ap.get("ssid") == own_ssid
            neighbors.append(n)
        if neighbors:
            snapshot["neighbors"] = neighbors[:30]  # schema maxItems

    def _clients(self, snapshot: dict, sniff, sta) -> None:
        clients: dict[str, Any] = {}
        uniq = sniff.get("unique_tx")
        if isinstance(uniq, int):
            clients["count"] = max(0, uniq)
        if isinstance(sta.get("rssi"), (int, float)):
            clients["avg_rssi_dbm"] = float(sta["rssi"])
        if clients:
            snapshot["clients"] = clients

        stations = sniff.get("stations") or []
        samples = [{"client_ref": str(s)} for s in stations if s][:50]
        if samples:
            snapshot["client_samples"] = samples

    def _events(self, snapshot: dict, scan, collected_at) -> None:
        events = []
        for ap in scan:
            csa_to = ap.get("csa_to")
            if isinstance(csa_to, int):
                ev: dict[str, Any] = {"type": "channel_change", "timestamp": collected_at, "channel_to": csa_to}
                if isinstance(ap.get("channel"), int):
                    ev["channel_from"] = ap["channel"]
                events.append(ev)
        if events:
            snapshot["events"] = events

    def _non_wifi(self, snapshot: dict, bt) -> None:
        ble = bt.get("ble_devices") or 0
        classic = bt.get("classic_devices") or 0
        if ble + classic <= 0:
            return
        # A device-presence signal, NOT a spectrum detection. severity scales
        # with how many BT emitters are in range; center/bandwidth are the
        # band-wide 2.4 GHz hop range, left unset since the probe can't resolve
        # a specific offender.
        strongest = bt.get("strongest_rssi")
        severity = min(100, (ble + classic) * 10 + (max(0, strongest + 90) if isinstance(strongest, (int, float)) else 0))
        snapshot["non_wifi_interferers"] = [{"type": "bluetooth", "severity": int(severity)}]


def _require_int(raw: dict, key: str, name: str) -> int:
    v = raw.get(key)
    if not isinstance(v, int):
        raise ContractViolation(f"{name}: `{key}` must be an integer, got {v!r}")
    return v


def _pct(numerator, denominator) -> float:
    return round(min(100.0, max(0.0, numerator / denominator * 100)), 1)
