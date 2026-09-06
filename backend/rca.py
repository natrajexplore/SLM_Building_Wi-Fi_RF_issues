"""Enforce taxonomy.output_contract on a model's raw diagnosis.

CLAUDE.md: model output MUST validate against the output contract; a cause_id
not in the taxonomy is a hard failure, not a warning; no numeric regulatory
claim without a retrieval citation.

This runs AFTER the model and BEFORE the response leaves the API. It reuses the
same predicate evaluator and hallucination heuristic the dataset generator and
the offline evaluator use, so "valid" means the same thing everywhere.
"""
from __future__ import annotations

from data import predicates
from data.taxonomy_loader import all_cause_ids, cause as get_cause
from data.teacher import _has_bare_regulatory_number

_VALID_IDS = set(all_cause_ids())
_REQUIRED = ("cause_id", "confidence", "evidence", "affected_bands", "remediation", "data_gaps")
_CONFIDENCE = {"low", "medium", "high"}


class RCAContractError(ValueError):
    """The model's diagnosis violates taxonomy.output_contract."""


def validate_rca(result: dict, snapshot: dict, *, has_citations: bool) -> dict:
    """Return `result` unchanged if it is contract-valid, else raise.

    `has_citations` is whether the retrieval step returned anything — a bare
    numeric regulatory claim is only permitted when it did.
    """
    if not isinstance(result, dict):
        raise RCAContractError("diagnosis is not a JSON object")

    for key in _REQUIRED:
        if key not in result:
            raise RCAContractError(f"missing required field {key!r}")

    if result["confidence"] not in _CONFIDENCE:
        raise RCAContractError(f"confidence must be one of {_CONFIDENCE}")

    cid = result["cause_id"]
    if cid is not None and cid not in _VALID_IDS:
        raise RCAContractError(f"cause_id {cid!r} is not in the taxonomy")

    for alt in result.get("ranked_alternatives", []):
        if not isinstance(alt, dict) or alt.get("cause_id") not in _VALID_IDS:
            raise RCAContractError(f"ranked_alternatives entry {alt!r} is not a valid cause")

    # evidence grounding — every cited path must resolve in the snapshot
    for item in result["evidence"]:
        path = (item or {}).get("field_path")
        if not isinstance(path, str):
            raise RCAContractError("evidence item without a string field_path")
        try:
            hits = predicates.select(snapshot, predicates.parse_path(path))
        except predicates.PredicateError:
            raise RCAContractError(f"evidence field_path {path!r} is not a valid canonical path")
        if not [v for v in hits if v is not None]:
            raise RCAContractError(f"evidence field_path {path!r} does not resolve in the snapshot")

    if cid is None:
        if not result["data_gaps"]:
            raise RCAContractError("an abstention (cause_id null) must list data_gaps")
    else:
        # necessary condition: the asserted cause's required_evidence must hold.
        if not predicates.required_evidence_met(snapshot, get_cause(cid)):
            raise RCAContractError(
                f"cause_id {cid!r} asserted but its required_evidence does not hold "
                "against this snapshot — the model must abstain instead"
            )

    # hallucination guard
    if not has_citations:
        for text in _prose(result):
            if _has_bare_regulatory_number(text):
                raise RCAContractError(
                    f"numeric regulatory claim with no retrieval citation: {text!r}"
                )

    return result


def _prose(result: dict):
    for item in result.get("evidence", []):
        yield str((item or {}).get("why_it_matters", ""))
    yield from (str(x) for x in result.get("remediation", []))
