"""Smoke tests for the Adapter contract (adapters/base.py, adapters/normalize.py).

No vendor adapters exist yet, so these exercise the contract with minimal
dummy subclasses rather than any real vendor mapping.

Run with: python -m unittest discover -s tests
"""
from __future__ import annotations

import unittest

from adapters.base import Adapter, ContractViolation
from adapters.normalize import (
    PseudonymisationError,
    SchemaValidationError,
    canonical_field_paths,
)

MINIMAL_SNAPSHOT = {
    "snapshot_id": "snap-1",
    "timestamp": "2026-01-01T00:00:00Z",
    "radio": {"band": "5GHz", "channel": 36, "channel_width_mhz": 80},
    "rf_metrics": {"noise_floor_dbm": -92},
}


class GoodAdapter(Adapter):
    name = "test_good"

    def _translate(self, raw):
        snapshot = {**MINIMAL_SNAPSHOT}
        snapshot["analysis_context"] = {"spectrum_capable": False}
        snapshot["client_samples"] = [{"client_ref": "AA:BB:CC:DD:EE:FF", "snr_db": 30}]
        snapshot["neighbors"] = [{"bss_ref": "11:22:33:44:55:66", "same_ess": True}]
        return snapshot


class NoSpectrumFlagAdapter(Adapter):
    name = "test_no_flag"

    def _translate(self, raw):
        return {**MINIMAL_SNAPSHOT}


class NamelessAdapter(Adapter):
    name = ""

    def _translate(self, raw):
        return {**MINIMAL_SNAPSHOT, "analysis_context": {"spectrum_capable": True}}


class SchemaInvalidAdapter(Adapter):
    name = "test_invalid"

    def _translate(self, raw):
        return {
            "snapshot_id": "snap-2",
            "timestamp": "2026-01-01T00:00:00Z",
            "radio": {"band": "5GHz", "channel": 36, "channel_width_mhz": 80},
            "rf_metrics": {"noise_floor_dbm": -92},
            "analysis_context": {"spectrum_capable": True},
            "not_a_real_field": "boom",  # additionalProperties: false at root
        }


class LeakyMacAdapter(Adapter):
    """Places a MAC where pseudonymise_identifiers() does not look."""

    name = "test_leaky"

    def _translate(self, raw):
        snapshot = {**MINIMAL_SNAPSHOT}
        snapshot["analysis_context"] = {"spectrum_capable": True}
        snapshot["neighbors"] = [
            {"bss_ref": "11:22:33:44:55:66", "vendor_hint": "AA:BB:CC:DD:EE:FF"}
        ]
        return snapshot


class CanonicalFieldPathsTests(unittest.TestCase):
    def test_map_typed_fields_are_tracked_as_leaves(self):
        # Regression: additionalProperties-only objects (no `properties` key)
        # were silently dropped from the path set instead of being tracked.
        paths = set(canonical_field_paths())
        self.assertIn("clients.phy_rate_distribution", paths)
        self.assertIn("clients.band_distribution", paths)

    def test_array_fields_tracked_whole_not_walked_into(self):
        paths = set(canonical_field_paths())
        self.assertIn("events", paths)
        self.assertNotIn("events.type", paths)
        self.assertNotIn("events[].type", paths)

    def test_source_and_missing_fields_excluded(self):
        paths = set(canonical_field_paths())
        self.assertFalse(any(p == "source" or p.startswith("source.") for p in paths))
        self.assertNotIn("analysis_context.missing_fields", paths)


class AdapterContractTests(unittest.TestCase):
    def test_well_formed_snapshot_validates_and_returns(self):
        result = GoodAdapter().to_canonical(raw={})
        self.assertEqual(result["snapshot_id"], "snap-1")
        self.assertEqual(result["source"]["adapter"], "test_good")

    def test_missing_fields_populated_for_unsupplied_canonical_fields(self):
        result = GoodAdapter().to_canonical(raw={})
        missing = result["analysis_context"]["missing_fields"]
        self.assertIn("radio.tx_power_dbm", missing)
        self.assertIn("rf_metrics.channel_utilization_pct", missing)
        # Supplied fields must NOT be reported missing.
        self.assertNotIn("radio.channel", missing)
        self.assertNotIn("rf_metrics.noise_floor_dbm", missing)

    def test_client_and_bss_identifiers_are_pseudonymised(self):
        result = GoodAdapter().to_canonical(raw={})
        client_ref = result["client_samples"][0]["client_ref"]
        bss_ref = result["neighbors"][0]["bss_ref"]
        self.assertNotEqual(client_ref, "AA:BB:CC:DD:EE:FF")
        self.assertNotEqual(bss_ref, "11:22:33:44:55:66")
        self.assertTrue(client_ref.startswith("cli-"))
        self.assertTrue(bss_ref.startswith("bss-"))

    def test_missing_spectrum_capable_is_a_contract_violation(self):
        with self.assertRaises(ContractViolation):
            NoSpectrumFlagAdapter().to_canonical(raw={})

    def test_missing_adapter_name_is_a_contract_violation(self):
        with self.assertRaises(ContractViolation):
            NamelessAdapter().to_canonical(raw={})

    def test_schema_invalid_output_fails_loudly(self):
        with self.assertRaises(SchemaValidationError):
            SchemaInvalidAdapter().to_canonical(raw={})

    def test_mac_outside_known_identifier_fields_is_caught(self):
        with self.assertRaises(PseudonymisationError):
            LeakyMacAdapter().to_canonical(raw={})

    def test_cannot_instantiate_adapter_without_translate(self):
        with self.assertRaises(TypeError):
            Adapter()  # abstract method _translate not implemented


if __name__ == "__main__":
    unittest.main()
