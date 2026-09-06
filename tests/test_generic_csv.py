"""Tests for adapters/generic_csv.py — the universal fallback adapter."""
from __future__ import annotations

import io
import unittest

from adapters.base import ContractViolation
from adapters.generic_csv import (
    ColumnMap,
    CsvMapping,
    CsvMappingError,
    GenericCsvAdapter,
    snapshots_from_csv,
)
from adapters.normalize import PseudonymisationError, SchemaValidationError

# A minimal, valid mapping: snapshot_id + timestamp from constants, the three
# schema-required radio fields + a couple of metrics from columns.
BASE_COLUMNS = [
    ColumnMap("ap", "radio.ap_id"),
    ColumnMap("chan", "radio.channel"),
    ColumnMap("width", "radio.channel_width_mhz"),
    ColumnMap("noise", "rf_metrics.noise_floor_dbm"),
    ColumnMap("util", "rf_metrics.channel_utilization_pct"),
    ColumnMap("dfs", "radio.dfs_required"),
]
BASE_CONSTANTS = {
    "snapshot_id": "row-1",
    "timestamp": "2026-03-01T12:00:00Z",
    "radio.band": "5GHz",
}


def _mapping(**over) -> CsvMapping:
    kw = dict(columns=BASE_COLUMNS, spectrum_capable=False, constants=dict(BASE_CONSTANTS))
    kw.update(over)
    return CsvMapping(**kw)


def _row(**over) -> dict:
    row = {"ap": "AP-12", "chan": "36", "width": "80", "noise": "-91.5",
           "util": "42", "dfs": "no"}
    row.update(over)
    return row


class TranslationTests(unittest.TestCase):
    def test_row_becomes_valid_canonical_snapshot_with_coerced_types(self):
        snap = GenericCsvAdapter(_mapping()).to_canonical(_row())
        self.assertEqual(snap["radio"]["channel"], 36)          # int
        self.assertEqual(snap["radio"]["channel_width_mhz"], 80)
        self.assertEqual(snap["rf_metrics"]["noise_floor_dbm"], -91.5)  # float
        self.assertIs(snap["radio"]["dfs_required"], False)     # bool
        self.assertEqual(snap["source"]["adapter"], "generic_csv")

    def test_null_token_cells_are_left_unpopulated_not_null(self):
        snap = GenericCsvAdapter(_mapping()).to_canonical(_row(util="n/a"))
        self.assertNotIn("channel_utilization_pct", snap["rf_metrics"])
        self.assertIn("rf_metrics.channel_utilization_pct",
                      snap["analysis_context"]["missing_fields"])

    def test_required_object_with_no_populated_columns_fails_loudly(self):
        # rf_metrics is schema-required; if every column feeding it is null the
        # adapter must not emit a half-formed snapshot.
        with self.assertRaises(SchemaValidationError):
            GenericCsvAdapter(_mapping()).to_canonical(_row(util="n/a", noise="n/a"))

    def test_spectrum_capable_comes_from_mapping(self):
        for flag in (True, False):
            snap = GenericCsvAdapter(_mapping(spectrum_capable=flag)).to_canonical(_row())
            self.assertIs(snap["analysis_context"]["spectrum_capable"], flag)

    def test_integer_column_accepts_a_decimal_string(self):
        snap = GenericCsvAdapter(_mapping()).to_canonical(_row(chan="36.0"))
        self.assertEqual(snap["radio"]["channel"], 36)

    def test_non_numeric_in_number_column_raises_contract_violation(self):
        with self.assertRaises(ContractViolation):
            GenericCsvAdapter(_mapping()).to_canonical(_row(noise="quiet"))

    def test_unrecognised_boolean_token_raises(self):
        with self.assertRaises(ContractViolation):
            GenericCsvAdapter(_mapping()).to_canonical(_row(dfs="maybe"))

    def test_mapped_column_missing_from_row_raises(self):
        with self.assertRaises(ContractViolation):
            GenericCsvAdapter(_mapping()).to_canonical({"ap": "AP-1"})  # no chan/width/...

    def test_bad_enum_value_passes_through_and_fails_schema(self):
        m = _mapping(constants={**BASE_CONSTANTS, "radio.band": "5.8GHz"})
        with self.assertRaises(SchemaValidationError):
            GenericCsvAdapter(m).to_canonical(_row())

    def test_missing_timestamp_fails_schema_not_silently_invented(self):
        m = _mapping(constants={"snapshot_id": "x", "radio.band": "5GHz"})
        with self.assertRaises(SchemaValidationError):
            GenericCsvAdapter(m).to_canonical(_row())

    def test_real_mac_in_a_mapped_column_is_still_caught(self):
        m = _mapping(columns=BASE_COLUMNS + [ColumnMap("bssid", "radio.radio_id")])
        with self.assertRaises(PseudonymisationError):
            GenericCsvAdapter(m).to_canonical(_row(bssid="AA:BB:CC:DD:EE:FF"))


