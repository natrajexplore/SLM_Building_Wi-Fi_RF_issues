# RF Root Cause SLM — Project Context

A small language model that diagnoses wireless RF problems across 2.4 GHz, 5 GHz
and 6 GHz and returns a root cause with a supporting evidence chain. Vendor
neutral by design: the model never sees vendor-native output.

Owner: Nataraj Angappan — network security / wireless architecture.

---

## Hard design decisions (already settled — do not relitigate)

**1. Vendor-neutral canonical schema.**
Every data source is normalized into `schema/canonical_rf.schema.json` by an
adapter before it reaches the model. Adding a vendor means writing an adapter,
never retraining. No vendor field names, CLI syntax or product names enter the
training data or the model's output.

**2. GPT-2 is not the teacher.**
Distillation here means: a frontier teacher model generates a synthetic RCA
dataset offline; a modern small base model is fine-tuned on it.

- Teacher: frontier model, offline dataset generation only. Not in the serving path.
- Student base: `Qwen2.5-1.5B-Instruct` (primary) or `Llama-3.2-1B-Instruct` (fallback).
- Method: QLoRA, 4-bit, single GPU.
- GPT-2 is retained only as a documented baseline for comparison, if at all.

**3. Temperature is split by stage.**

| Stage | Endpoint | Temp | Reason |
|---|---|---|---|
| Diagnosis | `/diagnose` | 0.1–0.2 | Invented causes are the primary failure mode |
| Explanation | `/explain` | 0.7–0.9 | Readability, alternative framings |

The UI exposes a temperature control on the explanation path only. The diagnosis
path stays low regardless of UI state. Never wire a single global temperature.

**4. RAG stays in the loop after fine-tuning.**
The SLM learns the reasoning pattern. The vector store supplies the facts —
regulatory tables, channel plans, power limits, IEEE clauses. A 1.5B model must
not state a numeric limit from parametric memory.

---

## Current state vs. target layout

We are midway through Build order phase 3 (adapters) below. What actually
exists: `schema/canonical_rf.schema.json`, `taxonomy/rf_root_causes.yaml`
(v0.2.0 — see the predicate-grammar note under Conventions), and
`adapters/base.py` + `adapters/normalize.py` (the Adapter ABC and its shared
validation/missing-fields/pseudonymisation logic, with smoke tests in
`tests/test_adapters_base.py`). **No concrete vendor adapter exists yet** —
not `generic_csv.py`, not `cisco_c9800.py`, nothing under `data/`,
`training/`, `rag/`, `backend/`, or `frontend/`. Don't assume any of those
directories or files exist; check before referencing one.

## Commands

- Install deps: `pip install -r requirements.txt` (currently just `jsonschema`).
- Run tests: `python -m unittest discover -s tests`. No pytest — it isn't
  installed and there's no dependency on it; stick to stdlib `unittest` for
  anything added here unless that changes deliberately.
- No build or lint step exists yet (no `train.py`, no backend/frontend to
  build). Update this section as those phases land instead of leaving it stale.

The tree below is the **target** layout; items not listed as existing above
are not built yet.

```
rf-slm/
├── CLAUDE.md
├── requirements.txt
├── schema/
│   └── canonical_rf.schema.json     # the contract — start here
├── taxonomy/
│   └── rf_root_causes.yaml          # labelled cause set, output vocabulary
├── adapters/
│   ├── base.py                      # Adapter ABC -> canonical dict            [done]
│   ├── normalize.py                 # validation + missing_fields + pseudonymisation [done]
│   ├── generic_csv.py               # BUILD NEXT — universal fallback
│   ├── generic_json.py
│   ├── cisco_c9800.py               # validation source (pyATS available)
│   ├── aruba_central.py
│   └── mist.py
├── data/
│   ├── generate.py                  # teacher-driven synthetic generation
│   ├── scenarios/                   # taxonomy x schema permutations
│   ├── train.jsonl
│   └── eval.jsonl
├── training/
│   ├── qlora_config.yaml
│   ├── train.py
│   └── evaluate.py                  # cause_id accuracy, evidence grounding
├── rag/
│   ├── ingest.py
│   ├── corpus/                      # standards + regulatory only
│   └── retriever.py                 # FAISS
├── backend/
│   ├── main.py                      # FastAPI
│   ├── routers/{diagnose,explain,ingest,retrieve}.py
│   ├── inference.py
│   └── models.py                    # Pydantic mirrors of canonical schema
├── frontend/                        # React + Vite + Tailwind
│   └── src/
└── tests/
    └── test_adapters_base.py        # [done]
```

