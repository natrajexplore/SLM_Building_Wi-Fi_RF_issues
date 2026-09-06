"""FastAPI app for the RF root-cause SLM.

    uvicorn backend.main:app --reload

Model backend is chosen by RF_SLM_BACKEND: `ollama` (default), `adapter` (the
phase-5 QLoRA output at RF_SLM_ADAPTER_DIR, default training/out), or `stub`.

Endpoints:
    POST /diagnose   canonical snapshot -> RCAResult   (temperature fixed low)
    POST /explain    snapshot + diagnosis -> prose     (temperature 0.7-0.9, clamped)
    POST /ingest     vendor rows/JSON -> canonical snapshot(s)
    POST /retrieve   query -> regulatory citations
    GET  /health     backend + index status

The two model paths run at deliberately different temperatures (CLAUDE.md hard
decision #3); there is no global temperature setting and the diagnosis path
cannot be tuned by a caller.
"""
from __future__ import annotations

from fastapi import FastAPI

from backend.config import get_settings
from backend.deps import backend_dep, retriever_dep
from backend.routers import diagnose, explain, ingest, retrieve
from data.taxonomy_loader import all_cause_ids, cause as get_cause

app = FastAPI(title="RF Root-Cause SLM", version="0.1.0")
app.include_router(diagnose.router, tags=["diagnose"])
app.include_router(explain.router, tags=["explain"])
app.include_router(ingest.router, tags=["ingest"])
app.include_router(retrieve.router, tags=["retrieve"])


@app.get("/taxonomy")
def taxonomy() -> dict:
    """The cause vocabulary — so a client can show names, not just IDs."""
    return {
        "causes": [
            {
                "id": cid,
                "name": get_cause(cid)["name"],
                "bands": get_cause(cid)["bands"],
                "severity_default": get_cause(cid).get("severity_default"),
            }
            for cid in all_cause_ids()
        ]
    }


@app.get("/health")
def health() -> dict:
    cfg = get_settings()
    retriever = retriever_dep()
    model = {
        "ollama": cfg.diagnose_model,
        "adapter": str(cfg.adapter_dir),
        "reference": "reference (deterministic, not the SLM)",
        "stub": "stub",
    }.get(cfg.model_backend, cfg.diagnose_model)

    backend_ready, backend_error = True, None
    try:
        backend_dep()
    except Exception as exc:  # never let /health 500 on a misconfigured backend
        backend_ready, backend_error = False, str(exc)

    return {
        "status": "ok" if backend_ready else "degraded",
        "model_backend": cfg.model_backend,
        "backend_ready": backend_ready,
        "backend_error": backend_error,
        "diagnose_model": model,
        "diagnose_temperature": cfg.diagnose_temperature,
        "explain_temperature_band": [cfg.explain_temperature_min, cfg.explain_temperature_max],
        "rag_enabled": cfg.rag_enabled,
        "rag_index": None if retriever is None else {
            "chunks": len(retriever.chunks),
            "embedder": retriever.manifest.get("embedder"),
            "review_status": retriever.manifest.get("review_status"),
        },
    }
