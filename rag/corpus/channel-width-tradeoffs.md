---
id: channel-width-tradeoffs
title: "Channel width vs. reuse and power spectral density"
bands: [5GHz, 6GHz]
domains: [global]
topics: [width, channel_plan]
sources:
  - "IEEE 802.11-2020 Clause 17/19 (VHT/HE); IEEE 802.11be (EHT, 320 MHz)"
review_status: unverified
---

## Non-overlapping channel count by width

Wider channels raise peak PHY rate but reduce the number of non-overlapping
channels available for reuse:

| Width  | Non-overlapping channels, U.S. 5 GHz (incl. DFS) | U.S. 6 GHz |
|--------|--------------------------------------------------|------------|
| 20 MHz | ~25                                              | 59         |
| 40 MHz | ~12                                              | 29         |
| 80 MHz | ~6                                               | 14         |
| 160 MHz| ~2                                               | 7          |
| 320 MHz| n/a (6 GHz / 802.11be only)                      | 3          |

Excluding DFS channels, or operating in a domain with less spectrum, cuts the
5 GHz figures sharply — often to two or three 80 MHz channels.

## Power spectral density

Transmit power is spread over the occupied bandwidth. Doubling channel width
halves the power per unit bandwidth (about 3 dB lower PSD) for the same total
EIRP, which reduces effective range per subcarrier. At the 6 GHz LPI PSD cap the
total EIRP actually rises with width up to the EIRP ceiling, but the cell-edge
SNR benefit of a wider channel is still limited and the reuse cost is real.

## Planning consequence

In dense deployments, channel reuse beats per-client peak rate: size width to
AP density and to the spectrum left after DFS/regulatory exclusions, not to
headline throughput. Wide width combined with a high co-channel-neighbour count
is a common cause of self-inflicted contention.
