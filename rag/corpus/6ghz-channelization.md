---
id: 6ghz-channelization
title: "6 GHz band plan, UNII-5 to UNII-8, and Preferred Scanning Channels"
bands: [6GHz]
domains: [US, ETSI]
topics: [channel_plan, discovery]
sources:
  - "IEEE 802.11ax-2021 / 802.11-2024 (6 GHz operation)"
  - "47 CFR §15.407 as amended by FCC 20-51 (6 GHz Report and Order, 2020)"
  - "CEPT ECC Decision (20)01 (5945-6425 MHz)"
review_status: verified
---

## Band extent

- **United States: 5925-7125 MHz (1200 MHz).** Sub-bands U-NII-5
  (5925-6425), U-NII-6 (6425-6525), U-NII-7 (6525-6875), U-NII-8
  (6875-7125). This yields 59 non-overlapping 20 MHz channels, or
  29x 40 MHz, 14x 80 MHz, 7x 160 MHz, plus 320 MHz channels for 802.11be.
- **Europe (CEPT): 5945-6425 MHz (480 MHz)** — the lower portion only,
  roughly 24x 20 MHz channels. Confirm per country.

## Channel numbering

6 GHz channel number = (centre frequency in MHz - 5950) / 5, with channel 2
as a special low-edge case in some references. An 80 MHz channel spans four
20 MHz channels; a 320 MHz channel spans sixteen.

## Preferred Scanning Channels (PSC)

To bound scan time in a band this wide, 802.11 designates a subset of 20 MHz
channels as Preferred Scanning Channels, spaced every 80 MHz (channels 5, 21,
37, 53, 69, 85, 101, 117, 133, 149, 165, 181, 197, 213, 229). A client doing a
PSC-only scan will only find a BSS whose primary 20 MHz channel is a PSC, or
which is advertised out of band. Placing the primary channel on a PSC is the
safe default.
