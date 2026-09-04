from __future__ import annotations

from dataclasses import dataclass

from .domain import BodyPoint, BodyState


@dataclass(frozen=True)
class FramingWarnings:
    top: bool = False
    bottom: bool = False


class FramingMonitor:
    """Detect when tracked limbs leave the camera frame during a run.

    Gameplay can keep using its confidence-weighted knee/ankle control point.
    This monitor deliberately locks the lower-body warning reference when play
    starts so that falling back to the knees cannot hide ankles leaving frame.
    """

    def __init__(self, *, grace_seconds: float = 0.5) -> None:
        self.grace_seconds = max(0.0, float(grace_seconds))
        self.reset()

    def reset(self) -> None:
        self._hands_armed = False
        self._lower_source: str | None = None
        self._hands_lost_since: float | None = None
        self._lower_lost_since: float | None = None

    @property
    def lower_source(self) -> str | None:
        return self._lower_source

    @staticmethod
    def _in_frame(point: BodyPoint) -> bool:
        return point.visible and 0.0 <= point.y <= 1.0

    @classmethod
    def _pair_in_frame(cls, points: tuple[BodyPoint, BodyPoint]) -> bool:
        return all(cls._in_frame(point) for point in points)

    @classmethod
    def _pair_lost(cls, points: tuple[BodyPoint, BodyPoint]) -> bool:
        return all(not cls._in_frame(point) for point in points)

    def start(
        self,
        body: BodyState,
        *,
        hands_enabled: bool,
        feet_enabled: bool,
    ) -> None:
        self.reset()
        if hands_enabled and self._pair_in_frame((body.left_wrist, body.right_wrist)):
            self._hands_armed = True
        if not feet_enabled:
            return
        if self._pair_in_frame((body.left_ankle, body.right_ankle)):
            self._lower_source = "ankles"
        elif self._pair_in_frame((body.left_knee, body.right_knee)):
            self._lower_source = "knees"

    @staticmethod
    def _update_loss_timer(
        lost: bool,
        since: float | None,
        now: float,
        grace_seconds: float,
    ) -> tuple[float | None, bool]:
        if not lost:
            return None, False
        if since is None:
            since = now
        return since, now - since + 1e-9 >= grace_seconds

    def update(
        self,
        body: BodyState,
        *,
        now: float,
        hands_enabled: bool,
        feet_enabled: bool,
    ) -> FramingWarnings:
        now = float(now)

        wrists = (body.left_wrist, body.right_wrist)
        if hands_enabled and not self._hands_armed and self._pair_in_frame(wrists):
            # Keyboard-started runs may acquire the camera pose after play starts.
            self._hands_armed = True
        self._hands_lost_since, top = self._update_loss_timer(
            hands_enabled and self._hands_armed and self._pair_lost(wrists),
            self._hands_lost_since,
            now,
            self.grace_seconds,
        )

        if feet_enabled and self._lower_source is None:
            # Prefer ankles whenever both are available at initial acquisition.
            if self._pair_in_frame((body.left_ankle, body.right_ankle)):
                self._lower_source = "ankles"
            elif self._pair_in_frame((body.left_knee, body.right_knee)):
                self._lower_source = "knees"

        if self._lower_source == "ankles":
            lower_points = (body.left_ankle, body.right_ankle)
        elif self._lower_source == "knees":
            lower_points = (body.left_knee, body.right_knee)
        else:
            lower_points = None
        self._lower_lost_since, bottom = self._update_loss_timer(
            feet_enabled and lower_points is not None and self._pair_lost(lower_points),
            self._lower_lost_since,
            now,
            self.grace_seconds,
        )

        return FramingWarnings(top=top, bottom=bottom)
