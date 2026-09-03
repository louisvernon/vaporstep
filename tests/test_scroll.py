import unittest

from vaporstep.domain import GameNote, NoteKind
from vaporstep.scroll import note_is_within_lookahead, note_progress


class ScrollTests(unittest.TestCase):
    def test_simfile_notes_scroll_in_beat_space(self):
        note = GameNote(time=99.0, lanes=(2,), kind=NoteKind.FOOT, beat=8.0)
        # Seconds are intentionally nonsensical here: source beat controls the
        # visual position for a real simfile note.
        self.assertAlmostEqual(note_progress(note, song_time=0.0, song_beat=0.0), 0.0)
        self.assertAlmostEqual(note_progress(note, song_time=0.0, song_beat=4.0), 0.5)
        self.assertAlmostEqual(note_progress(note, song_time=0.0, song_beat=8.0), 1.0)

    def test_beat_advancement_directly_changes_visual_speed(self):
        note = GameNote(time=4.0, lanes=(2,), kind=NoteKind.FOOT, beat=8.0)
        # If one second advances 2 beats (120 BPM), progress moves 0.25.
        p_120 = note_progress(note, song_time=1.0, song_beat=2.0)
        # If one second advances 4 beats (240 BPM), progress moves 0.50.
        p_240 = note_progress(note, song_time=1.0, song_beat=4.0)
        self.assertAlmostEqual(p_120, 0.25)
        self.assertAlmostEqual(p_240, 0.5)
        self.assertGreater(p_240, p_120)

    def test_lookahead_is_eight_beats_for_chart_notes(self):
        near = GameNote(time=100.0, lanes=(1,), kind=NoteKind.FOOT, beat=8.0)
        far = GameNote(time=0.1, lanes=(1,), kind=NoteKind.FOOT, beat=8.01)
        self.assertTrue(note_is_within_lookahead(near, song_time=0.0, song_beat=0.0))
        self.assertFalse(note_is_within_lookahead(far, song_time=0.0, song_beat=0.0))

    def test_demo_notes_keep_seconds_fallback(self):
        note = GameNote(time=4.0, lanes=(1,), kind=NoteKind.FOOT)
        self.assertAlmostEqual(note_progress(note, song_time=0.0, song_beat=0.0), 0.0)
        self.assertAlmostEqual(note_progress(note, song_time=2.0, song_beat=99.0), 0.5)

    def test_double_speed_halves_visual_lookahead_without_changing_hit_time(self):
        note = GameNote(time=4.0, lanes=(2,), kind=NoteKind.FOOT, beat=8.0)

        self.assertAlmostEqual(note_progress(note, 0.0, 4.0, speed=2.0), 0.0)
        self.assertAlmostEqual(note_progress(note, 0.0, 6.0, speed=2.0), 0.5)
        self.assertAlmostEqual(note_progress(note, 0.0, 8.0, speed=2.0), 1.0)


if __name__ == '__main__':
    unittest.main()
