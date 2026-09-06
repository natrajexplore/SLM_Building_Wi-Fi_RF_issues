"""POST /retrieve — query the regulatory corpus directly.

Used by the frontend's "show me the source" affordance and for debugging what
the diagnosis path is seeing. Returns the same Citation shape the RCA carries.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.deps import retriever_dep
from backend.schemas import Citation, RetrieveRequest, RetrieveResponse

router = APIRouter()


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve(req: RetrieveRequest, retriever=Depends(retriever_dep)) -> RetrieveResponse:
    if retriever is None:
        raise HTTPException(503, "retrieval index unavailable — run `python -m rag.ingest`")
    hits = retriever.retrieve(
        req.query, k=req.k, bands=req.bands, domains=req.domains, topics=req.topics
    )
    return RetrieveResponse(citations=[
        Citation(title=h.title, heading=h.heading, sources=list(h.sources),
                 review_status=h.review_status, score=h.score, text=h.text)
        for h in hits
    ])
