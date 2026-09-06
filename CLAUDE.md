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

What actually exists:

- `schema/canonical_rf.schema.json`, `taxonomy/rf_root_causes.yaml` (v0.2.0 —
  see the predicate-grammar note under Conventions; `output_contract` now also
  carries `optional_fields` / `abstention` shapes).
- `adapters/base.py` + `adapters/normalize.py` — the Adapter ABC and its shared
  validation/missing-fields/pseudonymisation logic.
- `adapters/generic_csv.py` — `GenericCsvAdapter`: a `CsvMapping` (column →
  scalar canonical path, coercion inferred from the schema) turns one flat CSV
  row into one snapshot. Array fields out of scope by design.
- `adapters/generic_json.py` — `GenericJsonAdapter`: a `JsonMapping` (dotted
  source paths → canonical paths, plus per-element maps for the array fields)
  turns a nested vendor JSON doc into one snapshot.
- `adapters/_common.py` — schema-type introspection + value coercion shared by
  both generic adapters. Example mappings: `adapters/generic_*.example.map.yaml`.
- **No vendor-specific adapter yet** — not `cisco_c9800.py`.
- `data/` — phase-4 synthetic generator, complete and runnable
  (`predicates.py`, `snapshots.py`, `scenarios.py`, `prompts.py`,
  `teacher.py`, `generate.py`). Teacher is a local Ollama model with an
  offline templated fallback. Structure in every label is ground truth by
  construction; the teacher only writes prose. `data/train.jsonl` /
  `data/eval.jsonl` are **generated, git-ignored** — they do not exist until
  you run the generator.
- `training/` — phase-5 QLoRA scaffold (`qlora_config.yaml`, `train.py`,
  `evaluate.py`). `train.py --dry-run` and `evaluate.py`'s scoring functions
  run with no GPU / no heavy deps. An actual fine-tune run has **not** been
  done (no GPU arranged) and `training/out/` does not exist.
- `rag/` — phase-6 retrieval layer, complete and runnable. `documents.py`
  (corpus parse + chunk), `embedder.py` (Ollama `nomic-embed-text`, offline
  hash fallback), `ingest.py` (build `rag/index/`), `retriever.py` (query →
  ranked `Citation`s with band/domain/topic filters; FAISS if installed, numpy
  otherwise). `rag/corpus/` has 10 starter fact sheets, **all
  `review_status: unverified`** pending a curator check against primary
  sources; every citation is flagged `[UNVERIFIED]` until then. `rag/index/`
  is generated + git-ignored.
- `backend/` — phase-7 FastAPI app, complete and runnable. `models.py` is
  **generated** from the schema (do-not-edit header carries the regen command);
  `schemas.py` the API envelopes + RCA output type; `config.py` the per-stage
  temperatures; `inference.py` the `ModelBackend` seam — `OllamaBackend`
  (default), `AdapterBackend` (`RF_SLM_BACKEND=adapter` → base + phase-5 LoRA
  at `RF_SLM_ADAPTER_DIR`, default `training/out`; heavy deps guarded, degrades
  cleanly with a clear `/health` error if the adapter or `requirements-train.txt`
  is missing), `StubBackend` for tests — plus diagnose/explain orchestration + RAG enrichment;
  `rca.py` enforces `taxonomy.output_contract` on model output; `routers/`
  has `/diagnose` `/explain` `/ingest` `/retrieve`, `main.py` adds `/health`.
- `frontend/` — phase-8 React + Vite + Tailwind v4 SPA. Paste a canonical
  snapshot → `/diagnose` → evidence chain + citations → `/explain`. The **only**
  temperature control is the explanation slider, range fixed `[0.70, 0.90]`
  (`components/ExplanationPanel.tsx`); the diagnosis path has none. Dev server
  proxies the API to `:8000`. `npm run build` type-checks and bundles.
  `node_modules/` and `dist/` are git-ignored by the scaffold's `.gitignore`.

## Commands

