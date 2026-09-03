from __future__ import annotations

from .config import LOOKAHEAD_BEATS, LOOKAHEAD_SECONDS
from .domain import GameNote


def _lookahead(value: float, speed: float) -> float:
    return value / max(0.25, float(speed))


def timed_progress(
    time: float,
    beat: float | None,
    song_time: float,
    song_beat: float,
    speed: float = 1.0,
) -> float:
    """Map an arbitrary chart timestamp/beat to 0..1 perspective progress."""
    if beat is not None:
        distance = max(beat - song_beat, 0.0)
        return max(0.0, min(1.0, 1.0 - distance / _lookahead(LOOKAHEAD_BEATS, speed)))
    distance = max(time - song_time, 0.0)
    return max(0.0, min(1.0, 1.0 - distance / _lookahead(LOOKAHEAD_SECONDS, speed)))


def note_progress(
    note: GameNote,
    song_time: float,
    song_beat: float,
    speed: float = 1.0,
) -> float:
    """Map an incoming note to 0..1 perspective progress.

    Real simfile notes carry their source beat and therefore scroll in musical
    beat space: a higher BPM advances ``song_beat`` faster and makes notes
    traverse the screen faster without changing their hit time. Synthetic/demo
    notes fall back to the original fixed-seconds behavior.
    """
    if note.judged and note.hit:
        return 1.0
    return timed_progress(note.time, note.beat, song_time, song_beat, speed)


def note_is_within_lookahead(
    note: GameNote,
    song_time: float,
    song_beat: float,
    speed: float = 1.0,
) -> bool:
    if note.beat is not None:
        return note.beat - song_beat <= _lookahead(LOOKAHEAD_BEATS, speed)
    return note.time - song_time <= _lookahead(LOOKAHEAD_SECONDS, speed)


def timed_is_within_lookahead(
    time: float,
    beat: float | None,
    song_time: float,
    song_beat: float,
    speed: float = 1.0,
) -> bool:
    if beat is not None:
        return beat - song_beat <= _lookahead(LOOKAHEAD_BEATS, speed)
    return time - song_time <= _lookahead(LOOKAHEAD_SECONDS, speed)
