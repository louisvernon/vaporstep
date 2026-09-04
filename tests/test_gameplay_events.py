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

from vaporstep.domain import BodyPoint, BodyState, GameNote, GameplayEventType, HitQuality, NoteKind
from vaporstep.session import GameSession


def _body(ts: float, lane: int | None, *, y: float = 0.65) -> BodyState:
    return BodyState(
        left_knee=BodyPoint(x=0.3, y=y, lane=lane, visible=lane is not None),
        pose_visible=lane is not None,
        timestamp=ts,
    )


def test_perfect_judgement_emits_one_timing_audio_event(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(demo_notes=[GameNote(time=1.0, lanes=(1,), kind=NoteKind.FOOT)])
    session.running = True

    # Warm the motion baseline while already occupying the target lane.
    clock[0] = 0.90
    session.update(_body(1.00, 1, y=0.60), True)
    clock[0] = 1.00
    session.update(_body(1.05, 1, y=0.60), True)
    # Downward stomp 50 ms after the beat still earns PERFECT.
    clock[0] = 1.05
    session.update(_body(1.10, 1, y=0.66), True)

    events = session.drain_gameplay_events()
    assert len(events) == 1
    assert events[0].event_type == GameplayEventType.JUDGEMENT
    assert events[0].quality == HitQuality.PERFECT
    # Export reconstruction aligns the confirmation cue to the authored beat.
    assert events[0].time == 1.0


def test_early_great_emits_confirmation_at_the_note_time(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(demo_notes=[GameNote(time=1.0, lanes=(1,), kind=NoteKind.FOOT)])
    session.running = True

    # Establish a different lane, then enter the target lane 180 ms early.
    clock[0] = 0.60
    session.update(_body(0.60, 2), True)
    clock[0] = 0.82
    session.update(_body(0.82, 1), True)
    clock[0] = 0.93
    session.update(_body(0.93, 1), True)
    clock[0] = 0.94
    session.update(BodyState(), True)
    assert session.drain_gameplay_events() == ()

    # It remains provisional at the authored beat so a slightly late PERFECT
    # still has a chance to replace it.
    clock[0] = 1.00
    session.update(BodyState(), True)
    assert session.drain_gameplay_events() == ()

    # Once the late PERFECT edge passes, the stored entry resolves to GREAT and
    # produces one confirmation event aligned to the authored beat.
    clock[0] = 1.07
    session.update(BodyState(), True)
    events = session.drain_gameplay_events()
    assert len(events) == 1
    assert events[0].quality == HitQuality.GREAT
    assert events[0].time == 1.0


def test_basic_hit_is_silent(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(demo_notes=[GameNote(time=1.0, lanes=(1,), kind=NoteKind.FOOT)])
    session.running = True

    clock[0] = 0.90
    session.update(_body(0.90, 1), True)
    clock[0] = 1.16
    session.update(_body(1.16, 1), True)

    assert session.notes[0].judgement == HitQuality.HIT
    assert session.drain_gameplay_events() == ()


def test_miss_is_silent(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(demo_notes=[GameNote(time=1.0, lanes=(1,), kind=NoteKind.FOOT)])
    session.running = True

    clock[0] = 1.16
    session.update(_body(1.16, 2), True)
    assert session.drain_gameplay_events() == ()
    assert session.notes[0].judged and not session.notes[0].hit


def test_raw_in_lane_strike_is_silent_without_a_judgement(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(demo_notes=[])
    session.running = True

    clock[0] = 0.40
    session.update(_body(0.40, 1, y=0.60), True)
    clock[0] = 0.50
    session.update(_body(0.50, 1, y=0.66), True)

    assert session.drain_gameplay_events() == ()


def test_lane_entry_without_note_is_silent(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(demo_notes=[])
    session.running = True

    clock[0] = 0.40
    session.update(_body(0.40, 2), True)
    clock[0] = 0.50
    session.update(_body(0.50, 1), True)
    assert session.drain_gameplay_events() == ()
