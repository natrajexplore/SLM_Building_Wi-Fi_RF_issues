"""Healthy baselines + typed path read/write + predicate satisfaction.

`scenarios.py` composes these into full training snapshots. The contract this
module upholds: after `satisfy(snapshot, predicate)` returns, `predicates.check`
for that predicate is True, and the snapshot is still shaped like the canonical
schema (final jsonschema validation happens in `generate.py`).
"""
from __future__ import annotations

import random
from typing import Any

from data.predicates import check, parse_path, select
from data.taxonomy_loader import resolve_threshold

# Fields the schema types as integer — margins must stay whole numbers.
_INTEGER_PATHS = {
    "rf_metrics.co_channel_neighbors",
    "rf_metrics.adjacent_channel_neighbors",
    "clients.count",
    "clients.legacy_client_count",
    "clients.sticky_clients",
    "clients.auth_failures_5m",
    "clients.assoc_failures_5m",
    "clients.roam_failures_5m",
}

# Percentage fields — clamp to [0, 100].
_PCT_PATHS = {
    "rf_metrics.channel_utilization_pct",
    "rf_metrics.rx_utilization_pct",
    "rf_metrics.tx_utilization_pct",
    "rf_metrics.interference_pct",
    "rf_metrics.retry_rate_pct",
    "rf_metrics.crc_error_rate_pct",
    "rf_metrics.airtime_efficiency_pct",
}

_CHANNEL_WIDTHS = [20, 40, 80, 160, 320]

_DEFAULT_CHANNEL = {"2.4GHz": 6, "5GHz": 36, "6GHz": 37}
_DEFAULT_WIDTH = {"2.4GHz": 20, "5GHz": 80, "6GHz": 80}

# Plausible values for `present` / `!=` satisfaction, keyed by full path.
_PLAUSIBLE: dict[str, Any] = {
    "radio.tx_power_dbm": 14.0,
    "radio.tx_power_max_dbm": 23.0,
    "radio.regulatory_domain": "GB",
    "radio.dfs_required": True,
    "site.ap_group": "ap-group-east",
    "site.site_id": "site-042",
    "capabilities.band_steering": True,
    "capabilities.dot11r": False,
    "capabilities.dot11k": True,
    "capabilities.dot11v": True,
    "capabilities.rnr_advertised": True,
    "capabilities.min_data_rate_mbps": 12.0,
    "analysis_context.reported_symptom": (
        "Users in the affected area report Wi-Fi 'not working' during busy hours."
    ),
    "clients.avg_roam_time_ms": 60.0,
    "clients.band_distribution": {"2.4GHz": 20.0, "5GHz": 65.0, "6GHz": 15.0},
}

# Realistic snap targets for a few `<=` / legacy cases where an arbitrary
# margin would look wrong (802.11b basic rates are 1/2/5.5/11).
_LEGACY_BASIC_RATES = [1.0, 2.0, 5.5, 11.0]


def healthy_baseline(band: str, rng: random.Random) -> dict:
    """A schema-valid snapshot with nominal RF for `band` and no problem present."""
    wpa3 = band == "6GHz"
    snap: dict[str, Any] = {
        "snapshot_id": f"syn-{rng.randrange(16**8):08x}",
        "timestamp": "2026-03-01T12:00:00Z",
        "site": {
            "site_id": "site-042",
            "environment": rng.choice(
                ["office", "education", "healthcare", "retail", "warehouse"]
            ),
        },
        "radio": {
            "band": band,
            "channel": _DEFAULT_CHANNEL[band],
            "channel_width_mhz": _DEFAULT_WIDTH[band],
            "tx_power_dbm": 12.0,
            "tx_power_max_dbm": 23.0,
            "admin_state": "enabled",
        },
        "rf_metrics": {
            "noise_floor_dbm": -92.0,
            "channel_utilization_pct": 16.0,
            "rx_utilization_pct": 9.0,
            "tx_utilization_pct": 7.0,
            "interference_pct": 3.0,
            "co_channel_neighbors": 1,
            "adjacent_channel_neighbors": 0,
            "strongest_neighbor_rssi_dbm": -82.0,
            "retry_rate_pct": 7.0,
            "crc_error_rate_pct": 1.0,
            "airtime_efficiency_pct": 82.0,
        },
        "clients": {
            "count": 14,
            "avg_snr_db": 33.0,
            "min_snr_db": 24.0,
            "avg_rssi_dbm": -58.0,
            "sticky_clients": 0,
            "legacy_client_count": 0,
            "auth_failures_5m": 0,
            "assoc_failures_5m": 0,
            "roam_failures_5m": 0,
            "avg_roam_time_ms": 55.0,
        },
        "capabilities": {
            "dot11k": True,
            "dot11v": True,
            "dot11r": True,
            "wpa3_enforced": wpa3,
            "band_steering": True,
            "min_data_rate_mbps": 12.0,
        },
        "analysis_context": {
            "observation_window_minutes": 60.0,
            "spectrum_capable": False,
            "neighbor_scan_available": True,
            "client_detail_available": False,
        },
    }
    if band == "6GHz":
        snap["radio"]["power_mode"] = "SP"
        snap["capabilities"]["afc_status"] = "granted"
        snap["capabilities"]["rnr_advertised"] = True
        snap["clients"]["band_distribution"] = {"5GHz": 55.0, "6GHz": 45.0}
    return snap


