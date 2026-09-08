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
- `adapters/esp32.py` — `Esp32Adapter`: `hardware/esp32_rf_probe` JSON → snapshot.
  2.4 GHz only, `spectrum_capable` always false, BLE scan → `non_wifi_interferers`
  bluetooth hint, beacon IEs → regulatory_domain / min rate / CSA events. Firmware
  + JSON spec in `hardware/esp32_rf_probe/`. `POST /ingest {format:"esp32"}`.
- `adapters/cisco_c9800.py` — `CiscoC9800Adapter`: Cisco Catalyst 9800 WLC
  "capture bundle" (a documented normalized dict, not raw CLI/RESTCONF —
  see the module docstring for why: exact Genie/YANG field names vary by
  IOS-XE release and can't be hardcoded without a real capture to check
  against) → snapshot. `spectrum_capable` is read per-radio from
  `radio.clean_air_enabled`, not hardcoded like ESP32 — a C9800 AP may or
  may not carry a CleanAir ASIC, independent of band; `non_wifi_interferers`
  is refused outright if the bundle supplies spectrum entries for a radio
  not flagged clean-air-capable. This is the phase-9 validation-source
  adapter; still unvalidated against a real lab capture.
- `data/` — phase-4 synthetic generator, complete and runnable
  (`predicates.py`, `snapshots.py`, `scenarios.py`, `prompts.py`,
  `teacher.py`, `generate.py`). Teacher is a local Ollama model with an
  offline templated fallback. Structure in every label is ground truth by
  construction; the teacher only writes prose. `data/train.jsonl` /
  `data/eval.jsonl` are **generated, git-ignored** — they do not exist until
  you run the generator.
- `training/` — phase-5 QLoRA scaffold (`qlora_config.yaml`, `train.py`,
  `evaluate.py`). `train.py --dry-run` and `evaluate.py`'s scoring functions
  run with no GPU / no heavy deps. Two `trl`/`transformers` API-drift bugs
  in `train.py` were found and fixed via CPU testing (`max_seq_length` →
  `max_length`, `warmup_ratio` → `warmup_steps`). The real (4-bit, GPU)
  fine-tune has **not** been done — confirmed no CUDA GPU is reachable from
  this dev environment or its remote agent — and `training/out/` does not
  exist. See build-order step 5 for what CPU testing did and didn't prove.
- `rag/` — phase-6 retrieval layer, complete and runnable. `documents.py`
  (corpus parse + chunk), `embedder.py` (Ollama `nomic-embed-text`, offline
  hash fallback), `ingest.py` (build `rag/index/`), `retriever.py` (query →
  ranked `Citation`s with band/domain/topic filters; FAISS if installed, numpy
  otherwise). `rag/corpus/` has 10 starter fact sheets, **all
  `review_status: verified`** as of a 2026-09-08 curation pass against FCC
  §15.247/§15.407, ETSI EN 300 328/301 893, CEPT ECC decisions, and IEEE
  802.11 — three files (`5ghz-dfs.md`, `6ghz-power-classes.md`,
  `eirp-limits-24-5ghz.md`) had real numeric errors corrected (DFS weather-radar
  CAC wrongly attributed to FCC instead of ETSI; 6 GHz LPI EIRP-vs-width and
  VLP PSD figures; the 2.4 GHz point-to-point vs point-to-multipoint
  antenna-gain reduction rule). The pass relied on authoritative secondary
  sources rather than the paywalled IEEE 802.11 primary text itself, and one
  sub-claim in `6ghz-discovery.md` (FILS Discovery's exact beacon-cadence
  relationship) is only weakly corroborated — a truly primary-source pass
  through actual IEEE text remains a candidate for revisiting later.
  `rag/index/` is generated + git-ignored.
