"""Tests for the FastAPI backend (backend/).

Uses TestClient + a StubBackend (no Ollama). The diagnosis snapshot is built by
the phase-4 scenario builder so it genuinely satisfies a cause's
required_evidence — that is what backend/rca.py checks.
"""
from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.deps import backend_dep, retriever_dep
from backend.inference import BackendError, StubBackend, build_backend
from backend.main import app
from data import generate, scenarios

CSV_MAPPING = {
    "spectrum_capable": False,
    "constants": {"snapshot_id": "r1", "timestamp": "2026-03-01T12:00:00Z", "radio.band": "5GHz"},
    "columns": [
        {"column": "ch", "path": "radio.channel"},
        {"column": "w", "path": "radio.channel_width_mhz"},
        {"column": "nf", "path": "rf_metrics.noise_floor_dbm"},
    ],
}


def _eligible_snapshot(cid: str = "RF-24-001") -> dict:
    spec = scenarios.build_single(cid, random.Random(3))
    generate._finalise_snapshot(spec["snapshot"])
    return spec["snapshot"], spec["held_paths"]


def _valid_rca(cid: str, held_paths: list[str], snapshot: dict) -> dict:
    return {
        "cause_id": cid,
        "confidence": "high",
        "evidence": [
            {"field_path": p,
             "observed_value": scenarios._observed(snapshot, p),
             "why_it_matters": "This reading is in the range the cause requires."}
            for p in held_paths
        ],
        "affected_bands": [snapshot["radio"]["band"]],
        "remediation": ["Re-plan the channel assignment."],
        "data_gaps": [],
    }


class BackendTestCase(unittest.TestCase):
    def setUp(self):
        self.stub = StubBackend()
        app.dependency_overrides[backend_dep] = lambda: self.stub
        app.dependency_overrides[retriever_dep] = lambda: None  # no RAG in tests
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()


