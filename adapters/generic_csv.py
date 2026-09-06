"""Universal fallback adapter: a flat CSV / row source -> canonical snapshot.

This is the adapter of last resort. It knows nothing about any vendor; the
caller supplies a mapping that says which column feeds which canonical field.
One CSV row becomes one snapshot.

    mapping = CsvMapping.from_yaml("my_export.map.yaml")
    for snapshot in snapshots_from_csv("export.csv", mapping):
        ...

What it deliberately does NOT do:

  - Array-typed canonical fields (`events`, `neighbors`, `client_samples`,
    `non_wifi_interferers`). A flat row cannot express a repeated group, and
    guessing at row-grouping is exactly the kind of best-effort behaviour the
    canonical boundary exists to stop. Sources with that data need
    `generic_json` or a real vendor adapter. A mapping that points at an
    array path raises at construction time, not silently mid-run.
  - Infer `analysis_context.spectrum_capable`. A generic CSV gives no way to
    know whether the platform does spectrum analysis, so the mapping MUST
    state it. `Adapter.to_canonical` enforces its presence regardless; this
    just makes the requirement explicit and up front.
  - Fabricate `snapshot_id` / `timestamp`. Both are schema-required. Map them
    from real columns, or set them in `constants`. A missing timestamp fails
    schema validation with a clear message rather than being invented.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

from adapters._common import (
    DEFAULT_BOOL_FALSE,
    DEFAULT_BOOL_TRUE,
    DEFAULT_NULL_TOKENS,
    MappingError,
    coerce_scalar,
    scalar_leaf_types,
)
from adapters.base import Adapter, ContractViolation

_ARRAY_ROOTS = {"events", "neighbors", "client_samples", "non_wifi_interferers"}


class CsvMappingError(MappingError):
    """The CSV mapping is wrong (bad target path, array target, missing flag)."""


@dataclass(frozen=True)
class ColumnMap:
    column: str
    path: str
    #: Override the coercion the schema would otherwise pick: int|float|bool|str.
    coerce: str | None = None


@dataclass
class CsvMapping:
    """How to turn one row into a canonical snapshot."""

    columns: list[ColumnMap]
    spectrum_capable: bool
    constants: dict[str, Any] = field(default_factory=dict)
    null_tokens: set[str] = field(default_factory=lambda: set(DEFAULT_NULL_TOKENS))
    bool_true: set[str] = field(default_factory=lambda: set(DEFAULT_BOOL_TRUE))
    bool_false: set[str] = field(default_factory=lambda: set(DEFAULT_BOOL_FALSE))

    def __post_init__(self) -> None:
        if not isinstance(self.spectrum_capable, bool):
            raise CsvMappingError("mapping.spectrum_capable must be a bool")
        seen: set[str] = set()
        for cm in self.columns:
            _reject_array_path(cm.path)
            if cm.path in seen:
                raise CsvMappingError(f"two columns both map to {cm.path!r}")
            seen.add(cm.path)
            if cm.coerce not in (None, "int", "float", "bool", "str"):
                raise CsvMappingError(f"unknown coerce {cm.coerce!r} for {cm.column!r}")
        for path in self.constants:
            _reject_array_path(path)

    @classmethod
    def from_dict(cls, doc: dict) -> "CsvMapping":
        cols = [
            ColumnMap(column=c["column"], path=c["path"], coerce=c.get("coerce"))
            for c in doc.get("columns", [])
        ]
        kwargs: dict[str, Any] = {
            "columns": cols,
            "spectrum_capable": doc["spectrum_capable"],
            "constants": dict(doc.get("constants", {})),
        }
        for key in ("null_tokens", "bool_true", "bool_false"):
            if key in doc:
                kwargs[key] = {str(x).lower() for x in doc[key]}
        return cls(**kwargs)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CsvMapping":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))


def _reject_array_path(path: str) -> None:
    root = path.split(".", 1)[0].rstrip("[]")
    if root in _ARRAY_ROOTS or "[]" in path:
        raise CsvMappingError(
            f"{path!r} targets an array-typed field; the generic CSV adapter "
            "handles scalar fields only (see module docstring)"
        )


class GenericCsvAdapter(Adapter):
    name = "generic_csv"

    def __init__(self, mapping: CsvMapping) -> None:
        self.mapping = mapping
        known = scalar_leaf_types()
        unknown = [
            cm.path for cm in mapping.columns if cm.path not in known
        ] + [p for p in mapping.constants if p not in known]
        # analysis_context.spectrum_capable is set by us, not mapped; everything
        # else must be a real scalar leaf so typos fail loudly here.
        unknown = [p for p in unknown if p != "analysis_context.spectrum_capable"]
        if unknown:
            raise CsvMappingError(
                "mapping targets that are not scalar canonical fields: "
                + ", ".join(sorted(unknown))
            )

    def _translate(self, raw: Any) -> dict:
        if not isinstance(raw, dict):
            raise ContractViolation(
                f"{self.name}._translate expects one CSV row as a dict "
                f"(csv.DictReader), got {type(raw).__name__}"
            )
        snapshot: dict[str, Any] = {}

        for path, value in self.mapping.constants.items():
            _assign(snapshot, path, value)

        for cm in self.mapping.columns:
            if cm.column not in raw:
                raise ContractViolation(
                    f"{self.name}: mapped column {cm.column!r} is absent from the row "
                    f"(row has: {', '.join(sorted(raw))})"
                )
            cell = raw[cm.column]
            if cell is None or str(cell).strip().lower() in self.mapping.null_tokens:
                continue  # unpopulated -> becomes an analysis_context.missing_fields entry
            _assign(snapshot, cm.path, self._coerce(cm, str(cell).strip()))

        snapshot.setdefault("analysis_context", {})["spectrum_capable"] = self.mapping.spectrum_capable
        return snapshot

    _COERCE_ALIAS = {"int": "integer", "float": "number", "bool": "boolean", "str": "string"}

    def _coerce(self, cm: ColumnMap, text: str) -> Any:
        kind = self._COERCE_ALIAS.get(cm.coerce) if cm.coerce else scalar_leaf_types().get(cm.path)
        try:
            return coerce_scalar(
                text, kind, bool_true=self.mapping.bool_true, bool_false=self.mapping.bool_false
            )
        except ValueError as exc:
            raise ContractViolation(
                f"{self.name}: column {cm.column!r} -> {cm.path!r}: {exc}"
            ) from None


def _assign(snapshot: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    node = snapshot
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def snapshots_from_csv(source: str | Path | io.TextIOBase, mapping: CsvMapping) -> Iterator[dict]:
    """Yield one canonical snapshot per row of `source` (a path or open text file)."""
    adapter = GenericCsvAdapter(mapping)
    if isinstance(source, (str, Path)):
        with open(source, newline="", encoding="utf-8") as f:
            yield from (adapter.to_canonical(row) for row in csv.DictReader(f))
    else:
        yield from (adapter.to_canonical(row) for row in csv.DictReader(source))
