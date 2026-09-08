from __future__ import annotations

import pytest

from vaporstep.domain import BodyPoint, PoseFigure
from vaporstep.pose_presentation import (
    MAX_EXTRAPOLATION_SECONDS,
    PRESENTATION_INTERVAL_SECONDS,
    PosePresentationExtrapolator,
)


def _figure(x: float, *, visible: bool = True) -> PoseFigure:
    return PoseFigure((BodyPoint(x=x, y=0.5, visible=visible),))


def test_real_pose_is_always_shown_immediately() -> None:
    smoother = PosePresentationExtrapolator()
    smoother.observe(_figure(0.2), captured_at=1.0, observed_at=10.0)
    smoother.observe(_figure(0.4), captured_at=1.0 + 1.0 / 15.0, observed_at=11.0)

    assert smoother.figure_at(11.0).point(0).x == pytest.approx(0.4)
    assert smoother.figure_at(11.0 + PRESENTATION_INTERVAL_SECONDS * 0.9).point(0).x == pytest.approx(0.4)


def test_fifteen_fps_input_gets_one_thirty_fps_intermediate_pose() -> None:
    smoother = PosePresentationExtrapolator()
    capture_dt = 1.0 / 15.0
    smoother.observe(_figure(0.2), captured_at=1.0, observed_at=10.0)
    smoother.observe(_figure(0.4), captured_at=1.0 + capture_dt, observed_at=11.0)

    predicted = smoother.figure_at(11.0 + PRESENTATION_INTERVAL_SECONDS + 1e-6)

    # The latest real pose moved +0.2 over 1/15 s. One 1/30 s
    # presentation step therefore advances half that distance.
    assert predicted.point(0).x == pytest.approx(0.5, abs=1e-6)


def test_new_real_pose_replaces_prediction_without_correction_blend() -> None:
    smoother = PosePresentationExtrapolator()
    smoother.observe(_figure(0.2), captured_at=1.0, observed_at=10.0)
    smoother.observe(_figure(0.4), captured_at=1.1, observed_at=11.0)
    assert smoother.figure_at(11.04).point(0).x > 0.4

    smoother.observe(_figure(0.43), captured_at=1.2, observed_at=11.05)

    assert smoother.figure_at(11.05).point(0).x == pytest.approx(0.43)


def test_prediction_stops_after_two_thirty_fps_steps() -> None:
    smoother = PosePresentationExtrapolator()
    smoother.observe(_figure(0.0), captured_at=1.0, observed_at=10.0)
    smoother.observe(_figure(0.1), captured_at=1.1, observed_at=11.0)

    at_limit = smoother.figure_at(11.0 + MAX_EXTRAPOLATION_SECONDS + 1e-6)
    much_later = smoother.figure_at(12.0)

    assert at_limit.point(0).x == pytest.approx(0.1 + MAX_EXTRAPOLATION_SECONDS)
    assert much_later.point(0).x == pytest.approx(at_limit.point(0).x)


def test_invisible_landmark_is_never_extrapolated() -> None:
    smoother = PosePresentationExtrapolator()
    smoother.observe(_figure(0.2, visible=True), captured_at=1.0, observed_at=10.0)
    smoother.observe(_figure(0.8, visible=False), captured_at=1.1, observed_at=11.0)

    predicted = smoother.figure_at(11.1)

    assert predicted.point(0).x == pytest.approx(0.8)
    assert predicted.point(0).visible is False


def test_duplicate_snapshot_does_not_restart_prediction_clock() -> None:
    smoother = PosePresentationExtrapolator()
    smoother.observe(_figure(0.2), captured_at=1.0, observed_at=10.0)
    latest = _figure(0.4)
    smoother.observe(latest, captured_at=1.1, observed_at=11.0)
    smoother.observe(latest, captured_at=1.1, observed_at=11.03)

    predicted = smoother.figure_at(11.04)

    assert predicted.point(0).x > 0.4
