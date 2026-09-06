---
id: 6ghz-security
title: "6 GHz mandatory security: WPA3, OWE, and protected management frames"
bands: [6GHz]
domains: [global]
topics: [security]
sources:
  - "IEEE 802.11-2020 (PMF / MFP, RSNA)"
  - "Wi-Fi Alliance WPA3 specification; Wi-Fi CERTIFIED 6 requirements"
review_status: unverified
---

## What 6 GHz requires

Operation in 6 GHz mandates a modern security association on every SSID:

- **WPA3-Personal (SAE)**, **Opportunistic Wireless Encryption (OWE)** for open
  networks, or **WPA3-Enterprise** (802.1X). WPA2-only and pre-shared-key WPA2
  (PSK) are not permitted.
- **Protected Management Frames (PMF / 802.11w) are required**, not optional.
- No WEP, no TKIP, and transition (mixed WPA2/WPA3) modes are not allowed on the
  6 GHz BSS itself.

## Consequence

A client that supports only WPA2 cannot associate on 6 GHz. This is correct
behaviour, and it presents as a client-side authentication or association
failure concentrated on a specific device population while other clients on the
same radio associate normally and RF metrics are healthy. The remedy is to
provide a 2.4/5 GHz SSID for legacy devices, not to weaken 6 GHz security
(which is not a tunable).
