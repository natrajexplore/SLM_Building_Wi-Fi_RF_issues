---
id: 24ghz-channel-plan
title: "2.4 GHz channel plan and non-overlapping channels"
bands: [2.4GHz]
domains: [global]
topics: [channel_plan]
sources:
  - "IEEE 802.11-2020, Clause 15 (DSSS) and Annex E"
  - "ITU-R RR Appendix (2.4 GHz ISM band 2400-2483.5 MHz)"
review_status: verified
---

## Band and channel spacing

The 2.4 GHz ISM band spans roughly 2400-2483.5 MHz. 802.11 defines 20 MHz
(nominally 22 MHz for legacy DSSS) channels centred 5 MHz apart and numbered
1-13 in most regions (channel 14 is Japan, DSSS only). Because a channel is
wider than the 5 MHz spacing, adjacent-numbered channels overlap in frequency.

## Non-overlapping set: 1, 6, 11

In regulatory domains that permit channels 1-11 (e.g. the United States),
channels 1, 6 and 11 are the only set of three that do not overlap. Where
channels up to 13 are allowed, 1/5/9/13 is sometimes cited as a four-channel
non-overlapping set for 20 MHz operation, but 1/6/11 remains the safe default
because it interoperates with 11-channel domains.

## Consequences for planning

Only three non-overlapping 20 MHz channels exist. Beyond a modest access-point
and client density, 2.4 GHz contention is a spectrum-supply limit that no
channel assignment can remove. 40 MHz operation in 2.4 GHz consumes two of the
three non-overlapping channels and is generally discouraged in any multi-AP
deployment. Channel widths above 20 MHz are not appropriate for 2.4 GHz in
enterprise designs.
