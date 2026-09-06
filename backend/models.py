"""GENERATED — do not edit by hand.

Pydantic mirror of schema/canonical_rf.schema.json (CLAUDE.md: the schema is the
single source of truth; these models are not hand-written twice). Regenerate
after any schema change:

    python -m datamodel_code_generator         --input schema/canonical_rf.schema.json --input-file-type jsonschema         --output backend/models.py --output-model-type pydantic_v2.BaseModel         --class-name CanonicalSnapshot --use-schema-description         --use-field-description --disable-timestamp --target-python-version 3.12         --enum-field-as-literal all --formatters black

`extra="forbid"` on every model mirrors the schema's `additionalProperties: false`.
Enum-valued fields are `Literal[...]` — validated strings, no enum classes.
"""

from __future__ import annotations
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, confloat, conint


class Source(BaseModel):
    """
    Provenance only. MUST NOT be passed to the model — used for audit and for optional vendor-syntax post-processing.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    adapter: str | None = None
    """
    Adapter that produced this record, e.g. cisco_c9800, aruba_central, mist, generic_csv.
    """
    collection_method: (
        Literal[
            'cli',
            'restconf',
            'rest_api',
            'snmp',
            'streaming_telemetry',
            'file_upload',
            'synthetic',
        ]
        | None
    ) = None
    raw_ref: str | None = None
    """
    Pointer to the archived raw payload.
    """


class Site(BaseModel):
    """
    Deployment context. Influences expected client density and interference profile.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    site_id: str | None = None
    environment: (
        Literal[
            'office',
            'warehouse',
            'healthcare',
            'education',
            'retail',
            'manufacturing',
            'hospitality',
            'outdoor',
            'high_density_venue',
            'unknown',
        ]
        | None
    ) = 'unknown'
    ap_group: str | None = None
    floor: str | None = None


class Radio(BaseModel):
    """
    Configuration and identity of the radio under diagnosis.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    ap_id: str | None = None
    radio_id: str | None = None
    band: Literal['2.4GHz', '5GHz', '6GHz']
    channel: int
    """
    Primary channel number in the band's numbering scheme.
    """
    channel_width_mhz: Literal[20, 40, 80, 160, 320]
    operating_class: int | None = None
    """
    IEEE 802.11 global operating class. Preferred over vendor band labels where available.
    """
    tx_power_dbm: float | None = None
    tx_power_max_dbm: float | None = None
    """
    Regulatory or hardware ceiling. Needed to detect TPC headroom exhaustion.
    """
    power_mode: Literal['LPI', 'SP', 'VLP', 'standard', 'n/a'] | None = 'n/a'
    """
    6 GHz power class. LPI = Low Power Indoor, SP = Standard Power (AFC-governed), VLP = Very Low Power.
    """
    regulatory_domain: str | None = None
    """
    ISO 3166-1 alpha-2 country code. Determines legal channel and power set.
    """
    phy_modes: (
        list[Literal['11a', '11b', '11g', '11n', '11ac', '11ax', '11be']] | None
    ) = None
    dfs_required: bool | None = None
    """
    True if the current channel sits in a DFS-mandated range for this regulatory domain.
    """
    admin_state: Literal['enabled', 'disabled', 'unknown'] | None = 'unknown'


class RfMetrics(BaseModel):
    """
    Measured RF conditions. This is the primary evidence surface for diagnosis.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    noise_floor_dbm: float | None = None
    """
    Typically -85 to -100. Elevated noise floor is a strong non-Wi-Fi interference signal.
    """
    channel_utilization_pct: confloat(ge=0.0, le=100.0) | None = None
    """
    Total airtime consumed, Wi-Fi and non-Wi-Fi combined.
    """
    rx_utilization_pct: confloat(ge=0.0, le=100.0) | None = None
    tx_utilization_pct: confloat(ge=0.0, le=100.0) | None = None
    interference_pct: confloat(ge=0.0, le=100.0) | None = None
    """
    Airtime lost to energy that is not decodable Wi-Fi on this BSS.
    """
    co_channel_neighbors: int | None = None
    """
    Count of neighbouring BSSs on the same primary channel above the CCA threshold.
    """
    adjacent_channel_neighbors: int | None = None
    """
    Count of overlapping-but-not-identical channel neighbours. Drives 2.4 GHz ACI diagnosis.
    """
    strongest_neighbor_rssi_dbm: float | None = None
    retry_rate_pct: confloat(ge=0.0, le=100.0) | None = None
    crc_error_rate_pct: confloat(ge=0.0, le=100.0) | None = None
    airtime_efficiency_pct: confloat(ge=0.0, le=100.0) | None = None
    """
    Useful throughput per unit airtime. Low value with low utilization suggests rate/PHY problems, not congestion.
    """


