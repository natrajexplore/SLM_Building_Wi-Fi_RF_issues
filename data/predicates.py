"""Evaluator for the v0.2.0 `required_evidence` predicate grammar.

Read the grammar block at the top of taxonomy/rf_root_causes.yaml first. This
module is the single mechanical interpretation of it, shared by:

  - data/scenarios.py  — to verify a constructed positive snapshot actually
                         makes its target cause assertion-eligible, and that an
                         abstention snapshot does NOT.
  - training/evaluate.py — the abstention metric: a model that asserts a cause
                         whose predicates do not all hold has failed.

Predicates gate ASSERTION ELIGIBILITY ONLY (taxonomy header). `required_evidence_met`
returning True means "this cause is a candidate", never "this cause is the answer".

Path forms supported (one segment = name + optional `[]` OR optional `["key"]`):
    field.sub            plain object access
    field[]              the array itself (existence / non-emptiness)
    field[].sub          wildcard: holds if ANY element's `sub` satisfies
    field["literal"]     object property by exact key (for dotted map keys)

Predicates: present | absent | == | != | >= | <= | > | <
"""
from __future__ import annotations

import re
from typing import Any

from data.taxonomy_loader import resolve_threshold

_SEGMENT_RE = re.compile(
    r"""
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    (?:
        (?P<array>\[\])
      | \[\s*"(?P<literal>[^"]+)"\s*\]
    )?
    """,
    re.VERBOSE,
)

_COMPARATORS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


class PredicateError(RuntimeError):
    """A predicate object or path is malformed — a taxonomy bug, not a data gap."""


def parse_path(path: str) -> list[tuple[str, str | None]]:
    """['rf_metrics.co_channel_neighbors'] -> [('rf_metrics', None), ('co_channel_neighbors', None)].

    Second tuple element is 'array' for `name[]`, or the literal key string for
    `name["key"]`, else None.
    """
    # Split on '.' EXCEPT inside a ["..."] literal key (which may contain a dot,
    # e.g. clients.band_distribution["2.4GHz"]).
    segments: list[tuple[str, str | None]] = []
    pos = 0
    while pos < len(path):
        m = _SEGMENT_RE.match(path, pos)
        if not m or m.start() != pos:
            raise PredicateError(f"unparseable path {path!r} at offset {pos}")
        if m.group("array"):
            segments.append((m.group("name"), "array"))
        elif m.group("literal") is not None:
            segments.append((m.group("name"), m.group("literal")))
        else:
            segments.append((m.group("name"), None))
        pos = m.end()
        if pos < len(path):
            if path[pos] != ".":
                raise PredicateError(f"expected '.' at offset {pos} in {path!r}")
            pos += 1
    if not segments:
        raise PredicateError(f"empty path {path!r}")
    return segments


def select(node: Any, segments: list[tuple[str, str | None]]) -> list[Any]:
    """Values a parsed path selects. [] when the path leads nowhere.

    A bare trailing `name[]` yields [the array itself]; `name[].sub` fans out
    over elements and yields one value per element that has `sub`.
    """
    if not segments:
        return [node]

    (name, marker), rest = segments[0], segments[1:]
    if not isinstance(node, dict) or name not in node:
        return []
    value = node[name]

    if marker == "array":
        if not rest:
            return [value]  # testing the array itself
        if not isinstance(value, list):
            return []
        out: list[Any] = []
        for element in value:
            out.extend(select(element, rest))
        return out

    if marker is not None:  # ["literal"]
        if not isinstance(value, dict) or marker not in value:
            return []
        return select(value[marker], rest)

    return select(value, rest)


def _target(pred: dict) -> Any:
    has_value = "value" in pred
    has_threshold = "threshold" in pred
    if has_value == has_threshold:
        raise PredicateError(
            f"comparison predicate must carry exactly one of value/threshold: {pred!r}"
        )
    return pred["value"] if has_value else resolve_threshold(pred["threshold"])


def check(snapshot: dict, pred: dict) -> bool:
    """True if a single predicate object (or any_of group) holds against `snapshot`."""
    if "any_of" in pred:
        members = pred["any_of"]
        if not isinstance(members, list) or not members:
            raise PredicateError(f"any_of must be a non-empty list: {pred!r}")
        return any(check(snapshot, m) for m in members)

    if "path" not in pred or "predicate" not in pred:
        raise PredicateError(f"predicate object needs 'path' and 'predicate': {pred!r}")

    op = pred["predicate"]
    values = select(snapshot, parse_path(pred["path"]))

    if op == "present":
        return any(v is not None for v in values)

    if op == "absent":
        # "missing, null, OR (for arrays) present but empty" — taxonomy header.
        if not values:
            return True
        return all(
            v is None or (isinstance(v, list) and len(v) == 0) for v in values
        )

    if op not in _COMPARATORS:
        raise PredicateError(f"unknown predicate {op!r} in {pred!r}")

    present = [v for v in values if v is not None]
    if not present:
        return False  # cannot assert a comparison against data that isn't there
    target = _target(pred)
    cmp = _COMPARATORS[op]
    for v in present:
        try:
            if cmp(v, target):
                return True
        except TypeError:
            # e.g. ">=" against a string — a taxonomy/data type mismatch.
            raise PredicateError(
                f"cannot apply {op!r} between {v!r} and {target!r} for "
                f"path {pred['path']!r}"
            ) from None
    return False


def required_evidence_met(snapshot: dict, cause: dict) -> bool:
    """True if EVERY entry in cause['required_evidence'] holds (implicit AND)."""
    return all(check(snapshot, entry) for entry in cause.get("required_evidence", []))


def unmet_predicates(snapshot: dict, cause: dict) -> list[dict]:
    """The required_evidence entries that do NOT hold — used to build data_gaps."""
    return [e for e in cause.get("required_evidence", []) if not check(snapshot, e)]


def evidence_paths(cause: dict) -> list[str]:
    """Flat list of every schema path named anywhere in cause['required_evidence'].

    any_of members are included. Used to know which fields to strip when
    building an abstention example, and to seed data_gaps.
    """
    paths: list[str] = []

    def walk(entry: dict) -> None:
        if "any_of" in entry:
            for m in entry["any_of"]:
                walk(m)
        elif "path" in entry:
            paths.append(entry["path"])

    for entry in cause.get("required_evidence", []):
        walk(entry)
    return paths
