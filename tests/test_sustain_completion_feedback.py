from vaporstep.calibration_renderer import Renderer
from vaporstep.domain import HitQuality, NoteKind
from vaporstep.motion import MotionEvent


def test_sustain_completion_pop_starts_when_renderer_first_sees_event():
    renderer = object.__new__(Renderer)
    renderer._sustain_pop_started = {}
    calls = []
    renderer._draw_hit_pop_bar = lambda kind, lane, age, quality: calls.append(
        (kind, lane, age, quality)
    )
    renderer._draw_hand_hit_pop = lambda lane, age, quality: calls.append(
        (NoteKind.HANDS, lane, age, quality)
    )

    event = MotionEvent(
        kind=NoteKind.FOOT,
        lane=2,
        song_time=9.5,
        limb="sustain",
        strength=2.2,
        source="sustain_complete",
    )

    # The scoring timestamp is deliberately old. The visual should still begin
    # at age zero the first time the renderer receives the completion event.
    renderer._draw_sustain_completion_pops((event,), 10.0)
    assert calls == [(NoteKind.FOOT, 2, 0.0, HitQuality.HIT)]

    renderer._draw_sustain_completion_pops((event,), 10.08)
    assert calls[-1][0:2] == (NoteKind.FOOT, 2)
    assert 0.079 < calls[-1][2] < 0.081

    call_count = len(calls)
    renderer._draw_sustain_completion_pops((event,), 10.30)
    assert len(calls) == call_count

    # Once the event falls out of the session's recent-event list its renderer
    # bookkeeping is released, so a later distinct event can animate normally.
    renderer._draw_sustain_completion_pops((), 10.31)
    assert renderer._sustain_pop_started == {}
