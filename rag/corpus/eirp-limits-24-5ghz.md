---
id: eirp-limits-24-5ghz
title: "2.4 and 5 GHz EIRP limits (US FCC and EU ETSI, high level)"
bands: [2.4GHz, 5GHz]
domains: [US, ETSI]
topics: [power]
sources:
  - "47 CFR §15.247 (2.4 GHz and 5.725-5.850 GHz)"
  - "47 CFR §15.407 (U-NII)"
  - "ETSI EN 300 328 (2.4 GHz); ETSI EN 301 893 (5 GHz)"
review_status: verified
---

## 2.4 GHz

- **United States (§15.247):** up to **1 W conducted / 36 dBm EIRP** for a
  point-to-multipoint system with a 6 dBi antenna; higher antenna gain requires
  a full 1 dB conducted reduction per 1 dB of gain above 6 dBi (dB-for-dB).
  **Fixed, point-to-point-only** links get the more lenient exception — 1 dB
  conducted reduction per 3 dB of gain above 6 dBi — which point-to-multipoint,
  omnidirectional, and multi-co-located-radiator systems do not qualify for.
- **Europe (EN 300 328):** **20 dBm EIRP**, with a power spectral density limit
  of 10 dBm/MHz.

## 5 GHz (EIRP, indoor RLAN, approximate)

| Sub-band            | United States (§15.407) | Europe (EN 301 893) |
|---------------------|-------------------------|---------------------|
| 5150-5250 (U-NII-1) | up to 30 dBm            | 23 dBm (indoor)     |
| 5250-5350 (U-NII-2A)| up to 30 dBm (DFS+TPC)  | 23 dBm (DFS+TPC)    |
| 5470-5725 (U-NII-2C)| up to 30 dBm (DFS+TPC)  | 30 dBm (DFS+TPC)    |
| 5725-5850 (U-NII-3) | up to 36 dBm            | not RLAN in CEPT    |

These figures are indicative and change as rules are amended (U-NII-1 outdoor
and client rules in particular). Always confirm against the current text of the
cited regulation for the specific device class and deployment.

## Cross-band caution

2.4 GHz propagates further than 5 GHz at equal EIRP. A uniform power setting
across bands produces oversized 2.4 GHz cells, self-interference between
same-ESS APs, and sticky-client conditions. The bands must be powered
independently.
