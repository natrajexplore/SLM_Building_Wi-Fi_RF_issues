"""The Adapter contract.

Every vendor integration is a subclass of Adapter. The SLM never receives
vendor-native telemetry directly: every source is normalized through an
adapter into schema/canonical_rf.schema.json before anything downstream
(training data generation, RAG, inference) sees it. Adding a vendor means
writing an adapter, never retraining.

No concrete vendor adapters exist yet -- see adapters/__init__.py.
"""
from __future__ import annotations

import abc
from typing import Any

from adapters.normalize import (
    compute_missing_fields,
    pseudonymise_identifiers,
    validate_canonical,
)


class ContractViolation(RuntimeError):
    """An adapter subclass violated the Adapter contract itself.

    Distinct from SchemaValidationError: this fires for things the JSON
    schema cannot express or enforce on its own -- e.g.
    analysis_context.spectrum_capable is an optional property with no
    schema-level "required" on it, so a merely-absent value passes schema
    validation. The contract needs it explicit regardless, so that check
    lives here rather than being (impossibly) delegated to the schema.
    """


class Adapter(abc.ABC):
    """Abstract base for all vendor adapters.

    Subclasses implement `_translate`, which does the vendor-specific field
    mapping only. `to_canonical` is the sole public entry point and wraps
    `_translate` with every invariant an adapter must uphold:

      1. analysis_context.missing_fields lists every canonical field this
         source could not supply (mechanically computed, then unioned with
         anything `_translate` already flagged itself).
      2. analysis_context.spectrum_capable is set -- never left absent.
      3. Client and BSS identifiers are pseudonymised; real MACs cannot
         leave this boundary.
      4. The result validates against the canonical schema before it is
         ever returned.

    None of the above is optional per-adapter. A subclass that wants to skip
    one has misunderstood the contract, not found a legitimate exception to
    it.
    """

    #: Human-readable adapter name, e.g. "cisco_c9800". Recorded in
    #: source.adapter for provenance. Subclasses must set this.
    name: str

    def to_canonical(self, raw: Any) -> dict:
        """Convert one vendor-native record into a canonical RF snapshot.

        Always returns a dict that validates against
        schema/canonical_rf.schema.json, or raises. Never returns a partial
        or best-effort snapshot -- a source that cannot be normalized is a
        hard failure, not degraded output.
        """
        if not getattr(self, "name", None):
            raise ContractViolation(
                f"{type(self).__name__} must set a class-level `name` "
                "(recorded in source.adapter for provenance)."
            )

        snapshot = self._translate(raw)
        if not isinstance(snapshot, dict):
            raise ContractViolation(
                f"{self.name}._translate must return a dict, got "
                f"{type(snapshot).__name__}."
            )

        source = snapshot.setdefault("source", {})
        source.setdefault("adapter", self.name)

        analysis_context = snapshot.setdefault("analysis_context", {})

        # Requirement 2 first: fail before doing any more work if the
        # adapter forgot this. An unset spectrum_capable is indistinguishable
        # from False downstream, and that distinction is load-bearing for
        # every non-Wi-Fi-interference diagnosis -- see
        # RF-24-003/RF-XB-003's discriminators in the taxonomy. The schema
        # cannot enforce this itself (spectrum_capable is an optional
        # property; absence alone would still validate), so it is enforced
        # here instead.
        if "spectrum_capable" not in analysis_context:
            raise ContractViolation(
                f"{self.name}: analysis_context.spectrum_capable must be "
                "set explicitly by _translate -- it cannot be inferred, "
                "defaulted, or left absent."
            )
        if not isinstance(analysis_context["spectrum_capable"], bool):
            raise ContractViolation(
                f"{self.name}: analysis_context.spectrum_capable must be a "
                f"bool, got {type(analysis_context['spectrum_capable']).__name__}."
            )

        # Requirement 1: union whatever the adapter already flagged (it may
        # know about source-specific gaps the mechanical diff can't infer)
        # with the mechanically-computed diff against the full canonical
        # field set.
        already_flagged = analysis_context.get("missing_fields", [])
        computed = compute_missing_fields(snapshot)
        analysis_context["missing_fields"] = sorted(set(already_flagged) | set(computed))

        # Requirement 3.
        snapshot = pseudonymise_identifiers(snapshot)

        # Requirement 4: fail loudly, do not catch and coerce.
        validate_canonical(snapshot)

        return snapshot

    @abc.abstractmethod
    def _translate(self, raw: Any) -> dict:
        """Vendor-specific field mapping into a canonical-shaped dict.

        Implementations must:
          - Set analysis_context.spectrum_capable explicitly (bool). Only
            the adapter knows whether its source platform offers spectrum
            analysis at all; to_canonical cannot infer this.
          - Leave a canonical field unpopulated ONLY when the source
            genuinely cannot supply it, never for convenience -- the
            resulting missing_fields list is exactly what the model uses to
            decide whether an absence is meaningful evidence.

        Implementations must NOT:
          - Populate analysis_context.missing_fields themselves unless they
            know of a gap the mechanical diff in to_canonical cannot infer
            (e.g. "this platform reports a field but we've observed it to be
            unreliable"). The mechanical computation runs regardless and is
            unioned with whatever is set here.
          - Pseudonymise client_ref / bss_ref themselves. to_canonical does
            this centrally, once, so the rule cannot be forgotten per-adapter
            or applied inconsistently.

        Raise on any input this adapter cannot make sense of. Returning a
        best-effort guess instead of raising is exactly the kind of thing
        the canonical-schema boundary exists to prevent.
        """
        raise NotImplementedError
