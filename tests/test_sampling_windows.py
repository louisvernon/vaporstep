import sys
from types import SimpleNamespace


class _FakeMusic:
    @staticmethod
    def stop():
        pass

    @staticmethod
    def get_pos():
        return -1

    @staticmethod
    def get_busy():
        return False


class _FakeMixer:
    music = _FakeMusic()

    @staticmethod
    def get_init():
        return False


sys.modules.setdefault("pygame", SimpleNamespace(mixer=_FakeMixer(), error=RuntimeError))

from vaporstep.adaptive_sampling import set_timing_critical, timing_critical
from vaporstep.domain import BodyState, GameNote, NoteKind
from vaporstep.session import GameSession


def test_session_publishes_camera_scoring_window(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(GameSession, "time", property(lambda self: clock[0]))
    session = GameSession(demo_notes=[GameNote(time=1.0, lanes=(1,), kind=NoteKind.FOOT)])
    session.running = True

    clock[0] = 0.60
    session.update(BodyState(), True)
    assert timing_critical() is False

    clock[0] = 0.71
    session.update(BodyState(), True)
    assert timing_critical() is True

    clock[0] = 1.16
    session.update(BodyState(), True)
    assert timing_critical() is False
    set_timing_critical(False)


def test_stopped_session_clears_sampling_window():
    set_timing_critical(True)
    session = GameSession(demo_notes=[])
    session.running = True

    session.stop()

    assert timing_critical() is False
