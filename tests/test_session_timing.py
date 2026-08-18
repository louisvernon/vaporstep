import sys
from types import SimpleNamespace


class _FakeMusic:
    @staticmethod
    def stop():
        pass


class _FakeMixer:
    music = _FakeMusic()

    @staticmethod
    def get_init():
        return False


sys.modules.setdefault("pygame", SimpleNamespace(mixer=_FakeMixer()))

from vaporstep.domain import BodyPoint, BodyState, GameNote, HitQuality, NoteKind
from vaporstep.session import GameSession


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
