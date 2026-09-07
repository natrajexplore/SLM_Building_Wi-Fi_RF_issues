"""Read esp32_rf_probe output -> ingest -> diagnose. Live serial or replay file.

    # live, once the CP210x COM port works:
    python hardware/read_probe.py --port COM3

    # offline, from saved Serial lines (no board, no pyserial needed):
    python hardware/read_probe.py --replay captures.jsonl --once

    # feed the frontend's "2.4GHz Live Test" tab instead of printing here:
    python hardware/read_probe.py --replay hardware/sample_capture.jsonl --live

Each line the probe emits is one JSON object (see hardware/esp32_rf_probe/README.md).
By default, for each: POST /ingest {format:esp32} -> canonical snapshot -> POST
/diagnose -> print the root cause, evidence chain and regulatory citations.
With --live, each line instead goes to POST /live/ingest -- the same path the
board's own WiFi BACKEND_URL would hit -- so it shows up in the frontend's live
tab via GET /live/feed, and nothing is printed here per-line. Raw lines are
appended to --save for later replay either way.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _post(backend: str, path: str, obj: dict) -> dict:
    req = urllib.request.Request(
        backend.rstrip("/") + path,
        data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path} -> HTTP {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"cannot reach backend at {backend} ({e}). Start it: "
                         "uvicorn backend.main:app --port 8000")


def handle(line: str, backend: str, save, live: bool) -> None:
    line = line.strip()
    if not line or not line.startswith("{"):
        return
    try:
        probe = json.loads(line)
    except json.JSONDecodeError:
        print(f"  (skipped non-JSON line: {line[:80]})", file=sys.stderr)
        return
    if "error" in probe:
        print(f"  probe reported: {probe['error']}", file=sys.stderr)
        return
    if save:
        save.write(line + "\n")
        save.flush()

    if live:
        sample = _post(backend, "/live/ingest", {"format": "esp32", "document": probe})
        print(f"  live sample #{sample['id']} posted ({sample['received_at']})", file=sys.stderr)
        return

    snap = _post(backend, "/ingest", {"format": "esp32", "document": probe})["snapshots"][0]
    m = snap["rf_metrics"]
    print(f"\n[{probe.get('collected_at', '?')}]  ch{snap['radio']['channel']} "
          f"({snap['radio']['band']})   co-channel={m.get('co_channel_neighbors')} "
          f"adjacent={m.get('adjacent_channel_neighbors')} "
          f"noise={m.get('noise_floor_dbm')}dBm util~{m.get('channel_utilization_pct')}% "
          f"retry={m.get('retry_rate_pct')}%")

    d = _post(backend, "/diagnose", {"snapshot": snap, "retrieve": True})
    if d["cause_id"] is None:
        print(f"  DIAGNOSIS: no cause asserted (data gap) - need {', '.join(d['data_gaps'][:4])}")
    else:
        print(f"  DIAGNOSIS: {d['cause_id']}  ({d['confidence']} confidence)  bands={d['affected_bands']}")
    for e in d["evidence"]:
        print(f"     - {e['field_path']} = {e['observed_value']}  - {e['why_it_matters']}")
    if d.get("ranked_alternatives"):
        print(f"     also plausible: {', '.join(a['cause_id'] for a in d['ranked_alternatives'])}")
    for r in d["remediation"]:
        print(f"     -> {r}")
    for c in d["citations"]:
        flag = "" if c["review_status"] == "verified" else " [UNVERIFIED]"
        print(f"     cite: {c['title']} ({'; '.join(c['sources'])}){flag}")


def run_replay(path: Path, backend: str, once: bool, save, live: bool) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        handle(line, backend, save, live)
        if once:
            return


def run_serial(port: str, baud: int, backend: str, once: bool, save, live: bool) -> None:
    try:
        import serial  # pyserial
    except ImportError:
        raise SystemExit("live serial needs pyserial:  pip install pyserial")
    print(f"reading {port} @ {baud}  (Ctrl-C to stop)", file=sys.stderr)
    with serial.Serial(port, baud, timeout=2) as ser:
        buf = ""
        while True:
            chunk = ser.read(512).decode("utf-8", "replace")
            if not chunk:
                continue
            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                handle(line, backend, save, live)
                if once:
                    return


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="serial port, e.g. COM3 or /dev/ttyUSB0")
    src.add_argument("--replay", type=Path, help="a file of saved probe JSON lines")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--backend", default="http://localhost:8000")
    ap.add_argument("--once", action="store_true", help="one sample then exit")
    ap.add_argument("--save", type=Path, help="append raw probe lines here for later replay")
    ap.add_argument("--live", action="store_true",
                     help="POST /live/ingest instead of /ingest+/diagnose, "
                          "so samples show up in the frontend's 2.4GHz Live Test tab")
    args = ap.parse_args(argv)

    save = open(args.save, "a", encoding="utf-8") if args.save else None
    try:
        if args.replay:
            run_replay(args.replay, args.backend, args.once, save, args.live)
        else:
            run_serial(args.port, args.baud, args.backend, args.once, save, args.live)
    except KeyboardInterrupt:
        pass
    finally:
        if save:
            save.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
