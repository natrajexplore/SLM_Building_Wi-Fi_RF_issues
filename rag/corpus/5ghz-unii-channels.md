---
id: 5ghz-unii-channels
title: "5 GHz UNII sub-bands and channel numbering"
bands: [5GHz]
domains: [US, ETSI]
topics: [channel_plan]
sources:
  - "IEEE 802.11-2020, Annex E (country information, operating classes)"
  - "47 CFR §15.407 (U-NII devices)"
  - "ETSI EN 301 893 (5 GHz RLAN)"
review_status: unverified
---

## Sub-bands (United States, FCC)

- **U-NII-1: 5150-5250 MHz** — channels 36, 40, 44, 48. Indoor/outdoor;
  no DFS. Historically the lowest-power segment; rules have been relaxed over
  time, so confirm the current EIRP against §15.407.
- **U-NII-2A: 5250-5350 MHz** — channels 52, 56, 60, 64. **DFS required.**
- **U-NII-2C / 2-Extended: 5470-5725 MHz** — channels 100-144. **DFS required.**
  Channels 120, 124, 128 are the weather-radar range (see the DFS fact sheet).
- **U-NII-3: 5725-5850 MHz** — channels 149, 153, 157, 161, 165. No DFS.

## Sub-bands (Europe, CEPT/ETSI)

- **5150-5350 MHz** — indoor use; 5250-5350 MHz requires DFS and TPC.
- **5470-5725 MHz** — requires DFS and TPC.
- The 5725-5875 MHz segment is not generally available for RLAN in CEPT
  countries; U-NII-3 channels 149-165 are typically not usable in the EU.

## Numbering

5 GHz channel number = (centre frequency in MHz - 5000) / 5. Wider channels are
named by their primary 20 MHz channel; an 80 MHz channel occupies four
consecutive 20 MHz channels and a 160 MHz channel eight.

## Planning consequence

A design validated in one regulatory domain can have materially fewer usable
20 MHz channels in another (e.g. loss of U-NII-3 in the EU, or a site policy
that excludes all DFS channels), forcing channel reuse and raising co-channel
interference.
