"""Tests for adapters/cisco_c9800.py — the Cisco Catalyst 9800 WLC adapter."""
from __future__ import annotations

import copy
import unittest

from adapters.base import ContractViolation
from adapters.cisco_c9800 import CiscoC9800Adapter
from adapters.normalize import PseudonymisationError

SAMPLE = {
    "collected_at": "2026-03-01T12:00:00Z",
    "ap_name": "AP-3F-12",
    "site": {"site_id": "hq-3f", "environment": "office", "ap_group": "floor3", "floor": "3"},
    "collection_method": "restconf",
    "observation_window_minutes": 5,
    "reported_symptom": "video calls drop near conference room B",
    "radio": {
        "slot_id": 1,
        "band": "5GHz",
        "channel": 36,
        "channel_width_mhz": 80,
        "operating_class": 121,
        "tx_power_dbm": 17,
        "tx_power_max_dbm": 20,
        "regulatory_domain": "US",
        "phy_modes": ["11ac", "11ax"],
        "dfs_required": True,
        "admin_state": "enabled",
        "clean_air_enabled": True,
    },
    "rrm": {
        "noise_floor_dbm": -92,
        "channel_utilization_pct": 34,
        "interference_pct": 6,
        "co_channel_neighbors": 2,
        "adjacent_channel_neighbors": 1,
        "strongest_neighbor_rssi_dbm": -55,
    },
    "clients": {
        "count": 18,
        "avg_snr_db": 28,
        "phy_rate_distribution": {"11ax": 70, "11ac": 30},
        "band_distribution": {"5GHz": 100},
        "samples": [
            {"client_mac": "aa:bb:cc:00:00:01", "snr_db": 30, "rssi_dbm": -52,
             "phy_mode": "11ax", "tx_rate_mbps": 866, "retry_rate_pct": 4,
             "supported_bands": ["5GHz"], "capabilities": ["11k", "11v"]},
        ],
    },
    "wlan": {
        "dot11k": True, "dot11v": True, "dot11r": False,
        "dot11w_pmf": "optional", "owe_enabled": False, "wpa3_enforced": True,
        "band_steering": True, "airtime_fairness": True,
        "afc_supported": False, "afc_status": "not_applicable",
        "min_data_rate_mbps": 12, "multicast_handling": "unicast_conversion",
        "bands_supported": ["5GHz"],
    },
    "neighbors": [
        {"bssid": "aa:bb:cc:00:00:02", "channel": 40, "channel_width_mhz": 80,
         "rssi_dbm": -60, "same_ess": False, "vendor_hint": "cisco"},
    ],
    "spectrum": [
        {"type": "microwave_oven", "severity": 40, "duty_cycle_pct": 12,
         "center_freq_mhz": 2450, "bandwidth_mhz": 20},
    ],
    "events": [
        {"type": "radar_detected", "timestamp": "2026-03-01T11:58:00Z",
         "channel_from": 116, "channel_to": 40, "detail": "DFS event"},
    ],
}


def _run(**overrides) -> dict:
    raw = copy.deepcopy(SAMPLE)
    raw.update(overrides)
    return CiscoC9800Adapter().to_canonical(raw)


