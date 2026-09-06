"""Phase 4 orchestrator: build, hard-validate and write the synthetic RCA set.

    python -m data.generate --count 3000 --out data/
    python -m data.generate --count 200 --no-teacher --seed 1      # fast, offline

Long runs checkpoint to data/_generated.jsonl after every accepted example;
re-running the same command resumes (same --count/--seed) rather than starting
over. train.jsonl / eval.jsonl / generation_report.json are written only when
every job is done.

Every example must clear ALL of these before it is written (a rejection is
counted and retried, not silently dropped):

  1. snapshot validates against schema/canonical_rf.schema.json
  2. label carries the output_contract required fields
  3. cause_id is a taxonomy id, or null for an abstention example
  4. every evidence[].field_path resolves in the snapshot   (grounding)
  5. abstention: cause_id is null AND the nearest cause's required_evidence
     genuinely does not hold
  6. non-abstention: the asserted cause's required_evidence holds, and so does
     every cause named in ranked_alternatives
  7. no bare numeric regulatory claim in any prose field   (teacher hallucination)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

from adapters.normalize import (
    SchemaValidationError,
    compute_missing_fields,
    validate_canonical,
)
from data import predicates, scenarios
from data.prompts import DIAGNOSIS_SYSTEM
from data.taxonomy_loader import all_cause_ids, cause as get_cause
from data.teacher import Teacher, TeacherUnavailable, _has_bare_regulatory_number

_KIND_MIX = [("single", 0.60), ("ambiguous", 0.25), ("abstention", 0.15)]
_CONF_BY_SEVERITY = {"high": "high", "medium": "medium", "low": "medium"}


class ExampleRejected(RuntimeError):
    """An assembled example failed a validation gate; caller should retry."""


# ---------------------------------------------------------------------------
# label assembly
# ---------------------------------------------------------------------------


def _finalise_snapshot(snapshot: dict) -> None:
    snapshot.pop("source", None)  # the model never sees provenance
    ac = snapshot.setdefault("analysis_context", {})
    ac["missing_fields"] = sorted(compute_missing_fields(snapshot))


def _label(spec: dict, snapshot: dict, teacher: Teacher) -> dict:
    band = spec["band"]
    if spec["kind"] == "abstention":
        gaps = spec["data_gap_paths"]
        return {
            "cause_id": None,
            "confidence": "low",
            "evidence": [],
            "affected_bands": [band],
            "remediation": [
                "Gather the evidence that would confirm or rule out the "
                "closest-matching cause (" + ", ".join(gaps) + "); it is absent "
                "or within normal range in this snapshot."
            ],
            "data_gaps": gaps,
        }

    cause = get_cause(spec["primary"])
    evidence = [
        {"field_path": p, "observed_value": scenarios._observed(snapshot, p)}
        for p in spec["held_paths"]
    ]
    summary = "; ".join(f"{e['field_path']}={e['observed_value']}" for e in evidence)
    rationales, remediation = teacher.narrate(cause, evidence, summary)
    for item, why in zip(evidence, rationales):
        item["why_it_matters"] = why
    label = {
        "cause_id": spec["primary"],
        "confidence": (
            "medium" if spec["kind"] == "ambiguous"
            else _CONF_BY_SEVERITY.get(cause.get("severity_default", "medium"), "medium")
        ),
        "evidence": evidence,
        "affected_bands": [band],
        "remediation": remediation,
        "data_gaps": spec["data_gap_paths"],
    }
    if spec["alternatives"]:
        label["ranked_alternatives"] = [
            {"cause_id": alt, "confidence": "low"} for alt in spec["alternatives"]
        ]
    return label


# ---------------------------------------------------------------------------
# validation gates
# ---------------------------------------------------------------------------

_REQUIRED_LABEL_FIELDS = (
    "cause_id", "confidence", "evidence", "affected_bands", "remediation", "data_gaps",
)
_VALID_IDS = set(all_cause_ids())


def _validate(spec: dict, snapshot: dict, label: dict) -> None:
    try:
        validate_canonical(snapshot)
    except SchemaValidationError as exc:
        raise ExampleRejected(f"schema: {exc}") from None

    for field in _REQUIRED_LABEL_FIELDS:
        if field not in label:
            raise ExampleRejected(f"label missing field {field!r}")

    cid = label["cause_id"]
    if cid is not None and cid not in _VALID_IDS:
        raise ExampleRejected(f"cause_id {cid!r} not in taxonomy")

    for item in label["evidence"]:
        path = item["field_path"]
        if not [v for v in predicates.select(snapshot, predicates.parse_path(path)) if v is not None]:
            raise ExampleRejected(f"ungrounded evidence path {path!r}")

    if spec["kind"] == "abstention":
        if cid is not None:
            raise ExampleRejected("abstention example asserted a cause")
        if predicates.required_evidence_met(snapshot, get_cause(spec["nearest"])):
            raise ExampleRejected("abstention snapshot still satisfies its nearest cause")
        if not label["data_gaps"]:
            raise ExampleRejected("abstention example has empty data_gaps")
    else:
        if not predicates.required_evidence_met(snapshot, get_cause(cid)):
            raise ExampleRejected(f"asserted cause {cid} not actually eligible")
        for alt in label.get("ranked_alternatives", []):
            if not predicates.required_evidence_met(snapshot, get_cause(alt["cause_id"])):
                raise ExampleRejected(f"alternative {alt['cause_id']} not eligible")

    for text in _prose_strings(label):
        if _has_bare_regulatory_number(text):
            raise ExampleRejected(f"bare regulatory number in prose: {text!r}")


def _prose_strings(label: dict):
    for item in label["evidence"]:
        yield item["why_it_matters"]
    yield from label["remediation"]


# ---------------------------------------------------------------------------
# one example
# ---------------------------------------------------------------------------


def build_example(cid: str, kind: str, teacher: Teacher, rng: random.Random) -> dict:
    if kind == "single":
        spec = scenarios.build_single(cid, rng)
    elif kind == "ambiguous":
        spec = scenarios.build_ambiguous(cid, rng)
        if spec is None:
            spec = scenarios.build_single(cid, rng)
    elif kind == "abstention":
        spec = scenarios.build_abstention(cid, rng)
    else:
        raise ValueError(kind)

    snapshot = spec["snapshot"]
    _finalise_snapshot(snapshot)
    label = _label(spec, snapshot, teacher)
    _validate(spec, snapshot, label)

    return {
        "messages": [
            {"role": "system", "content": DIAGNOSIS_SYSTEM},
            {"role": "user", "content": json.dumps(snapshot, indent=2, sort_keys=True)},
            {"role": "assistant", "content": json.dumps(label, indent=2)},
        ],
        "meta": {
            "kind": spec["kind"],
            "cause_id": label["cause_id"],
            "nearest": spec.get("nearest"),
            "alternatives": spec["alternatives"],
            "band": spec["band"],
        },
    }


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def _plan(count: int) -> list[tuple[str, str]]:
    ids = list(all_cause_ids())
    per_cause = max(1, count // len(ids))
    jobs: list[tuple[str, str]] = []
    for cid in ids:
        for kind, frac in _KIND_MIX:
            for _ in range(max(1, round(per_cause * frac))):
                jobs.append((cid, kind))
    return jobs


def generate(count: int, out_dir: Path, *, seed: int, eval_frac: float,
             teacher: Teacher, max_attempts: int, resume: bool = True) -> dict:
    rng = random.Random(seed)
    jobs = _plan(count)
    rng.shuffle(jobs)
    total = len(jobs)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Checkpointing: every accepted example is appended to _generated.jsonl as
    # it is produced, tagged with its job index. A killed run (or a laptop that
    # slept through the night) resumes from where it stopped as long as --count
    # and --seed match. The split + final files are written only at the end.
    ckpt = out_dir / "_generated.jsonl"
    ckpt_meta = out_dir / "_generated.meta.json"
    done: dict[int, dict] = {}
    rejects: Counter = Counter()

    if resume and ckpt.exists() and ckpt_meta.exists():
        prev = json.loads(ckpt_meta.read_text())
        if prev.get("count") == count and prev.get("seed") == seed:
            for line in ckpt.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    done[rec["_job_index"]] = rec
            print(f"resuming: {len(done)}/{total} already generated", file=sys.stderr, flush=True)
        else:
            print("checkpoint is for a different --count/--seed; starting fresh", file=sys.stderr)
            ckpt.unlink()
    elif ckpt.exists() and not resume:
        ckpt.unlink()

    ckpt_meta.write_text(json.dumps({"count": count, "seed": seed}))
    with open(ckpt, "a", encoding="utf-8") as ck:
        for i, (cid, kind) in enumerate(jobs):
            if i in done:
                continue
            for attempt in range(max_attempts):
                try:
                    rec = build_example(cid, kind, teacher, random.Random(seed + i * 97 + attempt))
                    rec["_job_index"] = i
                    ck.write(json.dumps(rec) + "\n")
                    ck.flush()
                    done[i] = rec
                    break
                except ExampleRejected as exc:
                    rejects[str(exc).split(":")[0]] += 1
            if (i + 1) % 50 == 0 or i + 1 == total:
                print(f"  [{i + 1}/{total}] kept {len(done)}", file=sys.stderr, flush=True)

    records = [dict(r) for r in done.values()]
    for r in records:
        r.pop("_job_index", None)

    # Stratified split: hold out `eval_frac` of the single-cause examples and a
    # deliberately heavier 2x of the ambiguous / abstention ones (those two are
    # their own first-class metrics — Top-3 and abstention rate — and need a
    # populated eval slice), without ever starving eval of single-cause records.
    by_kind: dict[str, list[dict]] = {}
    for rec in records:
        by_kind.setdefault(rec["meta"]["kind"], []).append(rec)
    eval_records: list[dict] = []
    train_records: list[dict] = []
    for kind, group in by_kind.items():
        rng.shuffle(group)
        frac = eval_frac * (2.0 if kind in ("ambiguous", "abstention") else 1.0)
        n = min(len(group) - 1, max(1, round(len(group) * frac)))
        eval_records += group[:n]
        train_records += group[n:]
    rng.shuffle(train_records)
    rng.shuffle(eval_records)

    _write_jsonl(out_dir / "train.jsonl", train_records)
    _write_jsonl(out_dir / "eval.jsonl", eval_records)

    report = {
        "requested": count,
        "planned_jobs": len(jobs),
        "written": len(records),
        "train": len(train_records),
        "eval": len(eval_records),
        "by_kind": dict(Counter(r["meta"]["kind"] for r in records)),
        "by_cause": dict(Counter(r["meta"]["cause_id"] or "ABSTAIN" for r in records)),
        "rejections": dict(rejects),
        "teacher": {"enabled": teacher.enabled, "model": teacher.model if teacher.enabled else None},
        "seed": seed,
    }
    (out_dir / "generation_report.json").write_text(json.dumps(report, indent=2))
    return report


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=3000, help="approx total examples")
    ap.add_argument("--out", type=Path, default=Path("data"), help="output directory")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--eval-frac", type=float, default=0.15)
    ap.add_argument("--max-attempts", type=int, default=6)
    ap.add_argument("--no-teacher", action="store_true", help="offline templated prose only")
    ap.add_argument("--teacher-model", default=None, help="Ollama model tag (overrides RF_SLM_TEACHER_MODEL)")
    ap.add_argument("--teacher-timeout", type=float, default=240.0,
                    help="per-call Ollama timeout (s); a 7B on CPU needs a generous one")
    ap.add_argument("--no-resume", action="store_true", help="ignore any existing checkpoint")
    args = ap.parse_args(argv)

    teacher = Teacher(enabled=not args.no_teacher, timeout=args.teacher_timeout)
    if args.teacher_model:
        teacher.model = args.teacher_model
    if teacher.enabled:
        print(f"teacher: {teacher.model} @ {teacher.host} (warming up — first call loads the model)",
              file=sys.stderr, flush=True)
        try:
            teacher.health_check()
        except TeacherUnavailable as exc:
            print(f"teacher unavailable: {exc}\n  run with --no-teacher to generate offline.", file=sys.stderr)
            return 2

    report = generate(
        args.count, args.out,
        seed=args.seed, eval_frac=args.eval_frac,
        teacher=teacher, max_attempts=args.max_attempts,
        resume=not args.no_resume,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
