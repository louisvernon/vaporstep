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

from vaporstep.chains import HOLD_OCCUPANCY_GRACE_SECONDS, assign_implicit_chains
from vaporstep.domain import BodyPoint, BodyState, ChainMode, ChainState, GameNote, GameplayEventType, NoteKind
from vaporstep.session import GameSession
from vaporstep.song import ChartInfo, LoadedChart, SongInfo


def _body(ts: float, lane: int | None) -> BodyState:
    point = BodyPoint(x=0.3, y=0.65, lane=lane, visible=lane is not None)
    return BodyState(left_knee=point, pose_visible=lane is not None, timestamp=ts)


def _song_info(path: str = "/tmp/song.sm") -> tuple[SongInfo, ChartInfo]:
    info = ChartInfo(index=0, difficulty="Medium", meter=5)
    song = SongInfo(
        simfile_path=Path(path),
        song_dir=Path("/tmp"),
        title="Song",
        subtitle="",
        artist="Artist",
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=(info,),
    )
    return song, info


def _chart():
    notes = [
        GameNote(time=1.0, beat=2.0, lanes=(1,), kind=NoteKind.FOOT),
        GameNote(time=1.5, beat=3.0, lanes=(1,), kind=NoteKind.FOOT),
        GameNote(time=2.0, beat=4.0, lanes=(1,), kind=NoteKind.FOOT),
    ]
    chains = assign_implicit_chains(notes)
    song, info = _song_info()
    return LoadedChart(
        song=song,
        chart=info,
        notes=tuple(notes),
        initial_bpm=120,
        last_note_time=2.0,
        chains=chains,
    )


def test_generated_chain_collapses_to_head_and_weighted_tail(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_chart(), chain_mode=ChainMode.BLOCKS)
    session.running = True

    assert session.stats.total_notes == 2
    assert session.stats.score_weights == (1.0, 2.0)

    clock[0] = 0.90
    session.update(_body(0.90, 1), True)
    clock[0] = 1.16
    session.update(_body(1.16, 1), True)
    assert session.notes[0].hit
    assert session.chains[0].state == ChainState.ACTIVE

    # Intermediate repeated steps are retained in the chart object, but are not
    # gameplay judgements while virtual holds are enabled.
    clock[0] = 1.60
    session.update(_body(1.60, 1), True)
    assert not session.notes[1].judged
    assert session.stats.hits == 1

    clock[0] = 2.01
    session.update(_body(2.01, 1), True)
    assert session.chains[0].state == ChainState.COMPLETE
    assert session.stats.hits == 2
    assert session.stats.misses == 0
    assert session.stats.dropped_holds == 0
    assert session.stats.combo == 2
    assert session.stats.score == 3000  # 1x head + 2x tail at combo 2


def test_chain_off_restores_individual_source_notes(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_chart(), chain_mode=ChainMode.OFF)
    session.running = True

    assert session.stats.total_notes == 3
    assert session.stats.score_weights == (1.0, 1.0, 1.0)

    for note_time, timestamp in ((1.0, 1.0), (1.5, 1.5), (2.0, 2.0)):
        clock[0] = note_time - 0.05
        session.update(_body(timestamp - 0.05, 1), True)
        clock[0] = note_time + 0.16
        session.update(_body(timestamp + 0.16, 1), True)

    assert all(note.judged and note.hit for note in session.notes)
    assert session.stats.hits == 3
    assert session.stats.combo == 3


def test_broken_generated_chain_preserves_combo_and_does_not_resume(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_chart(), chain_mode=ChainMode.BLOCKS)
    session.running = True

    clock[0] = 0.90
    session.update(_body(0.90, 1), True)
    last_occupancy = 1.16
    clock[0] = last_occupancy
    session.update(_body(last_occupancy, 1), True)
    assert session.chains[0].state == ChainState.ACTIVE
    assert session.stats.combo == 1

    # Grace starts at the last valid occupancy, not at the first bad frame.
    first_dropout = 1.40
    clock[0] = first_dropout
    session.update(_body(first_dropout, 2), True)
    assert session.chains[0].state == ChainState.ACTIVE

    before_break = last_occupancy + HOLD_OCCUPANCY_GRACE_SECONDS - 0.01
    clock[0] = before_break
    session.update(_body(before_break, 2), True)
    assert session.chains[0].state == ChainState.ACTIVE

    after_break = last_occupancy + HOLD_OCCUPANCY_GRACE_SECONDS + 0.01
    clock[0] = after_break
    session.update(_body(after_break, 2), True)
    assert session.chains[0].state == ChainState.BROKEN
    assert session.stats.combo == 1
    assert session.stats.misses == 0
    assert session.stats.dropped_holds == 0

    # Returning to the lane does not reactivate the sustain.
    clock[0] = after_break + 0.10
    session.update(_body(after_break + 0.10, 1), True)
    assert session.chains[0].state == ChainState.BROKEN

    # The single failed tail judgement hurts score/performance but not combo or timed misses.
    clock[0] = 2.01
    session.update(_body(2.01, 1), True)
    assert session.stats.misses == 0
    assert session.stats.dropped_holds == 1
    assert session.stats.combo == 1
    assert session.chains[0].completion_judged


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
    song, info = _song_info("/tmp/hold.sm")
    return LoadedChart(
        song=song,
        chart=info,
        notes=tuple(notes),
        initial_bpm=120,
        last_note_time=2.0,
        chains=chains,
        sustains=sustains,
    )


