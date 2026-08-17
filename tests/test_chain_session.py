import sys
from types import SimpleNamespace
from pathlib import Path


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

from vaporstep.chains import assign_implicit_chains
from vaporstep.domain import BodyPoint, BodyState, ChainMode, ChainState, GameNote, GameplayEventType, NoteKind
from vaporstep.session import GameSession
from vaporstep.song import ChartInfo, LoadedChart, SongInfo


def _body(ts: float, lane: int | None) -> BodyState:
    point = BodyPoint(x=0.3, y=0.65, lane=lane, visible=lane is not None)
    return BodyState(left_knee=point, pose_visible=lane is not None, timestamp=ts)


def _chart():
    notes = [
        GameNote(time=1.0, beat=2.0, lanes=(1,), kind=NoteKind.FOOT),
        GameNote(time=1.5, beat=3.0, lanes=(1,), kind=NoteKind.FOOT),
        GameNote(time=2.0, beat=4.0, lanes=(1,), kind=NoteKind.FOOT),
    ]
    chains = assign_implicit_chains(notes)
    info = ChartInfo(index=0, difficulty="Medium", meter=5)
    song = SongInfo(
        simfile_path=Path("/tmp/song.sm"),
        song_dir=Path("/tmp"),
        title="Song",
        subtitle="",
        artist="Artist",
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=(info,),
    )
    return LoadedChart(song=song, chart=info, notes=tuple(notes), initial_bpm=120, last_note_time=2.0, chains=chains)


def test_active_chain_continuations_do_not_require_new_timing_motion(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_chart(), chain_mode=ChainMode.BLOCKS)
    session.running = True

    clock[0] = 0.90
    session.update(_body(1.0, 1), True)
    clock[0] = 1.10
    session.update(_body(1.1, 1), True)
    assert session.notes[0].hit
    assert session.chains[0].state == ChainState.ACTIVE

    clock[0] = 1.50
    session.update(_body(1.5, 1), True)
    assert session.notes[1].hit
    assert session.notes[1].judgement.value == "hit"


def test_broken_chain_does_not_resume(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_chart(), chain_mode=ChainMode.BLOCKS)
    session.running = True

    clock[0] = 0.90
    session.update(_body(1.0, 1), True)
    clock[0] = 1.10
    session.update(_body(1.1, 1), True)
    assert session.chains[0].state == ChainState.ACTIVE

    # Stay away longer than the 200 ms tracking/dropout grace.
    clock[0] = 1.35
    session.update(_body(1.35, 2), True)
    assert session.chains[0].state == ChainState.BROKEN

    # Returning to the lane does not reactivate the chain.
    clock[0] = 1.61
    session.update(_body(1.61, 1), True)
    assert session.chains[0].state == ChainState.BROKEN
    assert session.notes[1].judged and not session.notes[1].hit


def _hold_chart():
    from vaporstep.chains import assign_sustains

    notes = [
        GameNote(
            time=1.0,
            beat=2.0,
            end_time=2.0,
            end_beat=4.0,
            lanes=(1,),
            kind=NoteKind.FOOT,
        )
    ]
    chains, sustains = assign_sustains(notes)
    info = ChartInfo(index=0, difficulty="Medium", meter=5)
    song = SongInfo(
        simfile_path=Path("/tmp/hold.sm"),
        song_dir=Path("/tmp"),
        title="Hold Song",
        subtitle="",
        artist="Artist",
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=(info,),
    )
    return LoadedChart(
        song=song,
        chart=info,
        notes=tuple(notes),
        initial_bpm=120,
        last_note_time=2.0,
        chains=chains,
        sustains=sustains,
    )


def test_explicit_hold_remains_active_when_implicit_chains_are_off(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_hold_chart(), chain_mode=ChainMode.OFF)
    session.running = True

    clock[0] = 0.90
    session.update(_body(0.90, 1), True)
    clock[0] = 1.10
    session.update(_body(1.10, 1), True)
    assert session.notes[0].hit
    assert session.chains[0].state == ChainState.ACTIVE

    clock[0] = 2.01
    session.update(_body(2.01, 1), True)
    assert session.chains[0].state == ChainState.COMPLETE
    assert session.stats.hits == 2  # timed head + virtual hold completion
    assert session.stats.misses == 0
    assert session.stats.total_notes == 2


def test_dropping_explicit_hold_breaks_combo_and_does_not_resume(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_hold_chart(), chain_mode=ChainMode.BLOCKS)
    session.running = True

    clock[0] = 0.90
    session.update(_body(0.90, 1), True)
    clock[0] = 1.10
    session.update(_body(1.10, 1), True)
    assert session.chains[0].state == ChainState.ACTIVE

    # Explicit holds deliberately get a 300 ms dropout/cross-step grace.
    clock[0] = 1.35
    session.update(_body(1.35, 2), True)
    assert session.chains[0].state == ChainState.ACTIVE
    assert session.stats.misses == 0
    events = session.drain_gameplay_events()
    assert all(event.event_type != GameplayEventType.SUSTAIN_BREAK for event in events)

    clock[0] = 1.41
    session.update(_body(1.41, 2), True)
    assert session.chains[0].state == ChainState.BROKEN
    assert session.stats.misses == 1
    assert session.stats.combo == 0

    clock[0] = 1.60
    session.update(_body(1.60, 1), True)
    assert session.chains[0].state == ChainState.BROKEN
    assert session.stats.misses == 1
