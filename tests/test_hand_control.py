from vaporstep.domain import BodyPoint
from vaporstep.hand_control import HandPoseResolver


def point(x: float, y: float) -> BodyPoint:
    return BodyPoint(x=x, y=y, visible=True)


def shoulders():
    return point(0.40, 0.40), point(0.60, 0.40)


def test_neutral_hands_do_not_occupy_a_lane():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver("left")
    sample = resolver.resolve(point(0.35, 0.48), left_shoulder, right_shoulder)
    assert sample.lane is None
    assert sample.visual.visible


def test_left_arm_maps_out_and_high_to_authored_lanes_one_and_two():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver("left")

    out = resolver.resolve(point(0.22, 0.43), left_shoulder, right_shoulder)
    assert out.lane == 1

    resolver.reset()
    high = resolver.resolve(point(0.38, 0.25), left_shoulder, right_shoulder)
    assert high.lane == 2


def test_right_arm_maps_high_and_out_to_authored_lanes_three_and_four():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver("right")

    high = resolver.resolve(point(0.62, 0.25), left_shoulder, right_shoulder)
    assert high.lane == 3

    resolver.reset()
    out = resolver.resolve(point(0.78, 0.43), left_shoulder, right_shoulder)
    assert out.lane == 4


def test_hysteresis_keeps_gesture_until_exit_threshold_is_crossed():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver("left")

    assert resolver.resolve(point(0.22, 0.43), left_shoulder, right_shoulder).lane == 1
    # Not far enough outward to newly enter lane 1, but still beyond OUT_EXIT.
    assert resolver.resolve(point(0.39, 0.43), left_shoulder, right_shoulder).lane == 1
    assert resolver.resolve(point(0.41, 0.45), left_shoulder, right_shoulder).lane is None


def test_diagonal_reach_chooses_more_decisive_gesture():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver("left")
    sample = resolver.resolve(point(0.24, 0.20), left_shoulder, right_shoulder)
    assert sample.lane in (1, 2)