# ---------------------------------------------------------------------------
# Typed path write / delete
# ---------------------------------------------------------------------------


def _required_siblings(array_name: str, element: dict) -> None:
    """Fill schema-`required` sibling fields on a freshly created array element."""
    if array_name == "events":
        element.setdefault("timestamp", "2026-03-01T12:03:00Z")
        element.setdefault("type", "channel_change")
    elif array_name == "non_wifi_interferers":
        element.setdefault("type", "unknown")


def set_path(snapshot: dict, path: str, value: Any) -> None:
    """Write `value` at `path`, creating intermediate objects as needed.

    `events[].type` appends a new element carrying `type=value` plus its
    required siblings; `clients.band_distribution["6GHz"]` sets a map key.
    """
    _set(snapshot, parse_path(path), value, root_name=None)


def _set(node: dict, segments: list[tuple[str, str | None]], value: Any, root_name):
    (name, marker), rest = segments[0], segments[1:]

    if marker == "array":
        if not rest:
            node[name] = value
            return
        element: dict = {}
        _set(element, rest, value, root_name=name)
        _required_siblings(name, element)
        node.setdefault(name, []).append(element)
        return

    if marker is not None:  # ["literal"] key
        target = node.setdefault(name, {})
        if not rest:
            target[marker] = value
            return
        _set(target.setdefault(marker, {}), rest, value, root_name=name)
        return

    if not rest:
        node[name] = value
        return
    _set(node.setdefault(name, {}), rest, value, root_name=name)


def delete_path(snapshot: dict, path: str) -> None:
    """Remove whatever `path` points at. Wildcard/array paths drop the array."""
    segments = parse_path(path)
    node: Any = snapshot
    for name, marker in segments[:-1]:
        if not isinstance(node, dict) or name not in node:
            return
        if marker == "array":
            node.pop(name, None)  # a wildcard mid-path: clearing the array suffices
            return
        node = node[name] if marker is None else node[name].get(marker)
        if node is None:
            return
    name, marker = segments[-1]
    if not isinstance(node, dict):
        return
    if marker is not None and marker != "array":
        node.get(name, {}).pop(marker, None)
    else:
        node.pop(name, None)


# ---------------------------------------------------------------------------
# Predicate satisfaction
# ---------------------------------------------------------------------------


def _is_bounded_pct(path: str) -> bool:
    leaf = path.split(".")[-1]
    return leaf.endswith("_pct") or "distribution" in path or path in _PCT_PATHS


def _abnormal_number(op: str, target: float, path: str, rng: random.Random) -> float:
    """A value on the clearly-abnormal side of `target` for comparison `op`."""
    integer = path in _INTEGER_PATHS
    span = rng.choice([2, 3, 4]) if integer else rng.choice([2.0, 4.0, 6.0])
    # Don't overshoot a boundary: a `<= 5` target with a margin of 6 must not
    # produce a negative percentage.
    if op in ("<", "<="):
        span = min(span, max(1.0, target / 2))
        val = target - span
    elif op in (">", ">="):
        val = target + span
    else:
        val = target
    if _is_bounded_pct(path):
        val = max(0.0, min(100.0, val))
    if integer:
        val = max(0, int(round(val)))  # every integer field in the schema is a count >= 0
    return val


