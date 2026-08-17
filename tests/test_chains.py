from vaporstep.chains import MAX_CHAIN_GAP_BEATS, assign_implicit_chains
from vaporstep.domain import GameNote, NoteKind


def _note(beat: float, lane: int, *, kind=NoteKind.FOOT, lanes=None, hold=False):
    lanes = tuple(lanes) if lanes is not None else (lane,)
    return GameNote(
        time=beat * 0.5,
        beat=beat,
        lanes=lanes,
        kind=kind,
        end_time=(beat + 1.0) * 0.5 if hold else None,
    )


def test_three_repeated_targets_with_two_beat_gaps_form_chain():
    notes = [_note(0, 1), _note(2, 1), _note(4, 1)]
    chains = assign_implicit_chains(notes)
    assert len(chains) == 1
    assert chains[0].lanes == (1,)
    assert [n.chain_index for n in notes] == [0, 1, 2]


def test_gap_over_two_beats_breaks_implicit_chain():
    notes = [_note(0, 1), _note(1, 1), _note(1 + MAX_CHAIN_GAP_BEATS + 0.01, 1)]
    chains = assign_implicit_chains(notes)
    assert chains == ()
    assert all(n.chain_id is None for n in notes)


def test_explicit_holds_are_not_converted_to_implicit_chains():
    notes = [_note(0, 1, hold=True), _note(1, 1), _note(2, 1), _note(3, 1)]
    chains = assign_implicit_chains(notes)
    assert len(chains) == 1
    assert notes[0].chain_id is None


def test_conflicting_chain_is_rejected_when_it_would_need_three_feet():
    # Lane 1 can become a continuous chain. If lane 2 also became a chain,
    # the discrete lane-3 note during their overlap would require three feet.
    notes = [
        _note(0, 1), _note(1, 1), _note(2, 1),
        _note(0, 2), _note(1, 2), _note(2, 2),
        _note(1.5, 3),
    ]
    chains = assign_implicit_chains(notes)
    assert len(chains) == 1
    assert chains[0].lanes in ((1,), (2,))
    chained_lanes = {notes[i].lanes for i in chains[0].note_indices}
    assert len(chained_lanes) == 1


def test_explicit_hold_becomes_always_on_sustain_segment():
    from vaporstep.chains import assign_sustains
    from vaporstep.domain import SustainSource

    notes = [_note(0, 1, hold=True)]
    # The helper's hold also needs the parsed tail beat used for beat-space rendering.
    notes[0].end_beat = 1.0
    implicit, sustains = assign_sustains(notes)
    assert implicit == ()
    assert len(sustains) == 1
    assert sustains[0].source == SustainSource.EXPLICIT_HOLD
    assert sustains[0].start_beat == 0.0
    assert sustains[0].end_beat == 1.0
    assert notes[0].chain_id == sustains[0].id


def test_implicit_chain_rejected_when_hold_reservation_would_require_three_feet():
    # Lane 1 is held continuously while repeated lane-2 notes would otherwise
    # become an implicit chain. A lane-3 note during the overlap makes that
    # generated chain impossible with only two feet.
    hold = _note(0, 1, hold=True)
    hold.end_time = 2.0
    hold.end_beat = 4.0
    notes = [
        hold,
        _note(0, 2), _note(1, 2), _note(2, 2),
        _note(1.5, 3),
    ]
    chains = assign_implicit_chains(notes)
    assert chains == ()
