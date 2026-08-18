import unittest

from vaporstep.lanes import (
    HystereticLaneResolver,
    confidence_weight,
    lower_leg_control_position,
    perspective_adjusted_x,
    zoom_normalized_x,
)


class LaneResolverTests(unittest.TestCase):
    def setUp(self):
        self.r = HystereticLaneResolver(0.1, 0.9, lane_count=4, hysteresis=0.01)

    def test_basic_lane_mapping(self):
        self.assertEqual(self.r.raw_lane(0.15), 1)
        self.assertEqual(self.r.raw_lane(0.35), 2)
        self.assertEqual(self.r.raw_lane(0.55), 3)
        self.assertEqual(self.r.raw_lane(0.75), 4)

    def test_outside_playfield_is_none(self):
        self.assertIsNone(self.r.raw_lane(0.05))
        self.assertIsNone(self.r.raw_lane(0.95))

    def test_horizontal_zoom_expands_motion_around_center(self):
        self.assertAlmostEqual(zoom_normalized_x(0.5, 1.10), 0.5)
        self.assertAlmostEqual(zoom_normalized_x(0.2, 1.10), 0.17)
        self.assertAlmostEqual(zoom_normalized_x(0.8, 1.10), 0.83)
        self.assertEqual(zoom_normalized_x(0.0, 1.10), 0.0)
        self.assertEqual(zoom_normalized_x(1.0, 1.10), 1.0)

    def test_perspective_adjustment_is_zero_at_receptor_and_grows_toward_origin(self):
        kwargs = dict(
            playfield_left=0.14,
            playfield_right=0.86,
            hit_y=0.10,
            vanish_y=0.50,
            vanish_half_width=0.055,
            strength=0.35,
        )
        at_hit = perspective_adjusted_x(0.35, 0.10, **kwargs)
        halfway = perspective_adjusted_x(0.35, 0.30, **kwargs)
        near_origin = perspective_adjusted_x(0.35, 0.48, **kwargs)
        self.assertAlmostEqual(at_hit, 0.35)
        self.assertLess(halfway, at_hit)
        self.assertLess(near_origin, halfway)

    def test_perspective_adjustment_preserves_center_and_can_be_disabled(self):
        kwargs = dict(
            playfield_left=0.18,
            playfield_right=0.82,
            hit_y=0.90,
            vanish_y=0.50,
            vanish_half_width=0.055,
        )
        self.assertAlmostEqual(perspective_adjusted_x(0.5, 0.65, strength=0.35, **kwargs), 0.5)
        self.assertAlmostEqual(perspective_adjusted_x(0.25, 0.65, strength=0.0, **kwargs), 0.25)

    def test_outer_lane_assist_expands_only_outer_lanes(self):
        assisted = HystereticLaneResolver(0.1, 0.9, lane_count=4, hysteresis=0.01, outer_assist=0.10)
        self.assertAlmostEqual(assisted.boundary(1), 0.32)
        self.assertAlmostEqual(assisted.boundary(2), 0.50)
        self.assertAlmostEqual(assisted.boundary(3), 0.68)
        self.assertEqual(assisted.raw_lane(0.315), 1)
        self.assertEqual(assisted.raw_lane(0.325), 2)
        self.assertEqual(assisted.raw_lane(0.675), 3)
        self.assertEqual(assisted.raw_lane(0.685), 4)

    def test_outer_lane_assist_keeps_hysteresis(self):
        assisted = HystereticLaneResolver(0.1, 0.9, lane_count=4, hysteresis=0.01, outer_assist=0.10)
        self.assertEqual(assisted.resolve(0.40), 2)
        self.assertEqual(assisted.resolve(0.315), 2)
        self.assertEqual(assisted.resolve(0.309), 1)
        self.assertEqual(assisted.resolve(0.325), 1)
        self.assertEqual(assisted.resolve(0.331), 2)

    def test_outer_edge_extension_does_not_move_inner_boundaries(self):
        extended = HystereticLaneResolver(
            0.1, 0.9, lane_count=4, hysteresis=0.01, outer_assist=0.10, outer_extension=0.15
        )
        self.assertAlmostEqual(extended.boundary(1), 0.32)
        self.assertAlmostEqual(extended.boundary(2), 0.50)
        self.assertAlmostEqual(extended.boundary(3), 0.68)
        self.assertEqual(extended.raw_lane(0.075), 1)
        self.assertEqual(extended.raw_lane(0.925), 4)
        self.assertIsNone(extended.raw_lane(0.065))
        self.assertIsNone(extended.raw_lane(0.935))

    def test_hysteresis_prevents_boundary_flicker(self):
        self.assertEqual(self.r.resolve(0.25), 1)
        self.assertEqual(self.r.resolve(0.305), 1)
        self.assertEqual(self.r.resolve(0.309), 1)
        self.assertEqual(self.r.resolve(0.311), 2)
        self.assertEqual(self.r.resolve(0.295), 2)
        self.assertEqual(self.r.resolve(0.289), 1)


if __name__ == "__main__":
    unittest.main()


def test_confidence_weight_is_smooth_and_bounded():
    assert confidence_weight(0.10, 0.25, 0.70) == 0.0
    assert confidence_weight(0.25, 0.25, 0.70) == 0.0
    assert confidence_weight(0.70, 0.25, 0.70) == 1.0
    assert confidence_weight(0.90, 0.25, 0.70) == 1.0
    middle = confidence_weight(0.475, 0.25, 0.70)
    assert 0.45 < middle < 0.55


def test_lower_leg_control_uses_full_configured_blend_at_good_confidence():
    x, y, weight = lower_leg_control_position(
        0.40,
        0.66,
        0.34,
        0.88,
        ankle_confidence=0.90,
        ankle_blend=0.45,
        confidence_low=0.25,
        confidence_high=0.70,
    )
    assert abs(weight - 0.45) < 1e-9
    assert abs(x - (0.40 + (0.34 - 0.40) * 0.45)) < 1e-9
    assert abs(y - (0.66 + (0.88 - 0.66) * 0.45)) < 1e-9


def test_lower_leg_control_fades_by_confidence_not_camera_edge():
    near_edge = lower_leg_control_position(
        0.40, 0.66, 0.34, 1.03,
        ankle_confidence=0.90,
        ankle_blend=0.45,
        confidence_low=0.25,
        confidence_high=0.70,
    )
    marginal = lower_leg_control_position(
        0.40, 0.66, 0.34, 0.80,
        ankle_confidence=0.35,
        ankle_blend=0.45,
        confidence_low=0.25,
        confidence_high=0.70,
    )
    lost = lower_leg_control_position(
        0.40, 0.66, 0.34, 0.80,
        ankle_confidence=0.10,
        ankle_blend=0.45,
        confidence_low=0.25,
        confidence_high=0.70,
    )
    assert near_edge[2] == 0.45
    assert 0.0 < marginal[2] < near_edge[2]
    assert lost == (0.40, 0.66, 0.0)


def test_lower_control_point_naturally_gets_less_foot_perspective_correction():
    kwargs = dict(
        playfield_left=0.18,
        playfield_right=0.82,
        hit_y=0.90,
        vanish_y=0.50,
        vanish_half_width=0.055,
        strength=0.45,
    )
    knee_x = perspective_adjusted_x(0.35, 0.66, **kwargs)
    shin_x = perspective_adjusted_x(0.35, 0.78, **kwargs)
    assert knee_x < shin_x < 0.35