class MappingValidationTests(unittest.TestCase):
    def test_array_target_rejected_at_construction(self):
        with self.assertRaises(CsvMappingError):
            CsvMapping(columns=[ColumnMap("x", "events[].type")], spectrum_capable=False)
        with self.assertRaises(CsvMappingError):
            CsvMapping(columns=[ColumnMap("x", "neighbors.rssi_dbm")], spectrum_capable=False)

    def test_unknown_path_rejected(self):
        with self.assertRaises(CsvMappingError):
            GenericCsvAdapter(_mapping(columns=[ColumnMap("x", "rf_metrics.snr_floor_dbm")]))

    def test_duplicate_target_path_rejected(self):
        with self.assertRaises(CsvMappingError):
            CsvMapping(
                columns=[ColumnMap("a", "radio.channel"), ColumnMap("b", "radio.channel")],
                spectrum_capable=False,
            )

    def test_non_bool_spectrum_flag_rejected(self):
        with self.assertRaises(CsvMappingError):
            CsvMapping(columns=[], spectrum_capable="yes")  # type: ignore[arg-type]

    def test_from_dict_round_trip(self):
        doc = {
            "spectrum_capable": True,
            "constants": {"snapshot_id": "c-1", "timestamp": "2026-03-01T00:00:00Z",
                          "radio.band": "6GHz"},
            "columns": [
                {"column": "Ch", "path": "radio.channel"},
                {"column": "W", "path": "radio.channel_width_mhz"},
                {"column": "NF", "path": "rf_metrics.noise_floor_dbm", "coerce": "float"},
            ],
        }
        m = CsvMapping.from_dict(doc)
        snap = GenericCsvAdapter(m).to_canonical({"Ch": "37", "W": "160", "NF": "-95"})
        self.assertEqual(snap["radio"]["band"], "6GHz")
        self.assertEqual(snap["radio"]["channel_width_mhz"], 160)


class ExampleMappingTests(unittest.TestCase):
    def test_shipped_example_mapping_loads_and_builds_a_valid_snapshot(self):
        from pathlib import Path

        m = CsvMapping.from_yaml(
            Path(__file__).resolve().parent.parent / "adapters" / "generic_csv.example.map.yaml"
        )
        row = {
            "AP Name": "AP-9", "Radio MAC": "n/a", "Channel": "40",
            "Channel Width": "80", "Tx Power (dBm)": "11", "Noise Floor (dBm)": "-93",
            "Channel Util %": "22", "Retry Rate %": "6", "Co-Channel APs": "2",
            "Client Count": "18", "Avg SNR": "31.5", "DFS Channel": "no",
            "Collected At": "2026-03-01T09:15:00Z", "Snapshot ID": "s-9",
        }
        snap = GenericCsvAdapter(m).to_canonical(row)
        self.assertEqual(snap["radio"]["band"], "5GHz")
        self.assertEqual(snap["clients"]["count"], 18)
        self.assertEqual(snap["clients"]["avg_snr_db"], 31.5)
        self.assertIs(snap["analysis_context"]["spectrum_capable"], False)


class CsvIterationTests(unittest.TestCase):
    def test_snapshots_from_csv_yields_one_per_row(self):
        text = "ap,chan,width,noise,util,dfs\n" \
               "AP-1,36,80,-92,10,no\n" \
               "AP-2,149,40,-90,55,yes\n"
        snaps = list(snapshots_from_csv(io.StringIO(text), _mapping()))
        self.assertEqual(len(snaps), 2)
        self.assertEqual(snaps[1]["radio"]["channel"], 149)
        self.assertIs(snaps[1]["radio"]["dfs_required"], True)
        for s in snaps:
            self.assertEqual(s["analysis_context"]["spectrum_capable"], False)


if __name__ == "__main__":
    unittest.main()
