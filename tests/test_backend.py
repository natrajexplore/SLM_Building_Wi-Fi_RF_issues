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

from backend import live_buffer
from backend.config import get_settings
from backend.deps import backend_dep, mongo_store_dep, retriever_dep, settings_dep
from backend.inference import BackendError, ReferenceBackend, StubBackend, build_backend
from backend.main import app
from backend.mongo import QueryStoreError
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


class FakeQueryStore:
    """In-memory QueryStore fake — never touches real MongoDB in tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.saved: list[dict] = []

    def save(self, query, answer, citations, temperature_used, created_at) -> str:
        if self.fail:
            raise QueryStoreError("fake store unavailable")
        doc = {"query": query, "answer": answer, "citations": citations,
               "temperature_used": temperature_used, "created_at": created_at}
        self.saved.append(doc)
        return str(len(self.saved))

    def ping(self) -> bool:
        return not self.fail


class BackendTestCase(unittest.TestCase):
    def setUp(self):
        self.stub = StubBackend()
        self.store = FakeQueryStore()
        app.dependency_overrides[backend_dep] = lambda: self.stub
        app.dependency_overrides[retriever_dep] = lambda: None  # no RAG in tests
        app.dependency_overrides[mongo_store_dep] = lambda: self.store
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

    def test_ingest_esp32(self):
        doc = {
            "collected_at": "2026-03-01T12:00:00Z", "channel": 6, "channel_width_mhz": 20,
            "sample_window_ms": 3000,
            "scan": [
                {"bssid": "aa:bb:cc:00:00:01", "ssid": "corp", "channel": 6, "rssi": -55},
                {"bssid": "aa:bb:cc:00:00:02", "ssid": "corp", "channel": 6, "rssi": -67},
                {"bssid": "aa:bb:cc:00:00:03", "ssid": "x", "channel": 6, "rssi": -71},
            ],
            "sniff": {"frames_total": 1000, "frames_retry": 120, "noise_floor_dbm_avg": -85.0,
                      "airtime_us": 1_500_000, "unique_tx": 8},
        }
        r = self.client.post("/ingest", json={"format": "esp32", "document": doc})
        self.assertEqual(r.status_code, 200, r.text)
        snap = r.json()["snapshots"][0]
        self.assertEqual(snap["radio"]["band"], "2.4GHz")
        self.assertIs(snap["analysis_context"]["spectrum_capable"], False)
        self.assertEqual(snap["rf_metrics"]["co_channel_neighbors"], 3)

    def test_ingest_esp32_missing_document_is_422(self):
        r = self.client.post("/ingest", json={"format": "esp32"})
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


class Live(BackendTestCase):
    def setUp(self):
        super().setUp()
        live_buffer.clear()

    def _esp32_doc(self) -> dict:
        return {
            "collected_at": "2026-03-01T12:00:00Z", "channel": 6, "channel_width_mhz": 20,
            "sample_window_ms": 3000,
            "scan": [
                {"bssid": "aa:bb:cc:00:00:01", "ssid": "corp", "channel": 6, "rssi": -55},
                {"bssid": "aa:bb:cc:00:00:02", "ssid": "corp", "channel": 6, "rssi": -67},
                {"bssid": "aa:bb:cc:00:00:03", "ssid": "x", "channel": 6, "rssi": -71},
            ],
            "sniff": {"frames_total": 1000, "frames_retry": 120, "noise_floor_dbm_avg": -85.0,
                      "airtime_us": 1_500_000, "unique_tx": 8},
        }

    def _use_reference_backend(self):
        from dataclasses import replace

        app.dependency_overrides[settings_dep] = lambda: replace(
            get_settings(), model_backend="reference", rag_enabled=False
        )
        app.dependency_overrides[backend_dep] = lambda: ReferenceBackend()

    def test_live_ingest_diagnoses_and_buffers_for_the_feed(self):
        self._use_reference_backend()
        r = self.client.post("/live/ingest", json={"format": "esp32", "document": self._esp32_doc()})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["id"], 1)
        self.assertEqual(body["snapshot"]["radio"]["band"], "2.4GHz")
        self.assertIn("confidence", body["diagnosis"])

        feed = self.client.get("/live/feed", params={"since": 0})
        self.assertEqual(feed.status_code, 200, feed.text)
        self.assertEqual(len(feed.json()["samples"]), 1)
        self.assertEqual(feed.json()["latest_id"], 1)

        # polling with the id already seen returns nothing new
        self.assertEqual(self.client.get("/live/feed", params={"since": 1}).json()["samples"], [])

    def test_live_ingest_rejects_non_esp32_format(self):
        r = self.client.post("/live/ingest", json={"format": "csv"})
        self.assertEqual(r.status_code, 422)

    def test_live_ingest_requires_document(self):
        r = self.client.post("/live/ingest", json={"format": "esp32"})
        self.assertEqual(r.status_code, 422)

    def test_live_feed_empty_before_any_sample(self):
        r = self.client.get("/live/feed")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"samples": [], "latest_id": 0})


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


class Ask(BackendTestCase):
    def test_ask_answers_and_stores(self):
        self.stub._responses.append("Use the non-overlapping 1/6/11 channel plan.")
        r = self.client.post("/ask", json={"query": "why avoid channel overlap on 2.4GHz?"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["answer"], "Use the non-overlapping 1/6/11 channel plan.")
        self.assertTrue(body["stored"])
        self.assertIsNotNone(body["id"])
        self.assertIsNone(body["store_error"])
        self.assertEqual(len(self.store.saved), 1)
        self.assertEqual(self.store.saved[0]["query"], "why avoid channel overlap on 2.4GHz?")

    def test_ask_runs_at_explanation_band_default_not_diagnosis_temperature(self):
        self.stub._responses.append("...")
        r = self.client.post("/ask", json={"query": "what is CCI?"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["temperature_used"], 0.8)
        self.assertEqual(self.stub.calls[0]["temperature"], 0.8)

    def test_ask_temperature_clamped_to_explanation_band(self):
        self.stub._responses.append("...")
        r = self.client.post("/ask", json={"query": "q", "temperature": 0.0})
        self.assertEqual(r.json()["temperature_used"], 0.7)

    def test_ask_degrades_gracefully_when_store_unavailable(self):
        self.store.fail = True
        self.stub._responses.append("An answer that could not be saved.")
        r = self.client.post("/ask", json={"query": "q"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["answer"], "An answer that could not be saved.")
        self.assertFalse(body["stored"])
        self.assertIsNone(body["id"])
        self.assertIn("unavailable", body["store_error"])

    def test_ask_rejects_empty_query(self):
        r = self.client.post("/ask", json={"query": ""})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.store.saved, [])


if __name__ == "__main__":
    unittest.main()