- `backend/` — phase-7 FastAPI app, complete and runnable. `models.py` is
  **generated** from the schema (do-not-edit header carries the regen command);
  `schemas.py` the API envelopes + RCA output type; `config.py` the per-stage
  temperatures; `inference.py` the `ModelBackend` seam — `OllamaBackend`
  (default), `AdapterBackend` (`RF_SLM_BACKEND=adapter` → base + phase-5 LoRA
  at `RF_SLM_ADAPTER_DIR`, default `training/out`; heavy deps guarded, degrades
  cleanly with a clear `/health` error if the adapter or `requirements-train.txt`
  is missing), `StubBackend` for tests — plus diagnose/explain orchestration + RAG enrichment;
  `rca.py` enforces `taxonomy.output_contract` on model output; `routers/`
  has `/diagnose` `/explain` `/ingest` `/retrieve` `/live` `/ask` (see below),
  `main.py` adds `/health`. `live_buffer.py` is an in-memory, single-process
  ring buffer (last 200 samples) feeding the 2.4 GHz hardware live-test tab —
  no persistence, resets on restart, deliberately not a durability guarantee.
  `routers/live.py`: `POST /live/ingest` accepts the same `{format:"esp32",
  document:{...}}` envelope as `/ingest` (so `hardware/esp32_rf_probe`'s
  existing `BACKEND_URL` POST needs no firmware change — just point it at
  `/live/ingest` instead of `/ingest`), runs it through `Esp32Adapter` +
  `run_diagnosis` at the same fixed diagnosis temperature as `/diagnose` (no
  caller-supplied temperature here either), and appends the result to the
  buffer tagged `source: "probe"`; `GET /live/feed?since=<id>` is what the
  frontend polls. `POST /live/demo` is the no-hardware path: it replays
  `hardware/sample_capture.jsonl` (6 real recorded probe captures, one
  comment-documented scenario per RF-24-* cause reachable from ESP32-only
  evidence, plus a deliberately ambiguous one) through the identical
  adapter → diagnose → buffer pipeline, tagged `source: "demo"` so demo and
  real-hardware samples never get confused in the same buffer.
  `live_buffer.clear()` (test-only) resets both the buffer and its id
  counter, not just the buffer — needed once more than one test hits the
  buffer in a single run.
  `routers/ask.py`: the Submit/Ask tab is a **multi-turn chat**, not
  isolated Q&A — `POST /ask` (`{message, conversation_id}`, the latter
  omitted to start a new conversation) fetches the conversation's prior
  messages, retrieves RAG context via `inference.run_ask` (new helper
  alongside `run_diagnosis`/`run_explanation`; grounds retrieval on the
  latest message only, includes prior turns as transcript context in the
  prompt — see `data/prompts.py`'s `ASK_SYSTEM`), answers at the
  explanation-band temperature (never a second exposed knob — see below),
  and persists both the user message and the reply through
  `query_store.py`'s `QueryStore` seam (mirrors the `ModelBackend` seam:
  `PostgresQueryStore` is real, a fake substitutes in tests via
  `app.dependency_overrides[deps.query_store_dep]`) as one `conversations`
  row + two `messages` rows.

  **Ask runs on its own model backend, deliberately separate from
  `model_backend`.** `ReferenceBackend` (this dev box's usual
  `RF_SLM_BACKEND=reference` for fast/deterministic `/diagnose`) only ever
  emits diagnosis JSON — it has no concept of prose. Handing it to `/ask`
  silently returned that same JSON as the "answer" to every question
  (caught when a real question got back `{"cause_id": null, ...}`). Fixed
  by giving `/ask` its own resolution: `ask_backend_dep` /
  `inference.build_ask_backend`, config via `RF_SLM_ASK_BACKEND` /
  `RF_SLM_ASK_MODEL` (default `ollama` + `qwen2.5:7b-instruct`);
  `build_ask_backend` raises outright on `ask_backend="reference"` so this
  class of bug can't recur silently. On this CPU-only dev machine that 7B
  model is the accurate choice but slow (~20-80s/turn — RAG context adds
  meaningfully to prompt-eval time); a small model
  (`RF_SLM_ASK_MODEL=qwen2.5:0.5b`) answers in ~10s but is frequently
  wrong on real questions — same accuracy-vs-latency ceiling documented
  throughout the fine-tuning section below. Real GPU hardware removes
  this tradeoff entirely.

  `GET /ask/conversations` lists saved conversations most-recent-first
  (`{id, title, created_at, message_count}`, title = the first message
  truncated); `GET /ask/conversations/{id}` returns a conversation's full
  message thread. A
  PostgreSQL outage degrades one `/ask` request (`stored: false`,
  `store_error` set) rather than failing it — this endpoint's job is the
  grounded answer, not the write. `POSTGRES_DSN` (default
  `postgresql://postgres@localhost:5432/rf_slm`) env var configures it;
  tables are created on first successful connection (no separate migration
  step); `psycopg` is lazily imported so the rest of `backend/` stays
  importable with no PostgreSQL installed at all. (Originally built
  against MongoDB — migrated to PostgreSQL; the `QueryStore` protocol was
  already storage-agnostic so only `backend/query_store.py` and its wiring
  changed. Originally flat one-row-per-Q&A too — migrated to
  conversations/messages for multi-turn chat; same reason, only the store
  and router changed shape.)
  `/taxonomy` (in `main.py`) now returns `description` / `discriminators`
  / `remediation_intent` / `confusable_with` per cause too, not just
  id/name/bands/severity — the frontend's Wireless Topics tab reads this,
  not a new endpoint.
