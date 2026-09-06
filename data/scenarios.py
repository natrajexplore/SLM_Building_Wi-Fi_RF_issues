"""Compose training snapshots + ground-truth labels, one cause at a time.

Three kinds, matching CLAUDE.md's evaluation targets:

  single      one cause's required_evidence satisfied; label asserts it.
  ambiguous   the target plus one confusable both eligible; label asserts the
              target and lists the confusable in ranked_alternatives.
  abstention  a single-cause snapshot with every required_evidence field
              stripped back out; label asserts nothing (cause_id null) and
              reports the stripped fields as data_gaps.

Structure in every label is derived from the snapshot the builder just made,
so `evidence[].field_path` always resolves. Prose (`why_it_matters`,
`remediation`) comes from the teacher, or from templates under `--no-teacher`.
"""
from __future__ import annotations

import random
from typing import Any

from data import predicates
from data.snapshots import healthy_baseline, satisfy, violate
from data.taxonomy_loader import cause as get_cause

_DFS_CHANNELS = [52, 100, 116, 132]


def _observed(snapshot: dict, path: str) -> Any:
    values = [v for v in predicates.select(snapshot, predicates.parse_path(path)) if v is not None]
    return values[0] if values else None


def _held_evidence_paths(snapshot: dict, cause: dict) -> list[str]:
    """Required-evidence paths that actually hold — the label's evidence spine."""
    held: list[str] = []
    for entry in cause.get("required_evidence", []):
        if "any_of" in entry:
            for member in entry["any_of"]:
                if member.get("predicate") == "absent":
                    continue
                if "path" in member and predicates.check(snapshot, member):
                    held.append(member["path"])
                    break
        elif "path" in entry and entry.get("predicate") != "absent" and predicates.check(snapshot, entry):
            # `absent` predicates have nothing observable to cite as evidence —
            # they are contextual gates, not evidence spine.
            held.append(entry["path"])
    # de-dup, keep order
    seen: set[str] = set()
    return [p for p in held if not (p in seen or seen.add(p))]


def _supporting_gaps(snapshot: dict, cause: dict) -> list[str]:
    """supporting_evidence signals absent from this snapshot → data_gaps."""
    gaps: list[str] = []
    for entry in cause.get("supporting_evidence", []):
        path = str(entry).split()[0]  # strip any `== value` shorthand
        try:
            values = predicates.select(snapshot, predicates.parse_path(path))
        except predicates.PredicateError:
            continue
        if not [v for v in values if v is not None]:
            gaps.append(path)
    return gaps


_CAUSE_TWEAKS = {}


def _tweak(cid: str):
    def deco(fn):
        _CAUSE_TWEAKS[cid] = fn
        return fn
    return deco


@_tweak("RF-XB-003")
def _t_xb003(snap, rng):
    snap["analysis_context"]["spectrum_capable"] = True


@_tweak("RF-24-003")
def _t_24003(snap, rng):
    snap["analysis_context"]["spectrum_capable"] = True
    snap.setdefault("non_wifi_interferers", []).append(
        {"type": rng.choice(["microwave_oven", "bluetooth", "continuous_transmitter"]),
         "severity": rng.randrange(40, 90)}
    )


@_tweak("RF-5-001")
def _t_5001(snap, rng):
    snap["radio"]["channel"] = rng.choice(_DFS_CHANNELS)
    snap["radio"]["dfs_required"] = True


@_tweak("RF-5-002")
def _t_5002(snap, rng):
    snap["radio"]["channel"] = rng.choice(_DFS_CHANNELS)
    snap["radio"]["dfs_required"] = True


def choose_band(cause: dict, rng: random.Random) -> str:
    return rng.choice(cause["bands"])


def _base_for(cause: dict, rng: random.Random) -> tuple[dict, str]:
    band = choose_band(cause, rng)
    snap = healthy_baseline(band, rng)
    return snap, band


def _apply(cause: dict, snap: dict, rng: random.Random) -> None:
    for entry in cause.get("required_evidence", []):
        satisfy(snap, entry, rng)
    tweak = _CAUSE_TWEAKS.get(cause["id"])
    if tweak:
        tweak(snap, rng)


# ---------------------------------------------------------------------------
# public builders
# ---------------------------------------------------------------------------


def build_single(cid: str, rng: random.Random) -> dict:
    cause = get_cause(cid)
    snap, band = _base_for(cause, rng)
    _apply(cause, snap, rng)
    return {
        "snapshot": snap,
        "band": band,
        "kind": "single",
        "primary": cid,
        "alternatives": [],
        "held_paths": _held_evidence_paths(snap, cause),
        "data_gap_paths": _supporting_gaps(snap, cause),
    }


def build_ambiguous(cid: str, rng: random.Random) -> dict | None:
    cause = get_cause(cid)
    band = choose_band(cause, rng)
    candidates = [
        c for c in cause.get("confusable_with", [])
        if band in get_cause(c)["bands"]
    ]
    if not candidates:
        return None
    other = rng.choice(candidates)
    snap = healthy_baseline(band, rng)
    _apply(cause, snap, rng)
    _apply(get_cause(other), snap, rng)
    if not (predicates.required_evidence_met(snap, cause)
            and predicates.required_evidence_met(snap, get_cause(other))):
        return None
    return {
        "snapshot": snap,
        "band": band,
        "kind": "ambiguous",
        "primary": cid,
        "alternatives": [other],
        "held_paths": _held_evidence_paths(snap, cause),
        "data_gap_paths": _supporting_gaps(snap, cause),
    }


def build_abstention(cid: str, rng: random.Random) -> dict:
    cause = get_cause(cid)
    snap, band = _base_for(cause, rng)
    _apply(cause, snap, rng)
    for entry in cause.get("required_evidence", []):
        violate(snap, entry, rng)
    stripped: list[str] = []
    seen: set[str] = set()
    for path in predicates.evidence_paths(cause):
        if path not in seen:
            seen.add(path)
            stripped.append(path)
    return {
        "snapshot": snap,
        "band": band,
        "kind": "abstention",
        "primary": None,
        "nearest": cid,
        "alternatives": [],
        "held_paths": [],
        "data_gap_paths": stripped,
    }
