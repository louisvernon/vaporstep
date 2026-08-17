import unittest

from vaporstep.lanes import HystereticLaneResolver, perspective_adjusted_x, zoom_normalized_x


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
        # Nominal width is 0.20, so the outside boundaries move inward by 0.02.
        self.assertAlmostEqual(assisted.boundary(1), 0.32)
        self.assertAlmostEqual(assisted.boundary(2), 0.50)
        self.assertAlmostEqual(assisted.boundary(3), 0.68)
        self.assertEqual(assisted.raw_lane(0.315), 1)
        self.assertEqual(assisted.raw_lane(0.325), 2)
        self.assertEqual(assisted.raw_lane(0.675), 3)
        self.assertEqual(assisted.raw_lane(0.685), 4)

    def test_outer_lane_assist_keeps_hysteresis(self):
        assisted = HystereticLaneResolver(0.1, 0.9, lane_count=4, hysteresis=0.01, outer_assist=0.10)
        # Start in lane 2. The assisted 1↔2 boundary is 0.32; moving left must
        # cross below 0.31 to enter lane 1.
        self.assertEqual(assisted.resolve(0.40), 2)
        self.assertEqual(assisted.resolve(0.315), 2)
        self.assertEqual(assisted.resolve(0.309), 1)
        # Coming back out must cross above 0.33.
        self.assertEqual(assisted.resolve(0.325), 1)
        self.assertEqual(assisted.resolve(0.331), 2)


    def test_outer_edge_extension_does_not_move_inner_boundaries(self):
        extended = HystereticLaneResolver(
            0.1, 0.9, lane_count=4, hysteresis=0.01, outer_assist=0.10, outer_extension=0.15
        )
        # Nominal lane width is 0.20, so only the outside acceptance edges
        # extend by 0.03. Interior assisted boundaries are unchanged.
        self.assertAlmostEqual(extended.boundary(1), 0.32)
        self.assertAlmostEqual(extended.boundary(2), 0.50)
        self.assertAlmostEqual(extended.boundary(3), 0.68)
        self.assertEqual(extended.raw_lane(0.075), 1)
        self.assertEqual(extended.raw_lane(0.925), 4)
        self.assertIsNone(extended.raw_lane(0.065))
        self.assertIsNone(extended.raw_lane(0.935))

    def test_hysteresis_prevents_boundary_flicker(self):
        # Boundary 1/2 is x=0.30.
        self.assertEqual(self.r.resolve(0.25), 1)
        self.assertEqual(self.r.resolve(0.305), 1)
        self.assertEqual(self.r.resolve(0.309), 1)
        self.assertEqual(self.r.resolve(0.311), 2)
        self.assertEqual(self.r.resolve(0.295), 2)
        self.assertEqual(self.r.resolve(0.289), 1)


if __name__ == "__main__":
    unittest.main()


def test_lower_leg_control_uses_ankle_when_reliable_and_in_frame():
    from vaporstep.lanes import lower_leg_control_position

    x, y, weight = lower_leg_control_position(
        0.40,
        0.66,
        0.34,
        0.88,
        ankle_reliable=True,
        ankle_blend=0.45,
        edge_fade_start=0.92,
        edge_fade_end=1.02,
    )
    assert abs(weight - 0.45) < 1e-9
    assert abs(x - (0.40 + (0.34 - 0.40) * 0.45)) < 1e-9
    assert abs(y - (0.66 + (0.88 - 0.66) * 0.45)) < 1e-9


def test_lower_leg_control_fades_to_knee_near_bottom_edge():
    from vaporstep.lanes import lower_leg_control_position

    full = lower_leg_control_position(
        0.40, 0.66, 0.34, 0.90,
        ankle_reliable=True,
        ankle_blend=0.45,
        edge_fade_start=0.92,
        edge_fade_end=1.02,
    )
    edge = lower_leg_control_position(
        0.40, 0.66, 0.34, 0.97,
        ankle_reliable=True,
        ankle_blend=0.45,
        edge_fade_start=0.92,
        edge_fade_end=1.02,
    )
    lost = lower_leg_control_position(
        0.40, 0.66, 0.34, 1.03,
        ankle_reliable=True,
        ankle_blend=0.45,
        edge_fade_start=0.92,
        edge_fade_end=1.02,
    )
    assert full[2] == 0.45
    assert 0.0 < edge[2] < full[2]
    assert lost == (0.40, 0.66, 0.0)


def test_lower_leg_control_falls_back_to_knee_when_ankle_unreliable():
    from vaporstep.lanes import lower_leg_control_position

    assert lower_leg_control_position(
        0.40, 0.66, 0.10, 0.85,
        ankle_reliable=False,
    ) == (0.40, 0.66, 0.0)


def test_lower_control_point_naturally_gets_less_foot_perspective_correction():
    from vaporstep.lanes import perspective_adjusted_x

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
    # Left-of-center points project farther left near the vanishing point. A
    # lower shin point is closer to receptor-space, so it stays closer to the
    # original X than the knee does.
    assert knee_x < shin_x < 0.35
