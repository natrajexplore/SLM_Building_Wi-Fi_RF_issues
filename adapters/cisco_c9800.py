"""Cisco Catalyst 9800 WLC adapter: capture bundle -> canonical snapshot.

**Input shape.** A live C9800 exposes RF state through `show wireless ...`
CLI (parseable with pyATS/Genie), RESTCONF against the
`Cisco-IOS-XE-wireless-*-oper.yang` datastores, or streaming telemetry --
and the exact key names in any of those differ by IOS-XE release and
collection path. Hardcoding this adapter against one specific Genie parser
version or one YANG revision without a real capture to check it against
would be guessing, not normalizing -- exactly what CLAUDE.md's build order
flags this adapter as: a *validation source*, to be checked against real lab
captures in phase 9, not assumed correct on day one.

So `_translate` does not parse CLI or RESTCONF JSON itself. It consumes a
**capture bundle**: a single dict, one per AP/radio sample, in the shape
documented below. Producing that bundle from a real WLC -- via a thin
pyATS/Genie glue script, or a RESTCONF client -- is exactly the phase-9 task;
this adapter is what that glue script's output must satisfy, and it is
where any real-capture surprises (a differently-cased enum, a field that
turns out absent on some IOS-XE release) get fixed.

Bundle shape (`raw`):

    {
      "collected_at": "2026-03-01T12:00:00Z",   # REQUIRED, RFC3339
      "ap_name": "AP-3F-12",                    # -> radio.ap_id
      "snapshot_id": "...",                     # optional, else derived
      "site": {"site_id": ..., "environment": ..., "ap_group": ..., "floor": ...},
      "collection_method": "restconf",          # optional, source.collection_method
      "raw_ref": "...",                         # optional, source.raw_ref
      "reported_symptom": "...",                # optional, analysis_context
      "observation_window_minutes": 5,          # optional, analysis_context
      "radio": {                                # REQUIRED
        "slot_id": 1,                           # -> radio.radio_id (stringified)
        "band": "5GHz", "channel": 36, "channel_width_mhz": 80,
        "operating_class": 121, "tx_power_dbm": 17, "tx_power_max_dbm": 20,
        "power_mode": "n/a", "regulatory_domain": "US",
        "phy_modes": ["11ac", "11ax"], "dfs_required": true,
        "admin_state": "enabled",
        "clean_air_enabled": true,              # drives spectrum_capable -- see below
      },
      "rrm": {                                  # -> rf_metrics, all optional
        "noise_floor_dbm": -92, "channel_utilization_pct": 34,
        "rx_utilization_pct": ..., "tx_utilization_pct": ...,
        "interference_pct": 6, "co_channel_neighbors": 2,
        "adjacent_channel_neighbors": 1, "strongest_neighbor_rssi_dbm": -55,
        "retry_rate_pct": ..., "crc_error_rate_pct": ..., "airtime_efficiency_pct": ...,
      },
      "clients": {                              # -> clients (aggregate), optional
        "count": 18, "avg_snr_db": 28, ...,
        "phy_rate_distribution": {"11ax": 70, "11ac": 30},
        "band_distribution": {"5GHz": 100},
        "samples": [                            # -> client_samples, optional
          {"client_mac": "aa:bb:cc:...", "snr_db": 30, "rssi_dbm": -52,
           "phy_mode": "11ax", "tx_rate_mbps": 866, "retry_rate_pct": 4,
           "supported_bands": ["5GHz"], "capabilities": ["11k", "11v"]},
        ],
      },
      "wlan": {                                 # -> capabilities, optional
        "dot11k": true, "dot11v": true, "dot11r": false,
        "dot11w_pmf": "optional", "owe_enabled": false, "wpa3_enforced": true,
        "band_steering": true, "airtime_fairness": true,
        "afc_supported": false, "afc_status": "not_applicable",
        "psc_only_beaconing": false, "rnr_advertised": true,
        "fils_discovery": false, "min_data_rate_mbps": 12,
        "multicast_handling": "unicast_conversion", "bands_supported": ["5GHz"],
      },
      "neighbors": [                            # -> neighbors, optional
        {"bssid": "aa:bb:...", "channel": 40, "channel_width_mhz": 80,
         "rssi_dbm": -60, "same_ess": false, "vendor_hint": "cisco"},
      ],
      "spectrum": [                             # -> non_wifi_interferers
        {"type": "microwave_oven", "severity": 40, "duty_cycle_pct": 12,
         "center_freq_mhz": 2450, "bandwidth_mhz": 20},
      ],
      "events": [                               # -> events
        {"type": "radar_detected", "timestamp": "2026-03-01T11:58:00Z",
         "channel_from": 116, "channel_to": 40, "detail": "..."},
      ],
    }

**CleanAir gates `non_wifi_interferers`, not band.** Unlike the ESP32 probe
(2.4 GHz only, spectrum-blind by construction), a C9800-managed AP may or may
not carry a CleanAir ASIC, independent of band -- so `spectrum_capable` here
is read from `radio.clean_air_enabled`, not hardcoded. `radio.clean_air_enabled`
absent is treated as `False` (no unverified capability claims): a capture
bundle must say a radio is spectrum-capable, that is never assumed. A bundle
that supplies `spectrum` entries for a radio *not* flagged clean_air_enabled
is a bundle-building bug, not data to normalize around -- see
`_non_wifi_interferers` below, which refuses that combination rather than
silently keeping or silently dropping the entries.

Only `collected_at` and `radio.{band,channel,channel_width_mhz}` are required;
everything else follows the canonical schema's own optionality. Loosely-typed
values (Genie/CLI parsing often yields strings for what the schema types as a
number or bool -- `"36"`, `"Enabled"`) are coerced via the same
`adapters._common.coerce_scalar` the generic adapters use.
"""
from __future__ import annotations

