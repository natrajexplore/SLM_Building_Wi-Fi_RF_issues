"""Nested-JSON fallback adapter: an arbitrary JSON object -> canonical snapshot.

Where `generic_csv` handles flat rows and scalar fields only, this handles a
nested vendor JSON document and can populate the array-typed canonical fields
(`events`, `neighbors`, `client_samples`, `non_wifi_interferers`).

    mapping = JsonMapping.from_yaml("vendor_export.map.yaml")
    snapshot = GenericJsonAdapter(mapping).to_canonical(vendor_doc)

Mapping shape:

    spectrum_capable: true            # REQUIRED — see generic_csv for why
    constants:                        # canonical path -> literal
      radio.band: "5GHz"
    scalars:
      - { from: "radio.primaryChannel", to: "radio.channel" }
      - { from: "metrics.noiseDbm",     to: "rf_metrics.noise_floor_dbm" }
    arrays:
      - from: "spectrumEvents"         # source array (dotted path into the doc)
        to: "events"                   # canonical array field
        element:
          - { from: "eventType", to: "type" }
          - { from: "occurredAt", to: "timestamp" }

`from` paths use dots for object traversal. A source path that is missing, or an
array `from` that is not a list, is skipped (it becomes a missing_fields entry
or an absent array) rather than raising — same tolerance as the CSV adapter's
null handling. A *mapping* that names an unknown canonical target still raises
at construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from adapters._common import (
    DEFAULT_BOOL_FALSE,
    DEFAULT_BOOL_TRUE,
    DEFAULT_NULL_TOKENS,
    MappingError,
    array_element_types,
    coerce_scalar,
    scalar_leaf_types,
)
from adapters.base import Adapter, ContractViolation


class JsonMappingError(MappingError):
    """The JSON mapping is wrong (unknown target field, bad array target)."""


@dataclass(frozen=True)
class FieldMap:
    src: str
    dst: str


@dataclass(frozen=True)
class ArrayMap:
    src: str
    dst: str
    element: tuple[FieldMap, ...]


@dataclass
class JsonMapping:
    spectrum_capable: bool
    scalars: list[FieldMap] = field(default_factory=list)
    arrays: list[ArrayMap] = field(default_factory=list)
    constants: dict[str, Any] = field(default_factory=dict)
    null_tokens: set[str] = field(default_factory=lambda: set(DEFAULT_NULL_TOKENS))
    bool_true: set[str] = field(default_factory=lambda: set(DEFAULT_BOOL_TRUE))
    bool_false: set[str] = field(default_factory=lambda: set(DEFAULT_BOOL_FALSE))

    def __post_init__(self) -> None:
        if not isinstance(self.spectrum_capable, bool):
            raise JsonMappingError("mapping.spectrum_capable must be a bool")

        scalar_types = scalar_leaf_types()
        array_types = array_element_types()

        seen: set[str] = set()
        for fm in self.scalars:
            if fm.dst not in scalar_types:
                raise JsonMappingError(f"scalar target {fm.dst!r} is not a canonical scalar field")
            if fm.dst in seen:
                raise JsonMappingError(f"two scalar maps both target {fm.dst!r}")
            seen.add(fm.dst)
        for path in self.constants:
            if path not in scalar_types:
                raise JsonMappingError(f"constant target {path!r} is not a canonical scalar field")
        for am in self.arrays:
            if am.dst not in array_types:
                raise JsonMappingError(
                    f"array target {am.dst!r} is not a canonical array field "
                    f"({', '.join(sorted(array_types))})"
                )
            allowed = array_types[am.dst]
            for fm in am.element:
                if fm.dst not in allowed:
                    raise JsonMappingError(
                        f"{am.dst}[].{fm.dst} is not a field of that array's elements"
                    )

    @classmethod
    def from_dict(cls, doc: dict) -> "JsonMapping":
        kwargs: dict[str, Any] = {
            "spectrum_capable": doc["spectrum_capable"],
            "scalars": [FieldMap(s["from"], s["to"]) for s in doc.get("scalars", [])],
            "arrays": [
                ArrayMap(
                    a["from"], a["to"],
                    tuple(FieldMap(e["from"], e["to"]) for e in a.get("element", [])),
                )
                for a in doc.get("arrays", [])
            ],
            "constants": dict(doc.get("constants", {})),
        }
        for key in ("null_tokens", "bool_true", "bool_false"):
            if key in doc:
                kwargs[key] = {str(x).lower() for x in doc[key]}
        return cls(**kwargs)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "JsonMapping":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))


def _dig(doc: Any, dotted: str) -> Any:
    node = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class GenericJsonAdapter(Adapter):
    name = "generic_json"

    def __init__(self, mapping: JsonMapping) -> None:
        self.mapping = mapping
        self._scalar_types = scalar_leaf_types()
        self._array_types = array_element_types()

    def _translate(self, raw: Any) -> dict:
        if not isinstance(raw, dict):
            raise ContractViolation(
                f"{self.name}._translate expects a JSON object (dict), got {type(raw).__name__}"
            )
        snapshot: dict[str, Any] = {}

        for path, value in self.mapping.constants.items():
            _assign(snapshot, path, value)

        for fm in self.mapping.scalars:
            value = _dig(raw, fm.src)
            if self._is_null(value):
                continue
            _assign(snapshot, fm.dst, self._coerce(fm.dst, self._scalar_types.get(fm.dst), value, fm.src))

        for am in self.mapping.arrays:
            source = _dig(raw, am.src)
            if not isinstance(source, list) or not source:
                continue
            allowed = self._array_types[am.dst]
            elements: list[dict] = []
            for i, item in enumerate(source):
                if not isinstance(item, dict):
                    raise ContractViolation(
                        f"{self.name}: {am.src}[{i}] is {type(item).__name__}, expected an object"
                    )
                built: dict[str, Any] = {}
                for fm in am.element:
                    value = _dig(item, fm.src)
                    if self._is_null(value):
                        continue
                    built[fm.dst] = self._coerce(
                        f"{am.dst}[].{fm.dst}", allowed.get(fm.dst), value, f"{am.src}[{i}].{fm.src}"
                    )
                if built:
                    elements.append(built)
            if elements:
                snapshot[am.dst] = elements

        snapshot.setdefault("analysis_context", {})["spectrum_capable"] = self.mapping.spectrum_capable
        return snapshot

    def _is_null(self, value: Any) -> bool:
        return value is None or (
            isinstance(value, str) and value.strip().lower() in self.mapping.null_tokens
        )

    def _coerce(self, dst: str, schema_type: str | None, value: Any, src: str) -> Any:
        try:
            return coerce_scalar(
                value, schema_type,
                bool_true=self.mapping.bool_true, bool_false=self.mapping.bool_false,
            )
        except ValueError as exc:
            raise ContractViolation(f"{self.name}: {src} -> {dst}: {exc}") from None


def _assign(snapshot: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    node = snapshot
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
