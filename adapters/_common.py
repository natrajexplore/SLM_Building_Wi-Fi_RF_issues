"""Internals shared by the two generic adapters (`generic_csv`, `generic_json`).

Schema introspection (the JSON-schema `type` of a canonical field, so a loose
string can be coerced to it), value coercion, the loose-token defaults, and the
common mapping-error class. One place, so the two adapters cannot drift.
"""
from __future__ import annotations

from functools import lru_cache

from adapters.normalize import load_schema

_SCALAR_TYPES = {"string", "integer", "number", "boolean"}

DEFAULT_NULL_TOKENS = {"", "n/a", "na", "null", "none", "-", "--", "unknown"}
DEFAULT_BOOL_TRUE = {"true", "t", "yes", "y", "1", "enabled", "on"}
DEFAULT_BOOL_FALSE = {"false", "f", "no", "n", "0", "disabled", "off"}


class MappingError(RuntimeError):
    """The adapter's column/field mapping is itself wrong (bad target, bad flag)."""


@lru_cache(maxsize=1)
def scalar_leaf_types() -> dict[str, str]:
    """`a.b.c` -> schema type, for every scalar leaf inside a fixed object.

    Does not descend into arrays or map-typed (`additionalProperties`-only)
    objects — those have no fixed sub-paths.
    """
    out: dict[str, str] = {}

    def walk(node: dict, prefix: str) -> None:
        for name, sub in node.get("properties", {}).items():
            path = f"{prefix}.{name}" if prefix else name
            if sub.get("type") == "object" and "properties" in sub:
                walk(sub, path)
            elif sub.get("type") in _SCALAR_TYPES:
                out[path] = sub["type"]

    walk(load_schema(), "")
    return out


@lru_cache(maxsize=1)
def array_element_types() -> dict[str, dict[str, str]]:
    """`{array_field: {element_scalar_field: schema type}}`.

    Only top-level array properties whose items are objects (events, neighbors,
    client_samples, non_wifi_interferers).
    """
    out: dict[str, dict[str, str]] = {}
    for name, sub in load_schema().get("properties", {}).items():
        if sub.get("type") != "array":
            continue
        items = sub.get("items", {})
        if items.get("type") != "object":
            continue
        fields = {
            fname: fsub["type"]
            for fname, fsub in items.get("properties", {}).items()
            if fsub.get("type") in _SCALAR_TYPES
        }
        if fields:
            out[name] = fields
    return out


def coerce_scalar(value, schema_type: str | None, *, bool_true: set[str], bool_false: set[str]):
    """Coerce a loose value (usually a string) to `schema_type`.

    Raises ValueError on a value that cannot be coerced — callers turn that
    into their own contract error with column/field context.
    """
    if schema_type in ("integer",):
        return int(round(float(value)))
    if schema_type in ("number",):
        return float(value)
    if schema_type in ("boolean",):
        if isinstance(value, bool):
            return value
        low = str(value).strip().lower()
        if low in bool_true:
            return True
        if low in bool_false:
            return False
        raise ValueError(f"{value!r} is not a recognised boolean")
    return str(value).strip() if not isinstance(value, str) else value.strip()
