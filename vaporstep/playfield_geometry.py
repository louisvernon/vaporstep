from __future__ import annotations

from dataclasses import dataclass
import math

from .config import (
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    FOOT_HIT_Y,
    FOOT_PLAYFIELD_LEFT,
    FOOT_PLAYFIELD_RIGHT,
    HAND_PLAYFIELD_LEFT,
    HAND_PLAYFIELD_RIGHT,
    OUTER_LANE_EDGE_EXTENSION,
    VANISH_HALF_WIDTH,
    VANISH_Y,
)
from .domain import NoteKind


HAND_BOUNDARIES = (0.0, 0.20, 0.50, 0.80, 1.0)
HAND_CENTERS = (0.10, 0.31, 0.69, 0.90)
HAND_NOTE_ARC_FRACTION = 0.62
HAND_FOOT_GAP_PX = 7.0
HAND_SHOULDER_EXTENSION = 0.12
HAND_TUNNEL_VERTICAL_SCALE = 0.96


@dataclass(frozen=True)
class Viewport:
    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def centerx(self) -> float:
        return self.left + self.width * 0.5


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def camera_rect(size: tuple[int, int]) -> Viewport:
    w, h = size
    camera_aspect = CAMERA_WIDTH / CAMERA_HEIGHT
    screen_aspect = w / max(h, 1)
    if screen_aspect >= camera_aspect:
        vh = float(h)
        vw = float(int(vh * camera_aspect))
        x = float((w - int(vw)) // 2)
        y = 0.0
    else:
        vw = float(w)
        vh = float(int(vw / camera_aspect))
        x = 0.0
        y = float((h - int(vh)) // 2)
    return Viewport(x, y, vw, vh)


def camera_x(size: tuple[int, int], normalized_x: float) -> float:
    viewport = camera_rect(size)
    return viewport.left + normalized_x * viewport.width


def camera_y(size: tuple[int, int], normalized_y: float) -> float:
    viewport = camera_rect(size)
    return viewport.top + normalized_y * viewport.height


def hit_bounds(size: tuple[int, int], kind: NoteKind) -> tuple[float, float]:
    if kind == NoteKind.HANDS:
        return (
            camera_x(size, HAND_PLAYFIELD_LEFT),
            camera_x(size, HAND_PLAYFIELD_RIGHT),
        )
    return (
        camera_x(size, FOOT_PLAYFIELD_LEFT),
        camera_x(size, FOOT_PLAYFIELD_RIGHT),
    )


def vanish_bounds(size: tuple[int, int]) -> tuple[float, float]:
    viewport = camera_rect(size)
    half = viewport.width * VANISH_HALF_WIDTH
    return viewport.centerx - half, viewport.centerx + half


def field_bounds(
    size: tuple[int, int],
    kind: NoteKind,
    progress: float,
) -> tuple[float, float]:
    p = clamp(progress) ** 1.35
    vl, vr = vanish_bounds(size)
    hl, hr = hit_bounds(size, kind)
    return vl + (hl - vl) * p, vr + (hr - vr) * p


def field_y(size: tuple[int, int], kind: NoteKind, progress: float) -> float:
    p = clamp(progress) ** 1.35
    start = camera_y(size, VANISH_Y)
    end = camera_y(size, 0.10 if kind == NoteKind.HANDS else FOOT_HIT_Y)
    return start + (end - start) * p


def lane_boundary_x(
    size: tuple[int, int],
    kind: NoteKind,
    boundary: int,
    progress: float,
) -> float:
    left, right = field_bounds(size, kind, progress)
    lane_w = (right - left) / 4.0
    x = left + boundary * lane_w
    edge_extension = lane_w * OUTER_LANE_EDGE_EXTENSION * clamp(progress)
    if boundary == 0:
        x -= edge_extension
    elif boundary == 4:
        x += edge_extension
    return x


def lane_center(
    size: tuple[int, int],
    kind: NoteKind,
    lane: int,
    progress: float,
) -> tuple[float, float]:
    left = lane_boundary_x(size, kind, lane - 1, progress)
    right = lane_boundary_x(size, kind, lane, progress)
    return (left + right) * 0.5, field_y(size, kind, progress)


def foot_lane_polygon(
    size: tuple[int, int],
    lane: int,
    start_progress: float = 0.0,
    end_progress: float = 1.0,
) -> list[tuple[int, int]]:
    y0 = field_y(size, NoteKind.FOOT, start_progress)
    y1 = field_y(size, NoteKind.FOOT, end_progress)
    return [
        (round(lane_boundary_x(size, NoteKind.FOOT, lane - 1, start_progress)), round(y0)),
        (round(lane_boundary_x(size, NoteKind.FOOT, lane, start_progress)), round(y0)),
        (round(lane_boundary_x(size, NoteKind.FOOT, lane, end_progress)), round(y1)),
        (round(lane_boundary_x(size, NoteKind.FOOT, lane - 1, end_progress)), round(y1)),
    ]


def _offset_rail(
    inner: tuple[float, float],
    outer: tuple[float, float],
    *,
    side: str,
    gap: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    dx = outer[0] - inner[0]
    dy = outer[1] - inner[1]
    length = max(1.0, math.hypot(dx, dy))
    if side == "left":
        nx, ny = -dy / length, dx / length
    else:
        nx, ny = dy / length, -dx / length
    return (
        (inner[0] + nx * gap, inner[1] + ny * gap),
        (outer[0] + nx * gap, outer[1] + ny * gap),
    )


def _hand_arc_geometry(
    size: tuple[int, int],
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    viewport = camera_rect(size)
    foot_y0 = field_y(size, NoteKind.FOOT, 0.0)
    foot_y1 = field_y(size, NoteKind.FOOT, 1.0)
    foot_left0 = lane_boundary_x(size, NoteKind.FOOT, 0, 0.0)
    foot_left1 = lane_boundary_x(size, NoteKind.FOOT, 0, 1.0)
    foot_right0 = lane_boundary_x(size, NoteKind.FOOT, 4, 0.0)
    foot_right1 = lane_boundary_x(size, NoteKind.FOOT, 4, 1.0)

    inner_left, outer_left = _offset_rail(
        (foot_left0, foot_y0),
        (foot_left1, foot_y1),
        side="left",
        gap=HAND_FOOT_GAP_PX,
    )
    inner_right, outer_right = _offset_rail(
        (foot_right0, foot_y0),
        (foot_right1, foot_y1),
        side="right",
        gap=HAND_FOOT_GAP_PX,
    )

    inner_cx = (inner_left[0] + inner_right[0]) * 0.5
    inner_base_y = (inner_left[1] + inner_right[1]) * 0.5
    inner_rx = max(8.0, (inner_right[0] - inner_left[0]) * 0.5)
    inner_ry = viewport.height * 0.105

    outer_cx = (outer_left[0] + outer_right[0]) * 0.5
    outer_base_y = (outer_left[1] + outer_right[1]) * 0.5
    outer_rx = max(inner_rx + 20.0, (outer_right[0] - outer_left[0]) * 0.5)
    outer_top = viewport.top + max(8.0, viewport.height * 0.018)
    outer_ry = max(inner_ry + 20.0, outer_base_y - outer_top)
    return (
        (inner_cx, inner_base_y, inner_rx, inner_ry),
        (outer_cx, outer_base_y, outer_rx, outer_ry),
    )


def ellipse_upper_point(
    geometry: tuple[float, float, float, float],
    along: float,
) -> tuple[float, float]:
    cx, base_y, rx, ry = geometry
    angle = math.pi + math.pi * clamp(along)
    return cx + rx * math.cos(angle), base_y + ry * math.sin(angle)


def hand_tunnel_geometry(
    size: tuple[int, int],
) -> tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
]:
    inner, old_outer = _hand_arc_geometry(size)
    viewport = camera_rect(size)

    inner_cx, inner_base_y, inner_rx, inner_ry = inner
    inner = (
        inner_cx,
        inner_base_y,
        inner_rx,
        inner_ry * HAND_TUNNEL_VERTICAL_SCALE,
    )

    outer_cx, outer_base_y, old_rx, old_ry = old_outer
    seam_left = (outer_cx - old_rx, outer_base_y)
    seam_right = (outer_cx + old_rx, outer_base_y)
    extension = viewport.width * HAND_SHOULDER_EXTENSION
    shoulder_left = (
        max(viewport.left + 10.0, seam_left[0] - extension),
        outer_base_y,
    )
    shoulder_right = (
        min(viewport.right - 10.0, seam_right[0] + extension),
        outer_base_y,
    )
    outer_rx = max(
        inner_rx + 20.0,
        (shoulder_right[0] - shoulder_left[0]) * 0.5,
    )
    outer = (
        (shoulder_left[0] + shoulder_right[0]) * 0.5,
        outer_base_y,
        outer_rx,
        old_ry * HAND_TUNNEL_VERTICAL_SCALE,
    )
    return inner, outer, (seam_left, seam_right, shoulder_left, shoulder_right)


def hand_point(
    size: tuple[int, int],
    along: float,
    progress: float,
) -> tuple[float, float]:
    inner, outer, _ = hand_tunnel_geometry(size)
    p = clamp(progress) ** 1.25
    ix, iy = ellipse_upper_point(inner, along)
    ox, oy = ellipse_upper_point(outer, along)
    return ix + (ox - ix) * p, iy + (oy - iy) * p


def hand_target_point(
    size: tuple[int, int],
    lane: int,
    progress: float = 1.0,
) -> tuple[float, float]:
    return hand_point(size, HAND_CENTERS[lane - 1], progress)


def hand_arc_points(
    size: tuple[int, int],
    start: float,
    end: float,
    progress: float,
    *,
    samples: int = 14,
) -> list[tuple[int, int]]:
    inner, outer, _ = hand_tunnel_geometry(size)
    p = clamp(progress) ** 1.25
    result: list[tuple[int, int]] = []
    for i in range(samples + 1):
        along = start + (end - start) * i / samples
        ix, iy = ellipse_upper_point(inner, along)
        ox, oy = ellipse_upper_point(outer, along)
        result.append((round(ix + (ox - ix) * p), round(iy + (oy - iy) * p)))
    return result


def hand_lane_arc(
    size: tuple[int, int],
    lane: int,
    progress: float,
    fraction: float = 1.0,
    *,
    samples: int = 14,
) -> list[tuple[int, int]]:
    start = HAND_BOUNDARIES[lane - 1]
    end = HAND_BOUNDARIES[lane]
    center = HAND_CENTERS[lane - 1]
    half = (end - start) * 0.5 * max(0.05, min(1.0, fraction))
    return hand_arc_points(
        size,
        center - half,
        center + half,
        progress,
        samples=samples,
    )


def hand_sector_polygon(size: tuple[int, int], lane: int) -> list[tuple[int, int]]:
    start = HAND_BOUNDARIES[lane - 1]
    end = HAND_BOUNDARIES[lane]
    outer = hand_arc_points(size, start, end, 1.0, samples=18)
    inner = hand_arc_points(size, end, start, 0.0, samples=18)
    return [*outer, *inner]


def hand_connector_points(
    size: tuple[int, int],
    lanes: tuple[int, ...],
    progress: float,
    *,
    samples: int = 30,
) -> list[tuple[int, int]]:
    ordered = sorted(set(lanes))
    if len(ordered) < 2:
        return []
    lane_width = HAND_BOUNDARIES[1] - HAND_BOUNDARIES[0]
    note_half = lane_width * 0.5 * HAND_NOTE_ARC_FRACTION
    start = HAND_CENTERS[ordered[0] - 1] + note_half
    end = HAND_CENTERS[ordered[-1] - 1] - note_half
    if end <= start:
        return []
    return hand_arc_points(size, start, end, progress, samples=samples)
