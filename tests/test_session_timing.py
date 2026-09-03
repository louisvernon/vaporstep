import sys
from types import SimpleNamespace

import pytest


class _FakeMusic:
    @staticmethod
    def stop():
        pass


class _FakeMixer:
    music = _FakeMusic()

    @staticmethod
    def get_init():
        return False


try:
    import pygame  # noqa: F401
except ImportError:
    sys.modules.setdefault("pygame", SimpleNamespace(mixer=_FakeMixer()))

from vaporstep.domain import BodyPoint, BodyState, GameNote, HitQuality, NoteKind
from vaporstep.session import READY_HOLD_SECONDS, GameSession


def _body(ts: float, *, knee_y: float = 0.60, lane: int = 2) -> BodyState:
    return BodyState(
        left_knee=BodyPoint(x=0.40, y=knee_y, lane=lane, visible=True),
        pose_visible=True,
        timestamp=ts,
    )


def _session(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(demo_notes=[GameNote(time=1.0, lanes=(2,), kind=NoteKind.FOOT)])
    session.running = True
    return session, clock


def test_occupancy_does_not_steal_in_lane_perfect(monkeypatch):
    session, clock = _session(monkeypatch)
    note = session.notes[0]

    # Establish occupancy before the receptor and keep the motion baseline warm.
    clock[0] = 0.90
    session.update(_body(1.00, knee_y=0.60), ready_to_start=True)
    assert not note.judged

    # At the exact beat, plain occupancy is provisional rather than an instant HIT.
    clock[0] = 1.00
    session.update(_body(1.05, knee_y=0.60), ready_to_start=True)
    assert not note.judged

    # A downward stomp 50 ms late while remaining in the same lane can now win PERFECT.
    clock[0] = 1.05
    session.update(_body(1.10, knee_y=0.65), ready_to_start=True)
    assert note.judged
    assert note.judgement == HitQuality.PERFECT


def test_plain_occupancy_settles_to_hit_at_late_grace(monkeypatch):
    session, clock = _session(monkeypatch)
    note = session.notes[0]

    clock[0] = 0.90
    session.update(_body(1.00), ready_to_start=True)
    clock[0] = 1.00
    session.update(_body(1.05), ready_to_start=True)
    assert not note.judged

    clock[0] = 1.16
    session.update(_body(1.16), ready_to_start=True)
    assert note.judged
    assert note.judgement == HitQuality.HIT


def test_keyboard_press_scores_perfect_without_continuous_occupancy(monkeypatch):
    session, clock = _session(monkeypatch)
    session.set_keyboard_mode(True)
    note = session.notes[0]

    clock[0] = 0.94
    session.register_keyboard_press(NoteKind.FOOT, 2)
    session.update(BodyState(), ready_to_start=True)
    assert not note.judged

    clock[0] = 1.0
    session.update(BodyState(), ready_to_start=True)
    assert note.judgement == HitQuality.PERFECT


def test_keyboard_press_can_score_late_great(monkeypatch):
    session, clock = _session(monkeypatch)
    session.set_keyboard_mode(True)
    note = session.notes[0]

    clock[0] = 1.20
    session.register_keyboard_press(NoteKind.FOOT, 2)
    session.update(BodyState(), ready_to_start=True)

    assert note.judgement == HitQuality.GREAT


def test_keyboard_start_request_begins_immediately(monkeypatch):
    import vaporstep.session as session_module

    monkeypatch.setattr(session_module.time, "monotonic", lambda: 10.0)
    session = GameSession(demo_notes=[GameNote(time=1.0, lanes=(2,), kind=NoteKind.FOOT)])

    session.update(BodyState(), ready_to_start=True, start_immediately=True)

    assert session.running


def test_keyboard_input_marks_run_separately(monkeypatch):
    session, clock = _session(monkeypatch)
    session.set_keyboard_mode(True)
    assert session.input_mode == "camera"

    clock[0] = 1.0
    session.register_keyboard_press(NoteKind.FOOT, 2)

    assert session.input_mode == "keyboard"


def test_completed_chart_can_skip_music_outro(monkeypatch):
    session, _clock = _session(monkeypatch)
    stopped = []
    monkeypatch.setattr("vaporstep.session._stop_music", lambda: stopped.append(True))
    session.stats.register_hit()

    assert session.scoring_complete
    assert session.finish_music_outro()
    assert session.finished
    # Keep the chart clock alive until the app records the completed run.
    assert session.running
    assert stopped == [True]


def test_music_outro_cannot_skip_before_scoring_finishes(monkeypatch):
    session, _clock = _session(monkeypatch)

    assert not session.scoring_complete
    assert not session.finish_music_outro()
    assert session.running


def test_chart_lead_in_starts_early_enough_for_first_note_to_enter_from_origin():
    from pathlib import Path
    from vaporstep.song import BeatMarker, ChartInfo, LoadedChart, SongInfo

    class _TimingEngine:
        @staticmethod
        def time_at(beat):
            return float(beat) * 0.5  # 120 BPM

        @staticmethod
        def beat_at(t):
            return float(t) * 2.0

    note = GameNote(time=1.0, beat=2.0, lanes=(2,), kind=NoteKind.FOOT)
    info = ChartInfo(index=0, difficulty="Medium", meter=5)
    song = SongInfo(
        simfile_path=Path("/tmp/lead.sm"),
        song_dir=Path("/tmp"),
        title="Lead",
        subtitle="",
        artist="",
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=(info,),
    )
    chart = LoadedChart(
        song=song,
        chart=info,
        notes=(note,),
        initial_bpm=120,
        last_note_time=1.0,
        beat_markers=(BeatMarker(0.0, 0),),
        timing_engine=_TimingEngine(),
    )
    session = GameSession(chart=chart)

    # First note is beat 2 and the playfield shows 8 beats ahead. Starting at
    # beat -6 (time -3s at 120 BPM) puts that note exactly at the origin.
    assert session._compute_lead_in_start_time() == -3.0


def test_demo_lead_in_uses_seconds_fallback():
    session = GameSession(demo_notes=[GameNote(time=2.0, lanes=(2,), kind=NoteKind.FOOT)])
    assert session._compute_lead_in_start_time() == -2.0


def test_ready_progress_tracks_prestart_hold(monkeypatch):
    import vaporstep.session as session_module

    clock = [20.0]
    monkeypatch.setattr(session_module.time, "monotonic", lambda: clock[0])
    session = GameSession(demo_notes=[GameNote(time=1.0, lanes=(2,), kind=NoteKind.HANDS)])
    assert session.ready_progress == 0.0

    session.update(BodyState(), ready_to_start=True)
    clock[0] += READY_HOLD_SECONDS / 2.0
    assert session.ready_progress == pytest.approx(0.5)


def test_session_pre_roll_delays_chart_zero_until_lead_in_finishes(monkeypatch):
    import vaporstep.session as session_module

    clock = [100.0]
    monkeypatch.setattr(session_module.time, "monotonic", lambda: clock[0])
    session = GameSession(demo_notes=[GameNote(time=2.0, lanes=(2,), kind=NoteKind.FOOT)])

    session._start(clock[0])
    assert session.running
    assert not session.audio_started
    assert session.time == -2.0

    clock[0] = 101.0
    assert session.time == -1.0

    # Crossing zero starts the song clock; no actual music is required for the
    # demo path, but chart time begins from zero rather than skipping ahead.
    clock[0] = 102.0
    session.update(BodyState(), ready_to_start=True)
    assert session.audio_started
    assert session.time == 0.0


def test_session_loads_music_at_pre_roll_start_and_only_plays_at_chart_zero(monkeypatch):
    from pathlib import Path

    import vaporstep.session as session_module
    from vaporstep.song import ChartInfo, LoadedChart, SongInfo

    calls: list[tuple[str, object]] = []

    class _Music:
        @staticmethod
        def load(path):
            calls.append(("load", path))

        @staticmethod
        def set_volume(volume):
            calls.append(("volume", volume))

        @staticmethod
        def play():
            calls.append(("play", None))

    monkeypatch.setattr(session_module.pygame.mixer, "music", _Music())
    note = GameNote(time=2.0, lanes=(2,), kind=NoteKind.FOOT)
    info = ChartInfo(index=0, difficulty="Medium", meter=5)
    song = SongInfo(
        simfile_path=Path("/tmp/preload.sm"),
        song_dir=Path("/tmp"),
        title="Preload",
        subtitle="",
        artist="",
        music_path=Path("/tmp/preload.ogg"),
        banner_path=None,
        background_path=None,
        charts=(info,),
    )
    session = GameSession(
        chart=LoadedChart(
            song=song,
            chart=info,
            notes=(note,),
            initial_bpm=120.0,
            last_note_time=2.0,
        )
    )

    session._start(100.0)

    assert calls == [
        ("load", str(song.music_path)),
        ("volume", session_module.GAMEPLAY_MUSIC_VOLUME),
    ]
    assert session.audio_loaded
    assert not session.audio_started

    session._start_audio_clock(102.0)

    assert calls[-1] == ("play", None)
    assert [name for name, _value in calls].count("load") == 1
    assert session.audio_started


def test_session_updates_only_notes_near_current_time(monkeypatch):
    notes = [
        GameNote(time=index * 0.05, lanes=(2,), kind=NoteKind.FOOT)
        for index in range(2000)
    ]
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(demo_notes=notes)
    session.running = True
    session.audio_started = True
    calls = []
    monkeypatch.setattr(
        session,
        "_update_regular_note",
        lambda note, body, t: calls.append(note.time),
    )

    session.update(BodyState(timestamp=1.0), ready_to_start=True)

    assert calls == [0.0, 0.05, 0.1]


def test_render_note_window_preserves_global_hand_ordinals() -> None:
    notes = [
        GameNote(
            time=float(index),
            lanes=(1,),
            kind=NoteKind.HANDS if index % 2 == 0 else NoteKind.FOOT,
        )
        for index in range(100)
    ]
    session = GameSession(demo_notes=notes)

    visible = session.render_notes(song_time=50.0, song_beat=100.0)
    visible_hands = [note for note in visible if note.kind == NoteKind.HANDS]

    assert len(visible) < len(session.notes)
    assert visible_hands
    assert visible_hands[0].visual_ordinal == 25


def test_new_hand_batch_restarts_with_pink_after_playfield_sized_gap() -> None:
    notes = [
        GameNote(time=beat * 0.5, beat=beat, lanes=(1,), kind=NoteKind.HANDS)
        for beat in (0.0, 1.0, 2.0, 11.0)
    ]

    session = GameSession(demo_notes=notes)

    assert [note.visual_ordinal % 2 for note in session.notes] == [0, 1, 0, 0]
