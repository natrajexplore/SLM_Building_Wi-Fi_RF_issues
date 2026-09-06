---
id: 24ghz-legacy-rates
title: "802.11b/g mandatory rates and airtime cost of low basic rates"
bands: [2.4GHz]
domains: [global]
topics: [phy_rates]
sources:
  - "IEEE 802.11-2020, Clause 15 (HR/DSSS) and Clause 17 (OFDM)"
review_status: unverified
---

## 802.11b (HR/DSSS) rates

802.11b defines data rates of 1, 2, 5.5 and 11 Mbit/s. 1 and 2 Mbit/s use DSSS
(Clause 15/16); 5.5 and 11 Mbit/s use HR/DSSS (CCK). A BSS that keeps any of
these as a mandatory ("basic") rate must transmit management and control frames
(beacons, probe responses) at that rate.

## 802.11g (ERP-OFDM) rates

802.11g adds OFDM rates 6, 9, 12, 18, 24, 36, 48 and 54 Mbit/s in 2.4 GHz. 6,
12 and 24 Mbit/s are the mandatory OFDM rates.

## Airtime effect of a low basic rate

Frame duration is inversely related to PHY rate. A beacon or a frame sent at
1 Mbit/s occupies on the order of ten times the airtime of the same frame at
12 Mbit/s. In a cell with many beaconing BSSes, or with clients that fall back
to 1-2 Mbit/s at range, low basic rates consume a disproportionate share of
channel time regardless of how much data they carry. Raising the minimum basic
rate above 11 Mbit/s disables 802.11b association entirely; this will
disassociate any DSSS-only device and must be checked against the client
inventory first.
