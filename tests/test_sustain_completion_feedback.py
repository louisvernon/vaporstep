import pytest

from vaporstep.domain import (
    ChainState,
    ImplicitChain,
    NoteKind,
    RuntimeChain,
    SustainSource,
)
from vaporstep.gameplay_presentation_renderer import (
    SUSTAIN_COMPLETION_FEEDBACK_SECONDS,
    Renderer,
)
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


def _hold(*, duration: float, last_occupancy_at: float | None = None) -> RuntimeChain:
    return RuntimeChain(
        definition=ImplicitChain(
            id=1,
            kind=NoteKind.FOOT,
            lanes=(2,),
            note_indices=(0,),
            start_time=0.0,
            end_time=duration,
            start_beat=0.0,
            end_beat=duration * 2.0,
            source=SustainSource.EXPLICIT_HOLD,
        ),
        state=ChainState.ACTIVE,
        last_occupancy_at=last_occupancy_at,
    )


def test_sustain_charge_has_one_quiet_second_then_ramps_over_five_seconds():
    short = _hold(duration=0.8)
    medium = _hold(duration=3.5)
    long = _hold(duration=6.0)

    assert Renderer._nominal_sustain_charge(short, 0.8) == 0.0
    assert Renderer._nominal_sustain_charge(medium, 3.5) == pytest.approx(0.5)
    assert Renderer._nominal_sustain_charge(long, 6.0) == pytest.approx(1.0)
    assert Renderer._nominal_sustain_charge(long, 12.0) == pytest.approx(1.0)


def test_sustain_charge_freezes_and_drains_when_unoccupied_then_snaps_back():
    chain = _hold(duration=6.0, last_occupancy_at=3.5)

    frozen = Renderer._nominal_sustain_charge(chain, 3.5)
    drained = Renderer._sustain_charge(chain, 3.75, occupied=False)
    assert drained == pytest.approx(
        frozen * Renderer._sustain_presence(chain, 3.75)
    )
    assert drained < frozen

    # Re-entry immediately uses the current timeline charge rather than slowly
    # rebuilding from the drained visual value.
    assert Renderer._sustain_charge(chain, 4.0, occupied=True) == pytest.approx(0.6)


def test_sustain_completion_feedback_outlives_the_short_event_buffer():
    renderer = object.__new__(Renderer)
    renderer._sustain_completion_started = {}
    event = _event()

    assert renderer._active_sustain_completion_feedback((event,), 10.0) == (
        (NoteKind.FOOT, 2, 0.0),
    )

    # The synthetic event may disappear on the next session update. The visual
    # confirmation must nevertheless remain alive for its full own lifetime.
    active = renderer._active_sustain_completion_feedback((), 10.30)
    assert active[0][0:2] == (NoteKind.FOOT, 2)
    assert active[0][2] == pytest.approx(0.30)

    assert renderer._active_sustain_completion_feedback(
        (),
        10.0 + SUSTAIN_COMPLETION_FEEDBACK_SECONDS + 0.01,
    ) == ()
    assert renderer._sustain_completion_started == {}


def test_simultaneous_sustain_completion_feedback_tracks_each_lane():
    renderer = object.__new__(Renderer)
    renderer._sustain_completion_started = {}
    left = _event(NoteKind.HANDS, 2)
    right = _event(NoteKind.HANDS, 3)

    active = renderer._active_sustain_completion_feedback((left, right), 20.0)
    assert {(kind, lane) for kind, lane, _ in active} == {
        (NoteKind.HANDS, 2),
        (NoteKind.HANDS, 3),
    }


def test_sustain_completion_is_not_also_sent_to_generic_receptor_flash():
    normal = _event(source="keyboard")
    sustain = _event()

    assert Renderer._ordinary_strike_events((normal, sustain)) == (normal,)