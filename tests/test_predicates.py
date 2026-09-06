"""Tests for data/predicates.py — the required_evidence grammar evaluator."""
from __future__ import annotations

import unittest

from data import predicates
from data.taxonomy_loader import all_cause_ids, cause as get_cause


class ParsePathTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(
            predicates.parse_path("rf_metrics.co_channel_neighbors"),
            [("rf_metrics", None), ("co_channel_neighbors", None)],
        )

    def test_array_marker(self):
        self.assertEqual(
            predicates.parse_path("events[].type"),
            [("events", "array"), ("type", None)],
        )

    def test_bare_array(self):
        self.assertEqual(predicates.parse_path("non_wifi_interferers[]"), [("non_wifi_interferers", "array")])

    def test_literal_key_with_dot(self):
        # The dot inside "2.4GHz" must NOT be treated as a path separator.
        self.assertEqual(
            predicates.parse_path('clients.band_distribution["2.4GHz"]'),
            [("clients", None), ("band_distribution", "2.4GHz")],
        )

    def test_malformed_raises(self):
        with self.assertRaises(predicates.PredicateError):
            predicates.parse_path("rf_metrics..noise")


class SelectTests(unittest.TestCase):
    SNAP = {
        "rf_metrics": {"co_channel_neighbors": 4},
        "events": [{"type": "radar_detected"}, {"type": "channel_change"}],
        "clients": {"band_distribution": {"2.4GHz": 70.0, "6GHz": 2.0}},
        "non_wifi_interferers": [],
    }

    def sel(self, path):
        return predicates.select(self.SNAP, predicates.parse_path(path))

    def test_plain_hit_and_miss(self):
        self.assertEqual(self.sel("rf_metrics.co_channel_neighbors"), [4])
        self.assertEqual(self.sel("rf_metrics.noise_floor_dbm"), [])

    def test_wildcard_fans_out(self):
        self.assertEqual(self.sel("events[].type"), ["radar_detected", "channel_change"])

    def test_bare_array_returns_the_array(self):
        self.assertEqual(self.sel("non_wifi_interferers[]"), [[]])

    def test_literal_key(self):
        self.assertEqual(self.sel('clients.band_distribution["6GHz"]'), [2.0])


class CheckTests(unittest.TestCase):
    def test_comparison_against_threshold(self):
        snap = {"rf_metrics": {"co_channel_neighbors": 5}}
        self.assertTrue(predicates.check(snap, {
            "path": "rf_metrics.co_channel_neighbors", "predicate": ">=",
            "threshold": "cci_neighbor_concern",
        }))

    def test_absent_matches_empty_array(self):
        self.assertTrue(predicates.check(
            {"non_wifi_interferers": []},
            {"path": "non_wifi_interferers[]", "predicate": "absent"},
        ))
        self.assertTrue(predicates.check(
            {}, {"path": "non_wifi_interferers[]", "predicate": "absent"}
        ))

    def test_absent_false_when_present_nonempty(self):
        self.assertFalse(predicates.check(
            {"non_wifi_interferers": [{"type": "bluetooth"}]},
            {"path": "non_wifi_interferers[]", "predicate": "absent"},
        ))

    def test_wildcard_equality_any_element(self):
        snap = {"events": [{"type": "channel_change"}, {"type": "radar_detected"}]}
        self.assertTrue(predicates.check(snap, {
            "path": "events[].type", "predicate": "==", "value": "radar_detected"
        }))

    def test_any_of_group(self):
        pred = {"any_of": [
            {"path": "capabilities.afc_status", "predicate": "==", "value": "denied"},
            {"path": "capabilities.afc_status", "predicate": "==", "value": "expired"},
        ]}
        self.assertTrue(predicates.check({"capabilities": {"afc_status": "expired"}}, pred))
        self.assertFalse(predicates.check({"capabilities": {"afc_status": "granted"}}, pred))

    def test_comparison_on_absent_is_false_not_error(self):
        self.assertFalse(predicates.check({}, {
            "path": "rf_metrics.retry_rate_pct", "predicate": ">=", "value": 25
        }))

    def test_value_and_threshold_both_present_raises(self):
        with self.assertRaises(predicates.PredicateError):
            predicates.check({"a": 1}, {"path": "a", "predicate": ">=", "value": 1, "threshold": "x"})


class TaxonomyWideTests(unittest.TestCase):
    def test_every_required_evidence_entry_is_evaluable(self):
        # A malformed predicate anywhere in the taxonomy raises here.
        empty: dict = {}
        for cid in all_cause_ids():
            for entry in get_cause(cid).get("required_evidence", []):
                predicates.check(empty, entry)  # must not raise

    def test_evidence_paths_collects_any_of_members(self):
        paths = predicates.evidence_paths(get_cause("RF-6-001"))
        self.assertIn("radio.power_mode", paths)
        self.assertIn("capabilities.afc_status", paths)


if __name__ == "__main__":
    unittest.main()
