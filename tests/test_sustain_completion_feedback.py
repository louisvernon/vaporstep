from vaporstep.gameplay_presentation_renderer import (
    SUSTAIN_COMPLETION_FLASH_SECONDS,
    Renderer,
)
from vaporstep.domain import NoteKind
from vaporstep.motion import MotionEvent


def _event(kind=NoteKind.FOOT, lane=2, *, source="sustain_complete"):
    return MotionEvent(
        kind=kind,
        lane=lane,
        song_time=9.5,
        limb="sustain",
        strength=2.2,
        source=source,
    )


def test_sustain_completion_flashes_note_shape_when_renderer_first_sees_event():
    renderer = object.__new__(Renderer)
    renderer._sustain_flash_started = {}
    calls = []
    renderer._draw_note_bar = lambda kind, lane, progress, color, hit: calls.append(
        ("foot", kind, lane, progress, color, hit)
    )
    renderer._draw_hand_note_arc = lambda lane, progress, color, highlight=False: calls.append(
        ("hand", lane, progress, color, highlight)
    )

    event = _event()

    # The scoring timestamp is deliberately old. The visual should still begin
    # at full brightness when the renderer first receives the completion event.
    renderer._draw_sustain_completion_flashes((event,), 10.0)
    assert calls[0][0:4] == ("foot", NoteKind.FOOT, 2, 1.0)
    assert calls[0][-1] is True

    renderer._draw_sustain_completion_flashes((event,), 10.10)
    assert calls[-1][0:4] == ("foot", NoteKind.FOOT, 2, 1.0)

    call_count = len(calls)
    renderer._draw_sustain_completion_flashes(
        (event,), 10.0 + SUSTAIN_COMPLETION_FLASH_SECONDS + 0.01
    )
    assert len(calls) == call_count

    # Once the event falls out of the session's recent-event list its renderer
    # bookkeeping is released, so a later distinct event can animate normally.
    renderer._draw_sustain_completion_flashes((), 10.40)
    assert renderer._sustain_flash_started == {}


def test_hand_sustain_completion_uses_hand_note_shape():
    renderer = object.__new__(Renderer)
    renderer._sustain_flash_started = {}
    calls = []
    renderer._draw_note_bar = lambda *args, **kwargs: calls.append(("foot", args, kwargs))
    renderer._draw_hand_note_arc = lambda lane, progress, color, highlight=False: calls.append(
        ("hand", lane, progress, highlight)
    )

    renderer._draw_sustain_completion_flashes(
        (_event(NoteKind.HANDS, 3),),
        20.0,
    )

    assert calls == [("hand", 3, 1.0, True)]


def test_sustain_completion_is_not_also_sent_to_generic_receptor_flash():
    normal = _event(source="keyboard")
    sustain = _event()

    assert Renderer._ordinary_strike_events((normal, sustain)) == (normal,)
