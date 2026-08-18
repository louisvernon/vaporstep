from vaporstep.domain import BodyPoint
from vaporstep.pose_input import _LowerLegFilter


def test_lower_leg_filter_eases_ankle_weight_in_and_out():
    tracker = _LowerLegFilter()
    knee = BodyPoint(x=0.40, y=0.65, visible=True)
    ankle = BodyPoint(x=0.30, y=0.90, visible=True)

    _, _, first = tracker.update(knee=knee, ankle=ankle, raw_ankle_weight=0.55)
    _, _, second = tracker.update(knee=knee, ankle=ankle, raw_ankle_weight=0.55)
    _, _, fading = tracker.update(knee=knee, ankle=ankle, raw_ankle_weight=0.0)

    assert 0.0 < first < second < 0.55
    assert first < fading < second


def test_lower_leg_filter_does_not_lag_current_position():
    tracker = _LowerLegFilter()
    knee = BodyPoint(x=0.30, y=0.65, visible=True)
    ankle = BodyPoint(x=0.25, y=0.90, visible=True)
    tracker.update(knee=knee, ankle=ankle, raw_ankle_weight=0.55)

    moved_knee = BodyPoint(x=0.70, y=0.65, visible=True)
    moved_ankle = BodyPoint(x=0.75, y=0.90, visible=True)
    x, y, weight = tracker.update(
        knee=moved_knee,
        ankle=moved_ankle,
        raw_ankle_weight=0.55,
    )

    assert x == moved_knee.x + (moved_ankle.x - moved_knee.x) * weight
    assert y == moved_knee.y + (moved_ankle.y - moved_knee.y) * weight
