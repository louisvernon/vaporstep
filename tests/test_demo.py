from vaporstep.demo import make_demo_notes


def test_calibration_notes_land_on_strong_120_bpm_beats() -> None:
    notes = make_demo_notes()

    assert [note.time for note in notes] == [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    assert all((note.time * 2.0) % 2.0 == 0.0 for note in notes)
