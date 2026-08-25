from vaporstep.domain import BodyPoint
from vaporstep.hand_control import HandPoseResolver


def point(x: float, y: float) -> BodyPoint:
    return BodyPoint(x=x, y=y, visible=True)


def shoulders():
    return point(0.40, 0.40), point(0.60, 0.40)


def test_neutral_wrist_does_not_occupy_a_lane():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver()
    sample = resolver.resolve(point(0.50, 0.48), left_shoulder, right_shoulder)
    assert sample.lane is None
    assert sample.visual.visible


def test_any_wrist_can_select_either_outer_segment():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver()

    assert resolver.resolve(point(0.34, 0.46), left_shoulder, right_shoulder).lane == 1
    resolver.reset()
    assert resolver.resolve(point(0.66, 0.46), left_shoulder, right_shoulder).lane == 4


def test_any_wrist_can_select_either_high_segment():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver()

    assert resolver.resolve(point(0.44, 0.30), left_shoulder, right_shoulder).lane == 2
    resolver.reset()
    assert resolver.resolve(point(0.56, 0.30), left_shoulder, right_shoulder).lane == 3


def test_cross_body_reach_can_select_opposite_side_segments():
    left_shoulder, right_shoulder = shoulders()
    left_wrist_resolver = HandPoseResolver()
    right_wrist_resolver = HandPoseResolver()

    # Resolver identity is irrelevant: either tracked wrist can occupy any lane.
    assert left_wrist_resolver.resolve(point(0.66, 0.46), left_shoulder, right_shoulder).lane == 4
    assert right_wrist_resolver.resolve(point(0.34, 0.46), left_shoulder, right_shoulder).lane == 1

    left_wrist_resolver.reset()
    right_wrist_resolver.reset()
    assert left_wrist_resolver.resolve(point(0.56, 0.30), left_shoulder, right_shoulder).lane == 3
    assert right_wrist_resolver.resolve(point(0.44, 0.30), left_shoulder, right_shoulder).lane == 2


def test_outer_hysteresis_keeps_segment_until_exit_threshold_is_crossed():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver()

    assert resolver.resolve(point(0.34, 0.46), left_shoulder, right_shoulder).lane == 1
    assert resolver.resolve(point(0.39, 0.46), left_shoulder, right_shoulder).lane == 1
    assert resolver.resolve(point(0.41, 0.46), left_shoulder, right_shoulder).lane is None


def test_high_hysteresis_keeps_raised_wrist_selected_during_small_drops():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver()

    assert resolver.resolve(point(0.44, 0.30), left_shoulder, right_shoulder).lane == 2
    assert resolver.resolve(point(0.44, 0.34), left_shoulder, right_shoulder).lane == 2
    assert resolver.resolve(point(0.44, 0.38), left_shoulder, right_shoulder).lane is None


def test_high_side_hysteresis_prevents_centerline_flicker():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver()

    assert resolver.resolve(point(0.46, 0.30), left_shoulder, right_shoulder).lane == 2
    # Slightly right of center remains lane 2 until crossing the side hysteresis.
    assert resolver.resolve(point(0.51, 0.30), left_shoulder, right_shoulder).lane == 2
    assert resolver.resolve(point(0.53, 0.30), left_shoulder, right_shoulder).lane == 3
