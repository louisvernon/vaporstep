from __future__ import annotations

from dataclasses import dataclass
import time

from .domain import BodyPoint, PoseFigure


PRESENTATION_FPS = 30.0
PRESENTATION_INTERVAL_SECONDS = 1.0 / PRESENTATION_FPS
MAX_EXTRAPOLATION_STEPS = 2
MAX_EXTRAPOLATION_SECONDS = PRESENTATION_INTERVAL_SECONDS * MAX_EXTRAPOLATION_STEPS


@dataclass(frozen=True)
class _RealPoseSample:
    figure: PoseFigure
    captured_at: float
    observed_at: float


class PosePresentationExtrapolator:
    """Generate display-only intermediate pose frames from real pose samples.

    Real MediaPipe results are always authoritative and are displayed unchanged
    as soon as the renderer observes them. Between real results, the character
    can advance on a fixed 30 Hz presentation timeline using constant velocity
    estimated from the two newest real capture-time samples.

    Prediction is deliberately short lived: at most two 30 Hz presentation
    steps are generated before the pose is held. This never feeds scoring,
    occupancy, motion detection, or the authoritative BodyState.
    """

    def __init__(self) -> None:
        self._previous: _RealPoseSample | None = None
        self._latest: _RealPoseSample | None = None

    def reset(self) -> None:
        self._previous = None
        self._latest = None

    def observe(
        self,
        figure: PoseFigure,
        *,
        captured_at: float,
        observed_at: float | None = None,
    ) -> None:
        captured_at = float(captured_at)
        if captured_at <= 0.0:
            return
        now = time.monotonic() if observed_at is None else float(observed_at)

        if self._latest is not None:
            if captured_at == self._latest.captured_at:
                # The renderer commonly sees the same camera snapshot for
                # several display frames. Do not restart prediction timing.
                return
            if captured_at < self._latest.captured_at:
                # MediaPipe is expected to remain chronological. Ignore stale
                # presentation input rather than rewinding the character.
                return
            self._previous = self._latest

        self._latest = _RealPoseSample(
            figure=figure,
            captured_at=captured_at,
            observed_at=now,
        )

    def figure_at(self, now: float | None = None) -> PoseFigure | None:
        latest = self._latest
        if latest is None:
            return None
        previous = self._previous
        if previous is None:
            return latest.figure

        current_time = time.monotonic() if now is None else float(now)
        elapsed_since_real = max(0.0, current_time - latest.observed_at)
        steps = min(
            MAX_EXTRAPOLATION_STEPS,
            int(elapsed_since_real / PRESENTATION_INTERVAL_SECONDS),
        )
        if steps <= 0:
            return latest.figure

        sample_dt = latest.captured_at - previous.captured_at
        if sample_dt <= 1e-6:
            return latest.figure

        prediction_dt = steps * PRESENTATION_INTERVAL_SECONDS
        ratio = min(MAX_EXTRAPOLATION_SECONDS, prediction_dt) / sample_dt
        return _extrapolate_figure(previous.figure, latest.figure, ratio)


def _extrapolate_figure(
    previous: PoseFigure,
    latest: PoseFigure,
    ratio: float,
) -> PoseFigure:
    points: list[BodyPoint] = []
    for index, current in enumerate(latest.landmarks):
        prior = previous.point(index)
        if not current.visible or not prior.visible:
            points.append(current)
            continue

        points.append(
            BodyPoint(
                x=current.x + (current.x - prior.x) * ratio,
                y=current.y + (current.y - prior.y) * ratio,
                lane=current.lane,
                visible=current.visible,
                source_weight=current.source_weight,
            )
        )
    return PoseFigure(tuple(points))
