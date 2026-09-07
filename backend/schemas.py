"""API request/response envelopes.

The canonical snapshot itself is `backend/models.py::CanonicalSnapshot`
(generated from the JSON schema). These are the wire types around it and the
structured RCA output, which mirrors `taxonomy.output_contract`.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models import CanonicalSnapshot

Band = Literal["2.4GHz", "5GHz", "6GHz"]
Confidence = Literal["low", "medium", "high"]


# --- diagnosis ------------------------------------------------------------


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_path: str
    observed_value: Any
    why_it_matters: str


class RankedAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cause_id: str
    confidence: Confidence


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    heading: str | None = None
    sources: list[str]
    review_status: str
    score: float
    text: str


class RCAResult(BaseModel):
    """Structured diagnosis. `cause_id` is null for an abstention."""

    model_config = ConfigDict(extra="forbid")
    cause_id: str | None
    confidence: Confidence
    evidence: list[EvidenceItem]
    affected_bands: list[Band]
    remediation: list[str]
    data_gaps: list[str]
    ranked_alternatives: list[RankedAlternative] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class DiagnoseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: CanonicalSnapshot
    retrieve: bool = True  # allow disabling RAG per-request (not temperature)


# --- explanation ---------------------------------------------------------


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: CanonicalSnapshot
    diagnosis: RCAResult
    # Only the explanation path exposes temperature. It is clamped to [0.7, 0.9]
    # server-side; the diagnosis path has no equivalent field by design.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class ExplainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanation: str
    temperature_used: float


# --- ingest ------------------------------------------------------------


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["csv", "json", "esp32"]
    mapping: dict[str, Any] | None = None     # required for csv/json, unused for esp32
    rows: list[dict[str, Any]] | None = None  # csv: list of row dicts
    document: dict[str, Any] | None = None    # json / esp32: one source doc


class IngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshots: list[CanonicalSnapshot]


# --- live feed (2.4 GHz hardware probe) ---------------------------------


class LiveSample(BaseModel):
    """One probe sample already diagnosed and held in the live buffer."""

    model_config = ConfigDict(extra="forbid")
    id: int
    received_at: str
    snapshot: CanonicalSnapshot
    diagnosis: RCAResult


class LiveFeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    samples: list[LiveSample]
    latest_id: int


# --- retrieve ----------------------------------------------------------


class RetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str
    k: int = Field(default=4, ge=1, le=20)
    bands: list[Band] | None = None
    domains: list[str] | None = None
    topics: list[str] | None = None


class RetrieveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citations: list[Citation]
