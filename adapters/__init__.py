"""Vendor adapter layer.

Every data source is normalized into schema/canonical_rf.schema.json by an
adapter before it reaches the model. See adapters/base.py for the contract
every adapter must satisfy, and adapters/normalize.py for the shared
validation, missing-fields, and pseudonymisation logic they all reuse.

No concrete vendor adapters exist yet.
"""