- `frontend/` — phase-8 React + Vite + Tailwind v4 SPA. Three tabs (`App.tsx`
  `mode` state), in display order: **Submit / Ask** (default tab, first —
  `components/AskPanel.tsx`) — a chat UI: a conversation list on the left
  (`GET /ask/conversations`, with "+ New conversation" and a manual
  Refresh button), message bubbles + input on the right. Sending appends
  an optimistic user bubble, then `POST /ask` returns the assistant reply
  (and the new `conversation_id` if this was a fresh conversation);
  citations on an assistant message sit behind a native `<details>`
  disclosure so the thread doesn't get overwhelmed. **2.4GHz Live Test**
  (`components/LiveTestPanel.tsx`) — polls `GET /live/feed` every 3s, lists
  incoming probe samples (channel, timestamp, cause_id/confidence), and
  renders the selected one through `DiagnosisView` / `ExplanationPanel`.
  "follow latest" auto-selects the newest sample; clicking an older row
  pins the view and turns it off. A "Load demo samples" button calls
  `POST /live/demo` for anyone without an ESP32 board — no CLI needed — and
  demo-sourced rows carry a `DEMO` badge (from `LiveSample.source`) so they're
  never mistaken for real hardware readings; both can sit in the feed at
  once. A `<details>` "How this tab works" disclosure (same pattern as the
  Ask tab's citations) explains the with-hardware vs. without-hardware paths,
  the tab's actual behaviour (3s poll not push, in-memory buffer resets on
  backend restart, no live-tab temperature control), and enumerates what the
  6 bundled demo samples each demonstrate — kept in sync **by hand** with the
  comment block at the top of `hardware/sample_capture.jsonl` (`DEMO_CASES`
  constant in the component); if that file's scenarios change, update both.
  **Wireless Topics** (third —
  `components/WirelessTopicsPanel.tsx`) — a read-only browser over the
  taxonomy from `/taxonomy`, grouped by band with a band filter; picking a
  cause shows its description, discriminators, remediation intent, and
  `confusable_with` links to jump between related causes. This replaced
  the old "Snapshot" tab (paste raw canonical-snapshot JSON → `/diagnose`
  → evidence chain → `/explain`) — that flow is gone from the UI by
  request, but `/diagnose` itself is unchanged and still very much in use
  (read_probe.py, `/live/ingest`, and `DiagnosisView`/`ExplanationPanel`
  still render diagnoses from the Live Test tab). The **only** temperature
  control anywhere is the explanation slider, range fixed `[0.70, 0.90]`
  (`components/ExplanationPanel.tsx`); the diagnosis path has none, and
  neither does `/ask` — it always runs at the explanation default
  server-side, with no second knob in the UI. Dev server proxies
  `/diagnose` `/explain` `/ingest` `/live` `/retrieve` `/ask` `/taxonomy`
  `/health` to `:8000` (`vite.config.ts`). `npm run build` type-checks and
  bundles. `node_modules/` and `dist/` are git-ignored by the scaffold's
  `.gitignore`.

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
  `RF_SLM_BACKEND`: `ollama` (default), `adapter` (phase-5 LoRA), `reference`
  (deterministic, no model — good for exercising the frontend), `stub` (no
  model, tests only). Regenerate `backend/models.py` after a schema change
  with the command in that file's header (`pip install -r requirements-dev.txt`).
  The Submit/Ask tab's `/ask` needs PostgreSQL reachable at `POSTGRES_DSN`
  (default `postgresql://postgres@localhost:5432/rf_slm`) to persist — the
  endpoint still answers without it, just with `stored: false` on the
  response. No PostgreSQL service is installed on this dev machine (the
  `winget` installer needs interactive UAC elevation); instead a portable
  copy lives at `.local/postgres/` (git-ignored — machine-local, not part
  of the repo, ~330MB zip build from EDB, no installer). One-time setup
  already done: `initdb -U postgres --auth=trust` (trust auth — local-only,
  same open posture the prior MongoDB setup had) then `createdb rf_slm`.
  Start it each session with:
  `./.local/postgres/bin/pg_ctl.exe -D ./.local/postgres/data -l ./.local/postgres/logs.log -o "-c shared_buffers=32MB -c max_connections=20 -c listen_addresses=127.0.0.1 -p 5432" start`
  — `pg_ctl start` daemonizes on its own (no need to background the shell
  command), and the low `shared_buffers`/`max_connections` keep its
  footprint small (this machine has been tight on RAM — MongoDB's default
  ~50%-of-RAM WiredTiger cache was implicated in repeated OOM kills of the
  whole dev stack, which is part of why this migrated to PostgreSQL).
  Stop with `./.local/postgres/bin/pg_ctl.exe -D ./.local/postgres/data
  stop`. It does not run as a Windows service, so it needs to be started
  manually each session; `/health`'s `query_store_connected` shows whether
  it's currently reachable.
