"""POST /ask — free-text RF question -> grounded answer, persisted for later review.

Unlike /diagnose (a canonical snapshot -> structured cause) and /explain (an
already-decided diagnosis -> prose), /ask takes an open question with no
snapshot at all — "what's the LPI EIRP limit for 6 GHz indoor?", "why does
2.4 GHz cell sizing differ from 5 GHz?". It retrieves regulatory context via
the same RAG index, composes an answer at the explanation-band temperature
(open-ended prose, not a low-temperature structured assertion — CLAUDE.md
hard decision #3), and persists {query, answer, citations} via the QueryStore
seam (backend/query_store.py). A storage outage degrades the response
(`stored: false`) rather than failing the request — the point of the
RAG-grounded answer is the endpoint's job, not the storage.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.config import Settings
from backend.deps import backend_dep, query_store_dep, retriever_dep, settings_dep
from backend.inference import BackendError, run_ask
from backend.query_store import QueryStore, QueryStoreError
from backend.schemas import AskHistoryItem, AskHistoryResponse, AskRequest, AskResponse

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
def ask(
    req: AskRequest,
    cfg: Settings = Depends(settings_dep),
    backend=Depends(backend_dep),
    retriever=Depends(retriever_dep),
    store: QueryStore = Depends(query_store_dep),
) -> AskResponse:
    temperature = cfg.clamp_explain_temperature(req.temperature)
    try:
        answer, citations = run_ask(req.query, temperature, backend, cfg, retriever)
    except BackendError as exc:
        raise HTTPException(503, str(exc))

    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    doc_id, store_error = None, None
    try:
        doc_id = store.save(
            req.query, answer, [c.model_dump() for c in citations], temperature, created_at
        )
    except QueryStoreError as exc:
        store_error = str(exc)

    return AskResponse(
        id=doc_id, query=req.query, answer=answer, citations=citations,
        temperature_used=temperature, created_at=created_at,
        stored=doc_id is not None, store_error=store_error,
    )


@router.get("/ask/history", response_model=AskHistoryResponse)
def ask_history(
    limit: int = Query(default=50, ge=1, le=200),
    store: QueryStore = Depends(query_store_dep),
) -> AskHistoryResponse:
    """Every previously saved Q&A, most recent first — not just this browser
    session's own submissions (that's what the tab shows without calling this)."""
    try:
        docs = store.list_recent(limit)
    except QueryStoreError as exc:
        return AskHistoryResponse(items=[], store_error=str(exc))
    return AskHistoryResponse(items=[AskHistoryItem.model_validate(d) for d in docs])
