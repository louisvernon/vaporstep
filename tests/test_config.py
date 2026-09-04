import unittest

from vaporstep.config import (
    FOOT_PLAYFIELD_LEFT,
    FOOT_PLAYFIELD_RIGHT,
    HAND_PLAYFIELD_LEFT,
    HAND_PLAYFIELD_RIGHT,
    HIT_WINDOW_SECONDS,
    OCCUPANCY_GRACE_SECONDS,
)


class PlayfieldConfigTests(unittest.TestCase):
    def test_basic_occupancy_is_more_forgiving_early_than_late(self):
        self.assertAlmostEqual(OCCUPANCY_GRACE_SECONDS, 0.20)
        self.assertAlmostEqual(HIT_WINDOW_SECONDS, 0.15)
        self.assertGreater(OCCUPANCY_GRACE_SECONDS, HIT_WINDOW_SECONDS)

    def test_hand_playfield_is_wider_than_foot_playfield(self):
        hand_width = HAND_PLAYFIELD_RIGHT - HAND_PLAYFIELD_LEFT
        foot_width = FOOT_PLAYFIELD_RIGHT - FOOT_PLAYFIELD_LEFT
        self.assertGreater(hand_width, foot_width)


if __name__ == "__main__":
    unittest.main()
