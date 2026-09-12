# Mutli use Wi-Fi Tools - SLM Building

A small language model that diagnoses wireless RF problems across **2.4 GHz, 5 GHz and 6 GHz** and returns a root cause with a supporting evidence chain, ranked alternatives, and remediation intent.

**Vendor neutral by design.** The model never sees vendor-native output. Every data source — a Cisco Catalyst 9800 capture bundle, an ESP32 probe reading, a CSV export — is normalized into one canonical schema by an adapter before it reaches the model. Adding a vendor means writing an adapter, never retraining.

---

## Contents

- [Why this exists](#why-this-exists)
- [How it works](#how-it-works)
- [RF issues covered](#rf-issues-covered)
- [Hardware](#hardware)
- [Building the SLM](#building-the-slm)
- [Repository layout](#repository-layout)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API](#api)
- [Testing](#testing)
- [Evaluation](#evaluation)
- [Project status](#project-status)
- [Limitations](#limitations)

---

## Why this exists

Wi-Fi troubleshooting is barely automated. A ticket reading *"Wi-Fi is slow in the warehouse"* can resolve to a dozen unrelated causes: co-channel interference from an over-dense channel plan, a microwave oven on 2.4 GHz, DFS radar events evacuating a 5 GHz radio, clients that never discover the 6 GHz BSS, or a wired-side fault that has nothing to do with RF at all.

Each vendor solves part of this inside its own ecosystem. Engineers solve all of it, slowly, using experience that transfers poorly. This project encodes that reasoning into a model small enough to run on a single GPU — or on CPU — inside a network where sending client telemetry to a hosted API is not acceptable.

Three properties drove every design decision:

1. **Vendor neutrality is structural, not aspirational.** It lives in the adapter boundary and the canonical schema, not in prompt wording.
2. **Invented root causes are the primary failure mode.** A confidently wrong RF diagnosis costs more engineer-hours than no diagnosis. Output is validated against a closed taxonomy; a `cause_id` outside it is a hard failure.
3. **A 1.5B model must never state a regulatory number from memory.** Numeric claims — EIRP limits, DFS CAC times, channel plans — come from retrieval with a citation, not from parametric weights.

---

## How it works

```
                    ┌──────────────────────────────────────────┐
 Vendor sources     │              ADAPTER LAYER               │
 ───────────────    │  cisco_c9800 · esp32 · generic_csv ·     │
 C9800 bundle    ──►│  generic_json                            │
 ESP32 probe     ──►│  ↓ validate · pseudonymise · missing_    │──┐
 CSV / JSON      ──►│    fields · strip provenance             │  │
                    └──────────────────────────────────────────┘  │
                                                                  ▼
                                         schema/canonical_rf.schema.json
                                                (the contract)
                                                                  │
                    ┌──────────────────────────────────────────┐  │
                    │           FastAPI BACKEND                │◄─┘
   React SPA  ◄────►│  /diagnose  temp 0.1–0.2  (pinned low)   │
   (Vite +          │  /explain   temp 0.7–0.9  (user slider)  │
    Tailwind v4)    │  /ask       multi-turn chat + RAG        │
                    │  /live/*    hardware probe feed          │
                    │  rca.py → enforces taxonomy contract     │
                    └───────┬──────────────────────┬───────────┘
                            │                      │
                   ┌────────▼────────┐    ┌────────▼─────────┐
                   │   SLM RUNTIME   │    │   RAG RETRIEVER  │
                   │ Qwen2.5-1.5B    │    │ regulatory facts,│
                   │ + QLoRA adapter │    │ channel plans,   │
                   │ (pluggable seam)│    │ IEEE clauses     │
                   └─────────────────┘    └──────────────────┘
```

**The split that matters:** the SLM learns the *reasoning pattern*. The vector store supplies the *facts*. Fine-tuning does not remove RAG from the loop — it never did.

### Temperature is split by stage

| Stage | Endpoint | Temperature | Reason |
|---|---|---|---|
| Diagnosis | `/diagnose`, `/live/ingest` | 0.1–0.2, pinned | Invented causes are the primary failure mode |
| Explanation | `/explain` | 0.7–0.9, user-adjustable | Readability, alternative framings |
| Ask | `/ask` | explanation band, server-side | Conversational grounding |

There is no global temperature knob, and the UI exposes a slider on the explanation path only. A high-temperature diagnosis produces a different root cause on consecutive runs of the same case — impossible to defend to anyone reviewing the tool.

---

## RF issues covered

The taxonomy in `taxonomy/rf_root_causes.yaml` defines **26 root causes** across four groups. It is the model's closed output vocabulary; IDs are stable forever once data has been generated against them.

Each cause carries: the physical or protocol mechanism, `required_evidence` gate predicates, `supporting_evidence` signals, `discriminators` for telling it apart from its neighbours, `confusable_with` links, vendor-neutral `remediation_intent`, and a default severity.

### 2.4 GHz — `RF-24-*`

| ID | Root cause |
|---|---|
| RF-24-001 | Co-channel interference from a non-1/6/11 channel plan |
| RF-24-002 | Adjacent-channel interference from overlapping channels |
| RF-24-003 | Non-Wi-Fi interference in the ISM band |
| RF-24-004 | Legacy low data rates consuming disproportionate airtime |
| RF-24-005 | Excessive cell overlap from over-powered radios |
| RF-24-006 | Client density exceeding channel capacity |

### 5 GHz — `RF-5-*`

| ID | Root cause |
|---|---|
| RF-5-001 | DFS radar detection forcing channel evacuation |
| RF-5-002 | Channel availability check blocking service on DFS channels |
| RF-5-003 | Channel width too wide for the available spectrum |
| RF-5-004 | Insufficient SNR at cell edge |
| RF-5-005 | Transmit power control misconfiguration |
| RF-5-006 | Regulatory domain restricting available channels |

### 6 GHz — `RF-6-*`

| ID | Root cause |
|---|---|
| RF-6-001 | AFC dependency blocking standard power operation |
| RF-6-002 | Low Power Indoor ceiling limiting coverage |
| RF-6-003 | Clients not discovering the 6 GHz BSS |
| RF-6-004 | WPA3/OWE enforcement excluding legacy clients |
| RF-6-005 | Client radio capability gap at 6 GHz |

### Cross-band — `RF-XB-*`

| ID | Root cause |
|---|---|
| RF-XB-001 | Sticky clients holding a degraded association |
| RF-XB-002 | Band steering failure or misconfiguration |
| RF-XB-003 | Elevated noise floor of undetermined origin |
| RF-XB-004 | Roaming failure from missing fast-transition support |
| RF-XB-005 | Inconsistent RF profile across AP groups |
| RF-XB-006 | Automatic channel selection instability |
| RF-XB-007 | **Wired-side or infrastructure fault presenting as RF degradation** |

### Capability gaps — `RF-CG-*`

| ID | Root cause |
|---|---|
| RF-CG-001 | Feature support asymmetry across the fleet |
| RF-CG-002 | Inconsistent 6 GHz readiness across a mixed fleet |

> **RF-XB-007 earns its place.** DHCP exhaustion, RADIUS timeouts, uplink saturation and PoE starvation all present as "Wi-Fi is broken." A model trained only on RF explanations will confidently supply an RF explanation for every one of them. Misattribution is the failure that burns credibility fastest with the engineers you want using this.

### Abstention is a first-class output

When the evidence required to assert a cause is absent from the snapshot, the correct answer is `cause_id: null` plus a populated `data_gaps` list — not a guess. This is measured as its own evaluation metric, not treated as an edge case.

---

## Hardware

Two distinct meanings, worth separating.

### 1. The ESP32 RF probe — real measurement hardware

`hardware/esp32_rf_probe/` is Arduino firmware turning an **ESP32-WROOM (38-pin)** into a working 2.4 GHz RF probe. It samples one channel and POSTs JSON that `adapters/esp32.py` normalizes into a canonical snapshot.

**What it genuinely measures:**

| Signal | Method |
|---|---|
| Neighbouring APs (BSSID, channel, RSSI, SSID, auth) | `WiFi.scanNetworks()` |
| Co- / adjacent-channel neighbour counts | Computed from the scan |
| Noise floor (dBm) | `rx_ctrl.noise_floor`, averaged over sniffed frames |
| Retry rate, FCS error rate | Retry bit / rx_state over sniffed frames |
| Channel utilisation (approximate) | Σ estimated frame airtime ÷ window |
| Regulatory domain, min basic rate, CSA events | Beacon IEs (country=7, rates=1, CSA=37) |
| Non-Wi-Fi interference hint | BLE scan → `{type: "bluetooth"}` presence |

**What it cannot do, and says so:** the board is 2.4 GHz only with no spectrum-analysis silicon, so every snapshot carries `radio.band = "2.4GHz"` and `analysis_context.spectrum_capable = false`. That flag is load-bearing — an empty `non_wifi_interferers` list means *nothing* when the source cannot see the spectrum, and the model is trained to treat it that way. Channel utilisation is a coarse estimate; the ESP32 exposes no CCA-busy counter.

**On-device setup portal.** WiFi credentials, backend host/port/path and an HTTPS toggle are configured at runtime through a captive portal, not compile-time macros. On first boot — or when BOOT (GPIO0) is held at power-on — the board hosts `RF-Probe-Setup-XXXX` with a login-gated setup page, in the style of a consumer router. Settings persist to NVS. Holding BOOT for 10s+ factory-resets both WiFi credentials and the admin login, so a mistyped password can never permanently lock the portal out from itself. `config.h` retains only sampling parameters.

**No board? There's a demo path.** `POST /live/demo` replays `hardware/sample_capture.jsonl` — 6 real recorded probe captures, one per `RF-24-*` cause reachable from ESP32-only evidence, plus a deliberately ambiguous one — through the identical adapter → diagnose → buffer pipeline. Demo rows carry a `DEMO` badge in the UI so they are never confused with live hardware readings.

### 2. Infrastructure the model reasons about

Vendor-neutral, via the adapter layer: controller-based, cloud-managed and standalone APs; 802.11n through 802.11be; 2×2 to 8×8 MIMO; dual- and tri-radio designs; internal and external antennas; PoE budget as an operating constraint; and client capability differences (supported bands, spatial streams, 802.11k/v/r support, Tx power ceiling) as first-class diagnostic inputs.

### 3. Compute hardware

| Purpose | Requirement |
|---|---|
| Schema, adapters, data generation, RAG, backend, tests | CPU only — no GPU, no CUDA toolchain |
| QLoRA fine-tune (16 GB preset) | Single CUDA GPU, 16 GB (T4-class or better) |
| QLoRA fine-tune (8 GB preset) | 8 GB CUDA GPU — `qlora_config.8gb.yaml`, batch 1, seq 1536, LoRA r=8, ~6–7 GB peak |
| Turing cards (T4, RTX 20xx) | Additionally `bf16: false`, `bnb_4bit_compute_dtype: float16` |
| Serving | CPU inference works; latency scales with model size |

Training dependencies live in `requirements-train.txt`, deliberately separate — the core repo must stay installable without a CUDA toolchain.

---

## Building the SLM

### Teacher and student

**GPT-2 is not the teacher.** Distillation here means a frontier model generates a synthetic RCA dataset *offline*; a modern small base model is fine-tuned on it. The teacher is never in the serving path.

| Role | Model |
|---|---|
| Teacher (offline dataset generation only) | Frontier model via Ollama; `qwen2.5:7b-instruct` used for the first run |
| Student base (primary) | `Qwen2.5-1.5B-Instruct` |
| Student base (fallback) | `Llama-3.2-1B-Instruct` |
| Method | QLoRA, 4-bit, single GPU |

### Ground truth by construction

The synthetic generator does not ask the teacher what the answer is. Scenario structure — the cause, the evidence paths, the eligibility predicates — is constructed from the schema and taxonomy first; the teacher only writes prose over a label that is already correct. This removes the largest risk in teacher-generated data, which is a fluent teacher confidently producing plausible-sounding RF nonsense that then propagates into the student.

**First generation run:** 2990 examples, 0 rejections, 98 per cause + 442 abstention cases, split train 2367 / eval 623. Full audit clean — every evidence path grounded in the snapshot, every asserted cause actually eligible under its predicates, every abstention carrying `cause_id: null` and non-empty `data_gaps`. Generated datasets are git-ignored; regenerate with the same seed to reproduce.

### The evidence predicate grammar

As of taxonomy v0.2.0, `required_evidence` entries are **predicate objects**, not bare field paths — `{path, predicate, value|threshold}`, or an `any_of` group, all ANDed. Predicates gate assertion *eligibility* only; they do not replace ranking, confidence, or discriminator reasoning. Read the grammar block at the top of `taxonomy/rf_root_causes.yaml` before writing anything that consumes this field.

### RAG corpus

`rag/corpus/` holds 10 curated fact sheets covering what the taxonomy references — 5 GHz DFS, UNII channel plans, 6 GHz power classes and discovery, EIRP limits, channel-width tradeoffs, the 2.4 GHz channel plan and legacy rates.

All are marked `review_status: verified` following a curation pass against FCC §15.247/§15.407, ETSI EN 300 328/301 893, CEPT ECC decisions, and IEEE 802.11. That pass corrected three real numeric errors: DFS weather-radar CAC time wrongly attributed to FCC rather than ETSI; 6 GHz LPI EIRP-vs-width and VLP PSD figures; and the 2.4 GHz point-to-point vs point-to-multipoint antenna-gain reduction rule.

Honest caveat: the pass relied on authoritative secondary sources, not the paywalled IEEE 802.11 primary text. One sub-claim in `6ghz-discovery.md` — FILS Discovery's exact beacon-cadence relationship — remains only weakly corroborated.

### Privacy at the boundary

Client and BSSID identifiers are pseudonymised inside `Adapter.to_canonical`, enforced in code rather than by convention. `adapters/normalize.py` additionally scans every snapshot for anything MAC-shaped and raises rather than letting it through. `source.*` is provenance only and is stripped before the model sees a snapshot. Real MACs never enter training data or logs.

---

## Repository layout

```
.
├── CLAUDE.md                         # design decisions + build state
├── schema/
│   └── canonical_rf.schema.json      # the contract — start here
├── taxonomy/
│   └── rf_root_causes.yaml           # 26 causes, output vocabulary, predicates
├── adapters/
│   ├── base.py                       # Adapter ABC → canonical dict
│   ├── normalize.py                  # validation, missing_fields, pseudonymisation
│   ├── _common.py                    # schema introspection + coercion
│   ├── generic_csv.py                # flat CSV row → snapshot
│   ├── generic_json.py               # nested vendor JSON → snapshot
│   ├── esp32.py                      # ESP32 probe → snapshot (2.4 GHz)
│   └── cisco_c9800.py                # C9800 capture bundle → snapshot
├── data/                             # synthetic dataset generator
│   ├── predicates.py                 # required_evidence grammar evaluator
│   ├── snapshots.py                  # baselines, path writes, satisfy/violate
│   ├── scenarios.py                  # single / ambiguous / abstention builders
│   ├── prompts.py                    # diagnosis, explanation, ask system prompts
│   ├── teacher.py                    # Ollama client + offline templated fallback
│   └── generate.py                   # orchestrator + hard validation
├── training/
│   ├── qlora_config.yaml             # Qwen2.5-1.5B QLoRA 4-bit (16 GB / T4)
│   ├── qlora_config.8gb.yaml         # low-VRAM preset
│   ├── train.py                      # SFT loop; --dry-run needs no GPU
│   └── evaluate.py                   # top-1/top-3, grounding, abstention, hallucination
├── rag/
│   ├── documents.py  embedder.py  ingest.py  retriever.py
│   └── corpus/                       # 10 verified fact sheets
├── backend/
│   ├── main.py                       # FastAPI app + /health + /taxonomy
│   ├── config.py                     # per-stage temperatures
│   ├── models.py                     # GENERATED from the JSON schema — do not edit
│   ├── schemas.py  inference.py  rca.py  deps.py
│   ├── query_store.py                # QueryStore seam (PostgreSQL)
│   ├── live_buffer.py                # in-memory ring buffer, last 200 samples
│   └── routers/{diagnose,explain,ingest,retrieve,live,ask}.py
├── frontend/                         # React + Vite + Tailwind v4 SPA
│   └── src/components/{AskPanel,LiveTestPanel,WirelessTopicsPanel,
│                       DiagnosisView,EvidenceChain,ExplanationPanel,
│                       CitationList,ConfidenceBadge,Section}.tsx
├── hardware/
│   ├── esp32_rf_probe/               # firmware, setup portal, dev cert generator
│   ├── read_probe.py                 # serial/replay → ingest → diagnose
│   └── sample_capture.jsonl          # 6 labelled demo captures
└── tests/                            # stdlib unittest, 10 modules
```

---

## Quick start

### Install

```bash
git clone https://github.com/natrajexplore/SLM_Building_Wi-Fi_RF_issues.git
cd SLM_Building_Wi-Fi_RF_issues

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Core dependencies are CPU-only. Training deps install separately on the GPU box:

```bash
pip install -r requirements.txt -r requirements-train.txt
```

### Run the backend

```bash
uvicorn backend.main:app --reload
# docs at http://127.0.0.1:8000/docs
```

For real ESP32 hardware on the LAN, bind all interfaces — `--reload` binds loopback only, which is invisible to the board:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

In the board's setup portal, set the backend host to the machine's actual LAN IP (`ipconfig` / `ip addr`), never `localhost` — from the board's perspective that means the board itself. Watch its serial output for `POST <url> -> <code>` to confirm delivery.

### Run the frontend

```bash
cd frontend && npm install && npm run dev
```

A colorful, icon-driven UI ("Multi use Wi-Fi Tool" in the header) over three tabs, in display order:

1. **Submit / Ask** — multi-turn chat grounded in RAG, with a saved conversation list and citations behind a disclosure. Replies stream in token-by-token (`POST /ask/stream`) with an animated "thinking" indicator while the model is generating, rather than a blank wait.
2. **2.4 GHz Live Test** — polls the live feed every 3s and renders each probe sample through the diagnosis and explanation views. Includes a "Load demo samples" button for anyone without a board.
3. **Wireless Topics** — read-only browser over the taxonomy, grouped by band and color-coded per band (2.4/5/6 GHz each get a distinct color used consistently across filters, section headers, and the detail view), with `confusable_with` links to jump between related causes.

### Generate the dataset

```bash
python -m data.generate --count 3000 --out data/      # needs Ollama + teacher model
python -m data.generate --count 3000 --no-teacher     # fast offline set
```

### Build the RAG index

```bash
python -m rag.ingest                                   # needs Ollama + nomic-embed-text
python -m rag.ingest --embedder hash                   # offline test index
python -m rag.retriever "6 GHz LPI EIRP limit" --band 6GHz
```

### Train

```bash
python -m training.train --dry-run                                # validates config + data, no GPU
python -m training.train --config training/qlora_config.8gb.yaml  # real run, needs CUDA
python -m training.evaluate --responder adapter --model training/out
```

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `RF_SLM_BACKEND` | `ollama` | `ollama` · `adapter` (phase-5 LoRA) · `reference` (deterministic, no model) · `stub` (tests) |
| `RF_SLM_ADAPTER_DIR` | `training/out` | LoRA adapter location when `RF_SLM_BACKEND=adapter` |
| `RF_SLM_ASK_BACKEND` | `ollama` | Separate backend for `/ask` — raises on `reference` by design |
| `RF_SLM_ASK_MODEL` | `qwen2.5:7b-instruct` | Ask model; a 0.5b model answers in ~10s but is frequently wrong |
| `RF_SLM_TEACHER_MODEL` | — | Ollama tag used for dataset generation |
| `POSTGRES_DSN` | `postgresql://postgres@localhost:5432/rf_slm` | Ask-tab conversation persistence |

**Why `/ask` has its own backend:** `ReferenceBackend` only ever emits diagnosis JSON — it has no concept of prose. Sharing it with `/ask` silently returned `{"cause_id": null, ...}` as the "answer" to every question. `build_ask_backend` now raises outright on `ask_backend="reference"` so that class of bug cannot recur quietly.

A PostgreSQL outage degrades one `/ask` request (`stored: false`, `store_error` set) rather than failing it — the endpoint's job is the grounded answer, not the write. Tables are created on first successful connection; `psycopg` is lazily imported so the rest of `backend/` stays importable with no PostgreSQL installed at all.

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /diagnose` | Canonical snapshot → ranked root causes + evidence chain. Temperature pinned low. |
| `POST /explain` | Diagnosis → prose explanation. Temperature 0.7–0.9, clamped. |
| `POST /ingest` | Vendor document + format → canonical snapshot |
| `POST /retrieve` | Query → ranked corpus citations, with band/domain/topic filters |
| `POST /live/ingest` | Same envelope as `/ingest`; diagnoses and appends to the live buffer |
| `GET /live/feed?since=<id>` | Polled by the Live Test tab |
| `POST /live/demo` | Replays the bundled captures — no hardware needed |
| `POST /ask` | Multi-turn grounded chat; persists to PostgreSQL |
| `POST /ask/stream` | Same as `/ask`, but the answer streams token-by-token over Server-Sent Events instead of waiting for the full reply |
| `GET /ask/conversations` | Saved conversations, most recent first |
| `DELETE /ask/conversations` | Irreversible wipe; the UI confirms first, and a store outage returns 503 rather than a silent no-op |
| `GET /taxonomy` | Full cause set with descriptions, discriminators, remediation intent |
| `GET /health` | Backend, index, and `query_store_connected` status |

Every model response passes through `rca.py`, which enforces `taxonomy.output_contract`. A `cause_id` not present in the taxonomy is a hard failure, not a warning.

**Why `/ask/stream` exists:** on a CPU-only deployment a full `/ask` reply can take 20–80s+, and streaming shows the answer as it's generated instead of leaving the UI blank for the whole round trip. Both `/ask` and `/ask/stream` cap the prior conversation resent to the model to the last 4 turns — older turns stay saved and visible in the sidebar, they just stop being resent as prompt context, so a long conversation doesn't keep getting slower turn over turn.

---

## Testing

```bash
python -m unittest discover -s tests
```

Stdlib `unittest` only, no pytest. Training tests import pure helpers, never torch — the suite runs with no GPU and no heavy dependencies installed.

---

## Evaluation

| Metric | What it measures |
|---|---|
| Top-1 `cause_id` accuracy | Correct primary diagnosis on the held-out set |
| Top-3 accuracy | Correct cause in the ranked set, on deliberately ambiguous cases |
| Evidence grounding | Every cited `field_path` must exist in the input snapshot |
| Abstention | With required evidence removed, the model must report a data gap, not assert a cause |
| Hallucination check | No numeric regulatory claim without a retrieval citation |

---

## Project status

Honest state, phase by phase.

| Phase | Component | Status |
|---|---|---|
| 1 | Canonical schema | Done |
| 2 | Taxonomy (26 causes, v0.2.0 predicates) | Done |
| 3 | Adapters — base, normalize, generic CSV/JSON, ESP32, C9800 | Done. C9800 **unvalidated against a real WLC**. Aruba Central and Mist not started. |
| 4 | Synthetic dataset generator | Done. 2990 examples generated, full audit clean. |
| 5 | QLoRA fine-tune | **Scaffold done, real run blocked.** No CUDA GPU reachable from the dev environment. `--dry-run` passes, and a real non-quantized LoRA loop was proven end-to-end on CPU (loss 1.87 → 1.05 over 4 steps). 4-bit quantization loads on CPU but hangs during training — genuine CUDA hardware is required. `training/out/` does not exist. |
| 6 | RAG layer + corpus | Done. 10 fact sheets verified. Still to do: expand coverage; wire retrieval into the diagnosis path so numeric claims always carry a citation. |
| 7 | FastAPI backend | Done. Still to do: auth and rate limiting before anything is exposed. |
| 8 | React frontend | Done. Still to do: an ingest UI for CSV/JSON with mapping. |
| 9 | Lab validation against real C9800 captures | Not started. Needs a lab capture set and pyATS/Genie or RESTCONF glue to fill the documented capture-bundle shape. |

**What this means in practice:** the full pipeline runs today with an untuned model served through Ollama. That untuned 7B fails the output-contract guard reasonably often by inventing `cause_id` values — the diagnosis prompt injects the closed vocabulary to reduce it, but reliable `/diagnose` serving needs phase 5. Set `RF_SLM_BACKEND=adapter` once `training/out/` exists.

Two dependency-drift bugs in `train.py` were found and fixed through CPU testing: `SFTConfig`'s `max_seq_length` → `max_length` rename, and its `warmup_ratio` → `warmup_steps`-only change in current `trl`/`transformers`.

The ESP32 setup portal, NVS persistence and the `WiFiClientSecure` POST path need verification on real hardware; they have not been tested beyond what a desktop can exercise.

---

## Limitations

- The model produces **probable** root causes, not verified ones. It is a diagnostic aid, not an authority.
- It cannot detect what is absent from its input. Non-Wi-Fi interference generally needs a spectrum analyser to confirm — and when `spectrum_capable` is false, an empty interferer list carries no information at all.
- Physical-layer problems — obstruction, reflection, antenna mounting — can be inferred but not measured from telemetry.
- Regulatory rules for 5 GHz DFS and 6 GHz power classes vary by country. Verify against local regulation before acting on a channel or power recommendation.
- `live_buffer.py` is in-memory and single-process. It resets on restart and is deliberately not a durability guarantee.
- The C9800 adapter consumes a documented normalized bundle, not raw CLI or RESTCONF, because exact Genie/YANG field names vary by IOS-XE release and cannot be hardcoded without a real capture to check against.
- Nothing here should be applied to a production network without engineering judgement.

## Known traps

Encoded in the taxonomy discriminators, and worth stating plainly:

- 2.4 GHz cell size is not 5/6 GHz cell size. Never share a power setting between them.
- Healthy RF plus a real user complaint usually means `RF-XB-007`, not more RF tuning.
- Discontinuous 6 GHz coverage is worse than no 6 GHz.

---

## Contributing

The highest-value contributions are well-documented RF case studies with confirmed root causes and full telemetry, and new vendor adapters. Please anonymise SSIDs, BSSIDs, client MACs and site identifiers before submitting; the adapter layer will reject MAC-shaped values regardless.

## License

*To be added.*

## Author

**Nataraj Angappan** — Network Security Engineer, wireless architecture
[LinkedIn](https://linkedin.com/in/nataraj-angappan-3a8614138)