- Core deps: `pip install -r requirements.txt` (`jsonschema`, `rfc3339-validator`
  for date-time enforcement, `PyYAML`, `numpy`, `faiss-cpu` for `rag/`).
  Training-only deps (torch/transformers/peft/bitsandbytes/trl) are in
  `requirements-train.txt`, installed separately on the GPU box.
- Run tests: `python -m unittest discover -s tests`. Stdlib `unittest` only — no
  pytest. The training tests import only pure helpers, never torch.
- Generate the synthetic dataset (phase 4):
  `python -m data.generate --count 3000 --out data/` (needs Ollama running with
  `RF_SLM_TEACHER_MODEL` pulled), or `--no-teacher` for a fast offline set.
- Validate the training config + data without a GPU: `python -m training.train --dry-run`.
  On an 8 GB card use `--config training/qlora_config.8gb.yaml` (batch 1, seq
  1536, LoRA r=8; ~6-7 GB peak). Turing cards (T4, RTX 20xx) also need
  `bf16: false` + `bnb_4bit_compute_dtype: float16` — noted in that file.
- Score a model against the eval targets:
  `python -m training.evaluate --responder ollama --model <tag>` (baseline), or
  `--responder adapter --model training/out` after a fine-tune.
- Build the RAG index (phase 6): `python -m rag.ingest` (needs Ollama with
  `nomic-embed-text` pulled; `--embedder hash` for an offline test index).
  Query it: `python -m rag.retriever "6 GHz LPI EIRP limit" --band 6GHz`.
- Run the backend (phase 7): `uvicorn backend.main:app --reload`.
  `RF_SLM_BACKEND`: `ollama` (default), `adapter` (phase-5 LoRA), `stub` (no
  model). Regenerate `backend/models.py` after a schema change with the command
  in that file's header (`pip install -r requirements-dev.txt`).
- No lint step. No frontend to build yet.

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
│   ├── _common.py                   # schema introspection + coercion (shared) [done]
│   ├── generic_csv.py               # flat CSV row, scalar fields              [done]
│   ├── generic_json.py              # nested JSON incl. array fields           [done]
│   ├── cisco_c9800.py               # BUILD NEXT — validation source (pyATS available)
│   ├── aruba_central.py
│   └── mist.py
├── data/
│   ├── predicates.py                # required_evidence grammar evaluator      [done]
│   ├── snapshots.py                 # baselines + path write + satisfy/violate [done]
│   ├── scenarios.py                 # single / ambiguous / abstention builders [done]
│   ├── prompts.py                   # diagnosis (low-temp) + explanation prompts [done]
│   ├── teacher.py                   # Ollama client + offline fallback         [done]
│   ├── generate.py                  # orchestrator + hard validation          [done]
│   ├── train.jsonl                  # generated, git-ignored
│   └── eval.jsonl                   # generated, git-ignored
├── training/
│   ├── qlora_config.yaml            # Qwen2.5-1.5B, QLoRA 4-bit (16 GB / T4)   [done]
│   ├── qlora_config.8gb.yaml        # low-VRAM preset for an 8 GB card         [done]
│   ├── train.py                     # SFT loop; --dry-run needs no GPU         [done]
│   └── evaluate.py                  # top-1/top-3, grounding, abstention, hallucination [done]
├── rag/
│   ├── documents.py                 # corpus file format + chunking           [done]
│   ├── embedder.py                  # Ollama nomic-embed-text + hash fallback  [done]
│   ├── ingest.py                    # corpus -> rag/index/                     [done]
│   ├── retriever.py                 # query -> ranked Citations (FAISS/numpy)  [done]
│   ├── corpus/                      # 10 starter fact sheets, all unverified   [done]
│   └── index/                       # generated, git-ignored
├── backend/
│   ├── main.py                      # FastAPI app + /health                    [done]
│   ├── config.py                    # per-stage temperatures, backend/index    [done]
│   ├── models.py                    # GENERATED Pydantic mirror of the schema  [done]
│   ├── schemas.py                   # API envelopes + RCAResult                 [done]
│   ├── inference.py                 # ModelBackend seam + orchestration        [done]
│   ├── rca.py                       # enforces taxonomy.output_contract        [done]
│   ├── deps.py                      # DI providers (overridden in tests)       [done]
│   └── routers/{diagnose,explain,ingest,retrieve}.py                           [done]
├── frontend/                        # React + Vite + Tailwind v4            [done]
│   ├── src/api.ts  src/types.ts  src/example.ts
│   ├── src/App.tsx
│   └── src/components/{SnapshotInput,DiagnosisView,EvidenceChain,
│                        CitationList,ExplanationPanel,ConfidenceBadge,Section}.tsx
└── tests/
    ├── test_adapters_base.py        # [done]
    ├── test_generic_csv.py          # [done]
    ├── test_generic_json.py         # [done]
    ├── test_predicates.py           # [done]
    ├── test_data_generation.py      # [done]
    ├── test_training.py             # [done]
    ├── test_rag.py                  # [done]
    └── test_backend.py              # [done]