class HealthAndIngest(BackendTestCase):
    def test_health(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_ingest_csv(self):
        r = self.client.post("/ingest", json={
            "format": "csv", "mapping": CSV_MAPPING,
            "rows": [{"ch": "36", "w": "80", "nf": "-92"}, {"ch": "149", "w": "40", "nf": "-90"}],
        })
        self.assertEqual(r.status_code, 200, r.text)
        snaps = r.json()["snapshots"]
        self.assertEqual(len(snaps), 2)
        self.assertEqual(snaps[1]["radio"]["channel"], 149)
        self.assertFalse(snaps[0]["analysis_context"]["spectrum_capable"])

    def test_ingest_bad_mapping_is_422(self):
        bad = {**CSV_MAPPING, "columns": [{"column": "x", "path": "events[].type"}]}
        r = self.client.post("/ingest", json={"format": "csv", "mapping": bad, "rows": [{"x": "y"}]})
        self.assertEqual(r.status_code, 422)


class Diagnose(BackendTestCase):
    def test_valid_diagnosis_passes_through_and_uses_fixed_low_temperature(self):
        snap, held = _eligible_snapshot("RF-24-001")
        self.stub._responses.append(json.dumps(_valid_rca("RF-24-001", held, snap)))
        r = self.client.post("/diagnose", json={"snapshot": snap, "retrieve": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["cause_id"], "RF-24-001")
        self.assertEqual(self.stub.calls[0]["temperature"], 0.15)  # never caller-controlled

    def test_ineligible_cause_is_rejected_422(self):
        snap, _ = _eligible_snapshot("RF-24-001")
        # assert a cause whose evidence is NOT in this snapshot
        self.stub._responses.append(json.dumps({
            "cause_id": "RF-5-001", "confidence": "high", "evidence": [],
            "affected_bands": ["5GHz"], "remediation": [], "data_gaps": [],
        }))
        r = self.client.post("/diagnose", json={"snapshot": snap, "retrieve": False})
        self.assertEqual(r.status_code, 422)
        self.assertIn("required_evidence", r.json()["detail"])

    def test_non_json_model_output_is_422(self):
        snap, _ = _eligible_snapshot()
        self.stub._responses.append("I think it's probably co-channel interference.")
        r = self.client.post("/diagnose", json={"snapshot": snap, "retrieve": False})
        self.assertEqual(r.status_code, 422)

    def test_bad_snapshot_is_422_before_model_call(self):
        r = self.client.post("/diagnose", json={"snapshot": {"snapshot_id": "x"}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.stub.calls, [])

    def test_bare_regulatory_number_without_citation_is_rejected(self):
        snap, held = _eligible_snapshot("RF-24-001")
        rca = _valid_rca("RF-24-001", held, snap)
        rca["remediation"] = ["Set EIRP to 36 dBm."]
        self.stub._responses.append(json.dumps(rca))
        r = self.client.post("/diagnose", json={"snapshot": snap, "retrieve": False})
        self.assertEqual(r.status_code, 422)
        self.assertIn("citation", r.json()["detail"])


class BackendSelection(unittest.TestCase):
    def test_unknown_backend_raises(self):
        from dataclasses import replace

        with self.assertRaises(BackendError):
            build_backend(replace(get_settings(), model_backend="nope"))

    def test_reference_backend_produces_a_contract_valid_diagnosis(self):
        from dataclasses import replace

        from backend.inference import run_diagnosis

        snap, held = _eligible_snapshot("RF-24-001")
        cfg = replace(get_settings(), model_backend="reference", rag_enabled=False)
        result = run_diagnosis(snap, build_backend(cfg), cfg, retriever=None)
        self.assertEqual(result.cause_id, "RF-24-001")
        self.assertTrue(result.evidence)
        self.assertTrue(all(e.field_path in held for e in result.evidence))

    def test_reference_backend_abstains_when_nothing_is_eligible(self):
        from dataclasses import replace

        from backend.inference import run_diagnosis

        # a healthy 5 GHz snapshot satisfies no cause's required_evidence
        from data.snapshots import healthy_baseline
        snap = healthy_baseline("5GHz", random.Random(0))
        snap["analysis_context"]["spectrum_capable"] = False
        generate._finalise_snapshot(snap)
        cfg = replace(get_settings(), model_backend="reference", rag_enabled=False)
        result = run_diagnosis(snap, build_backend(cfg), cfg, retriever=None)
        self.assertIsNone(result.cause_id)
        self.assertTrue(result.data_gaps)

    def test_adapter_backend_without_a_trained_adapter_raises_clearly(self):
        from dataclasses import replace

        with tempfile.TemporaryDirectory() as d:
            cfg = replace(get_settings(), model_backend="adapter", adapter_dir=Path(d))
            with self.assertRaises(BackendError) as cm:
                build_backend(cfg)
            self.assertIn("no LoRA adapter", str(cm.exception))

    def test_adapter_backend_reports_missing_training_deps(self):
        from dataclasses import replace

        try:
            import peft  # noqa: F401
        except ImportError:
            pass
        else:
            self.skipTest("peft is installed; this asserts the missing-deps path")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "adapter_config.json").write_text("{}")
            cfg = replace(get_settings(), model_backend="adapter", adapter_dir=Path(d))
            with self.assertRaises(BackendError) as cm:
                build_backend(cfg)
            self.assertIn("requirements-train.txt", str(cm.exception))


class Explain(BackendTestCase):
    def _payload(self, temperature=None):
        snap, held = _eligible_snapshot("RF-24-001")
        body = {"snapshot": snap, "diagnosis": _valid_rca("RF-24-001", held, snap)}
        if temperature is not None:
            body["temperature"] = temperature
        return body

    def test_temperature_clamped_low(self):
        self.stub._responses.append("Here is the explanation.")
        r = self.client.post("/explain", json=self._payload(temperature=0.1))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["temperature_used"], 0.7)
        self.assertEqual(self.stub.calls[0]["temperature"], 0.7)

    def test_temperature_clamped_high(self):
        self.stub._responses.append("...")
        r = self.client.post("/explain", json=self._payload(temperature=1.9))
        self.assertEqual(r.json()["temperature_used"], 0.9)

    def test_temperature_default_when_absent(self):
        self.stub._responses.append("...")
        r = self.client.post("/explain", json=self._payload())
        self.assertEqual(r.json()["temperature_used"], 0.8)


if __name__ == "__main__":
    unittest.main()
