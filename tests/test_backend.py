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
import urllib.error
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from backend import live_buffer
from backend.config import get_settings
from backend.deps import ask_backend_dep, backend_dep, query_store_dep, retriever_dep, settings_dep
from backend.inference import BackendError, OllamaBackend, ReferenceBackend, StubBackend, build_backend
from backend.main import app
from backend.query_store import QueryStoreError
from data import generate, scenarios


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Minimal SSE parser mirroring frontend/src/api.ts's askStream framing."""
    events: list[tuple[str, dict]] = []
    for raw in text.split("\n\n"):
        raw = raw.strip()
        if not raw:
            continue
        event, data = "message", None
        for line in raw.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        events.append((event, data))
    return events

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
    """In-memory QueryStore fake — never touches real PostgreSQL in tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.conversations: dict[str, dict] = {}  # id -> {title, created_at}
        self.messages: dict[str, list[dict]] = {}  # conversation_id -> [message, ...]
        self._next_conv_id = 1
        self._next_msg_id = 1

    def create_conversation(self, title, created_at) -> str:
        if self.fail:
            raise QueryStoreError("fake store unavailable")
        cid = str(self._next_conv_id)
        self._next_conv_id += 1
        self.conversations[cid] = {"title": title, "created_at": created_at}
        self.messages[cid] = []
        return cid

    def add_message(self, conversation_id, role, content, citations, temperature_used, created_at) -> str:
        if self.fail:
            raise QueryStoreError("fake store unavailable")
        if conversation_id not in self.conversations:
            raise QueryStoreError(f"no such conversation {conversation_id!r}")
        mid = str(self._next_msg_id)
        self._next_msg_id += 1
        self.messages[conversation_id].append({
            "id": mid, "role": role, "content": content, "citations": citations,
            "temperature_used": temperature_used, "created_at": created_at,
        })
        return mid

    def get_messages(self, conversation_id) -> list[dict]:
        if self.fail:
            raise QueryStoreError("fake store unavailable")
        return list(self.messages.get(conversation_id, []))

    def list_conversations(self, limit: int) -> list[dict]:
        if self.fail:
            raise QueryStoreError("fake store unavailable")
        items = [
            {"id": cid, "title": c["title"], "created_at": c["created_at"],
             "message_count": len(self.messages.get(cid, []))}
            for cid, c in self.conversations.items()
        ]
        return list(reversed(items))[:limit]

    def clear_all(self) -> None:
        if self.fail:
            raise QueryStoreError("fake store unavailable")
        self.conversations.clear()
        self.messages.clear()

    def ping(self) -> bool:
        return not self.fail


class BackendTestCase(unittest.TestCase):
    def setUp(self):
        self.stub = StubBackend()
        self.store = FakeQueryStore()
        app.dependency_overrides[backend_dep] = lambda: self.stub
        app.dependency_overrides[ask_backend_dep] = lambda: self.stub  # same stub, separate seam
        app.dependency_overrides[retriever_dep] = lambda: None  # no RAG in tests
        app.dependency_overrides[query_store_dep] = lambda: self.store
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()


class HealthAndIngest(BackendTestCase):
    def test_health(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_taxonomy_includes_topic_browser_detail(self):
        r = self.client.get("/taxonomy")
        self.assertEqual(r.status_code, 200, r.text)
        causes = r.json()["causes"]
        self.assertTrue(causes)
        rf24001 = next(c for c in causes if c["id"] == "RF-24-001")
        self.assertTrue(rf24001["description"])
        self.assertTrue(rf24001["discriminators"])
        self.assertTrue(rf24001["remediation_intent"])
        self.assertIsInstance(rf24001["confusable_with"], list)

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

    def test_live_ingest_default_source_is_probe(self):
        self._use_reference_backend()
        r = self.client.post("/live/ingest", json={"format": "esp32", "document": self._esp32_doc()})
        self.assertEqual(r.json()["source"], "probe")

    def test_live_demo_replays_bundled_captures_as_demo_source(self):
        self._use_reference_backend()
        r = self.client.post("/live/demo")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # hardware/sample_capture.jsonl: healthy / RF-24-001 / RF-24-002 /
        # RF-24-003 / RF-24-006 / RF-24-001+RF-24-006 (ambiguous, higher
        # severity wins as the primary cause_id).
        self.assertEqual(
            [s["diagnosis"]["cause_id"] for s in body["samples"]],
            [None, "RF-24-001", "RF-24-002", "RF-24-003", "RF-24-006", "RF-24-001"],
        )
        self.assertTrue(all(s["source"] == "demo" for s in body["samples"]))
        ambiguous = body["samples"][-1]["diagnosis"]
        self.assertIn("RF-24-006", [a["cause_id"] for a in ambiguous["ranked_alternatives"]])

        feed = self.client.get("/live/feed", params={"since": 0})
        self.assertEqual(len(feed.json()["samples"]), 6)

    def test_live_demo_is_additive_to_existing_probe_samples(self):
        self._use_reference_backend()
        self.client.post("/live/ingest", json={"format": "esp32", "document": self._esp32_doc()})
        r = self.client.post("/live/demo")
        self.assertEqual(r.status_code, 200, r.text)
        feed = self.client.get("/live/feed", params={"since": 0}).json()
        self.assertEqual(len(feed["samples"]), 7)
        self.assertEqual(feed["samples"][0]["source"], "probe")
        self.assertTrue(all(s["source"] == "demo" for s in feed["samples"][1:]))


class BackendSelection(unittest.TestCase):
    def test_unknown_backend_raises(self):
        from dataclasses import replace

        with self.assertRaises(BackendError):
            build_backend(replace(get_settings(), model_backend="nope"))

    def test_ask_backend_rejects_reference(self):
        # ReferenceBackend only ever emits diagnosis JSON, never prose -- this
        # is exactly the bug where the Ask tab returned raw {"cause_id": ...}
        # instead of an answer. build_ask_backend must refuse it outright.
        from dataclasses import replace

        from backend.inference import build_ask_backend

        with self.assertRaises(BackendError) as cm:
            build_ask_backend(replace(get_settings(), ask_backend="reference"))
        self.assertIn("not valid", str(cm.exception))

    def test_ask_backend_is_independent_of_diagnose_backend(self):
        # diagnose/explain can run the deterministic reference engine while
        # /ask runs a real (here, stub) prose-capable backend at the same time.
        from dataclasses import replace

        from backend.inference import build_ask_backend

        cfg = replace(get_settings(), model_backend="reference", ask_backend="stub")
        self.assertIsInstance(build_backend(cfg), ReferenceBackend)
        self.assertIsInstance(build_ask_backend(cfg), StubBackend)

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
    def test_ask_starts_a_new_conversation_and_stores_both_messages(self):
        self.stub._responses.append("Use the non-overlapping 1/6/11 channel plan.")
        r = self.client.post("/ask", json={"message": "why avoid channel overlap on 2.4GHz?"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["answer"], "Use the non-overlapping 1/6/11 channel plan.")
        self.assertTrue(body["stored"])
        self.assertIsNotNone(body["conversation_id"])
        self.assertIsNotNone(body["message_id"])
        self.assertIsNone(body["store_error"])

        stored = self.store.messages[body["conversation_id"]]
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]["role"], "user")
        self.assertEqual(stored[0]["content"], "why avoid channel overlap on 2.4GHz?")
        self.assertEqual(stored[1]["role"], "assistant")
        self.assertEqual(stored[1]["content"], body["answer"])

    def test_ask_saves_user_message_before_calling_the_slow_model(self):
        # The model call can take 20-80s on the real ollama backend. If the
        # user's message were only saved *after* generation (as it used to
        # be), refreshing the conversation list mid-reply would show a
        # newly-created conversation with zero messages -- looking broken,
        # not "still thinking". A fake backend records how many messages
        # exist in the store at the moment it's invoked, proving the user's
        # message landed first.
        store = self.store

        class RecordingBackend:
            def __init__(self):
                self.seen_message_count = None

            def generate(self, system, user, *, temperature):
                self.seen_message_count = sum(len(v) for v in store.messages.values())
                return "an answer"

        recorder = RecordingBackend()
        app.dependency_overrides[ask_backend_dep] = lambda: recorder
        r = self.client.post("/ask", json={"message": "q"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(recorder.seen_message_count, 1)  # user message only, not yet the reply

    def test_ask_followup_includes_prior_turn_as_context(self):
        self.stub._responses.extend(["First answer.", "Second answer."])
        first = self.client.post("/ask", json={"message": "what is CCI?"}).json()
        self.client.post(
            "/ask",
            json={"message": "and what about ACI?", "conversation_id": first["conversation_id"]},
        )
        second_call_prompt = self.stub.calls[1]["user"]
        self.assertIn("what is CCI?", second_call_prompt)
        self.assertIn("First answer.", second_call_prompt)
        self.assertIn("and what about ACI?", second_call_prompt)

    def test_ask_history_capped_to_recent_turns(self):
        from backend.routers.ask import _HISTORY_TURNS

        conv_id = None
        for i in range(_HISTORY_TURNS + 2):
            self.stub._responses.append(f"answer {i}")
            r = self.client.post("/ask", json={"message": f"question {i}", "conversation_id": conv_id})
            conv_id = r.json()["conversation_id"]
        last_prompt = self.stub.calls[-1]["user"]
        self.assertNotIn("question 0", last_prompt)  # aged out of the capped history
        self.assertIn(f"question {_HISTORY_TURNS + 1}", last_prompt)  # the new message itself
        # Nothing is lost from the store/sidebar, only from what's resent to the model.
        self.assertEqual(len(self.store.messages[conv_id]), 2 * (_HISTORY_TURNS + 2))

    def test_ask_runs_at_explanation_band_default_not_diagnosis_temperature(self):
        self.stub._responses.append("...")
        r = self.client.post("/ask", json={"message": "what is CCI?"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["temperature_used"], 0.8)
        self.assertEqual(self.stub.calls[0]["temperature"], 0.8)

    def test_ask_temperature_clamped_to_explanation_band(self):
        self.stub._responses.append("...")
        r = self.client.post("/ask", json={"message": "q", "temperature": 0.0})
        self.assertEqual(r.json()["temperature_used"], 0.7)

    def test_ask_degrades_gracefully_when_store_unavailable(self):
        self.store.fail = True
        self.stub._responses.append("An answer that could not be saved.")
        r = self.client.post("/ask", json={"message": "q"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["answer"], "An answer that could not be saved.")
        self.assertFalse(body["stored"])
        self.assertIsNone(body["message_id"])
        self.assertIn("unavailable", body["store_error"])

    def test_ask_rejects_empty_message(self):
        r = self.client.post("/ask", json={"message": ""})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.store.conversations, {})

    def test_ask_conversations_lists_most_recent_first(self):
        self.stub._responses.extend(["a1", "b1"])
        self.client.post("/ask", json={"message": "first conversation"})
        self.client.post("/ask", json={"message": "second conversation"})

        r = self.client.get("/ask/conversations")
        self.assertEqual(r.status_code, 200, r.text)
        items = r.json()["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "second conversation")  # most recent first
        self.assertEqual(items[1]["title"], "first conversation")
        self.assertEqual(items[0]["message_count"], 2)  # user + assistant
        self.assertIsNone(r.json()["store_error"])

    def test_ask_conversations_respects_limit(self):
        self.stub._responses.extend(["a", "b", "c"])
        for q in ("q1", "q2", "q3"):
            self.client.post("/ask", json={"message": q})
        r = self.client.get("/ask/conversations", params={"limit": 2})
        self.assertEqual(len(r.json()["items"]), 2)

    def test_ask_conversations_degrades_gracefully_when_store_unavailable(self):
        self.store.fail = True
        r = self.client.get("/ask/conversations")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["items"], [])
        self.assertIn("unavailable", body["store_error"])

    def test_ask_conversations_empty_when_nothing_saved(self):
        r = self.client.get("/ask/conversations")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"items": [], "store_error": None})

    def test_clear_conversations_deletes_everything(self):
        self.stub._responses.extend(["a1", "b1"])
        self.client.post("/ask", json={"message": "first conversation"})
        self.client.post("/ask", json={"message": "second conversation"})

        r = self.client.delete("/ask/conversations")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"cleared": True})

        self.assertEqual(self.client.get("/ask/conversations").json()["items"], [])
        self.assertEqual(self.store.conversations, {})
        self.assertEqual(self.store.messages, {})

    def test_clear_conversations_is_503_when_store_unavailable(self):
        self.store.fail = True
        r = self.client.delete("/ask/conversations")
        self.assertEqual(r.status_code, 503)

    def test_get_conversation_returns_full_thread(self):
        self.stub._responses.extend(["First answer.", "Second answer."])
        first = self.client.post("/ask", json={"message": "what is CCI?"}).json()
        self.client.post(
            "/ask",
            json={"message": "and ACI?", "conversation_id": first["conversation_id"]},
        )
        r = self.client.get(f"/ask/conversations/{first['conversation_id']}")
        self.assertEqual(r.status_code, 200, r.text)
        messages = r.json()["messages"]
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user", "assistant"])
        self.assertEqual(messages[0]["content"], "what is CCI?")
        self.assertEqual(messages[-1]["content"], "Second answer.")

    def test_get_conversation_degrades_with_503_when_store_unavailable(self):
        self.store.fail = True
        r = self.client.get("/ask/conversations/1")
        self.assertEqual(r.status_code, 503)


class AskStream(BackendTestCase):
    def test_ask_stream_emits_chunks_then_done_with_full_answer(self):
        self.stub._responses.append("Use the 1/6/11 channel plan.")
        r = self.client.post("/ask/stream", json={"message": "why avoid overlap?"})
        self.assertEqual(r.status_code, 200, r.text)

        events = _parse_sse(r.text)
        self.assertGreaterEqual(len(events), 2)  # at least one chunk + done
        self.assertTrue(all(e == "chunk" for e, _ in events[:-1]))
        self.assertEqual(events[-1][0], "done")

        chunk_text = "".join(d["text"] for _, d in events[:-1])
        self.assertEqual(chunk_text.strip(), "Use the 1/6/11 channel plan.")

        done = events[-1][1]
        self.assertEqual(done["answer"], "Use the 1/6/11 channel plan.")
        self.assertTrue(done["stored"])
        self.assertIsNotNone(done["conversation_id"])
        self.assertIsNotNone(done["message_id"])

        stored = self.store.messages[done["conversation_id"]]
        self.assertEqual(stored[0]["role"], "user")
        self.assertEqual(stored[1]["role"], "assistant")
        self.assertEqual(stored[1]["content"], "Use the 1/6/11 channel plan.")

    def test_ask_stream_saves_user_message_before_generation_like_ask_does(self):
        r = self.client.post("/ask/stream", json={"message": "why avoid overlap?"})
        events = _parse_sse(r.text)
        conv_id = events[-1][1]["conversation_id"]
        self.assertEqual(len(self.store.messages[conv_id]), 2)  # user + assistant, both saved

    def test_ask_stream_followup_includes_prior_turn_as_context(self):
        self.stub._responses.extend(["First answer.", "Second answer."])
        first_events = _parse_sse(
            self.client.post("/ask/stream", json={"message": "what is CCI?"}).text
        )
        conv_id = first_events[-1][1]["conversation_id"]
        self.client.post(
            "/ask/stream", json={"message": "and what about ACI?", "conversation_id": conv_id}
        )
        second_call_prompt = self.stub.calls[1]["user"]
        self.assertIn("what is CCI?", second_call_prompt)
        self.assertIn("First answer.", second_call_prompt)
        self.assertIn("and what about ACI?", second_call_prompt)

    def test_ask_stream_error_event_on_backend_failure(self):
        class FailingBackend:
            def stream(self, system, user, *, temperature):
                raise BackendError("ollama down")

        app.dependency_overrides[ask_backend_dep] = lambda: FailingBackend()
        r = self.client.post("/ask/stream", json={"message": "q"})
        self.assertEqual(r.status_code, 200, r.text)  # the SSE response itself always starts 200
        events = _parse_sse(r.text)
        self.assertEqual(events[-1], ("error", {"message": "ollama down"}))
        # Nothing gets saved as the assistant's reply when the backend failed.
        conv_id = next(iter(self.store.conversations))
        self.assertEqual(len(self.store.messages[conv_id]), 1)  # user message only

    def test_ask_stream_degrades_gracefully_when_store_unavailable(self):
        self.store.fail = True
        self.stub._responses.append("An answer that could not be saved.")
        r = self.client.post("/ask/stream", json={"message": "q"})
        events = _parse_sse(r.text)
        done = events[-1][1]
        self.assertEqual(done["answer"], "An answer that could not be saved.")
        self.assertFalse(done["stored"])
        self.assertIsNone(done["message_id"])
        self.assertIn("unavailable", done["store_error"])

    def test_ask_stream_runs_at_explanation_band_temperature(self):
        self.stub._responses.append("...")
        r = self.client.post("/ask/stream", json={"message": "q"})
        done = _parse_sse(r.text)[-1][1]
        self.assertEqual(done["temperature_used"], 0.8)
        self.assertEqual(self.stub.calls[0]["temperature"], 0.8)


class OllamaStreaming(unittest.TestCase):
    """Unit tests for OllamaBackend.stream()'s NDJSON parsing -- no real Ollama needed."""

    def _fake_response(self, lines: list[bytes]):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def __iter__(self):
                return iter(lines)

        return FakeResponse()

    def test_stream_yields_content_deltas_and_stops_at_done(self):
        lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}).encode(),
            json.dumps({"message": {"content": " world"}, "done": False}).encode(),
            json.dumps({"message": {"content": ""}, "done": True}).encode(),
        ]
        backend = OllamaBackend("qwen2.5:7b-instruct", "http://localhost:11434", 5.0)
        with mock.patch(
            "backend.inference.urllib.request.urlopen",
            return_value=self._fake_response(lines),
        ):
            chunks = list(backend.stream("sys", "user", temperature=0.8))
        self.assertEqual(chunks, ["Hello", " world"])

    def test_stream_raises_backend_error_on_connection_failure(self):
        backend = OllamaBackend("qwen2.5:7b-instruct", "http://localhost:11434", 5.0)
        with mock.patch(
            "backend.inference.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(BackendError):
                list(backend.stream("sys", "user", temperature=0.8))


if __name__ == "__main__":
    unittest.main()
