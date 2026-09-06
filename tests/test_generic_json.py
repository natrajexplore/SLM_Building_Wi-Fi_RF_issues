"""Tests for adapters/generic_json.py — the nested-JSON fallback adapter."""
from __future__ import annotations

import unittest

from adapters.base import ContractViolation
from adapters.generic_json import (
    ArrayMap,
    FieldMap,
    GenericJsonAdapter,
    JsonMapping,
    JsonMappingError,
)
from adapters.normalize import PseudonymisationError, SchemaValidationError

CONSTS = {"snapshot_id": "j-1", "timestamp": "2026-03-01T12:00:00Z", "radio.band": "5GHz"}


def _mapping(**over) -> JsonMapping:
    kw = dict(
        spectrum_capable=True,
        constants=dict(CONSTS),
        scalars=[
            FieldMap("rf.primaryChannel", "radio.channel"),
            FieldMap("rf.width", "radio.channel_width_mhz"),
            FieldMap("metrics.noiseDbm", "rf_metrics.noise_floor_dbm"),
            FieldMap("metrics.utilPct", "rf_metrics.channel_utilization_pct"),
        ],
        arrays=[
            ArrayMap("events", "events", (
                FieldMap("kind", "type"), FieldMap("at", "timestamp"),
            )),
            ArrayMap("nearby", "neighbors", (
                FieldMap("bssid", "bss_ref"), FieldMap("rssi", "rssi_dbm"),
                FieldMap("sameEss", "same_ess"),
            )),
        ],
    )
    kw.update(over)
    return JsonMapping(**kw)


def _doc(**over) -> dict:
    d = {
        "rf": {"primaryChannel": 36, "width": 80},
        "metrics": {"noiseDbm": -90.5, "utilPct": 33},
        "events": [
            {"kind": "radar_detected", "at": "2026-03-01T12:01:00Z"},
            {"kind": "channel_change", "at": "2026-03-01T12:01:05Z"},
        ],
        "nearby": [
            {"bssid": "bss-aaa", "rssi": -70, "sameEss": True},
        ],
    }
    d.update(over)
    return d


class TranslationTests(unittest.TestCase):
    def test_nested_scalars_and_arrays_become_valid_snapshot(self):
        snap = GenericJsonAdapter(_mapping()).to_canonical(_doc())
        self.assertEqual(snap["radio"]["channel"], 36)
        self.assertEqual(snap["rf_metrics"]["noise_floor_dbm"], -90.5)
        self.assertEqual([e["type"] for e in snap["events"]], ["radar_detected", "channel_change"])
        self.assertEqual(snap["neighbors"][0]["rssi_dbm"], -70)
        self.assertIs(snap["neighbors"][0]["same_ess"], True)
        self.assertIs(snap["analysis_context"]["spectrum_capable"], True)

    def test_missing_source_array_yields_no_canonical_array(self):
        snap = GenericJsonAdapter(_mapping()).to_canonical(_doc(events=[], nearby=None))
        self.assertNotIn("events", snap)
        self.assertNotIn("neighbors", snap)

    def test_missing_scalar_source_becomes_missing_field(self):
        doc = _doc()
        del doc["metrics"]["utilPct"]
        snap = GenericJsonAdapter(_mapping()).to_canonical(doc)
        self.assertIn("rf_metrics.channel_utilization_pct",
                      snap["analysis_context"]["missing_fields"])

    def test_array_element_type_coercion_uses_schema(self):
        # rssi is a schema `number`; a stringy source value is coerced.
        doc = _doc(nearby=[{"bssid": "bss-x", "rssi": "-66.0", "sameEss": "yes"}])
        snap = GenericJsonAdapter(_mapping()).to_canonical(doc)
        self.assertEqual(snap["neighbors"][0]["rssi_dbm"], -66.0)
        self.assertIs(snap["neighbors"][0]["same_ess"], True)

    def test_bad_enum_in_array_element_fails_schema(self):
        doc = _doc(events=[{"kind": "not_a_real_event", "at": "2026-03-01T12:00:00Z"}])
        with self.assertRaises(SchemaValidationError):
            GenericJsonAdapter(_mapping()).to_canonical(doc)

    def test_array_element_missing_its_required_field_fails_schema(self):
        # events[] requires `timestamp`; drop it and schema validation catches it.
        doc = _doc(events=[{"kind": "radar_detected"}])
        with self.assertRaises(SchemaValidationError):
            GenericJsonAdapter(_mapping()).to_canonical(doc)

    def test_non_object_array_item_raises_contract_violation(self):
        with self.assertRaises(ContractViolation):
            GenericJsonAdapter(_mapping()).to_canonical(_doc(nearby=["just a string"]))

    def test_real_mac_in_a_free_text_element_field_is_caught(self):
        m = _mapping(arrays=[
            ArrayMap("nearby", "neighbors", (
                FieldMap("bssid", "bss_ref"), FieldMap("desc", "vendor_hint"),
            )),
        ])
        doc = _doc(nearby=[{"bssid": "bss-x", "desc": "seen as AA:BB:CC:DD:EE:FF"}])
        with self.assertRaises(PseudonymisationError):
            GenericJsonAdapter(m).to_canonical(doc)

    def test_a_real_mac_in_bss_ref_is_pseudonymised_not_leaked(self):
        doc = _doc(nearby=[{"bssid": "AA:BB:CC:DD:EE:FF", "rssi": -70, "sameEss": True}])
        snap = GenericJsonAdapter(_mapping()).to_canonical(doc)
        self.assertTrue(snap["neighbors"][0]["bss_ref"].startswith("bss-"))
        self.assertNotIn("AA:BB", snap["neighbors"][0]["bss_ref"])


