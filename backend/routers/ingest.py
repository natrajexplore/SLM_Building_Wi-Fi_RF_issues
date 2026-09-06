"""POST /ingest — raw vendor rows / JSON -> canonical snapshot(s).

Thin HTTP wrapper over the generic adapters. Vendor-specific adapters, when
they exist, get their own ingest modes here; the model never sees any of this
input directly.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from adapters.base import ContractViolation
from adapters.generic_csv import CsvMapping, CsvMappingError, GenericCsvAdapter
from adapters.generic_json import GenericJsonAdapter, JsonMapping, JsonMappingError
from adapters.normalize import PseudonymisationError, SchemaValidationError
from backend.schemas import IngestRequest, IngestResponse

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest) -> IngestResponse:
    try:
        if req.format == "csv":
            if req.rows is None:
                raise HTTPException(422, "csv ingest requires `rows`")
            adapter = GenericCsvAdapter(CsvMapping.from_dict(req.mapping))
            snapshots = [adapter.to_canonical(r) for r in req.rows]
        else:
            if req.document is None:
                raise HTTPException(422, "json ingest requires `document`")
            adapter = GenericJsonAdapter(JsonMapping.from_dict(req.mapping))
            snapshots = [adapter.to_canonical(req.document)]
    except (CsvMappingError, JsonMappingError) as exc:
        raise HTTPException(422, f"bad mapping: {exc}")
    except (ContractViolation, PseudonymisationError) as exc:
        raise HTTPException(422, f"adapter rejected input: {exc}")
    except SchemaValidationError as exc:
        raise HTTPException(422, f"normalised snapshot failed schema validation: {exc}")

    return IngestResponse(snapshots=snapshots)
