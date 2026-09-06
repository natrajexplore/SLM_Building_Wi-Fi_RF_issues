"""Load and index taxonomy/rf_root_causes.yaml.

Nothing here interprets the predicate grammar (that is `predicates`) or builds
snapshots (that is `snapshots`/`scenarios`). This module is purely: read the
file, expose causes by id, and resolve threshold *names* to their numeric
values so downstream code never has to know which tier a threshold lives in.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "taxonomy" / "rf_root_causes.yaml"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "canonical_rf.schema.json"


class TaxonomyError(RuntimeError):
    """The taxonomy file is structurally not what this code expects."""


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, Any]:
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict) or "causes" not in doc:
        raise TaxonomyError("taxonomy file has no top-level 'causes' list")
    return doc


@lru_cache(maxsize=1)
def causes_by_id() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for cause in load_taxonomy()["causes"]:
        cid = cause["id"]
        if cid in out:
            raise TaxonomyError(f"duplicate cause id {cid!r} in taxonomy")
        out[cid] = cause
    return out


@lru_cache(maxsize=1)
def all_cause_ids() -> tuple[str, ...]:
    return tuple(causes_by_id())


@lru_cache(maxsize=1)
def thresholds() -> dict[str, float]:
    """Flatten thresholds.defensible + thresholds.operational into one name->value map.

    The two tiers differ only in epistemic status (see the taxonomy header);
    for *evaluating* a predicate the value is the value regardless of tier, so
    a single flat lookup is what callers actually want. A name collision
    across tiers would be a taxonomy bug and is raised rather than silently
    resolved.
    """
    raw = load_taxonomy().get("thresholds", {})
    flat: dict[str, float] = {}
    for tier in ("defensible", "operational"):
        for name, value in (raw.get(tier) or {}).items():
            if name in flat:
                raise TaxonomyError(
                    f"threshold {name!r} defined in more than one tier"
                )
            flat[name] = value
    return flat


def resolve_threshold(name: str) -> float:
    try:
        return thresholds()[name]
    except KeyError:
        raise TaxonomyError(
            f"predicate references threshold {name!r} which is not defined "
            "under thresholds.defensible or thresholds.operational"
        ) from None


def output_contract() -> dict[str, Any]:
    return load_taxonomy()["output_contract"]


def cause(cid: str) -> dict:
    try:
        return causes_by_id()[cid]
    except KeyError:
        raise TaxonomyError(f"no such cause id: {cid!r}") from None
