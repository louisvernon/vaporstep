from __future__ import annotations

from collections import deque
import threading

from .debug_state import set_scoring_sample_context
from .domain import BodyState


_lock = threading.Lock()
_completed: deque[BodyState] = deque()
_last_timestamp = 0.0
_buffered_scoring_ages_ms: dict[float, float] = {}


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
        if len(bodies) > 1:
            newest_timestamp = float(bodies[-1].timestamp)
            for body in bodies[:-1]:
                timestamp = float(body.timestamp)
                _buffered_scoring_ages_ms[timestamp] = max(
                    0.0,
                    (newest_timestamp - timestamp) * 1000.0,
                )
        return bodies


def consume_buffered_scoring_age_ms(timestamp: float) -> float | None:
    """Return how far this retained scoring sample trails the newest drained pose."""
    with _lock:
        return _buffered_scoring_ages_ms.pop(float(timestamp), None)


def clear_capture_bodies() -> None:
    global _last_timestamp
    with _lock:
        _completed.clear()
        _buffered_scoring_ages_ms.clear()
        _last_timestamp = 0.0
    set_scoring_sample_context(None)