- Run the frontend (phase 8): `cd frontend && npm run dev` (proxies to the
  backend on `:8000`, see `vite.config.ts`); `npm run build` type-checks and
  bundles for production.
- No lint step.

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
│   ├── esp32.py                     # ESP32 RF probe -> snapshot (2.4 GHz)     [done]
│   ├── cisco_c9800.py               # C9800 WLC capture bundle -> snapshot   [done]
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
│   ├── corpus/                      # 10 starter fact sheets, all verified     [done]
│   └── index/                       # generated, git-ignored
├── backend/
│   ├── main.py                      # FastAPI app + /health                    [done]
│   ├── config.py                    # per-stage temperatures, backend/index    [done]
│   ├── models.py                    # GENERATED Pydantic mirror of the schema  [done]
│   ├── schemas.py                   # API envelopes + RCAResult                 [done]
│   ├── inference.py                 # ModelBackend seam + orchestration        [done]
│   ├── rca.py                       # enforces taxonomy.output_contract        [done]
│   ├── deps.py                      # DI providers (overridden in tests)       [done]
│   ├── query_store.py               # QueryStore seam (Submit/Ask persistence) [done]
│   ├── live_buffer.py               # in-memory ring buffer (live-test tab)    [done]
│   └── routers/{diagnose,explain,ingest,retrieve,live,ask}.py                  [done]
├── frontend/                        # React + Vite + Tailwind v4            [done]
│   ├── src/api.ts  src/types.ts  src/example.ts
│   ├── src/App.tsx
│   └── src/components/{SnapshotInput,DiagnosisView,EvidenceChain,CitationList,
│                        ExplanationPanel,ConfidenceBadge,Section,
│                        LiveTestPanel,AskPanel}.tsx
├── hardware/
│   ├── esp32_rf_probe/              # Arduino firmware + JSON spec for esp32.py [done]
│   ├── read_probe.py                # serial/replay -> ingest -> diagnose (or --live) [done]
│   └── sample_capture.jsonl         # 6 recorded, RF-24-*-labelled demo captures [done]
└── tests/
    ├── test_adapters_base.py        # [done]
    ├── test_generic_csv.py          # [done]
    ├── test_generic_json.py         # [done]
    ├── test_esp32.py                # [done]
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
3. **Adapters.** `base.py`, `normalize.py`, `generic_csv.py`, `generic_json.py`,
   `esp32.py`, `cisco_c9800.py` done. `cisco_c9800.py` consumes a documented
   capture-bundle shape, not raw CLI/RESTCONF — it is unvalidated against a
   real WLC until phase 9 supplies a lab capture and (if the bundle-building
   glue reveals gaps) adjustments here. `aruba_central.py` / `mist.py` still
   to build. (Not on the critical path for phases 4–5: the synthetic
   generator builds canonical snapshots directly from the schema + taxonomy,
   so it does not wait on a vendor adapter. Adapters are still required
   before phase 9 lab validation.)
