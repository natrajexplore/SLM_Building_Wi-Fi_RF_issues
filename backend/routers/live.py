"""POST /live/ingest, GET /live/feed, POST /live/demo — the 2.4 GHz hardware
probe live feed, and a no-hardware substitute for it.

`hardware/esp32_rf_probe` already POSTs `{"format":"esp32","document":{...}}`
on every sample to whatever backend host/path its on-device setup portal was
given (see wifi_portal.cpp) — the same envelope `/ingest` accepts. Set the
path to `/live/ingest` instead of `/ingest` in the portal to feed the
frontend's "2.4GHz Live Test" tab: each sample is normalized,
diagnosed at the fixed diagnosis temperature (same path as `/diagnose`, no
caller-supplied temperature here either), and held in `live_buffer` for the
frontend to poll. `/ingest` is unchanged and still the right endpoint for
one-off ingestion (read_probe.py, CSV/JSON uploads) that should not appear in
the live tab.

`/live/demo` exists for anyone without an ESP32 board: it replays the same
`hardware/sample_capture.jsonl` `read_probe.py --replay --live` would, through
the identical adapter -> diagnose -> buffer path, so the tab behaves exactly
as it would with real hardware attached. Demo samples carry `source: "demo"`
so the frontend can label them distinctly from `source: "probe"` samples a
real board posted — the two can coexist in the same buffer without being
mistaken for each other.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

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

_DEMO_CAPTURE = Path(__file__).resolve().parent.parent.parent / "hardware" / "sample_capture.jsonl"


def _ingest_esp32_document(
    document: dict, cfg: Settings, backend, retriever, source: str
) -> LiveSample:
    try:
        snapshot = Esp32Adapter().to_canonical(document)
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
    sample = live_buffer.append(snapshot, diagnosis.model_dump(mode="json"), received_at, source=source)
    return LiveSample.model_validate(sample)


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
    return _ingest_esp32_document(req.document, cfg, backend, retriever, source="probe")


@router.get("/live/feed", response_model=LiveFeedResponse)
def live_feed(since: int = 0) -> LiveFeedResponse:
    samples = [LiveSample.model_validate(s) for s in live_buffer.since(since)]
    return LiveFeedResponse(samples=samples, latest_id=live_buffer.latest_id())


@router.post("/live/demo", response_model=LiveFeedResponse)
def live_demo(
    cfg: Settings = Depends(settings_dep),
    backend=Depends(backend_dep),
    retriever=Depends(retriever_dep),
) -> LiveFeedResponse:
    """Replay the bundled sample captures into the live buffer for anyone
    without a probe. Each line is a real recorded ESP32 sample engineered to
    make exactly one (or, for the last line, two) RF-24-* cause(s)
    assertion-eligible — see the comments at the top of the capture file."""
    if not _DEMO_CAPTURE.exists():
        raise HTTPException(500, f"demo capture file missing: {_DEMO_CAPTURE}")

    before = live_buffer.latest_id()
    for line in _DEMO_CAPTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        _ingest_esp32_document(json.loads(line), cfg, backend, retriever, source="demo")

    samples = [LiveSample.model_validate(s) for s in live_buffer.since(before)]
    return LiveFeedResponse(samples=samples, latest_id=live_buffer.latest_id())
