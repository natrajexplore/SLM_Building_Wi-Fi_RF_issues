"""POST /explain — snapshot + diagnosis -> readable prose.

This is the only path that exposes temperature, and it is clamped server-side to
[0.7, 0.9] (config). A request asking for 0.1 or 1.5 gets the clamped value and
the response reports what was actually used.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.config import Settings
from backend.deps import backend_dep, settings_dep
from backend.inference import BackendError, run_explanation
from backend.schemas import ExplainRequest, ExplainResponse

router = APIRouter()


@router.post("/explain", response_model=ExplainResponse)
def explain(
    req: ExplainRequest,
    cfg: Settings = Depends(settings_dep),
    backend=Depends(backend_dep),
) -> ExplainResponse:
    temperature = cfg.clamp_explain_temperature(req.temperature)
    snapshot = req.snapshot.model_dump(exclude_none=True, mode="json")
    diagnosis = req.diagnosis.model_dump(mode="json")
    try:
        text = run_explanation(snapshot, diagnosis, temperature, backend, cfg)
    except BackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return ExplainResponse(explanation=text, temperature_used=temperature)