4. **Synthetic dataset.** Generator built (`data/`). First real run done:
   2990 examples (`qwen2.5:7b-instruct` teacher, seed 7), 0 rejections, 98 per
   cause + 442 abstention, train 2367 / eval 623. Full audit clean — every
   evidence path grounded, every asserted cause actually eligible, every
   abstention has cause_id null + non-empty data_gaps. Prose is good with
   occasional 7B fuzziness (acronym slips, weak edge-case reasoning); a
   stronger teacher would improve a v2 regen. Files are git-ignored; regenerate
   with the same command to reproduce.
5. **Fine-tune.** QLoRA scaffold built (`training/`), phase-4 dataset done
   (2990 examples). `--dry-run` is wired for CI. Blocked on a CUDA GPU —
   confirmed absent on both the dev machine (Intel integrated graphics only)
   and this session's remote agent environment; no laptop GPU is available
   either. Both configs (`qlora_config.yaml`, `qlora_config.8gb.yaml`) are
   validated: `--dry-run` passes, and a real (non-quantized) LoRA training
   loop was proven end-to-end on CPU against the real base model and real
   data (loss 1.87→1.05 over 4 steps). Real 4-bit `BitsAndBytesConfig`
   quantization loads on CPU but hangs during actual training — genuine
   CUDA hardware is required for the real run, not just more patience.
   Two dependency-drift bugs in `train.py` were found this way and fixed:
   `SFTConfig`'s `max_seq_length`→`max_length` rename, and its
   `warmup_ratio`→`warmup_steps`-only change in current `trl`/`transformers`.
   Resume with `python -m training.train --config training/qlora_config.8gb.yaml`
   (or the 16GB variant) the moment CUDA hardware is available.
6. **RAG corpus.** Layer built (`rag/`): corpus format, chunking, Ollama
   embeddings, ingest, retriever with band/domain/topic filters. 10 starter
   fact sheets covering what the taxonomy references, all curated and flipped
   to `review_status: verified` (see the `rag/` bullet above for what was
   corrected). Still to do: expand coverage; wire the retriever into the
   diagnosis path so numeric regulatory claims carry a citation.
7. **FastAPI backend.** Built (`backend/`): `/diagnose` (temperature pinned
   low), `/explain` (0.7-0.9, clamped), `/ingest` (generic adapters), `/retrieve`
   (corpus), `/live/ingest` + `/live/feed` (2.4 GHz hardware probe live feed,
   in-memory buffer — see `live_buffer.py` above), `/health`. `ModelBackend` is
   pluggable — `OllamaBackend` serves now, the QLoRA adapter slots in once
   phase 5 runs. `rca.py` enforces the output contract on every response,
   including live-feed diagnoses. An untuned 7B via `OllamaBackend` fails
   that guard often (invents cause_ids) — the diagnosis prompt injects the
   closed cause vocabulary to reduce it, but reliable `/diagnose` serving needs
   phase 5 — set `RF_SLM_BACKEND=adapter` once `training/out/` exists. Still to
   do: auth / rate limiting for anything exposed.
8. **React frontend.** Built (`frontend/`): snapshot editor, diagnosis view
   (evidence chain, ranked alternatives, remediation, data gaps, citations with
   UNVERIFIED flags), explanation panel with the only temperature slider
   (`[0.70, 0.90]`); a second tab, **2.4GHz Live Test**, polls the live buffer
   and renders each hardware-probe sample through the same diagnosis/
   explanation views — now with a no-hardware "Load demo samples" path
   (`POST /live/demo`, `hardware/sample_capture.jsonl`), demo/probe source
   badges, and an in-tab explanation of both usage modes and the RF-24-*
   test cases the demo set walks through (see the `frontend/` bullet above).
   Still to do: an ingest UI for CSV/JSON + mapping; polish.
9. **Validate** against real C9800 lab captures. `cisco_c9800.py` is built
   (phase 3 done) but unvalidated; still needs a lab capture set and a thin
   pyATS/Genie-or-RESTCONF glue script that fills the capture-bundle shape
   its module docstring documents — that step is also where any mismatch
   between this adapter's assumed field names and the real WLC's actual
   output gets caught and fixed.

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
