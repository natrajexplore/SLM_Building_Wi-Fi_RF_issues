---
id: 6ghz-discovery
title: "6 GHz BSS discovery: RNR, FILS, and restricted probing"
bands: [6GHz]
domains: [global]
topics: [discovery]
sources:
  - "IEEE 802.11ax-2021 (6 GHz out-of-band discovery, Reduced Neighbor Report)"
  - "IEEE 802.11ai-2016 (FILS)"
review_status: verified
---

## Why discovery is different at 6 GHz

To limit probe-request traffic across 1200 MHz of spectrum, 802.11 restricts
active scanning in 6 GHz. A client generally will not send probe requests on a
6 GHz channel unless it has a prior indication that a BSS is present. It relies
on three mechanisms instead:

## Reduced Neighbor Report (RNR)

A co-located 2.4 GHz or 5 GHz AP advertises the 6 GHz BSS (its channel, BSSID,
SSID hint) in a Reduced Neighbor Report element in its own beacons and probe
responses. This is the primary out-of-band path. If the lower-band radios are
disabled or do not carry the RNR, capable clients may never discover the 6 GHz
BSS despite good coverage.

## Preferred Scanning Channels

See the channelization fact sheet. A client doing a PSC-only passive scan finds
only BSSes whose primary channel is a PSC.

## FILS Discovery frames

The 6 GHz AP itself may broadcast lightweight FILS Discovery frames (more often
than full beacons) so a passively scanning client on that channel sees the BSS
sooner.

## Diagnostic signature

A healthy 6 GHz radio (good SNR, low utilization) carrying almost no clients
while 5 GHz is congested is the signature of a discovery failure — check RNR
advertisement from co-located radios, PSC placement, and that the lower-band
radios are enabled.
