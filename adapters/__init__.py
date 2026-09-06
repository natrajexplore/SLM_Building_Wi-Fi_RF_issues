"""Vendor adapter layer.

Every data source is normalized into schema/canonical_rf.schema.json by an
adapter before it reaches the model. See adapters/base.py for the contract
every adapter must satisfy, and adapters/normalize.py for the shared
validation, missing-fields, and pseudonymisation logic they all reuse.

Concrete adapters:
  - generic_csv.GenericCsvAdapter — flat CSV row + column mapping -> snapshot.
    Scalar fields only.
  - generic_json.GenericJsonAdapter — nested vendor JSON + path mapping ->
    snapshot, including the array-typed fields (events, neighbors, …).
  - esp32.Esp32Adapter — `hardware/esp32_rf_probe` JSON -> snapshot. 2.4 GHz
    only, spectrum_capable always false; real source for the RF-24-* causes.

`adapters/_common.py` holds the schema introspection + coercion the generic
adapters share.

Still to build: cisco_c9800, aruba_central, mist.
"""
