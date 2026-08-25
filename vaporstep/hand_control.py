from __future__ import annotations

from dataclasses import dataclass

from .domain import BodyPoint


# Four authored hand lanes become four body-relative gestures:
# 1 left/out, 2 left/high, 3 right/high, 4 right/out.
# Thresholds are expressed in shoulder-width units so body translation and
# player/camera distance largely divide out.
HIGH_ENTER = 0.62
HIGH_EXIT = 0.44
OUT_ENTER = 0.72
OUT_EXIT = 0.50
VISUAL_RANGE = 1.45


@dataclass(frozen=True)
class HandControlSample:
    lane: int | None
    visual: BodyPoint
    high_amount: float
    out_amount: float


class HandPoseResolver:
    """Resolve one wrist into neutral, high, or outward body-relative state."""

    def __init__(self, side: str) -> None:
        if side not in ("left", "right"):
            raise ValueError("side must be left or right")
        self.side = side
        self.current_lane: int | None = None

    @property
    def high_lane(self) -> int:
        return 2 if self.side == "left" else 3

    @property
    def out_lane(self) -> int:
        return 1 if self.side == "left" else 4

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
        outward = -dx if self.side == "left" else dx
        high_amount = max(0.0, up)
        out_amount = max(0.0, outward)

        lane = self.current_lane
        if lane == self.high_lane:
            if high_amount < HIGH_EXIT:
                lane = None
        elif lane == self.out_lane:
            if out_amount < OUT_EXIT:
                lane = None

        if lane is None:
            high_ready = high_amount >= HIGH_ENTER
            out_ready = out_amount >= OUT_ENTER
            if high_ready or out_ready:
                # If both are plausible, choose the more decisively crossed
                # threshold. This makes a diagonal reach stable instead of
                # flickering between HIGH and OUT.
                high_score = high_amount / HIGH_ENTER
                out_score = out_amount / OUT_ENTER
                lane = self.high_lane if high_score >= out_score else self.out_lane

        self.current_lane = lane

        # Continuous visual feedback uses the same body-relative coordinates but
        # does not drive gameplay. 0.5/0.5 is neutral; upward is screen-up.
        visual_x = max(0.0, min(1.0, 0.5 + dx / (2.0 * VISUAL_RANGE)))
        visual_y = max(0.0, min(1.0, 0.5 - up / (2.0 * VISUAL_RANGE)))
        visual = BodyPoint(x=visual_x, y=visual_y, lane=lane, visible=True)
        return HandControlSample(lane, visual, high_amount, out_amount)
