from __future__ import annotations

from dataclasses import dataclass

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
VISUAL_RANGE = 1.45


@dataclass(frozen=True)
class HandControlSample:
    lane: int | None
    visual: BodyPoint
    high_amount: float
    horizontal_amount: float


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

        # Retain normalized controller-space coordinates for diagnostics and
        # possible future UI work. Gameplay currently uses segment highlighting.
        visual_x = max(0.0, min(1.0, 0.5 + dx / (2.0 * VISUAL_RANGE)))
        visual_y = max(0.0, min(1.0, 0.5 - up / (2.0 * VISUAL_RANGE)))
        visual = BodyPoint(x=visual_x, y=visual_y, lane=lane, visible=True)
        return HandControlSample(lane, visual, high_amount, horizontal_amount)
