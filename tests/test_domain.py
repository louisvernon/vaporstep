import unittest

from vaporstep.domain import BodyPoint, BodyState, ChainMode, GameNote, NoteKind, occupancy_is_fresh


class SatisfactionTests(unittest.TestCase):
    def test_single_foot_note_accepts_either_knee(self):
        body = BodyState(left_knee=BodyPoint(lane=3, visible=True))
        self.assertTrue(GameNote(1.0, (3,), NoteKind.FOOT).is_satisfied(body))
        self.assertFalse(GameNote(1.0, (2,), NoteKind.FOOT).is_satisfied(body))

    def test_invisible_knee_does_not_count(self):
        body = BodyState(left_knee=BodyPoint(lane=3, visible=False))
        self.assertFalse(GameNote(1.0, (3,), NoteKind.FOOT).is_satisfied(body))

    def test_recent_occupancy_has_short_expiry(self):
        self.assertTrue(occupancy_is_fresh(10.00, 10.08, 0.10))
        self.assertFalse(occupancy_is_fresh(10.00, 10.11, 0.10))
        self.assertFalse(occupancy_is_fresh(None, 10.00, 0.10))

    def test_double_requires_two_hand_lanes(self):
        body = BodyState(
            left_wrist=BodyPoint(lane=1, visible=True),
            right_wrist=BodyPoint(lane=4, visible=True),
        )
        self.assertTrue(GameNote(1.0, (1, 4), NoteKind.HANDS).is_satisfied(body))
        self.assertFalse(GameNote(1.0, (1, 3), NoteKind.HANDS).is_satisfied(body))


if __name__ == "__main__":
    unittest.main()


def test_foot_lanes_prefer_virtual_control_points_when_present():
    body = BodyState(
        left_knee=BodyPoint(lane=1, visible=True),
        right_knee=BodyPoint(lane=4, visible=True),
        left_foot_control=BodyPoint(lane=2, visible=True),
        right_foot_control=BodyPoint(lane=3, visible=True),
    )
    assert body.foot_lanes == frozenset({2, 3})


def test_virtual_hold_mode_is_strictly_two_state():
    assert tuple(ChainMode) == (ChainMode.BLOCKS, ChainMode.OFF)
    assert ChainMode.BLOCKS.label == "ON"
    assert ChainMode.OFF.label == "OFF"
    assert ChainMode.BLOCKS.shifted() == ChainMode.OFF
    assert ChainMode.OFF.shifted() == ChainMode.BLOCKS
