from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


class _FakeMusic:
    @staticmethod
    def stop():
        pass

    @staticmethod
    def get_busy():
        return True


class _FakeMixer:
    music = _FakeMusic()

    @staticmethod
    def get_init():
        return False


try:
    import pygame  # noqa: F401
except ImportError:
    sys.modules.setdefault("pygame", SimpleNamespace(mixer=_FakeMixer()))

from vaporstep.camera_samples import (
    clear_capture_bodies,
    drain_capture_bodies,
    publish_capture_body,
)
from vaporstep.domain import BodyPoint, BodyState, GameNote, HitQuality, NoteKind
from vaporstep.session import GameSession


def _camera_body(captured_at: float, *, lane: int) -> BodyState:
    return BodyState(
        left_knee=BodyPoint(x=0.40, y=0.60, lane=lane, visible=True),
        pose_visible=True,
        timestamp=captured_at,
        timestamp_is_capture=True,
    )


def _running_session(monkeypatch, note: GameNote):
    import vaporstep.session as session_module

    monotonic = [10.20]
    chart_time = [1.20]
    monkeypatch.setattr(session_module.time, "monotonic", lambda: monotonic[0])
    monkeypatch.setattr(GameSession, "time", property(lambda self: chart_time[0]))
    session = GameSession(demo_notes=(note,))
    session.running = True
    session.audio_started = True
    return session, monotonic, chart_time


def test_keyboard_support_does_not_disable_camera_capture_time_scoring(monkeypatch) -> None:
    note = GameNote(time=1.0, lanes=(2,), kind=NoteKind.FOOT)
    session, monotonic, chart_time = _running_session(monkeypatch, note)
    session.set_keyboard_mode(True)  # This is how the real app runs camera play.

    monotonic[0] = 10.20
    chart_time[0] = 1.20
    session.update(_camera_body(10.00, lane=2), ready_to_start=True)

    # The camera frame was captured on the beat, so merely enabling keyboard
    # fallback must not evaluate it against the visibly newer 1.20 playfield.
    assert not session.notes[0].judged
    assert session.notes[0].last_occupancy_at == pytest.approx(1.0)


def test_one_render_update_consumes_every_completed_camera_result(monkeypatch) -> None:
    note = GameNote(time=1.0, lanes=(2,), kind=NoteKind.FOOT)
    session, monotonic, chart_time = _running_session(monkeypatch, note)
    session.set_keyboard_mode(True)

    clear_capture_bodies()
    samples = (
        _camera_body(9.95, lane=1),
        _camera_body(10.00, lane=2),  # decisive on-beat evidence
        _camera_body(10.20, lane=3),
    )
    for sample in samples:
        publish_capture_body(sample)

    # Simulate a slow rendered frame: all three inferences completed before the
    # game loop got to call update once. The latest rendered pose is lane 3, but
    # scoring must still see the intermediate lane-2 result.
    monotonic[0] = 10.20
    chart_time[0] = 1.20
    session.update(samples[-1], ready_to_start=True)

    assert session.notes[0].judged
    assert session.notes[0].hit
    assert session.notes[0].judgement in (HitQuality.HIT, HitQuality.GREAT, HitQuality.PERFECT)
    assert drain_capture_bodies() == ()


def test_completed_camera_buffer_preserves_chronological_results() -> None:
    clear_capture_bodies()
    bodies = tuple(_camera_body(timestamp, lane=lane) for timestamp, lane in ((1.0, 1), (1.05, 2), (1.10, 3)))
    for body in bodies:
        publish_capture_body(body)

    drained = drain_capture_bodies()

    assert [body.timestamp for body in drained] == [1.0, 1.05, 1.10]
    assert [next(iter(body.foot_lanes)) for body in drained] == [1, 2, 3]


def test_completed_camera_buffer_ignores_duplicate_timestamp() -> None:
    clear_capture_bodies()
    publish_capture_body(_camera_body(1.0, lane=1))
    publish_capture_body(_camera_body(1.0, lane=2))

    drained = drain_capture_bodies()

    assert len(drained) == 1
    assert drained[0].foot_lanes == frozenset((1,))
