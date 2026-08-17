from __future__ import annotations

from dataclasses import dataclass




def zoom_normalized_x(x: float, factor: float) -> float:
    """Scale normalized horizontal position about center and clamp to 0..1."""
    if factor <= 0:
        return max(0.0, min(1.0, x))
    return max(0.0, min(1.0, 0.5 + (x - 0.5) * factor))


def lower_leg_control_position(
    knee_x: float,
    knee_y: float,
    ankle_x: float,
    ankle_y: float,
    *,
    ankle_reliable: bool,
    ankle_blend: float = 0.45,
    edge_fade_start: float = 0.92,
    edge_fade_end: float = 1.02,
) -> tuple[float, float, float]:
    """Return an adaptive virtual lower-leg control point.

    With a reliable ankle comfortably inside frame, the point sits
    ``ankle_blend`` of the way from knee to ankle. As the ankle approaches the
    bottom image edge, its contribution fades smoothly toward the knee. If the
    ankle is not reliable, the knee is used directly. The returned third value
    is the effective ankle weight, useful for calibration/debug display.
    """
    blend = max(0.0, min(1.0, float(ankle_blend)))
    if not ankle_reliable or blend <= 0.0:
        return float(knee_x), float(knee_y), 0.0

    start = float(edge_fade_start)
    end = max(start + 1e-6, float(edge_fade_end))
    if ankle_y <= start:
        edge_factor = 1.0
    elif ankle_y >= end:
        edge_factor = 0.0
    else:
        edge_factor = 1.0 - (float(ankle_y) - start) / (end - start)

    weight = blend * max(0.0, min(1.0, edge_factor))
    x = float(knee_x) + (float(ankle_x) - float(knee_x)) * weight
    y = float(knee_y) + (float(ankle_y) - float(knee_y)) * weight
    return x, y, weight


def perspective_adjusted_x(
    x: float,
    y: float,
    *,
    playfield_left: float,
    playfield_right: float,
    hit_y: float,
    vanish_y: float,
    vanish_half_width: float,
    strength: float = 0.45,
) -> float:
    """Partially project a point in the tapered playfield to receptor-space X.

    Lane resolvers remain simple fixed-width receptor lanes. The visible rails,
    however, converge toward ``vanish_y``. This helper maps X outward according
    to how narrow the rendered field is at the point's Y, then blends that full
    perspective projection with the original X. ``strength=0`` preserves the
    old purely-horizontal mapping; ``strength=1`` follows the rendered taper.
    """
    x = max(0.0, min(1.0, float(x)))
    strength = max(0.0, min(1.0, float(strength)))
    receptor_half = max((playfield_right - playfield_left) * 0.5, 1e-6)
    vanish_half = max(float(vanish_half_width), 1e-6)

    vertical_span = hit_y - vanish_y
    if abs(vertical_span) < 1e-6:
        return x

    # 0 at the vanishing region, 1 at (or beyond) the receptor. Hands have a
    # negative vertical span; feet a positive one, so the same formula works.
    progress = (y - vanish_y) / vertical_span
    progress = max(0.0, min(1.0, progress))
    local_half = vanish_half + (receptor_half - vanish_half) * progress

    full_projected = 0.5 + (x - 0.5) * (receptor_half / max(local_half, 1e-6))
    adjusted = x + (full_projected - x) * strength
    return max(0.0, min(1.0, adjusted))

@dataclass
class HystereticLaneResolver:
    """Resolve normalized x into a fixed lane with tiny boundary hysteresis.

    There are no dead zones inside the playfield. A point outside the playfield
    returns None. Once a point owns a lane, it must cross slightly beyond the
    adjacent boundary before the lane changes.
    """

    left: float
    right: float
    lane_count: int = 4
    hysteresis: float = 0.012
    outer_assist: float = 0.0
    outer_extension: float = 0.0
    current_lane: int | None = None

    def raw_lane(self, x: float) -> int | None:
        width = (self.right - self.left) / self.lane_count
        extension = max(0.0, min(0.5, float(self.outer_extension))) * width
        if x < self.left - extension or x > self.right + extension:
            return None
        if x < self.left:
            return 1
        if x > self.right:
            return self.lane_count
        for left_lane in range(1, self.lane_count):
            if x < self.boundary(left_lane):
                return left_lane
        return self.lane_count

    def boundary(self, left_lane: int) -> float:
        """Boundary between ``left_lane`` and the lane immediately to its right.

        ``outer_assist`` expands only the two outside lanes. For four lanes the
        1↔2 boundary moves right and the 3↔4 boundary moves left; the 2↔3
        boundary remains centered. Hysteresis is applied around these assisted
        boundaries by :meth:`resolve`.
        """
        width = (self.right - self.left) / self.lane_count
        boundary = self.left + width * left_lane
        assist = max(0.0, min(0.45, float(self.outer_assist))) * width
        if self.lane_count >= 3:
            if left_lane == 1:
                boundary += assist
            elif left_lane == self.lane_count - 1:
                boundary -= assist
        return boundary

    def resolve(self, x: float) -> int | None:
        raw = self.raw_lane(x)
        if raw is None:
            self.current_lane = None
            return None

        if self.current_lane is None:
            self.current_lane = raw
            return raw

        lane = self.current_lane

        # Moving right: require crossing past the next boundary + hysteresis.
        while lane < self.lane_count:
            b = self.boundary(lane)
            if x > b + self.hysteresis:
                lane += 1
            else:
                break

        # Moving left: require crossing past the previous boundary - hysteresis.
        while lane > 1:
            b = self.boundary(lane - 1)
            if x < b - self.hysteresis:
                lane -= 1
            else:
                break

        self.current_lane = lane
        return lane