class TranslationTests(unittest.TestCase):
    def test_produces_valid_canonical_snapshot(self):
        snap = _run()
        self.assertEqual(snap["radio"]["band"], "5GHz")
        self.assertEqual(snap["radio"]["channel"], 36)
        self.assertEqual(snap["radio"]["ap_id"], "AP-3F-12")
        self.assertEqual(snap["radio"]["radio_id"], "1")
        self.assertEqual(snap["source"]["adapter"], "cisco_c9800")

    def test_missing_collected_at_refuses_rather_than_inventing(self):
        raw = copy.deepcopy(SAMPLE)
        del raw["collected_at"]
        with self.assertRaises(ContractViolation):
            CiscoC9800Adapter().to_canonical(raw)

    def test_missing_radio_object_refused(self):
        raw = copy.deepcopy(SAMPLE)
        del raw["radio"]
        with self.assertRaises(ContractViolation):
            CiscoC9800Adapter().to_canonical(raw)

    def test_missing_required_radio_field_refused(self):
        for key in ("band", "channel", "channel_width_mhz"):
            raw = copy.deepcopy(SAMPLE)
            del raw["radio"][key]
            with self.assertRaises(ContractViolation):
                CiscoC9800Adapter().to_canonical(raw)

    def test_phy_modes_and_bands_supported_pass_through(self):
        snap = _run()
        self.assertEqual(snap["radio"]["phy_modes"], ["11ac", "11ax"])
        self.assertEqual(snap["capabilities"]["bands_supported"], ["5GHz"])

    def test_rf_metrics_mapped(self):
        m = _run()["rf_metrics"]
        self.assertEqual(m["noise_floor_dbm"], -92)
        self.assertEqual(m["co_channel_neighbors"], 2)
        self.assertEqual(m["adjacent_channel_neighbors"], 1)

    def test_site_mapped(self):
        site = _run()["site"]
        self.assertEqual(site["site_id"], "hq-3f")
        self.assertEqual(site["environment"], "office")

    def test_source_collection_method_mapped(self):
        self.assertEqual(_run()["source"]["collection_method"], "restconf")

    def test_invalid_collection_method_refused(self):
        with self.assertRaises(ContractViolation):
            _run(collection_method="carrier_pigeon")

    def test_capabilities_mapped(self):
        caps = _run()["capabilities"]
        self.assertTrue(caps["dot11k"])
        self.assertFalse(caps["dot11r"])
        self.assertEqual(caps["dot11w_pmf"], "optional")
        self.assertEqual(caps["min_data_rate_mbps"], 12)

    def test_clients_aggregate_and_distributions(self):
        clients = _run()["clients"]
        self.assertEqual(clients["count"], 18)
        self.assertEqual(clients["phy_rate_distribution"], {"11ax": 70.0, "11ac": 30.0})
        self.assertEqual(clients["band_distribution"], {"5GHz": 100.0})

    def test_client_samples_pseudonymised(self):
        samples = _run()["client_samples"]
        self.assertEqual(len(samples), 1)
        self.assertTrue(samples[0]["client_ref"].startswith("cli-"))
        self.assertEqual(samples[0]["phy_mode"], "11ax")
        self.assertEqual(samples[0]["supported_bands"], ["5GHz"])

    def test_client_samples_truncated_to_50(self):
        samples = [
            {"client_mac": f"aa:bb:cc:00:{i:02x}:01", "snr_db": 20}
            for i in range(60)
        ]
        snap = _run(clients={"count": 60, "samples": samples})
        self.assertEqual(len(snap["client_samples"]), 50)

    def test_neighbors_pseudonymised(self):
        neighbors = _run()["neighbors"]
        self.assertEqual(len(neighbors), 1)
        self.assertTrue(neighbors[0]["bss_ref"].startswith("bss-"))
        self.assertEqual(neighbors[0]["channel"], 40)
        self.assertFalse(neighbors[0]["same_ess"])

    def test_events_mapped_and_validated(self):
        events = _run()["events"]
        self.assertEqual(events[0]["type"], "radar_detected")
        self.assertEqual(events[0]["channel_from"], 116)
        self.assertEqual(events[0]["channel_to"], 40)

    def test_unknown_event_type_refused(self):
        raw = copy.deepcopy(SAMPLE)
        raw["events"][0]["type"] = "flux_capacitor_overload"
        with self.assertRaises(ContractViolation):
            CiscoC9800Adapter().to_canonical(raw)

    def test_spectrum_capable_true_when_clean_air_enabled(self):
        self.assertIs(_run()["analysis_context"]["spectrum_capable"], True)

    def test_spectrum_capable_false_when_absent(self):
        raw = copy.deepcopy(SAMPLE)
        del raw["radio"]["clean_air_enabled"]
        del raw["spectrum"]
        snap = CiscoC9800Adapter().to_canonical(raw)
        self.assertIs(snap["analysis_context"]["spectrum_capable"], False)

    def test_non_wifi_interferers_mapped_when_clean_air_enabled(self):
        nwi = _run()["non_wifi_interferers"]
        self.assertEqual(nwi[0]["type"], "microwave_oven")
        self.assertEqual(nwi[0]["severity"], 40)

    def test_spectrum_entries_without_clean_air_refused(self):
        raw = copy.deepcopy(SAMPLE)
        raw["radio"]["clean_air_enabled"] = False
        with self.assertRaises(ContractViolation):
            CiscoC9800Adapter().to_canonical(raw)

    def test_unknown_interferer_type_refused(self):
        raw = copy.deepcopy(SAMPLE)
        raw["spectrum"][0]["type"] = "death_ray"
        with self.assertRaises(ContractViolation):
            CiscoC9800Adapter().to_canonical(raw)

    def test_neighbor_scan_and_client_detail_flags(self):
        ctx = _run()["analysis_context"]
        self.assertTrue(ctx["neighbor_scan_available"])
        self.assertTrue(ctx["client_detail_available"])

    def test_no_neighbors_or_samples_means_flags_false(self):
        snap = _run(neighbors=[], clients={"count": 0})
        ctx = snap["analysis_context"]
        self.assertFalse(ctx["neighbor_scan_available"])
        self.assertFalse(ctx["client_detail_available"])

    def test_reported_symptom_and_observation_window_mapped(self):
        ctx = _run()["analysis_context"]
        self.assertEqual(ctx["reported_symptom"], "video calls drop near conference room B")
        self.assertEqual(ctx["observation_window_minutes"], 5.0)

    def test_loosely_typed_string_values_coerced(self):
        raw = copy.deepcopy(SAMPLE)
        raw["radio"]["channel"] = "36"
        raw["radio"]["dfs_required"] = "Enabled"
        raw["rrm"]["noise_floor_dbm"] = "-92"
        snap = CiscoC9800Adapter().to_canonical(raw)
        self.assertEqual(snap["radio"]["channel"], 36)
        self.assertIs(snap["radio"]["dfs_required"], True)
        self.assertEqual(snap["rf_metrics"]["noise_floor_dbm"], -92.0)

    def test_missing_fields_flags_what_c9800_capture_cannot_supply(self):
        raw = {
            "collected_at": "2026-03-01T12:00:00Z",
            "radio": {"band": "5GHz", "channel": 36, "channel_width_mhz": 80},
        }
        missing = CiscoC9800Adapter().to_canonical(raw)["analysis_context"]["missing_fields"]
        self.assertIn("rf_metrics.noise_floor_dbm", missing)
        self.assertIn("radio.tx_power_dbm", missing)
        self.assertNotIn("radio.band", missing)

    def test_real_mac_reaching_a_propagated_field_is_caught(self):
        raw = copy.deepcopy(SAMPLE)
        raw["neighbors"][0]["vendor_hint"] = "AA:BB:CC:DD:EE:FF"
        with self.assertRaises(PseudonymisationError):
            CiscoC9800Adapter().to_canonical(raw)

    def test_raw_input_must_be_dict(self):
        with self.assertRaises(ContractViolation):
            CiscoC9800Adapter().to_canonical(["not", "a", "dict"])


if __name__ == "__main__":
    unittest.main()
