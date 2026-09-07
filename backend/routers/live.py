"""POST /live/ingest, GET /live/feed — the 2.4 GHz hardware probe live feed.

`hardware/esp32_rf_probe` already POSTs `{"format":"esp32","document":{...}}`
to `BACKEND_URL` on every sample (see esp32_rf_probe.ino) — the same envelope
`/ingest` accepts. Point `BACKEND_URL` at `/live/ingest` instead of `/ingest`
to feed the frontend's "2.4GHz Live Test" tab: each sample is normalized,
diagnosed at the fixed diagnosis temperature (same path as `/diagnose`, no
caller-supplied temperature here either), and held in `live_buffer` for the
frontend to poll. `/ingest` is unchanged and still the right endpoint for
one-off ingestion (read_probe.py, CSV/JSON uploads) that should not appear in
the live tab.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from adapters.base import ContractViolation
from adapters.esp32 import Esp32Adapter
from adapters.normalize import PseudonymisationError, SchemaValidationError
from backend import live_buffer
from backend.config import Settings
from backend.deps import backend_dep, retriever_dep, settings_dep
from backend.inference import BackendError, run_diagnosis
from backend.rca import RCAContractError
from backend.schemas import IngestRequest, LiveFeedResponse, LiveSample

router = APIRouter()


@router.post("/live/ingest", response_model=LiveSample)
def live_ingest(
    req: IngestRequest,
    cfg: Settings = Depends(settings_dep),
    backend=Depends(backend_dep),
    retriever=Depends(retriever_dep),
) -> LiveSample:
    if req.format != "esp32":
        raise HTTPException(422, "the live feed only accepts format=esp32")
    if req.document is None:
        raise HTTPException(422, "esp32 ingest requires `document` (the probe JSON)")

    try:
        snapshot = Esp32Adapter().to_canonical(req.document)
    except (ContractViolation, PseudonymisationError) as exc:
        raise HTTPException(422, f"adapter rejected input: {exc}")
    except SchemaValidationError as exc:
        raise HTTPException(422, f"normalised snapshot failed schema validation: {exc}")

    try:
        diagnosis = run_diagnosis(snapshot, backend, cfg, retriever)
    except RCAContractError as exc:
        raise HTTPException(422, f"model output rejected: {exc}")
    except BackendError as exc:
        raise HTTPException(503, str(exc))

    received_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    sample = live_buffer.append(snapshot, diagnosis.model_dump(mode="json"), received_at)
    return LiveSample.model_validate(sample)


@router.get("/live/feed", response_model=LiveFeedResponse)
def live_feed(since: int = 0) -> LiveFeedResponse:
    samples = [LiveSample.model_validate(s) for s in live_buffer.since(since)]
    return LiveFeedResponse(samples=samples, latest_id=live_buffer.latest_id())
