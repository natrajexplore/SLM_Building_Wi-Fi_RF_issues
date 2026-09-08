---
id: 5ghz-dfs
title: "Dynamic Frequency Selection: CAC, non-occupancy, and channel move"
bands: [5GHz]
domains: [US, ETSI]
topics: [dfs]
sources:
  - "47 CFR §15.407(h) (DFS)"
  - "ETSI EN 301 893 §4.2.6 (DFS)"
  - "ITU-R M.1652 (DFS to protect radiodetermination service)"
review_status: verified
---

## Channel Availability Check (CAC)

Before transmitting on a DFS channel, an AP must monitor it for radar for a
Channel Availability Check period during which it cannot serve clients:

- **Standard DFS channels: 60 seconds** — this is the figure in 47 CFR
  §15.407(h) and applies uniformly across FCC DFS channels; the current CFR
  text does not carry a separate, longer CAC for the weather-radar range.
- **Weather-radar channels (5600-5650 MHz — channels 120, 124, 128): ETSI EN
  301 893 mandates a 600 second (10 minute) CAC** for this range to reliably
  detect meteorological radar. Do not assume the FCC figure is also 600s —
  treat 60s as the FCC default for these channels absent a confirmed CFR cite
  to the contrary.

Repeated CAC cycles present to users as intermittent AP unavailability whose
windows align with the CAC duration rather than with traffic load.

## In-service monitoring and channel move

While operating on a DFS channel the AP runs continuous in-service monitoring.
On detecting a radar pattern it must:

- **Stop transmitting on that channel within the Channel Move Time — 10 seconds**
  (of which the aggregate transmission during the move is bounded, ~260 ms in the
  FCC rules).
- Announce the move to associated clients via a Channel Switch Announcement
  where possible.

## Non-Occupancy Period

After a radar detection the channel must not be used for the **Non-Occupancy
Period of at least 30 minutes.**

## Diagnostic notes

Radar events that correlate in time with the reported symptom, followed
immediately by a channel-change event, indicate genuine DFS evacuation.
Recurrence at a consistent time of day suggests a fixed radar source (airport
or weather radar). This is distinct from algorithmic channel-selection churn,
which shows repeated channel changes with no corresponding radar detection.
