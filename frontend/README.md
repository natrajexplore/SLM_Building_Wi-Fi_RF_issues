# frontend — RF Root-Cause SLM

React + Vite + Tailwind v4. Single page: paste a canonical RF snapshot, run
`/diagnose`, read the evidence chain + retrieved regulatory citations, then run
`/explain` for prose.

## Design constraint

The **only** temperature control in the UI is the slider in the explanation
panel, and its range is fixed to `[0.70, 0.90]`. The diagnosis path has no
temperature affordance and never will — invented causes are the primary failure
mode there (CLAUDE.md hard decision #3). `ExplanationPanel.tsx` is the single
place that value lives.

## Run

```bash
# 1. backend on :8000
cd .. && uvicorn backend.main:app --port 8000     # RF_SLM_BACKEND=stub for no model

# 2. frontend on :5173 (proxies /diagnose, /explain, /ingest, /retrieve, /taxonomy, /health)
npm install
npm run dev
```

`npm run build` type-checks (`tsc -b`) and bundles to `dist/`.

## Layout

- `api.ts` — fetch wrappers; pulls `detail` out of FastAPI 422/503 bodies
- `types.ts` — mirrors `backend/schemas.py`
- `example.ts` — a demo snapshot (RF-24-001 signature)
- `components/DiagnosisView` — cause + confidence + evidence + alternatives +
  remediation + data gaps + `CitationList` (each citation flags `UNVERIFIED`)
- `components/ExplanationPanel` — the temperature slider + `/explain`
