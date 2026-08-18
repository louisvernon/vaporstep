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
    def test_basic_occupancy_grace_allows_more_late_camera_latency(self):
        self.assertAlmostEqual(OCCUPANCY_GRACE_SECONDS, 0.10)
        self.assertAlmostEqual(HIT_WINDOW_SECONDS, 0.15)
        self.assertGreater(HIT_WINDOW_SECONDS, OCCUPANCY_GRACE_SECONDS)

    def test_hand_playfield_is_wider_than_foot_playfield(self):
        hand_width = HAND_PLAYFIELD_RIGHT - HAND_PLAYFIELD_LEFT
        foot_width = FOOT_PLAYFIELD_RIGHT - FOOT_PLAYFIELD_LEFT
        self.assertGreater(hand_width, foot_width)


if __name__ == "__main__":
    unittest.main()