def satisfy(snapshot: dict, predicate: dict, rng: random.Random) -> None:
    """Mutate `snapshot` in place so `predicates.check(snapshot, predicate)` is True."""
    if "any_of" in predicate:
        satisfy(snapshot, rng.choice(predicate["any_of"]), rng)
        return

    path, op = predicate["path"], predicate["predicate"]

    if op == "present":
        if check(snapshot, predicate):
            return
        set_path(snapshot, path, _plausible_for(path, rng))
        return

    if op == "absent":
        delete_path(snapshot, path)
        return

    target = predicate["value"] if "value" in predicate else resolve_threshold(
        predicate["threshold"]
    )

    if op == "==":
        set_path(snapshot, path, target)
        return
    if op == "!=":
        set_path(snapshot, path, _something_other_than(path, target, rng))
        return

    # >, >=, <, <=
    if path == "radio.channel_width_mhz":
        options = [w for w in _CHANNEL_WIDTHS if _COMPARE[op](w, target)]
        set_path(snapshot, path, rng.choice(options))
        return
    if path == "capabilities.min_data_rate_mbps" and op in ("<=", "<"):
        options = [r for r in _LEGACY_BASIC_RATES if _COMPARE[op](r, target)]
        set_path(snapshot, path, rng.choice(options) if options else 1.0)
        return
    set_path(snapshot, path, _abnormal_number(op, float(target), path, rng))


_COMPARE = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}

_INVERSE_OP = {">=": "<", ">": "<=", "<": ">=", "<=": ">", "==": "!=", "!=": "=="}

# The only required_evidence paths the schema marks `required` — for these,
# abstention resets to a normal reading instead of deleting (a delete would be
# schema-invalid).
_SCHEMA_REQUIRED = {"radio.channel_width_mhz", "radio.band", "radio.channel"}


def violate(snapshot: dict, predicate: dict, rng: random.Random) -> None:
    """Mutate `snapshot` so `predicates.check(snapshot, predicate)` becomes False.

    Used to build abstention examples: take a positive snapshot and knock the
    evidence back out — a normal reading, a missing optional field, or a
    removed event array — without leaving the snapshot schema-invalid.
    """
    if "any_of" in predicate:
        for member in predicate["any_of"]:
            violate(snapshot, member, rng)
        return

    path, op = predicate["path"], predicate["predicate"]
    segments = parse_path(path)
    wildcard = any(marker == "array" for _, marker in segments)

    if wildcard:
        delete_path(snapshot, path)  # drops the whole array — evidence gone
        return
    if op in ("present", "==", "!="):
        # Nothing to "read normally" for these — just remove the field. Every
        # such path in the taxonomy is schema-optional, so this stays valid.
        delete_path(snapshot, path)
        return
    if op == "absent":
        set_path(snapshot, path, _plausible_for(path, rng))
        return

    if path not in _SCHEMA_REQUIRED:
        delete_path(snapshot, path)
        return

    flipped = dict(predicate)
    flipped["predicate"] = _INVERSE_OP[op]
    satisfy(snapshot, flipped, rng)
    if check(snapshot, predicate):  # boundary case — flip didn't take
        delete_path(snapshot, path)


def _plausible_for(path: str, rng: random.Random) -> Any:
    if path in _PLAUSIBLE:
        return _PLAUSIBLE[path]
    leaf = path.split(".")[-1].rstrip("[]")
    if leaf.endswith("_pct"):
        return 12.0
    if leaf.endswith(("_count", "_5m")) or leaf in {"count", "co_channel_neighbors"}:
        return rng.randrange(1, 6)
    if leaf.endswith(("_db", "_dbm", "_ms", "_mbps", "_mhz")):
        return 10.0
    if leaf.startswith(("is_", "has_", "dot11", "afc_", "wpa3", "owe_")):
        return True
    return "present"


def _something_other_than(path: str, value: Any, rng: random.Random) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    return f"not-{value}"
