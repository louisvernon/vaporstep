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
    high = resolver.resolve(point(0.38, 0.30), left_shoulder, right_shoulder)
    assert high.lane == 2


def test_right_arm_maps_high_and_out_to_authored_lanes_three_and_four():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver("right")

    high = resolver.resolve(point(0.62, 0.30), left_shoulder, right_shoulder)
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


def test_raised_hand_wins_even_when_it_is_far_outward():
    left_shoulder, right_shoulder = shoulders()
    left = HandPoseResolver("left")
    right = HandPoseResolver("right")

    # These are deliberately very lateral as well as raised. HIGH should be a
    # simple raise gesture, not require the wrist to move horizontally over the
    # head or compete with the OUT gesture.
    assert left.resolve(point(0.20, 0.29), left_shoulder, right_shoulder).lane == 2
    assert right.resolve(point(0.80, 0.29), left_shoulder, right_shoulder).lane == 3


def test_high_hysteresis_keeps_a_raised_hand_selected_during_small_drops():
    left_shoulder, right_shoulder = shoulders()
    resolver = HandPoseResolver("left")

    assert resolver.resolve(point(0.34, 0.30), left_shoulder, right_shoulder).lane == 2
    # Below the entry threshold, but still above the lower HIGH exit threshold.
    assert resolver.resolve(point(0.34, 0.34), left_shoulder, right_shoulder).lane == 2
    assert resolver.resolve(point(0.34, 0.36), left_shoulder, right_shoulder).lane is None