class MappingValidationTests(unittest.TestCase):
    def test_unknown_scalar_target_rejected(self):
        with self.assertRaises(JsonMappingError):
            JsonMapping(spectrum_capable=True, scalars=[FieldMap("x", "rf_metrics.bogus")])

    def test_unknown_array_target_rejected(self):
        with self.assertRaises(JsonMappingError):
            JsonMapping(spectrum_capable=True,
                        arrays=[ArrayMap("x", "widgets", (FieldMap("a", "b"),))])

    def test_unknown_array_element_field_rejected(self):
        with self.assertRaises(JsonMappingError):
            JsonMapping(spectrum_capable=True,
                        arrays=[ArrayMap("x", "events", (FieldMap("a", "not_a_field"),))])

    def test_shipped_example_mapping_loads_and_builds_a_valid_snapshot(self):
        from pathlib import Path

        m = JsonMapping.from_yaml(
            Path(__file__).resolve().parent.parent / "adapters" / "generic_json.example.map.yaml"
        )
        doc = {
            "ap": {"id": "AP-7", "collectedAt": "2026-03-01T10:00:00Z"},
            "radio": {"primaryChannel": 52, "widthMHz": 80, "txPowerDbm": 14, "dfs": True},
            "metrics": {"noiseFloorDbm": -94, "channelUtil": 18, "retryRate": 5},
            "clients": {"total": 20, "avgSnr": 34},
            "spectrumEvents": [{"type": "radar_detected", "time": "2026-03-01T10:02:00Z"}],
            "neighborBss": [{"bssid": "bss-7a", "channel": 52, "rssiDbm": -75, "sameEss": False}],
        }
        snap = GenericJsonAdapter(m).to_canonical(doc)
        self.assertEqual(snap["radio"]["channel"], 52)
        self.assertEqual(snap["events"][0]["type"], "radar_detected")
        self.assertEqual(snap["neighbors"][0]["channel"], 52)
        self.assertIs(snap["analysis_context"]["spectrum_capable"], True)

    def test_from_dict(self):
        m = JsonMapping.from_dict({
            "spectrum_capable": False,
            "constants": CONSTS,
            "scalars": [
                {"from": "c", "to": "radio.channel"},
                {"from": "w", "to": "radio.channel_width_mhz"},
                {"from": "nf", "to": "rf_metrics.noise_floor_dbm"},
            ],
            "arrays": [{"from": "evs", "to": "events",
                        "element": [{"from": "t", "to": "type"}, {"from": "ts", "to": "timestamp"}]}],
        })
        snap = GenericJsonAdapter(m).to_canonical(
            {"c": 6, "w": 20, "nf": -93, "evs": [{"t": "ap_reboot", "ts": "2026-03-01T00:00:00Z"}]}
        )
        self.assertEqual(snap["events"][0]["type"], "ap_reboot")
        self.assertIs(snap["analysis_context"]["spectrum_capable"], False)


if __name__ == "__main__":
    unittest.main()
