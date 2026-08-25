from __future__ import annotations

from dataclasses import dataclass
import math

from .domain import BodyPoint


# Both wrists use this same body-relative four-segment map:
# 1 = low/out left, 2 = high left, 3 = high right, 4 = low/out right.
# Thresholds are expressed in shoulder-width units so translation and camera
# distance largely divide out.
HIGH_ENTER = 0.24
HIGH_EXIT = 0.12
OUT_ENTER = 0.72
OUT_EXIT = 0.50
HIGH_SIDE_HYSTERESIS = 0.10


@dataclass(frozen=True)
class HandControlSample:
    lane: int | None
    control: BodyPoint
    high_amount: float
    horizontal_amount: float

    @property
    def visual(self) -> BodyPoint:
        """Compatibility alias for the canonical body-relative control point."""
        return self.control


def hand_control_perimeter_along(control: BodyPoint) -> float:
    """Project canonical hand-control coordinates onto the tunnel perimeter.

    ``control.x`` is horizontal displacement divided by the OUT entry threshold
    and clamped to -1..1. ``control.y`` is upward displacement divided by the
    HIGH entry threshold. Because the renderer uses these same threshold-scaled
    coordinates, the non-hysteretic gesture boundaries naturally line up with
    the four visual hand segments. Hysteresis may legitimately let the resolved
    lane lag the continuous marker slightly at a boundary.
    """
    x = max(-1.0, min(1.0, float(control.x)))
    y = max(0.0, float(control.y))
    angle = math.atan2(y, x)
    return max(0.0, min(1.0, 1.0 - angle / math.pi))


class HandPoseResolver:
    """Resolve either wrist into one body-relative hand-playfield segment."""

    def __init__(self) -> None:
        self.current_lane: int | None = None

    def reset(self) -> None:
        self.current_lane = None

    def resolve(
        self,
        wrist: BodyPoint,
        left_shoulder: BodyPoint,
        right_shoulder: BodyPoint,
    ) -> HandControlSample:
        if not (wrist.visible and left_shoulder.visible and right_shoulder.visible):
            self.current_lane = None
            return HandControlSample(None, BodyPoint(), 0.0, 0.0)

        shoulder_width = abs(right_shoulder.x - left_shoulder.x)
        if shoulder_width < 0.035:
            self.current_lane = None
            return HandControlSample(None, BodyPoint(), 0.0, 0.0)

        center_x = (left_shoulder.x + right_shoulder.x) * 0.5
        shoulder_y = (left_shoulder.y + right_shoulder.y) * 0.5
        dx = (wrist.x - center_x) / shoulder_width
        up = (shoulder_y - wrist.y) / shoulder_width
        high_amount = max(0.0, up)
        horizontal_amount = abs(dx)

        was_high = self.current_lane in (2, 3)
        high_threshold = HIGH_EXIT if was_high else HIGH_ENTER
        if high_amount >= high_threshold:
            # HIGH is primarily a vertical gesture. Once raised, horizontal
            # position only selects the left or right upper segment. Keep a
            # small center-line hysteresis band so an almost-centered wrist does
            # not flicker between lanes 2 and 3.
            if self.current_lane == 2 and dx <= HIGH_SIDE_HYSTERESIS:
                lane = 2
            elif self.current_lane == 3 and dx >= -HIGH_SIDE_HYSTERESIS:
                lane = 3
            else:
                lane = 2 if dx < 0.0 else 3
        else:
            # Low hands stay neutral around the torso. Crossing far enough left
            # or right selects the corresponding OUT segment, regardless of
            # which physical wrist made the reach.
            if self.current_lane == 1:
                lane = 1 if dx <= -OUT_EXIT else None
            elif self.current_lane == 4:
                lane = 4 if dx >= OUT_EXIT else None
            elif dx <= -OUT_ENTER:
                lane = 1
            elif dx >= OUT_ENTER:
                lane = 4
            else:
                lane = None

        self.current_lane = lane

        # Canonical continuous controller coordinates. These are deliberately
        # expressed in the resolver's own threshold units rather than arbitrary
        # screen units, so visualization and classification share one geometry.
        control_x = max(-1.0, min(1.0, dx / OUT_ENTER))
        control_y = max(0.0, up / HIGH_ENTER)
        control = BodyPoint(
            x=control_x,
            y=control_y,
            lane=lane,
            visible=True,
        )
        return HandControlSample(lane, control, high_amount, horizontal_amount)
