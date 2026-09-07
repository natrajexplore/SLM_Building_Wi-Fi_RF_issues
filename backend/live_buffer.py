"""In-memory ring buffer of live probe samples for the frontend's 2.4 GHz Live
Test tab.

A probe (e.g. `hardware/esp32_rf_probe`, `BACKEND_URL` pointed at
`/live/ingest`) posts one sample at a time; the frontend polls `/live/feed`
for anything newer than the last id it saw. Single-process, in-memory only —
samples live only as long as this backend process runs. That is the right
tradeoff for the lab/demo use this targets; it is not a durability guarantee
and must not become one without an explicit decision to add persistence.
"""
from __future__ import annotations

import itertools
import threading
from collections import deque
from typing import TypedDict


class LiveSampleDict(TypedDict):
    id: int
    received_at: str
    snapshot: dict
    diagnosis: dict


_MAXLEN = 200
_lock = threading.Lock()
_counter = itertools.count(1)
_buffer: deque[LiveSampleDict] = deque(maxlen=_MAXLEN)


def append(snapshot: dict, diagnosis: dict, received_at: str) -> LiveSampleDict:
    with _lock:
        sample: LiveSampleDict = {
            "id": next(_counter),
            "received_at": received_at,
            "snapshot": snapshot,
            "diagnosis": diagnosis,
        }
        _buffer.append(sample)
        return sample


def since(after_id: int) -> list[LiveSampleDict]:
    with _lock:
        return [s for s in _buffer if s["id"] > after_id]


def latest_id() -> int:
    with _lock:
        return _buffer[-1]["id"] if _buffer else 0


def clear() -> None:
    """Test-only: reset the buffer between test cases."""
    with _lock:
        _buffer.clear()
