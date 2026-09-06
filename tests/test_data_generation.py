"""Tests for the phase-4 synthetic generator (data/scenarios.py, data/generate.py).

Everything runs with the offline templated teacher — no Ollama required.
"""
from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from adapters.normalize import validate_canonical
from data import generate, predicates, scenarios
from data.taxonomy_loader import all_cause_ids, cause as get_cause
from data.teacher import Teacher, _has_bare_regulatory_number


class ScenarioBuilderTests(unittest.TestCase):
    def test_single_is_schema_valid_and_eligible_for_every_cause(self):
        for cid in all_cause_ids():
            spec = scenarios.build_single(cid, random.Random(hash(cid) & 0xFFFF))
            generate._finalise_snapshot(spec["snapshot"])
            validate_canonical(spec["snapshot"])  # raises on failure
            self.assertTrue(
                predicates.required_evidence_met(spec["snapshot"], get_cause(cid)),
                f"{cid}: built positive snapshot does not satisfy its own required_evidence",
            )

    def test_single_evidence_paths_all_resolve(self):
        for cid in all_cause_ids():
            spec = scenarios.build_single(cid, random.Random(3))
            generate._finalise_snapshot(spec["snapshot"])
            for path in spec["held_paths"]:
                hits = predicates.select(spec["snapshot"], predicates.parse_path(path))
                self.assertTrue([v for v in hits if v is not None], f"{cid}: {path} unresolved")

    def test_abstention_breaks_eligibility_and_stays_schema_valid(self):
        for cid in all_cause_ids():
            spec = scenarios.build_abstention(cid, random.Random(hash(cid) & 0xFFFF))
            generate._finalise_snapshot(spec["snapshot"])
            validate_canonical(spec["snapshot"])
            self.assertFalse(
                predicates.required_evidence_met(spec["snapshot"], get_cause(cid)),
                f"{cid}: abstention snapshot still satisfies the cause",
            )
            self.assertTrue(spec["data_gap_paths"], f"{cid}: abstention produced no data gaps")

    def test_ambiguous_when_built_has_two_eligible_causes(self):
        built = 0
        for cid in all_cause_ids():
            spec = scenarios.build_ambiguous(cid, random.Random(11))
            if spec is None:
                continue
            built += 1
            snap = spec["snapshot"]
            generate._finalise_snapshot(snap)
            self.assertTrue(predicates.required_evidence_met(snap, get_cause(spec["primary"])))
            for alt in spec["alternatives"]:
                self.assertTrue(predicates.required_evidence_met(snap, get_cause(alt)))
        self.assertGreater(built, 5, "almost no ambiguous scenarios were constructible")


class EndToEndTests(unittest.TestCase):
    def test_generate_offline_produces_valid_split(self):
        teacher = Teacher(enabled=False)
        with tempfile.TemporaryDirectory() as d:
            report = generate.generate(
                count=260, out_dir=Path(d), seed=1, eval_frac=0.15,
                teacher=teacher, max_attempts=6,
            )
            self.assertGreater(report["written"], 150)
            self.assertEqual(len(report["by_cause"]), len(all_cause_ids()) + 1)  # +ABSTAIN
            train = _read(Path(d) / "train.jsonl")
            ev = _read(Path(d) / "eval.jsonl")
            self.assertTrue(train and ev)
            # every written record must re-pass the full validation gate
            for rec in train + ev:
                snap = json.loads(rec["messages"][1]["content"])
                label = json.loads(rec["messages"][2]["content"])
                spec = {
                    "kind": rec["meta"]["kind"],
                    "primary": rec["meta"]["cause_id"],
                    "nearest": rec["meta"].get("nearest"),
                    "alternatives": rec["meta"]["alternatives"],
                    "band": rec["meta"]["band"],
                    "held_paths": [e["field_path"] for e in label["evidence"]],
                    "data_gap_paths": label["data_gaps"],
                }
                generate._validate(spec, snap, label)  # raises ExampleRejected on any regression

    def test_eval_split_contains_every_kind(self):
        with tempfile.TemporaryDirectory() as d:
            generate.generate(count=400, out_dir=Path(d), seed=2, eval_frac=0.15,
                              teacher=Teacher(enabled=False), max_attempts=6)
            kinds = {r["meta"]["kind"] for r in _read(Path(d) / "eval.jsonl")}
            self.assertEqual(kinds, {"single", "ambiguous", "abstention"})


class NarrateTests(unittest.TestCase):
    CAUSE = get_cause("RF-24-001")
    EVIDENCE = [
        {"field_path": "rf_metrics.co_channel_neighbors", "observed_value": 5},
        {"field_path": "rf_metrics.channel_utilization_pct", "observed_value": 82.0},
    ]

    def test_offline_returns_template_rationales_and_verbatim_intent(self):
        rationales, remediation = Teacher(enabled=False).narrate(self.CAUSE, self.EVIDENCE, "x")
        self.assertEqual(len(rationales), 2)
        self.assertEqual(remediation, self.CAUSE["remediation_intent"])

    def test_batched_teacher_reply_is_parsed_and_guarded(self):
        t = Teacher(enabled=True)
        t._chat = lambda system, user: json.dumps({
            "rationales": [
                "Many co-channel BSSs force airtime to be shared on 5 GHz.",
                "Utilisation this high means the channel is saturated by EIRP of 200 mW.",  # bad: bare limit
            ],
        })
        rationales, remediation = t.narrate(self.CAUSE, self.EVIDENCE, "x")
        self.assertIn("co-channel", rationales[0])
        self.assertNotIn("200 mW", rationales[1])  # fell back to template
        self.assertEqual(remediation, self.CAUSE["remediation_intent"])  # never model-reworded

    def test_misaligned_rationale_count_falls_back_entirely(self):
        t = Teacher(enabled=True)
        t._chat = lambda system, user: '{"rationales": ["only one"], "remediation": []}'
        rationales, _ = t.narrate(self.CAUSE, self.EVIDENCE, "x")
        self.assertEqual(len(rationales), 2)
        self.assertTrue(all("gating conditions" in r for r in rationales))


class HallucinationGuardTests(unittest.TestCase):
    def test_band_names_are_not_flagged(self):
        self.assertFalse(_has_bare_regulatory_number("Re-plan the 2.4 GHz channel assignment onto 1/6/11."))
        self.assertFalse(_has_bare_regulatory_number("Migrate clients to 5 GHz or 6 GHz."))

    def test_bare_limit_is_flagged(self):
        self.assertTrue(_has_bare_regulatory_number("The EIRP limit here is 36 dBm."))

    def test_cited_limit_is_allowed(self):
        self.assertFalse(_has_bare_regulatory_number("Per the regulatory corpus, the limit is 30 dBm."))


def _read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


if __name__ == "__main__":
    unittest.main()
