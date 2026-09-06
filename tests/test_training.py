"""Tests for the training scaffold.

Only the config loader, the jsonl reader and the pure scoring functions are
exercised — nothing here imports torch / transformers / peft.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from training import evaluate, train

_TRAINING = Path(__file__).resolve().parent.parent / "training"
_CFG = _TRAINING / "qlora_config.yaml"


class ConfigTests(unittest.TestCase):
    def test_config_loads_with_required_keys(self):
        cfg = train.load_config(_CFG)
        self.assertEqual(cfg["base_model"], "Qwen/Qwen2.5-1.5B-Instruct")
        for key in ("data", "lora", "training", "quantization"):
            self.assertIn(key, cfg)
        self.assertIn("q_proj", cfg["lora"]["target_modules"])

    def test_all_shipped_configs_load_and_keep_effective_batch_32(self):
        for path in sorted(_TRAINING.glob("qlora_config*.yaml")):
            cfg = train.load_config(path)
            t = cfg["training"]
            eff = t["per_device_train_batch_size"] * t["gradient_accumulation_steps"]
            self.assertEqual(eff, 32, f"{path.name}: effective batch {eff} != 32")
            self.assertLessEqual(cfg["data"]["max_seq_length"], 4096)

    def test_8gb_preset_is_lower_footprint_than_default(self):
        default = train.load_config(_CFG)
        low = train.load_config(_TRAINING / "qlora_config.8gb.yaml")
        self.assertLess(low["data"]["max_seq_length"], default["data"]["max_seq_length"] + 1)
        self.assertLessEqual(
            low["training"]["per_device_train_batch_size"],
            default["training"]["per_device_train_batch_size"],
        )
        self.assertLessEqual(low["lora"]["r"], default["lora"]["r"])

    def test_read_chat_jsonl_rejects_non_assistant_tail(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"messages": [{"role": "user", "content": "hi"}]}) + "\n")
            path = Path(f.name)
        with self.assertRaises(SystemExit):
            train.read_chat_jsonl(path)


class ExtractJsonTests(unittest.TestCase):
    def test_pulls_object_from_surrounding_prose(self):
        raw = 'Here is the diagnosis:\n{"cause_id": "RF-24-001", "confidence": "high"}\nThanks.'
        self.assertEqual(evaluate.extract_json(raw)["cause_id"], "RF-24-001")

    def test_nested_braces(self):
        raw = '{"a": {"b": 1}, "c": 2}'
        self.assertEqual(evaluate.extract_json(raw), {"a": {"b": 1}, "c": 2})

    def test_unparseable_returns_none(self):
        self.assertIsNone(evaluate.extract_json("no json here"))


class ScoreRecordTests(unittest.TestCase):
    SNAP = {"rf_metrics": {"co_channel_neighbors": 5, "channel_utilization_pct": 80.0}}

    def test_correct_single(self):
        meta = {"kind": "single", "cause_id": "RF-24-001"}
        pred = {
            "cause_id": "RF-24-001",
            "evidence": [{"field_path": "rf_metrics.co_channel_neighbors", "why_it_matters": "x"}],
            "remediation": ["Re-plan the 2.4 GHz channel plan."],
        }
        s = evaluate.score_record(meta, self.SNAP, pred)
        self.assertTrue(s["top1"])
        self.assertTrue(s["grounded"])
        self.assertFalse(s["hallucinated"])

    def test_wrong_single(self):
        meta = {"kind": "single", "cause_id": "RF-24-001"}
        s = evaluate.score_record(meta, self.SNAP, {"cause_id": "RF-5-004", "evidence": []})
        self.assertFalse(s["top1"])
        self.assertFalse(s["grounded"])  # asserted a cause, cited nothing

    def test_top3_ambiguous_hits_via_alternatives(self):
        meta = {"kind": "ambiguous", "cause_id": "RF-24-002"}
        pred = {"cause_id": "RF-24-001",
                "ranked_alternatives": [{"cause_id": "RF-24-002", "confidence": "low"}],
                "evidence": [{"field_path": "rf_metrics.channel_utilization_pct"}]}
        s = evaluate.score_record(meta, self.SNAP, pred)
        self.assertTrue(s["top3_ambiguous"])

    def test_abstention_success_and_failure(self):
        meta = {"kind": "abstention", "cause_id": None}
        ok = evaluate.score_record(meta, self.SNAP, {"cause_id": None, "evidence": []})
        bad = evaluate.score_record(meta, self.SNAP, {"cause_id": "RF-24-001", "evidence": []})
        self.assertTrue(ok["abstained_when_required"])
        self.assertFalse(bad["abstained_when_required"])

    def test_ungrounded_evidence_path(self):
        meta = {"kind": "single", "cause_id": "RF-24-001"}
        pred = {"cause_id": "RF-24-001",
                "evidence": [{"field_path": "rf_metrics.noise_floor_dbm"}]}  # absent in SNAP
        self.assertFalse(evaluate.score_record(meta, self.SNAP, pred)["grounded"])

    def test_hallucination_flagged(self):
        meta = {"kind": "single", "cause_id": "RF-6-002"}
        pred = {"cause_id": "RF-6-002", "evidence": [],
                "remediation": ["Raise EIRP to 30 dBm."]}
        self.assertTrue(evaluate.score_record(meta, self.SNAP, pred)["hallucinated"])

    def test_unparseable_prediction(self):
        meta = {"kind": "single", "cause_id": "RF-24-001"}
        s = evaluate.score_record(meta, self.SNAP, None)
        self.assertFalse(s["parsed"])
        self.assertFalse(s["top1"])


class AggregateTests(unittest.TestCase):
    def test_none_values_are_excluded_from_rates(self):
        scores = [
            {"parsed": True, "top1": True, "top3_ambiguous": None, "grounded": True,
             "abstained_when_required": None, "hallucinated": False},
            {"parsed": True, "top1": False, "top3_ambiguous": None, "grounded": False,
             "abstained_when_required": None, "hallucinated": False},
        ]
        agg = evaluate.aggregate(scores)
        self.assertEqual(agg["top1_accuracy"], 0.5)
        self.assertIsNone(agg["top3_ambiguous"])


class EchoResponderEndToEnd(unittest.TestCase):
    def test_echo_scores_gold_as_perfect(self):
        # Regenerate a tiny eval set and confirm the harness gives the gold
        # labels a clean sheet — guards against a scoring-logic regression.
        import random
        from data import generate
        from data.teacher import Teacher

        with tempfile.TemporaryDirectory() as d:
            generate.generate(count=180, out_dir=Path(d), seed=9, eval_frac=0.2,
                              teacher=Teacher(enabled=False), max_attempts=6)
            report = evaluate.run(Path(d) / "eval.jsonl", evaluate.EchoResponder())
        self.assertEqual(report["parse_rate"], 1.0)
        self.assertEqual(report["evidence_grounding"], 1.0)
        self.assertEqual(report["abstention_rate"], 1.0)
        self.assertEqual(report["hallucination_rate"], 0.0)
        if report["top1_accuracy"] is not None:
            self.assertEqual(report["top1_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
