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

from vaporstep.chains import HOLD_OCCUPANCY_GRACE_SECONDS
from vaporstep.domain import (
    BodyPoint,
    BodyState,
    ChainState,
    GameNote,
    HitQuality,
    ImplicitChain,
    NoteKind,
    RuntimeChain,
    SustainSource,
)
from vaporstep.session import GameSession


def _camera_body(captured_at: float, *, lane: int = 2) -> BodyState:
    return BodyState(
        left_knee=BodyPoint(x=0.40, y=0.60, lane=lane, visible=True),
        pose_visible=True,
        timestamp=captured_at,
        timestamp_is_capture=True,
    )


def _running_session(monkeypatch, *, note: GameNote | None = None):
    import vaporstep.session as session_module

    monotonic = [10.0]
    chart_time = [0.0]
    monkeypatch.setattr(session_module.time, "monotonic", lambda: monotonic[0])
    monkeypatch.setattr(GameSession, "time", property(lambda self: chart_time[0]))
    session = GameSession(demo_notes=() if note is None else (note,))
    session.running = True
    session.audio_started = True
    return session, monotonic, chart_time


def test_delayed_occupancy_is_scored_at_capture_time(monkeypatch):
    note = GameNote(time=1.0, lanes=(2,), kind=NoteKind.FOOT)
    session, monotonic, chart_time = _running_session(monkeypatch, note=note)

    # This result arrives when the visible playfield is already 200 ms past the
    # note, but the camera captured the occupied lane exactly on the beat.
    monotonic[0] = 10.20
    chart_time[0] = 1.20
    session.update(_camera_body(10.00), ready_to_start=True)

    assert not session.notes[0].judged
    assert session.notes[0].last_occupancy_at == pytest.approx(1.0)

    # Advancing the completed-input watermark past the late occupancy window
    # settles that historical occupancy to HIT rather than having missed at 1.20.
    monotonic[0] = 10.36
    chart_time[0] = 1.36
    session.update(_camera_body(10.16), ready_to_start=True)

    assert session.notes[0].judged
    assert session.notes[0].judgement == HitQuality.HIT


def test_camera_miss_waits_for_completed_input_watermark(monkeypatch):
    note = GameNote(time=1.0, lanes=(2,), kind=NoteKind.FOOT)
    session, monotonic, chart_time = _running_session(monkeypatch, note=note)

    # Current chart time is already beyond the miss window, but completed camera
    # evidence is only at 0.95, so the note must remain pending.
    monotonic[0] = 10.20
    chart_time[0] = 1.20
    session.update(_camera_body(9.95, lane=3), ready_to_start=True)
    assert not session.notes[0].judged

    # Once a completed sample itself advances beyond the late window, the miss is
    # safe to finalize.
    monotonic[0] = 10.40
    chart_time[0] = 1.40
    session.update(_camera_body(10.16, lane=3), ready_to_start=True)
    assert session.notes[0].judged
    assert not session.notes[0].hit


def test_sustain_break_uses_historical_camera_time(monkeypatch):
    session, monotonic, chart_time = _running_session(monkeypatch)
    definition = ImplicitChain(
        id=1,
        kind=NoteKind.FOOT,
        lanes=(2,),
        note_indices=(),
        start_time=0.5,
        end_time=3.0,
        start_beat=1.0,
        end_beat=6.0,
        source=SustainSource.EXPLICIT_HOLD,
    )
    chain = RuntimeChain(
        definition=definition,
        state=ChainState.ACTIVE,
        last_occupancy_at=1.0,
    )
    session.chains = [chain]
    session._chain_by_id = {1: chain}

    sample_time = 1.0 + HOLD_OCCUPANCY_GRACE_SECONDS - 0.01
    chart_time[0] = sample_time + 0.25
    monotonic[0] = 10.50
    captured_at = monotonic[0] - (chart_time[0] - sample_time)
    session.update(_camera_body(captured_at, lane=3), ready_to_start=True)
    assert chain.state == ChainState.ACTIVE

    sample_time = 1.0 + HOLD_OCCUPANCY_GRACE_SECONDS + 0.01
    chart_time[0] = sample_time + 0.25
    monotonic[0] = 10.70
    captured_at = monotonic[0] - (chart_time[0] - sample_time)
    session.update(_camera_body(captured_at, lane=3), ready_to_start=True)
    assert chain.state == ChainState.BROKEN