---

## Build order

Do not skip ahead. Each phase gates the next.

1. **Schema freeze.** Review `canonical_rf.schema.json` field by field against
   real WLC output. Adding fields later invalidates generated training data.
2. **Taxonomy review.** `rf_root_causes.yaml` is the output vocabulary. Cause IDs
   are stable forever once data is generated against them.
3. **Adapters.** `base.py` + `normalize.py` done. `generic_csv.py` next, then
   `cisco_c9800.py` for validation against real captures.
4. **Synthetic dataset.** Taxonomy × schema permutations via the teacher.
   Target 3–5k examples, deliberately including ambiguous and multi-cause cases.
5. **Fine-tune.** QLoRA on the student base.
6. **RAG corpus.** Standards ingest, FAISS index.
7. **FastAPI backend.**
8. **React frontend.**
9. **Validate** against real C9800 lab captures.

---

## Conventions

- Pydantic models in `backend/models.py` are generated from the JSON schema, not
  hand-written twice. Schema is the single source of truth.
- `source.*` is provenance only and is stripped before the model sees a snapshot.
- Client and BSSID identifiers are pseudonymised at the adapter boundary. Real
  MACs never enter training data or logs. Enforced in code, not just by
  convention: `Adapter.to_canonical` (`adapters/base.py`) routes every
  snapshot through `adapters/normalize.py`'s `pseudonymise_identifiers`, which
  also defensively scans the whole snapshot for anything MAC-shaped and raises
  rather than letting it through.
- `analysis_context.missing_fields` must be populated by every adapter, and
  `analysis_context.spectrum_capable` must always be set explicitly (an unset
  value is indistinguishable from `False` downstream). Both are enforced by
  `Adapter.to_canonical` itself — a concrete adapter subclass cannot forget
  either without `to_canonical` raising `ContractViolation`.
- Model output must validate against `taxonomy.output_contract`. A `cause_id` not
  present in the taxonomy is a hard failure, not a warning.
- **`required_evidence` in the taxonomy is predicate objects as of v0.2.0**,
  not bare field paths — `{path, predicate, value|threshold}` or an `any_of`
  group of them, all ANDed together. Read the grammar block at the top of
  `taxonomy/rf_root_causes.yaml` before writing anything (synthetic data
  generation, evaluation, an evidence-checker) that consumes
  `required_evidence` — treating an entry as a bare path will break. Predicates
  gate assertion *eligibility* only; they don't replace ranking, confidence,
  or `discriminators` reasoning. `supporting_evidence` is unchanged — still
  plain paths.

## Evaluation targets

- Top-1 `cause_id` accuracy on held-out synthetic set.
- Top-3 accuracy on deliberately ambiguous cases.
- Evidence grounding: every cited `field_path` must exist in the input snapshot.
- Abstention: on snapshots with required evidence removed, the model must report
  a data gap rather than assert a cause. This is a first-class metric, not an
  edge case.
- Hallucination check: no numeric regulatory claim without a retrieval citation.

## Known traps

- 2.4 GHz cell size is not 5/6 GHz cell size. Never share a power setting.
- Empty `non_wifi_interferers` means nothing when `spectrum_capable` is false.
- Healthy RF plus a real user complaint usually means `RF-XB-007`, not more tuning.
- Discontinuous 6 GHz coverage is worse than no 6 GHz.
