"""Tests for adapters/esp32.py — the ESP32 RF probe adapter."""
from __future__ import annotations

import copy
import unittest

from adapters.base import ContractViolation
from adapters.esp32 import Esp32Adapter
from adapters.normalize import PseudonymisationError

SAMPLE = {
    "probe": "esp32-rf-probe",
    "fw_version": "0.1.0",
    "collected_at": "2026-03-01T12:00:00Z",
    "channel": 6,
    "channel_width_mhz": 20,
    "sample_window_ms": 3000,
    "scan": [
        {"bssid": "aa:bb:cc:00:00:01", "ssid": "corp", "channel": 6, "rssi": -55,
         "auth": "wpa2", "country": "GB", "min_rate_mbps": 1, "ht": True},
        {"bssid": "aa:bb:cc:00:00:02", "ssid": "corp", "channel": 6, "rssi": -67, "auth": "wpa2"},
        {"bssid": "aa:bb:cc:00:00:03", "ssid": "guest", "channel": 6, "rssi": -71, "auth": "wpa2"},
        {"bssid": "aa:bb:cc:00:00:04", "ssid": "other", "channel": 3, "rssi": -60, "auth": "wpa2"},
        {"bssid": "aa:bb:cc:00:00:05", "ssid": "far", "channel": 11, "rssi": -80, "auth": "wpa3"},
        {"bssid": "aa:bb:cc:00:00:06", "ssid": "movingap", "channel": 6, "rssi": -70,
         "auth": "wpa2", "csa_to": 1},
    ],
    "sniff": {
        "frames_total": 2000, "frames_retry": 300, "frames_fcs_error": 50,
        "beacons": 400, "data_frames": 1100, "mgmt_frames": 500, "ctrl_frames": 400,
        "airtime_us": 2_100_000, "noise_floor_dbm_avg": -84.3, "rssi_dbm_avg": -68.0,
        "unique_tx": 12, "stations": ["ff:ee:dd:00:00:aa", "ff:ee:dd:00:00:bb"],
    },
    "bt": {"ble_devices": 5, "classic_devices": 1, "strongest_rssi": -58},
    "sta": {"connected": True, "bssid": "aa:bb:cc:00:00:01", "ssid": "corp", "rssi": -55, "channel": 6},
}


def _run(**overrides) -> dict:
    raw = copy.deepcopy(SAMPLE)
    raw.update(overrides)
    return Esp32Adapter().to_canonical(raw)


class TranslationTests(unittest.TestCase):
    def test_produces_valid_canonical_snapshot(self):
        snap = _run()
        self.assertEqual(snap["radio"]["band"], "2.4GHz")
        self.assertEqual(snap["radio"]["channel"], 6)
        self.assertEqual(snap["source"]["adapter"], "esp32_rf_probe")

    def test_spectrum_capable_is_always_false(self):
        self.assertIs(_run()["analysis_context"]["spectrum_capable"], False)

    def test_missing_collected_at_refuses_rather_than_inventing(self):
        raw = copy.deepcopy(SAMPLE)
        del raw["collected_at"]
        with self.assertRaises(ContractViolation):
            Esp32Adapter().to_canonical(raw)
        raw["collected_at"] = 1234567  # an uptime int, not RFC3339
        with self.assertRaises(ContractViolation):
            Esp32Adapter().to_canonical(raw)

    def test_missing_channel_width_refused(self):
        raw = copy.deepcopy(SAMPLE)
        del raw["channel_width_mhz"]
        with self.assertRaises(ContractViolation):
            Esp32Adapter().to_canonical(raw)

    def test_co_and_adjacent_channel_counts(self):
        m = _run()["rf_metrics"]
        # channel-6 APs in scan: 00:01 (own BSS, excluded), 00:02, 00:03, 00:06 -> 3
        self.assertEqual(m["co_channel_neighbors"], 3)
        # within +-4 of 6, not 6: ch3 (00:04) yes, ch11 (00:05) no -> 1
        self.assertEqual(m["adjacent_channel_neighbors"], 1)

    def test_derived_rates_and_utilisation(self):
        m = _run()["rf_metrics"]
        self.assertEqual(m["retry_rate_pct"], 15.0)          # 300/2000
        self.assertEqual(m["crc_error_rate_pct"], round(50 / 2050 * 100, 1))
        self.assertEqual(m["noise_floor_dbm"], -84.3)
        self.assertEqual(m["channel_utilization_pct"], 70.0)  # 2.1e6 / 3e6
        self.assertEqual(m["strongest_neighbor_rssi_dbm"], -55.0)

    def test_regulatory_domain_from_country_ie(self):
        self.assertEqual(_run()["radio"]["regulatory_domain"], "GB")

    def test_neighbors_pseudonymised_and_same_ess_set(self):
        neighbors = _run()["neighbors"]
        self.assertTrue(all(n["bss_ref"].startswith("bss-") for n in neighbors))
        by_ref = {tuple(sorted(n.items())) for n in neighbors}
        self.assertEqual(len(by_ref), len(neighbors))
        # 'corp' and 'guest' vs connected ssid 'corp'
        same = [n for n in neighbors if n.get("same_ess")]
        self.assertEqual(len(same), 2)  # the two 'corp' APs

    def test_client_samples_pseudonymised(self):
        samples = _run()["client_samples"]
        self.assertEqual(len(samples), 2)
        self.assertTrue(all(s["client_ref"].startswith("cli-") for s in samples))

    def test_csa_becomes_channel_change_event(self):
        events = _run()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "channel_change")
        self.assertEqual(events[0]["channel_to"], 1)
        self.assertEqual(events[0]["channel_from"], 6)

    def test_bluetooth_presence_becomes_non_wifi_interferer(self):
        nwi = _run()["non_wifi_interferers"]
        self.assertEqual(nwi[0]["type"], "bluetooth")
        self.assertGreater(nwi[0]["severity"], 0)

    def test_no_bluetooth_means_no_interferer_entry(self):
        snap = _run(bt={"ble_devices": 0, "classic_devices": 0})
        self.assertNotIn("non_wifi_interferers", snap)

    def test_missing_fields_flags_what_esp32_cannot_supply(self):
        missing = _run()["analysis_context"]["missing_fields"]
        self.assertIn("radio.tx_power_dbm", missing)          # ESP32 doesn't report it
        self.assertIn("rf_metrics.interference_pct", missing)
        self.assertNotIn("rf_metrics.noise_floor_dbm", missing)  # this one it does

    def test_real_mac_reaching_a_propagated_field_is_caught(self):
        # country IE -> radio.regulatory_domain is a raw string passthrough; a
        # MAC landing there must still trip the defensive scan in to_canonical.
        raw = copy.deepcopy(SAMPLE)
        for ap in raw["scan"]:
            ap["country"] = "AA:BB:CC:DD:EE:FF"
        with self.assertRaises(PseudonymisationError):
            Esp32Adapter().to_canonical(raw)


if __name__ == "__main__":
    unittest.main()