from typing import Any

from adapters._common import array_element_types, coerce_scalar, scalar_leaf_types
from adapters.base import Adapter, ContractViolation

_VALID_EVENT_TYPES = {
    "radar_detected", "channel_change", "cac_started", "cac_completed", "cac_failed",
    "power_change", "width_change", "radio_reset", "ap_reboot",
    "afc_grant_received", "afc_grant_denied", "afc_grant_expired",
    "coverage_hole_detected", "rrm_dca_run", "interference_threshold_exceeded",
    "client_excluded", "roam_failure",
}

_VALID_INTERFERER_TYPES = {
    "bluetooth", "microwave_oven", "zigbee", "cordless_phone", "video_bridge",
    "wireless_camera", "radar", "jammer", "continuous_transmitter", "unknown",
}

_VALID_COLLECTION_METHODS = {
    "cli", "restconf", "rest_api", "snmp", "streaming_telemetry", "file_upload", "synthetic",
}

_BOOL_TRUE = {"true", "t", "yes", "y", "1", "enabled", "on"}
_BOOL_FALSE = {"false", "f", "no", "n", "0", "disabled", "off"}


class CiscoC9800Adapter(Adapter):
    name = "cisco_c9800"

    def __init__(self) -> None:
        self._scalar_types = scalar_leaf_types()
        self._array_types = array_element_types()

    def _translate(self, raw: Any) -> dict:
        if not isinstance(raw, dict):
            raise ContractViolation(
                f"{self.name}._translate expects one capture-bundle dict, got {type(raw).__name__}"
            )

        collected_at = raw.get("collected_at")
        if not isinstance(collected_at, str) or "T" not in collected_at:
            raise ContractViolation(
                f"{self.name}: capture bundle needs `collected_at` as an RFC3339 timestamp. "
                "Refusing to invent one."
            )

        radio_raw = raw.get("radio")
        if not isinstance(radio_raw, dict):
            raise ContractViolation(f"{self.name}: capture bundle needs a `radio` object.")

        ap_name = raw.get("ap_name")
        slot_id = radio_raw.get("slot_id")

        snapshot: dict[str, Any] = {
            "snapshot_id": raw.get("snapshot_id")
            or f"c9800-{ap_name or 'ap'}-radio{slot_id if slot_id is not None else '?'}-{collected_at}",
            "timestamp": collected_at,
            "radio": self._radio(radio_raw, ap_name),
            "rf_metrics": self._scalars("rf_metrics", raw.get("rrm") or {}),
            "analysis_context": self._analysis_context(raw, radio_raw),
        }

        self._source(snapshot, raw)
        self._site(snapshot, raw.get("site"))
        self._clients(snapshot, raw.get("clients") or {})
        self._neighbors(snapshot, raw.get("neighbors") or [])
        self._events(snapshot, raw.get("events") or [])
        self._non_wifi_interferers(snapshot, raw.get("spectrum") or [], radio_raw)

        wlan_raw = raw.get("wlan") or {}
        capabilities = self._scalars("capabilities", wlan_raw)
        if wlan_raw.get("bands_supported"):
            capabilities["bands_supported"] = [str(b) for b in wlan_raw["bands_supported"]]
        if capabilities:
            snapshot["capabilities"] = capabilities

        return snapshot

    # -- scalar sections ------------------------------------------------

    def _radio(self, radio_raw: dict, ap_name: Any) -> dict:
        for key in ("band", "channel", "channel_width_mhz"):
            if radio_raw.get(key) is None:
                raise ContractViolation(f"{self.name}: `radio.{key}` is required and was not supplied.")

        radio = self._scalars("radio", radio_raw, skip={"slot_id", "clean_air_enabled", "phy_modes"})
        if ap_name is not None:
            radio["ap_id"] = str(ap_name)
        if radio_raw.get("slot_id") is not None:
            radio["radio_id"] = str(radio_raw["slot_id"])
        if radio_raw.get("phy_modes"):
            radio["phy_modes"] = [str(p) for p in radio_raw["phy_modes"]]
        return radio

    def _scalars(self, section: str, raw: dict, *, skip: frozenset = frozenset()) -> dict:
        """Copy the scalar leaves of `raw` that belong under canonical `section`,
        coercing each to the type the schema declares. Unknown keys are ignored
        (a capture bundle may carry vendor context this adapter doesn't use).
        Map-typed fields (phy_rate_distribution, band_distribution) and
        array-typed fields (phy_modes, bands_supported) are not scalar leaves
        and are handled by their callers instead."""
        out: dict[str, Any] = {}
        for key, value in raw.items():
            if key in skip or value is None:
                continue
            dst = f"{section}.{key}"
            schema_type = self._scalar_types.get(dst)
            if schema_type is None:
                continue
            out[key] = self._coerce(value, self._scalar_types[dst], dst)
        return out

    def _coerce(self, value: Any, schema_type: str | None, src: str) -> Any:
        try:
            return coerce_scalar(value, schema_type, bool_true=_BOOL_TRUE, bool_false=_BOOL_FALSE)
        except ValueError as exc:
            raise ContractViolation(f"{self.name}: {src}: {exc}") from None

    def _source(self, snapshot: dict, raw: dict) -> None:
        method = raw.get("collection_method")
        raw_ref = raw.get("raw_ref")
        if method is None and raw_ref is None:
            return
        source = snapshot.setdefault("source", {})
        if method is not None:
            if method not in _VALID_COLLECTION_METHODS:
                raise ContractViolation(
                    f"{self.name}: `collection_method` {method!r} is not one of "
                    f"{sorted(_VALID_COLLECTION_METHODS)}"
                )
            source["collection_method"] = method
        if raw_ref is not None:
            source["raw_ref"] = str(raw_ref)

    def _site(self, snapshot: dict, site_raw: Any) -> None:
        if not isinstance(site_raw, dict):
            return
        site = self._scalars("site", site_raw)
        if site:
            snapshot["site"] = site

    def _analysis_context(self, raw: dict, radio_raw: dict) -> dict:
        ctx: dict[str, Any] = {
            "spectrum_capable": bool(radio_raw.get("clean_air_enabled", False)),
            "neighbor_scan_available": bool(raw.get("neighbors")),
            "client_detail_available": bool((raw.get("clients") or {}).get("samples")),
        }
        window = raw.get("observation_window_minutes")
        if isinstance(window, (int, float)):
            ctx["observation_window_minutes"] = float(window)
        symptom = raw.get("reported_symptom")
        if isinstance(symptom, str) and symptom.strip():
            ctx["reported_symptom"] = symptom
        return ctx

    # -- arrays -----------------------------------------------------------

    def _clients(self, snapshot: dict, clients_raw: dict) -> None:
        aggregate = self._scalars(
            "clients", clients_raw,
            skip={"samples", "phy_rate_distribution", "band_distribution"},
        )
        for key in ("phy_rate_distribution", "band_distribution"):
            dist = clients_raw.get(key)
            if dist:
                aggregate[key] = {
                    str(band): self._coerce(pct, "number", f"clients.{key}.{band}")
                    for band, pct in dist.items()
                }
        if aggregate:
            snapshot["clients"] = aggregate

        samples_raw = clients_raw.get("samples") or []
        samples = []
        for i, c in enumerate(samples_raw):
            if not isinstance(c, dict):
                raise ContractViolation(f"{self.name}: clients.samples[{i}] must be an object")
            mac = c.get("client_mac")
            if not mac:
                continue
            entry: dict[str, Any] = {"client_ref": str(mac)}  # pseudonymised by to_canonical
            for key in ("snr_db", "rssi_dbm", "phy_mode", "tx_rate_mbps", "retry_rate_pct"):
                if c.get(key) is not None:
                    entry[key] = self._coerce(
                        c[key], self._array_types["client_samples"][key], f"clients.samples[{i}].{key}"
                    )
            for key in ("supported_bands", "capabilities"):
                if c.get(key):
                    entry[key] = [str(v) for v in c[key]]
            samples.append(entry)
        if samples:
            snapshot["client_samples"] = samples[:50]  # schema maxItems

    def _neighbors(self, snapshot: dict, neighbors_raw: list) -> None:
        neighbors = []
        for i, n in enumerate(neighbors_raw):
            if not isinstance(n, dict):
                raise ContractViolation(f"{self.name}: neighbors[{i}] must be an object")
            bssid = n.get("bssid")
            if not bssid:
                continue
            entry: dict[str, Any] = {"bss_ref": str(bssid)}  # pseudonymised by to_canonical
            for key in ("channel", "channel_width_mhz", "rssi_dbm", "same_ess"):
                if n.get(key) is not None:
                    entry[key] = self._coerce(
                        n[key], self._array_types["neighbors"][key], f"neighbors[{i}].{key}"
                    )
            if n.get("vendor_hint"):
                entry["vendor_hint"] = str(n["vendor_hint"])
            neighbors.append(entry)
        if neighbors:
            snapshot["neighbors"] = neighbors[:30]  # schema maxItems

    def _events(self, snapshot: dict, events_raw: list) -> None:
        events = []
        for i, e in enumerate(events_raw):
            if not isinstance(e, dict):
                raise ContractViolation(f"{self.name}: events[{i}] must be an object")
            etype = e.get("type")
            ts = e.get("timestamp")
            if etype not in _VALID_EVENT_TYPES:
                raise ContractViolation(
                    f"{self.name}: events[{i}].type {etype!r} is not one of {sorted(_VALID_EVENT_TYPES)}"
                )
            if not isinstance(ts, str) or "T" not in ts:
                raise ContractViolation(f"{self.name}: events[{i}].timestamp must be an RFC3339 string")
            entry: dict[str, Any] = {"type": etype, "timestamp": ts}
            for key in ("channel_from", "channel_to"):
                if e.get(key) is not None:
                    entry[key] = int(e[key])
            if e.get("detail"):
                entry["detail"] = str(e["detail"])
            events.append(entry)
        if events:
            snapshot["events"] = events

    def _non_wifi_interferers(self, snapshot: dict, spectrum_raw: list, radio_raw: dict) -> None:
        if not spectrum_raw:
            return
        if not radio_raw.get("clean_air_enabled", False):
            raise ContractViolation(
                f"{self.name}: capture bundle supplies `spectrum` entries but "
                "`radio.clean_air_enabled` is not true -- a radio without spectrum "
                "analysis cannot report detections. Fix the bundle-building step, "
                "not this adapter."
            )
        interferers = []
        for i, s in enumerate(spectrum_raw):
            if not isinstance(s, dict):
                raise ContractViolation(f"{self.name}: spectrum[{i}] must be an object")
            itype = s.get("type")
            if itype not in _VALID_INTERFERER_TYPES:
                raise ContractViolation(
                    f"{self.name}: spectrum[{i}].type {itype!r} is not one of "
                    f"{sorted(_VALID_INTERFERER_TYPES)}"
                )
            entry: dict[str, Any] = {"type": itype}
            for key in ("severity", "duty_cycle_pct", "center_freq_mhz", "bandwidth_mhz"):
                if s.get(key) is not None:
                    entry[key] = self._coerce(
                        s[key], self._array_types["non_wifi_interferers"][key], f"spectrum[{i}].{key}"
                    )
            interferers.append(entry)
        if interferers:
            snapshot["non_wifi_interferers"] = interferers
