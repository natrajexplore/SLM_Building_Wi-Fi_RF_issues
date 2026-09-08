---
id: 6ghz-power-classes
title: "6 GHz power classes: LPI, Standard Power (AFC), VLP"
bands: [6GHz]
domains: [US, ETSI]
topics: [power]
sources:
  - "47 CFR §15.407 as amended by FCC 20-51; FCC 23-86 (VLP, ET Docket 18-295 / GN Docket 17-183)"
  - "CEPT ECC Decision (20)01; ECC Report 302 (AFC in 5925-6425 MHz)"
review_status: verified
---

## Low Power Indoor (LPI)

Indoor-only, no AFC coordination required. Power is capped by a **flat 30 dBm
EIRP ceiling** and by **5 dBm/MHz power spectral density (PSD)**, whichever
binds first — PSD is the binding constraint below ~320 MHz of bandwidth, so
actual EIRP scales with channel width up to the 30 dBm ceiling:

- 20 MHz: PSD-limited to **~18 dBm EIRP** (5 dBm/MHz + 10·log10(20)).
- 80 MHz: **~24 dBm EIRP**.
- 160 MHz: **~27 dBm EIRP**.
- 320 MHz (802.11be, EHT): PSD reaches the 30 dBm ceiling exactly.
- Client-to-AP PSD is 6 dB lower than the AP's.
- LPI devices may not be battery-powered as portable units and may not have
  weatherised or external-antenna forms.

## Standard Power (SP)

Higher EIRP (up to **36 dBm EIRP**, PSD up to **23 dBm/MHz** in the U.S.),
permitted only in U-NII-5 and U-NII-7 and only with a valid grant from an
**Automated Frequency Coordination (AFC)** system. The AFC returns permitted
channels and power for the AP's registered geolocation and antenna height.
Grants expire and must be renewed (typically at least daily). Without a current
grant the AP must fall back to LPI limits.

## Very Low Power (VLP)

Introduced later (FCC 23-86, later expanded band-wide by a November 2024
order): portable operation across the band (indoors and
outdoors) with no AFC, at a very low EIRP (**14 dBm EIRP, PSD −5 dBm/MHz** in
the U.S. — PSD binds below ~80 MHz of bandwidth, the 14 dBm ceiling above
that). Intended for short-range device-to-device use, not infrastructure
coverage.

## Diagnostic notes

A 6 GHz coverage shortfall that coincides with `power_mode = LPI` where the
design assumed Standard Power, or with an AFC grant that has expired or been
denied, points to an AFC dependency rather than ordinary under-coverage. When
power is already at the LPI ceiling and SNR is still marginal, increasing power
is not an available remedy — it is a design-density problem, made worse at wide
channel widths where the PSD cap bites hardest.
