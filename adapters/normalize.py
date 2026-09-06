"""Shared validation, missing-fields, and pseudonymisation logic.

Every concrete adapter goes through adapters/base.py's Adapter.to_canonical,
which calls the functions in this module. Adapters should never reimplement
schema validation, missing-fields computation, or identifier pseudonymisation
themselves -- that is exactly the kind of per-adapter drift this module
exists to prevent.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "canonical_rf.schema.json"

# source.* is provenance only (see the schema's own description for that
# property) and is stripped before the model ever sees a snapshot, so its
# completeness is not something the model needs surfaced via missing_fields.
_EXCLUDED_TOP_LEVEL = {"source"}

# Array-typed canonical fields are tracked as a single leaf path (the array
# key itself), not walked item-by-item. An empty array is meaningful data --
# "no radar events occurred", "no non-Wi-Fi interference detected" -- not a
# missing field, and that distinction is already carried by
# analysis_context's spectrum_capable / neighbor_scan_available /
# client_detail_available flags. Listing "events[].type" as "missing"
# whenever no matching event happened would make missing_fields noisy to the
# point of being useless.
_ARRAY_FIELDS = {"non_wifi_interferers", "client_samples", "events", "neighbors"}


class SchemaValidationError(RuntimeError):
    """A snapshot failed validation against the canonical schema.

    Adapters must let this propagate -- never catch it and coerce or drop
    the record silently. The whole point of the canonical schema is that
    the SLM never sees anything that didn't pass it.
    """


class PseudonymisationError(RuntimeError):
    """A raw MAC-formatted identifier survived pseudonymisation.

    This indicates an adapter bug (an identifier reached the output through
    a path pseudonymise_identifiers() doesn't scrub, or bypassed it
    entirely), not a data-quality issue in the source. It must never be
    caught and ignored.
    """


# ---------------------------------------------------------------------------
# Schema loading & validation
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _validator() -> jsonschema.protocols.Validator:
    schema = load_schema()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    # Without an explicit FormatChecker, jsonschema never enforces "format"
    # keywords (format is advisory-only per spec unless a checker is wired
    # in) -- so timestamp / events[].timestamp's "format": "date-time" would
    # silently accept garbage strings. "date-time" specifically also needs
    # the rfc3339-validator package registered (see requirements.txt); it is
    # NOT present in jsonschema.FormatChecker() out of the box.
    return validator_cls(schema, format_checker=jsonschema.FormatChecker())


def validate_canonical(snapshot: dict) -> None:
    """Validate `snapshot` against schema/canonical_rf.schema.json.

    Collects every violation (not just the first) so a failure is
    actionable in one pass. Raises SchemaValidationError on any violation;
    returns None (no truthy/falsy verdict to accidentally ignore) on success.
    """
    errors = sorted(_validator().iter_errors(snapshot), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    details = "\n".join(
        f"  - {'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors
    )
    raise SchemaValidationError(
        f"Snapshot failed canonical schema validation "
        f"({len(errors)} error{'s' if len(errors) != 1 else ''}):\n{details}"
    )


# ---------------------------------------------------------------------------
# Missing-fields computation
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def canonical_field_paths() -> tuple[str, ...]:
    """Every dot-notation field path the canonical schema defines, used as
    the universe for missing_fields.

    Walks object properties recursively. Array-typed properties are recorded
    as a single path (their own key), not walked item-by-item -- see
    _ARRAY_FIELDS above for why. `source.*` is excluded entirely, and
    `analysis_context.missing_fields` is excluded from itself.
    """
    schema = load_schema()
    paths: list[str] = []

    def walk(node: dict, prefix: str) -> None:
        for name, sub in node.get("properties", {}).items():
            if not prefix and name in _EXCLUDED_TOP_LEVEL:
                continue
            path = f"{prefix}.{name}" if prefix else name
            if path == "analysis_context.missing_fields":
                continue
            # Recurse only into objects with a fixed, named `properties` set.
            # A map-typed object (additionalProperties, no `properties` --
            # e.g. clients.phy_rate_distribution, clients.band_distribution)
            # has no fixed sub-paths to walk into and must be tracked as a
            # leaf, same as an array; otherwise it silently vanishes from
            # the path set instead of being tracked at all.
            #
            # `name not in _ARRAY_FIELDS` is redundant today: every current
            # member of _ARRAY_FIELDS has schema type "array", so
            # `sub.get("type") == "object"` already excludes it before this
            # clause is even reached. It is kept as defense-in-depth for a
            # schema revision that ever models one of those fields as an
            # object with `properties` while it is still logically a
            # collection -- see test_array_fields_tracked_whole_not_walked_into.
            if sub.get("type") == "object" and "properties" in sub and name not in _ARRAY_FIELDS:
                walk(sub, path)
            else:
                paths.append(path)

    walk(schema, "")
    return tuple(paths)


def _get_by_path(snapshot: dict, path: str) -> Any:
    node: Any = snapshot
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def compute_missing_fields(snapshot: dict) -> list[str]:
    """Canonical field paths absent from `snapshot`.

    A field is "missing" when its key is not present in the snapshot at all
    -- omit it, do not set it to `None`/null. The canonical schema does not
    permit null for any typed field, so a field explicitly set to null will
    make validate_canonical() reject the whole snapshot later in the same
    to_canonical() pipeline, even though it is correctly reported here.
    (`_get_by_path` treats a null value the same as an absent key only so
    that mistake surfaces as an accurate missing_fields entry rather than a
    KeyError -- it is not an invitation to use null on purpose.)

    This is a mechanical presence check against the schema's full field set,
    not a judgement about the source platform's actual capability. An
    adapter must only leave a field unpopulated when its source genuinely
    cannot supply it -- never out of laziness -- because this list is
    exactly what the model relies on to decide whether an absence is
    meaningful evidence or just an ungathered field. Enforcing that
    intent is on the adapter author; this function only computes the diff.
    """
    return [p for p in canonical_field_paths() if _get_by_path(snapshot, p) is None]


# ---------------------------------------------------------------------------
# Pseudonymisation
# ---------------------------------------------------------------------------

# A real deployment must set this so pseudonyms aren't reproducible by anyone
# who doesn't hold the salt. The fallback keeps local development and tests
# working without configuration, but is deliberately not something you'd
# want to rely on for anything that leaves this machine.
_PSEUDONYM_SALT = os.environ.get(
    "RF_SLM_PSEUDONYM_SALT",
    "rf-slm-dev-salt-set-RF_SLM_PSEUDONYM_SALT-for-anything-real",
)

# Not anchored: a MAC embedded in free text (an `events[].detail` string, a
# `vendor_hint`, a capability entry) must still be caught by the defensive
# scan below -- that is the whole point of scanning every string rather than
# just the two known identifier fields. The alternation covers both the
# colon/hyphen octet form and Cisco's three-group dotted form (aabb.ccdd.eeff),
# which IOS-XE / pyATS emit natively. The hex-boundary lookarounds keep it from
# matching a fragment of a longer hex-and-colon run (e.g. an IPv6 address).
_MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f])"
    r"(?:[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}"
    r"|[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})"
    r"(?![0-9A-Fa-f])"
)


def looks_like_real_mac(value: str) -> bool:
    """True if `value` contains something shaped like an unpseudonymised MAC.

    Substring match, not whole-string: an identifier buried in an otherwise
    free-text field still counts.
    """
    return isinstance(value, str) and bool(_MAC_RE.search(value))


def _canonical_mac(real_id: str) -> str:
    """Fold textual variants of one MAC to a single form before hashing.

    `AA:BB:CC:DD:EE:FF`, `aa-bb-cc-dd-ee-ff` and Cisco's `aabb.ccdd.eeff` are
    the same physical identifier; hashing them verbatim would produce three
    different pseudonyms and silently break the cross-snapshot correlation
    that pseudonymise() promises. Anything that is not 12 hex digits once
    separators are stripped is returned unchanged.
    """
    stripped = re.sub(r"[:.\-]", "", real_id)
    if len(stripped) == 12:
        try:
            int(stripped, 16)
        except ValueError:
            return real_id
        return stripped.lower()
    return real_id


def pseudonymise(real_id: str, *, prefix: str) -> str:
    """Deterministic, non-reversible pseudonym for one client or BSS identifier.

    Keyed with HMAC-SHA256 under a salt so the real value cannot be recovered
    from the output, while the same real_id still maps to the same pseudonym
    within one salt -- repeat sightings of a client or BSS correlate across
    snapshots without ever carrying the original identifier. The identifier is
    canonicalised first (see _canonical_mac) so the same MAC in different
    textual forms correlates rather than fragmenting into distinct pseudonyms.
    """
    digest = hmac.new(
        _PSEUDONYM_SALT.encode("utf-8"),
        _canonical_mac(real_id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _iter_strings(node: Any) -> Iterable[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _iter_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_strings(v)


def _assert_no_raw_macs(snapshot: dict) -> None:
    """Defense in depth: scan the whole snapshot, not just the two known
    identifier fields, for anything MAC-shaped. Client and BSS identifiers
    are the fields this module knows to pseudonymise; a MAC surfacing
    anywhere else (a vendor free-text `detail` field, a `vendor_hint`, a
    capability string) would otherwise pass through undetected.
    """
    for value in _iter_strings(snapshot):
        if looks_like_real_mac(value):
            raise PseudonymisationError(
                "A raw MAC-formatted identifier survived pseudonymisation: "
                f"{value!r}. This means an identifier reached the output "
                "through a path pseudonymise_identifiers() does not scrub, "
                "or bypassed it entirely -- fix the adapter, do not catch "
                "this error."
            )


def pseudonymise_identifiers(snapshot: dict) -> dict:
    """Return a copy of `snapshot` with every client and BSS identifier
    replaced by a pseudonym.

    Covers exactly the fields the canonical schema documents as identifiers:
    client_samples[].client_ref and neighbors[].bss_ref. Then defensively
    scans the entire result for anything MAC-shaped that slipped through
    some other path, and raises rather than letting it through.
    """
    snapshot = copy.deepcopy(snapshot)

    for sample in snapshot.get("client_samples") or []:
        ref = sample.get("client_ref")
        if ref:
            sample["client_ref"] = pseudonymise(str(ref), prefix="cli")

    for neighbor in snapshot.get("neighbors") or []:
        ref = neighbor.get("bss_ref")
        if ref:
            neighbor["bss_ref"] = pseudonymise(str(ref), prefix="bss")

    _assert_no_raw_macs(snapshot)
    return snapshot
