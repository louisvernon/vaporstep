from __future__ import annotations

import time

from .config import HIT_WINDOW_SECONDS, OCCUPANCY_GRACE_SECONDS
from .domain import BodyState, GameNote, NoteKind, occupancy_is_fresh


DEMO_LENGTH = 10.0
READY_HOLD_SECONDS = 0.8


def make_demo_notes() -> list[GameNote]:
    return [
        GameNote(2.0, (2,), NoteKind.FOOT),
        GameNote(3.0, (4,), NoteKind.FOOT),
        GameNote(4.0, (1, 4), NoteKind.HANDS),
        GameNote(5.0, (3,), NoteKind.FOOT),
        GameNote(6.0, (1,), NoteKind.FOOT),
        GameNote(7.0, (2, 3), NoteKind.HANDS),
        GameNote(8.0, (4,), NoteKind.FOOT),
    ]


class DemoSession:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.notes = make_demo_notes()
        self.running = False
        self.ready_since: float | None = None

    def restart(self) -> None:
        self.started = time.monotonic()
        self.notes = make_demo_notes()
        self.running = False
        self.ready_since = None

    @property
    def time(self) -> float:
        if not self.running:
            return 0.0
        elapsed = time.monotonic() - self.started
        if elapsed >= DEMO_LENGTH:
            self.started = time.monotonic()
            self.notes = make_demo_notes()
            return 0.0
        return elapsed

    def update(self, body: BodyState, ready_to_start: bool) -> None:
        now = time.monotonic()
        if not self.running:
            if ready_to_start:
                if self.ready_since is None:
                    self.ready_since = now
                elif now - self.ready_since >= READY_HOLD_SECONDS:
                    self.running = True
                    self.started = now
                    self.notes = make_demo_notes()
            else:
                self.ready_since = None
            return

        t = self.time
        for note in self.notes:
            if note.judged:
                continue
            delta = t - note.time
            if (
                -OCCUPANCY_GRACE_SECONDS <= delta <= HIT_WINDOW_SECONDS
                and note.is_satisfied(body)
            ):
                note.last_occupancy_at = t
            if delta >= 0.0:
                recent = occupancy_is_fresh(
                    note.last_occupancy_at, t, OCCUPANCY_GRACE_SECONDS
                )
                if delta <= HIT_WINDOW_SECONDS and recent:
                    note.judged = True
                    note.hit = True
                    note.judged_at = t
                    continue
            if delta > HIT_WINDOW_SECONDS:
                note.judged = True
                note.hit = False
                note.judged_at = t