```

---

## Build order

Do not skip ahead. Each phase gates the next.

1. **Schema freeze.** Review `canonical_rf.schema.json` field by field against
   real WLC output. Adding fields later invalidates generated training data.
2. **Taxonomy review.** `rf_root_causes.yaml` is the output vocabulary. Cause IDs
   are stable forever once data is generated against them.
3. **Adapters.** `base.py`, `normalize.py`, `generic_csv.py`, `generic_json.py`
   done. Next: `cisco_c9800.py` for validation against real captures. (Not on
   the critical path for phases 4–5: the synthetic generator builds canonical
   snapshots directly from the schema + taxonomy, so it does not wait on a
   vendor adapter. Adapters are still required before phase 9 lab validation.)
4. **Synthetic dataset.** Generator built (`data/`). First real run done:
   2990 examples (`qwen2.5:7b-instruct` teacher, seed 7), 0 rejections, 98 per
   cause + 442 abstention, train 2367 / eval 623. Full audit clean — every
   evidence path grounded, every asserted cause actually eligible, every
   abstention has cause_id null + non-empty data_gaps. Prose is good with
   occasional 7B fuzziness (acronym slips, weak edge-case reasoning); a
   stronger teacher would improve a v2 regen. Files are git-ignored; regenerate
   with the same command to reproduce.
5. **Fine-tune.** QLoRA scaffold built (`training/`). Blocked on: a GPU, and a
   phase-4 dataset from a real teacher. `--dry-run` is wired for CI.
6. **RAG corpus.** Layer built (`rag/`): corpus format, chunking, Ollama
   embeddings, ingest, retriever with band/domain/topic filters. 10 starter
   fact sheets covering what the taxonomy references. Still to do: curator
   verifies each fact sheet against its primary source and flips
   `review_status` to `verified`; expand coverage; wire the retriever into the
   diagnosis path so numeric regulatory claims carry a citation.
7. **FastAPI backend.** Built (`backend/`): `/diagnose` (temperature pinned
   low), `/explain` (0.7-0.9, clamped), `/ingest` (generic adapters), `/retrieve`
   (corpus), `/health`. `ModelBackend` is pluggable — `OllamaBackend` serves
   now, the QLoRA adapter slots in once phase 5 runs. `rca.py` enforces the
   output contract on every response. An untuned 7B via `OllamaBackend` fails
   that guard often (invents cause_ids) — the diagnosis prompt injects the
   closed cause vocabulary to reduce it, but reliable `/diagnose` serving needs
   phase 5 — set `RF_SLM_BACKEND=adapter` once `training/out/` exists. Still to
   do: auth / rate limiting for anything exposed.
8. **React frontend.** Built (`frontend/`): snapshot editor, diagnosis view
   (evidence chain, ranked alternatives, remediation, data gaps, citations with
   UNVERIFIED flags), explanation panel with the only temperature slider
   (`[0.70, 0.90]`). Still to do: an ingest UI for CSV/JSON + mapping; polish.
9. **Validate** against real C9800 lab captures. Needs `cisco_c9800.py`
   (phase 3 remainder) and a lab capture set.

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
