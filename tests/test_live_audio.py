import sys
from types import SimpleNamespace

import numpy as np

from vaporstep.audio_fx import GameplaySounds, _calibration_beat
from vaporstep.domain import GameplayEvent, GameplayEventType, HitQuality, NoteKind


def test_gameplay_hit_sound_is_created_before_first_judgement(monkeypatch):
    made_pcm = []
    play_calls = []

    class _Sound:
        @staticmethod
        def play():
            play_calls.append(True)

    fake_pygame = SimpleNamespace(
        mixer=SimpleNamespace(
            get_init=lambda: (44_100, -16, 2),
            init=lambda: None,
        ),
        sndarray=SimpleNamespace(
            make_sound=lambda pcm: made_pcm.append(pcm) or _Sound(),
        ),
    )
    monkeypatch.setitem(sys.modules, "pygame", fake_pygame)

    sounds = GameplaySounds()

    assert len(made_pcm) == 1
    events = [
        GameplayEvent(0.0, GameplayEventType.JUDGEMENT, NoteKind.FOOT, HitQuality.GREAT, True),
        GameplayEvent(0.0, GameplayEventType.JUDGEMENT, NoteKind.HANDS, HitQuality.PERFECT, True),
    ]
    sounds.play(events)

    assert len(made_pcm) == 1
    assert len(play_calls) == 2


def test_calibration_loop_has_distinct_safe_drum_steps():
    steps = [_calibration_beat(index, 44_100) for index in range(4)]

    assert len(steps[0]) > len(steps[1])
    assert len(steps[2]) > len(steps[3])
    assert all(np.isfinite(step).all() for step in steps)
    assert all(0.0 < np.max(np.abs(step)) < 1.0 for step in steps)
    assert not np.array_equal(steps[0], steps[2])
