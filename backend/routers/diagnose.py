"""POST /diagnose — canonical snapshot -> structured root-cause analysis.

Low temperature, fixed server-side (config.diagnose_temperature). The request
body has no temperature field; invented causes are the primary failure mode and
the diagnosis path must not be tunable.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from adapters.normalize import SchemaValidationError, validate_canonical
from backend.config import Settings
from backend.deps import backend_dep, retriever_dep, settings_dep
from backend.inference import BackendError, run_diagnosis
from backend.rca import RCAContractError
from backend.schemas import DiagnoseRequest, RCAResult

router = APIRouter()


@router.post("/diagnose", response_model=RCAResult)
def diagnose(
    req: DiagnoseRequest,
    cfg: Settings = Depends(settings_dep),
    backend=Depends(backend_dep),
    retriever=Depends(retriever_dep),
) -> RCAResult:
    snapshot = req.snapshot.model_dump(exclude_none=True, mode="json")
    try:
        validate_canonical(snapshot)
    except SchemaValidationError as exc:
        raise HTTPException(status_code=422, detail=f"snapshot failed schema validation: {exc}")

    cfg = cfg if req.retrieve else _no_rag(cfg)
    try:
        return run_diagnosis(snapshot, backend, cfg, retriever)
    except RCAContractError as exc:
        raise HTTPException(status_code=422, detail=f"model output rejected: {exc}")
    except BackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _no_rag(cfg: Settings) -> Settings:
    from dataclasses import replace

    return replace(cfg, rag_enabled=False)