def test_explicit_hold_is_head_plus_weighted_tail_even_when_chains_are_off(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_hold_chart(), chain_mode=ChainMode.OFF)
    session.running = True

    assert session.stats.total_notes == 2
    assert session.stats.score_weights == (1.0, 2.0)

    clock[0] = 0.90
    session.update(_body(0.90, 1), True)
    clock[0] = 1.16
    session.update(_body(1.16, 1), True)
    assert session.notes[0].hit
    assert session.chains[0].state == ChainState.ACTIVE

    clock[0] = 2.01
    session.update(_body(2.01, 1), True)
    assert session.chains[0].state == ChainState.COMPLETE
    assert session.stats.hits == 2
    assert session.stats.misses == 0
    assert session.stats.dropped_holds == 0
    assert session.stats.total_notes == 2
    assert session.stats.score == 3000


def test_dropping_explicit_hold_preserves_combo_and_does_not_resume(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_hold_chart(), chain_mode=ChainMode.BLOCKS)
    session.running = True

    clock[0] = 0.90
    session.update(_body(0.90, 1), True)
    last_occupancy = 1.16
    clock[0] = last_occupancy
    session.update(_body(last_occupancy, 1), True)
    assert session.chains[0].state == ChainState.ACTIVE
    assert session.stats.combo == 1

    first_dropout = 1.40
    clock[0] = first_dropout
    session.update(_body(first_dropout, 2), True)
    assert session.chains[0].state == ChainState.ACTIVE
    assert session.stats.misses == 0
    events = session.drain_gameplay_events()
    assert all(event.event_type != GameplayEventType.SUSTAIN_BREAK for event in events)

    before_break = last_occupancy + HOLD_OCCUPANCY_GRACE_SECONDS - 0.01
    clock[0] = before_break
    session.update(_body(before_break, 2), True)
    assert session.chains[0].state == ChainState.ACTIVE

    after_break = last_occupancy + HOLD_OCCUPANCY_GRACE_SECONDS + 0.01
    clock[0] = after_break
    session.update(_body(after_break, 2), True)
    assert session.chains[0].state == ChainState.BROKEN
    assert session.stats.misses == 0
    assert session.stats.dropped_holds == 0
    assert session.stats.combo == 1

    clock[0] = after_break + 0.10
    session.update(_body(after_break + 0.10, 1), True)
    assert session.chains[0].state == ChainState.BROKEN

    clock[0] = 2.01
    session.update(_body(2.01, 1), True)
    assert session.stats.misses == 0
    assert session.stats.dropped_holds == 1
    assert session.stats.combo == 1


def test_missed_hold_head_breaks_combo_once_and_tail_does_not_break_it_again(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(chart=_hold_chart(), chain_mode=ChainMode.BLOCKS)
    session.running = True

    # Build a combo before the hold, then miss the head after the late window closes.
    session.stats.register_hit()
    session.stats.register_hit()
    assert session.stats.combo == 2

    clock[0] = 1.16
    session.update(_body(1.16, None), True)
    assert session.notes[0].judged and not session.notes[0].hit
    assert session.stats.combo == 0
    assert session.chains[0].state == ChainState.BROKEN

    # Rebuild a combo before the tail arrives.
    session.stats.register_hit()
    session.stats.register_hit()
    assert session.stats.combo == 2

    clock[0] = 2.01
    session.update(_body(2.01, None), True)
    assert session.stats.misses == 1  # missed head remains a timed-target miss
    assert session.stats.dropped_holds == 1  # failed tail is reported separately
    assert session.stats.combo == 2


def test_single_late_occupancy_sample_counts_as_fallback_hit(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    note = GameNote(time=1.0, beat=2.0, lanes=(1,), kind=NoteKind.FOOT)
    song, info = _song_info("/tmp/single.sm")
    chart = LoadedChart(
        song=song,
        chart=info,
        notes=(note,),
        initial_bpm=120,
        last_note_time=1.0,
    )
    session = GameSession(chart=chart)
    session.running = True

    # A single pose result arriving 140 ms late remains enough for the forgiving
    # fallback HIT, though it cannot earn timing quality without a longer stay.
    clock[0] = 1.14
    session.update(_body(1.14, 1), True)
    assert not session.notes[0].judged

    clock[0] = 1.16
    session.update(_body(1.16, None), True)
    assert session.notes[0].judged and session.notes[0].hit
