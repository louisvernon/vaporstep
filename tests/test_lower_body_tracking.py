from vaporstep.domain import BodyPoint
from vaporstep.pose_input import _LowerLegFilter


def test_lower_leg_filter_eases_ankle_weight_in_and_out():
    tracker = _LowerLegFilter()
    knee = BodyPoint(x=0.40, y=0.65, visible=True)
    ankle = BodyPoint(x=0.30, y=0.90, visible=True)

    _, _, first = tracker.update(knee=knee, ankle=ankle, raw_ankle_weight=0.45)
    _, _, second = tracker.update(knee=knee, ankle=ankle, raw_ankle_weight=0.45)
    _, _, fading = tracker.update(knee=knee, ankle=ankle, raw_ankle_weight=0.0)

    assert 0.0 < first < second < 0.45
    assert first < fading < second


def test_lower_leg_filter_limits_one_frame_horizontal_glitch():
    tracker = _LowerLegFilter()
    knee = BodyPoint(x=0.30, y=0.65, visible=True)
    ankle = BodyPoint(x=0.25, y=0.90, visible=True)
    first_x, _, _ = tracker.update(knee=knee, ankle=ankle, raw_ankle_weight=0.45)

    glitch_knee = BodyPoint(x=0.90, y=0.65, visible=True)
    glitch_ankle = BodyPoint(x=0.95, y=0.90, visible=True)
    second_x, _, _ = tracker.update(
        knee=glitch_knee,
        ankle=glitch_ankle,
        raw_ankle_weight=0.45,
    )

    # The output may move toward a sustained real movement, but not teleport
    # across the camera on one noisy pose sample.
    assert 0.0 < second_x - first_x < 0.10
