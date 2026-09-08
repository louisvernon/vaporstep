from __future__ import annotations

from collections import deque
import threading

from .domain import BodyState


_lock = threading.Lock()
_completed: deque[BodyState] = deque()
_last_timestamp = 0.0


def publish_capture_body(body: BodyState) -> None:
    """Retain every completed chronological camera result for gameplay scoring."""
    if not body.timestamp_is_capture or body.timestamp <= 0.0:
        return

    timestamp = float(body.timestamp)
    global _last_timestamp
    with _lock:
        # MediaPipe LIVE_STREAM results are chronological. Ignore an accidental
        # duplicate rather than letting a repeated snapshot become new evidence.
        if timestamp <= _last_timestamp:
            return
        _completed.append(body)
        _last_timestamp = timestamp


def drain_capture_bodies() -> tuple[BodyState, ...]:
    """Return all completed camera bodies since the previous gameplay update."""
    with _lock:
        bodies = tuple(_completed)
        _completed.clear()
        return bodies


def clear_capture_bodies() -> None:
    global _last_timestamp
    with _lock:
        _completed.clear()
        _last_timestamp = 0.0