class NonWifiInterferer(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    type: Literal[
        'bluetooth',
        'microwave_oven',
        'zigbee',
        'cordless_phone',
        'video_bridge',
        'wireless_camera',
        'radar',
        'jammer',
        'continuous_transmitter',
        'unknown',
    ]
    severity: conint(ge=0, le=100) | None = None
    duty_cycle_pct: confloat(ge=0.0, le=100.0) | None = None
    center_freq_mhz: float | None = None
    bandwidth_mhz: float | None = None


class Clients(BaseModel):
    """
    Aggregate client-side view. Per-client detail belongs in client_samples.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    count: conint(ge=0) | None = None
    avg_snr_db: float | None = None
    min_snr_db: float | None = None
    avg_rssi_dbm: float | None = None
    sticky_clients: int | None = None
    """
    Clients associated below an acceptable SNR while a materially better AP is available.
    """
    legacy_client_count: int | None = None
    """
    Clients capable only of 11b/11g/11a rates. Drives airtime-consumption diagnosis.
    """
    phy_rate_distribution: dict[str, confloat(ge=0.0, le=100.0)] | None = None
    """
    Share of clients per PHY generation. Keys: 11b, 11g, 11n, 11ac, 11ax, 11be. Values: percentage.
    """
    band_distribution: dict[str, confloat(ge=0.0, le=100.0)] | None = None
    """
    Where clients actually landed across bands. Reveals band-steering failure.
    """
    auth_failures_5m: int | None = None
    assoc_failures_5m: int | None = None
    roam_failures_5m: int | None = None
    avg_roam_time_ms: float | None = None


class ClientSample(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    client_ref: str | None = None
    """
    Pseudonymised identifier. MUST NOT be a real MAC address.
    """
    snr_db: float | None = None
    rssi_dbm: float | None = None
    phy_mode: str | None = None
    tx_rate_mbps: float | None = None
    retry_rate_pct: float | None = None
    supported_bands: list[Literal['2.4GHz', '5GHz', '6GHz']] | None = None
    capabilities: list[str] | None = None


class Event(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    type: Literal[
        'radar_detected',
        'channel_change',
        'cac_started',
        'cac_completed',
        'cac_failed',
        'power_change',
        'width_change',
        'radio_reset',
        'ap_reboot',
        'afc_grant_received',
        'afc_grant_denied',
        'afc_grant_expired',
        'coverage_hole_detected',
        'rrm_dca_run',
        'interference_threshold_exceeded',
        'client_excluded',
        'roam_failure',
    ]
    timestamp: AwareDatetime
    channel_from: int | None = None
    channel_to: int | None = None
    detail: str | None = None


class Capabilities(BaseModel):
    """
    Feature state of this radio/WLAN. Central to the capability-gap root-cause class in mixed-vendor fleets.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    bands_supported: list[Literal['2.4GHz', '5GHz', '6GHz']] | None = None
    dot11k: bool | None = None
    dot11v: bool | None = None
    dot11r: bool | None = None
    dot11w_pmf: Literal['disabled', 'optional', 'required', 'unknown'] | None = None
    owe_enabled: bool | None = None
    wpa3_enforced: bool | None = None
    band_steering: bool | None = None
    airtime_fairness: bool | None = None
    afc_supported: bool | None = None
    afc_status: (
        Literal['granted', 'denied', 'pending', 'expired', 'not_applicable', 'unknown']
        | None
    ) = None
    psc_only_beaconing: bool | None = None
    """
    6 GHz: whether the AP beacons only on Preferred Scanning Channels.
    """
    rnr_advertised: bool | None = None
    """
    6 GHz out-of-band discovery via Reduced Neighbor Report from 2.4/5 GHz.
    """
    fils_discovery: bool | None = None
    min_data_rate_mbps: float | None = None
    """
    Lowest mandatory basic rate. Key lever for 2.4 GHz legacy-rate problems.
    """
    multicast_handling: (
        Literal['unicast_conversion', 'multicast_direct', 'flood', 'drop', 'unknown']
        | None
    ) = None


class Neighbor(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    bss_ref: str | None = None
    """
    Pseudonymised BSSID.
    """
    channel: int | None = None
    channel_width_mhz: int | None = None
    rssi_dbm: float | None = None
    same_ess: bool | None = None
    """
    True if part of the same SSID/ESS — distinguishes self-interference from foreign interference.
    """
    vendor_hint: str | None = None


class AnalysisContext(BaseModel):
    """
    Tells the model what it can and cannot conclude from this snapshot. Prevents confident diagnosis from absent data.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    observation_window_minutes: float | None = None
    spectrum_capable: bool | None = None
    """
    False means non_wifi_interferers being empty carries no diagnostic weight.
    """
    client_detail_available: bool | None = None
    neighbor_scan_available: bool | None = None
    missing_fields: list[str] | None = None
    """
    Explicit list of canonical fields the source platform could not supply.
    """
    reported_symptom: str | None = None
    """
    Free-text user complaint, e.g. 'video calls drop in the east wing around 2pm'.
    """


class CanonicalSnapshot(BaseModel):
    """
    Vendor-neutral representation of a single radio's RF state at a point in time. Every vendor adapter MUST normalize into this shape. The SLM never sees vendor-native output.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    snapshot_id: str
    """
    Opaque unique id for this snapshot.
    """
    timestamp: AwareDatetime
    """
    ISO 8601 UTC timestamp of collection.
    """
    source: Source | None = None
    """
    Provenance only. MUST NOT be passed to the model — used for audit and for optional vendor-syntax post-processing.
    """
    site: Site | None = None
    """
    Deployment context. Influences expected client density and interference profile.
    """
    radio: Radio
    """
    Configuration and identity of the radio under diagnosis.
    """
    rf_metrics: RfMetrics
    """
    Measured RF conditions. This is the primary evidence surface for diagnosis.
    """
    non_wifi_interferers: list[NonWifiInterferer] | None = None
    """
    Spectrum-analysis detections, where the platform provides them. Absence is not evidence of absence — see analysis_context.spectrum_capable.
    """
    clients: Clients | None = None
    """
    Aggregate client-side view. Per-client detail belongs in client_samples.
    """
    client_samples: list[ClientSample] | None = Field(None, max_length=50)
    """
    Optional per-client records for targeted diagnosis. Keep bounded — do not dump full client tables into the model.
    """
    events: list[Event] | None = None
    """
    Time-ordered RF-relevant events in the observation window. Radar and channel-change events are decisive for 5 GHz diagnosis.
    """
    capabilities: Capabilities | None = None
    """
    Feature state of this radio/WLAN. Central to the capability-gap root-cause class in mixed-vendor fleets.
    """
    neighbors: list[Neighbor] | None = Field(None, max_length=30)
    """
    Observed neighbouring BSSs. Vendor field is intentionally coarse — used for capability-gap reasoning only, never for vendor-specific remediation.
    """
    analysis_context: AnalysisContext | None = None
    """
    Tells the model what it can and cannot conclude from this snapshot. Prevents confident diagnosis from absent data.
    """
