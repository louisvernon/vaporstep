from __future__ import annotations

import math

import pygame

from . import renderer_base as _base
from .config import (
    FOOT_HIT_Y,
    FOOT_PLAYFIELD_LEFT,
    FOOT_PLAYFIELD_RIGHT,
    LANE_PERSPECTIVE_STRENGTH,
    LOOKAHEAD_BEATS,
    LOOKAHEAD_SECONDS,
    OUTER_LANE_EDGE_EXTENSION,
    VANISH_HALF_WIDTH,
    VANISH_Y,
)
from .domain import (
    BodyState,
    ChainMode,
    ChainState,
    GameNote,
    HitQuality,
    NoteKind,
    RuntimeChain,
    SustainSource,
)
from .hand_control import hand_control_perimeter_along
from .keyboard_input import label_for_lane
from .lanes import perspective_adjusted_x
from .motion import MOTION_EVENT_VISUAL_SECONDS, MotionEvent
from .scroll import note_is_within_lookahead, timed_is_within_lookahead, timed_progress


# Public renderer palette/helpers used by sibling UI modules.
BG = _base.BG
CYAN = _base.CYAN
MAGENTA = _base.MAGENTA
PURPLE = _base.PURPLE
WHITE = _base.WHITE
DIM = _base.DIM
GRID = _base.GRID
GREEN = _base.GREEN
RED = _base.RED
AMBER = _base.AMBER
ELECTRIC_YELLOW = _base.ELECTRIC_YELLOW
HIT_BRICK_POP_SECONDS = _base.HIT_BRICK_POP_SECONDS
_blend = _base._blend

# Authored hand lanes retain their left-to-right semantic ordering along the
# tunnel shell: 1 left/out, 2 left/high, 3 right/high, 4 right/out.
_HAND_BOUNDARIES = (0.0, 0.25, 0.50, 0.75, 1.0)
_HAND_CENTERS = (0.125, 0.375, 0.625, 0.875)
_HAND_NOTE_ARC_FRACTION = 0.62
_HAND_FOOT_GAP_PX = 7.0

_HAND_SHOULDER_EXTENSION = 0.12
_HAND_TUNNEL_VERTICAL_SCALE = 0.86
_HAND_TRACKER_OFFSET_PX = 10.0
_TARGET_PREENTRY_BEATS = 1.5
_TARGET_PREENTRY_SECONDS = 0.75
_NOTE_BREATHE_CYCLE_SECONDS = 1.6


class Renderer(_base.Renderer):
    """Authoritative gameplay renderer for the projected hand tunnel and foot field."""

    @staticmethod
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

    def _hand_arc_geometry(self):
        """Return the unflattened inner/outer upper ellipses for the hand tunnel."""
        viewport = self._camera_rect()
        foot_y0 = self._field_y(NoteKind.FOOT, 0.0)
        foot_y1 = self._field_y(NoteKind.FOOT, 1.0)
        foot_left0 = self._lane_boundary_x(NoteKind.FOOT, 0, 0.0)
        foot_left1 = self._lane_boundary_x(NoteKind.FOOT, 0, 1.0)
        foot_right0 = self._lane_boundary_x(NoteKind.FOOT, 4, 0.0)
        foot_right1 = self._lane_boundary_x(NoteKind.FOOT, 4, 1.0)

        inner_left, outer_left = self._offset_rail(
            (foot_left0, foot_y0),
            (foot_left1, foot_y1),
            side="left",
            gap=_HAND_FOOT_GAP_PX,
        )
        inner_right, outer_right = self._offset_rail(
            (foot_right0, foot_y0),
            (foot_right1, foot_y1),
            side="right",
            gap=_HAND_FOOT_GAP_PX,
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

    @staticmethod
    def _ellipse_upper_point(
        geometry: tuple[float, float, float, float],
        along: float,
    ) -> tuple[float, float]:
        cx, base_y, rx, ry = geometry
        t = max(0.0, min(1.0, along))
        angle = math.pi + math.pi * t
        return cx + rx * math.cos(angle), base_y + ry * math.sin(angle)

    def _scratch_surface(self, name: str, *, alpha: bool = False) -> pygame.Surface:
        surface = getattr(self, name, None)
        if surface is None or surface.get_size() != self.size:
            surface = pygame.Surface(
                self.size,
                pygame.SRCALPHA if alpha else 0,
            )
            setattr(self, name, surface)
        surface.fill((0, 0, 0, 0) if alpha else (0, 0, 0))
        return surface

    def _hand_tunnel_geometry(self):
        cached = getattr(self, "_hand_geometry_cache", None)
        if cached is not None and cached[0] == self.size:
            return cached[1]

        inner, old_outer = self._hand_arc_geometry()
        viewport = self._camera_rect()

        inner_cx, inner_base_y, inner_rx, inner_ry = inner
        inner = (
            inner_cx,
            inner_base_y,
            inner_rx,
            inner_ry * _HAND_TUNNEL_VERTICAL_SCALE,
        )

        outer_cx, outer_base_y, old_rx, old_ry = old_outer
        seam_left = (outer_cx - old_rx, outer_base_y)
        seam_right = (outer_cx + old_rx, outer_base_y)
        extension = viewport.width * _HAND_SHOULDER_EXTENSION
        shoulder_left = (
            max(float(viewport.left + 10), seam_left[0] - extension),
            outer_base_y,
        )
        shoulder_right = (
            min(float(viewport.right - 10), seam_right[0] + extension),
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
            old_ry * _HAND_TUNNEL_VERTICAL_SCALE,
        )
        result = (inner, outer, (seam_left, seam_right, shoulder_left, shoulder_right))
        self._hand_geometry_cache = (self.size, result)
        return result

    def _hand_point(self, along: float, progress: float) -> tuple[float, float]:
        inner, outer, _ = self._hand_tunnel_geometry()
        p = max(0.0, min(1.0, progress)) ** 1.25
        ix, iy = self._ellipse_upper_point(inner, along)
        ox, oy = self._ellipse_upper_point(outer, along)
        return ix + (ox - ix) * p, iy + (oy - iy) * p

    def _hand_target_point(self, lane: int, progress: float) -> tuple[float, float]:
        return self._hand_point(_HAND_CENTERS[lane - 1], progress)

    def _hand_arc_points(
        self,
        start: float,
        end: float,
        progress: float,
        *,
        samples: int = 12,
    ) -> list[tuple[int, int]]:
        inner, outer, _ = self._hand_tunnel_geometry()
        p = max(0.0, min(1.0, progress)) ** 1.25
        points: list[tuple[int, int]] = []
        for i in range(samples + 1):
            along = start + (end - start) * i / samples
            ix, iy = self._ellipse_upper_point(inner, along)
            ox, oy = self._ellipse_upper_point(outer, along)
            points.append((
                int(ix + (ox - ix) * p),
                int(iy + (oy - iy) * p),
            ))
        return points

    def _hand_lane_arc(
        self,
        lane: int,
        progress: float,
        fraction: float = 1.0,
    ) -> list[tuple[int, int]]:
        start = _HAND_BOUNDARIES[lane - 1]
        end = _HAND_BOUNDARIES[lane]
        center = (start + end) * 0.5
        half = (end - start) * 0.5 * max(0.05, min(1.0, fraction))
        return self._hand_arc_points(center - half, center + half, progress, samples=14)

    def _hand_sector_polygon(self, lane: int) -> list[tuple[int, int]]:
        start = _HAND_BOUNDARIES[lane - 1]
        end = _HAND_BOUNDARIES[lane]
        outer = self._hand_arc_points(start, end, 1.0, samples=18)
        inner = self._hand_arc_points(end, start, 0.0, samples=18)
        return [*outer, *inner]

    def _hand_lane_direction(self, lane: int) -> tuple[float, float]:
        inner = self._hand_target_point(lane, 0.0)
        outer = self._hand_target_point(lane, 1.0)
        dx, dy = outer[0] - inner[0], outer[1] - inner[1]
        length = max(1.0, math.hypot(dx, dy))
        return dx / length, dy / length

    def _hand_note_arc_points(
        self,
        lane: int,
        progress: float,
        fraction: float,
        *,
        samples: int = 14,
    ) -> list[tuple[int, int]]:
        start = _HAND_BOUNDARIES[lane - 1]
        end = _HAND_BOUNDARIES[lane]
        center = _HAND_CENTERS[lane - 1]
        half = (end - start) * 0.5 * max(0.05, min(1.0, fraction))
        return self._hand_arc_points(
            center - half,
            center + half,
            progress,
            samples=samples,
        )

    def _draw_hand_note_arc(
        self,
        lane: int,
        progress: float,
        color,
        *,
        highlight: bool = False,
    ) -> None:
        p = max(0.0, min(1.0, progress))
        arc = self._hand_note_arc_points(lane, p, _HAND_NOTE_ARC_FRACTION)
        thickness = max(5, int(5 + 12 * p))
        pygame.draw.lines(self.screen, BG, False, arc, thickness + 9)
        pygame.draw.lines(self.screen, color, False, arc, thickness)
        if highlight:
            pygame.draw.lines(self.screen, WHITE, False, arc, max(1, thickness // 5))

    def _draw_hand_note_connector(
        self,
        lanes: tuple[int, ...],
        progress: float,
        color,
        song_time: float,
        beat_pulse: float,
        downbeat: bool,
    ) -> None:
        """Electrically join the heads that belong to one simultaneous note."""
        ordered = sorted(set(lanes))
        if len(ordered) < 2:
            return

        lane_width = _HAND_BOUNDARIES[1] - _HAND_BOUNDARIES[0]
        note_half = lane_width * 0.5 * _HAND_NOTE_ARC_FRACTION
        start = _HAND_CENTERS[ordered[0] - 1] + note_half
        end = _HAND_CENTERS[ordered[-1] - 1] - note_half
        if end <= start:
            return

        p = max(0.0, min(1.0, progress))
        probe_points = self._hand_arc_points(start, end, p, samples=12)
        path_length = sum(
            math.hypot(x1 - x0, y1 - y0)
            for (x0, y0), (x1, y1) in zip(probe_points, probe_points[1:])
        )
        foot_start = (
            self._lane_boundary_x(NoteKind.FOOT, 0, 0.0),
            self._field_y(NoteKind.FOOT, 0.0),
        )
        foot_end = (
            self._lane_boundary_x(NoteKind.FOOT, 0, 1.0),
            self._field_y(NoteKind.FOOT, 1.0),
        )
        reference_length = max(
            1.0,
            math.hypot(foot_end[0] - foot_start[0], foot_end[1] - foot_start[1]),
        )
        spatial_span = path_length / reference_length
        samples = max(4, int(round(30 * spatial_span)))
        base_points = self._hand_arc_points(start, end, p, samples=samples)
        pulse = max(0.0, min(1.0, beat_pulse))
        amplitude = 0.30 * (11.2 + (33.6 if downbeat else 25.6) * pulse)
        amplitude = min(amplitude, max(3.0, path_length * 0.12))
        lane_phase = sum(ordered) * 0.73
        points: list[tuple[int, int]] = []
        for index, (x, y) in enumerate(base_points):
            before = base_points[max(0, index - 1)]
            after = base_points[min(len(base_points) - 1, index + 1)]
            dx, dy = after[0] - before[0], after[1] - before[1]
            length = max(1.0, math.hypot(dx, dy))
            nx, ny = -dy / length, dx / length
            along = index / max(1, len(base_points) - 1)
            noise = self._electric_noise(
                song_time,
                along * spatial_span,
                lane_phase,
            )
            offset = amplitude * noise
            points.append((int(round(x + nx * offset)), int(round(y + ny * offset))))

        glow = min(1.0, 0.34 + pulse * (0.58 if downbeat else 0.46))
        trace_color = _blend(DIM, color, glow)
        self._draw_electric_trace(points, trace_color)

    def _draw_hand_hit_pop(self, lane: int, age: float, quality: HitQuality) -> None:
        phase = max(0.0, min(1.0, age / HIT_BRICK_POP_SECONDS))
        power = {HitQuality.HIT: 1.0, HitQuality.GREAT: 1.28, HitQuality.PERFECT: 1.60}[quality]
        fade = (1.0 - phase) ** 0.72
        hot = _blend(MAGENTA, WHITE, min(0.92, 0.40 + 0.24 * power))
        color = _blend(BG, hot, fade)
        fraction = min(
            0.88,
            _HAND_NOTE_ARC_FRACTION
            + 0.12 * math.sin(min(1.0, phase * 1.5) * math.pi),
        )
        arc = self._hand_note_arc_points(lane, 1.0, fraction)
        thickness = max(3, int((14 + 4 * power) * (0.72 + 0.28 * fade)))
        pygame.draw.lines(self.screen, BG, False, arc, thickness + 10)
        pygame.draw.lines(self.screen, color, False, arc, thickness)
        if fade > 0.15:
            pygame.draw.lines(self.screen, _blend(color, WHITE, 0.68 * fade), False, arc, 2)

    def _hand_depth_band(self, p0: float, p1: float) -> list[tuple[int, int]]:
        outer = self._hand_arc_points(0.0, 1.0, p1, samples=64)
        inner = self._hand_arc_points(1.0, 0.0, p0, samples=64)
        return [*outer, *inner]

    def _floor_gutter_outer_point(self, side: str, progress: float) -> tuple[float, float]:
        along = 0.0 if side == "left" else 1.0
        wall_x, _ = self._hand_point(along, progress)
        return wall_x, self._field_y(NoteKind.FOOT, progress)

    def _floor_gutter_polygon(self, side: str, samples: int = 20) -> list[tuple[int, int]]:
        boundary = 0 if side == "left" else 4
        outer = [
            tuple(int(v) for v in self._floor_gutter_outer_point(side, i / samples))
            for i in range(samples + 1)
        ]
        foot = [
            (
                int(self._lane_boundary_x(NoteKind.FOOT, boundary, i / samples)),
                int(self._field_y(NoteKind.FOOT, i / samples)),
            )
            for i in range(samples, -1, -1)
        ]
        return [*outer, *foot]

    def _draw_floor_gutter_structure(self, rail_color) -> None:
        floor_surface = self._scratch_surface("_alpha_scratch", alpha=True)
        for side in ("left", "right"):
            pygame.draw.polygon(
                floor_surface,
                (*GRID, 10),
                self._floor_gutter_polygon(side),
            )
        self.screen.blit(floor_surface, (0, 0))

        for side in ("left", "right"):
            boundary = 0 if side == "left" else 4
            points = [
                tuple(int(v) for v in self._floor_gutter_outer_point(side, i / 24.0))
                for i in range(25)
            ]
            pygame.draw.lines(self.screen, rail_color, False, points, 1)
            for step in range(1, 8):
                progress = step / 8.0
                outer = self._floor_gutter_outer_point(side, progress)
                inner = (
                    self._lane_boundary_x(NoteKind.FOOT, boundary, progress),
                    self._field_y(NoteKind.FOOT, progress),
                )
                pygame.draw.line(self.screen, rail_color, inner, outer, 1)

    def _draw_hand_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        enabled: bool,
    ) -> None:
        occupied = body.hand_lanes if enabled else frozenset()
        disabled = _blend(DIM, BG, 0.58)

        depth_surface = self._scratch_surface("_alpha_scratch", alpha=True)
        for band in range(8):
            p0 = band / 8.0
            p1 = (band + 1) / 8.0
            mid = (p0 + p1) * 0.5
            alpha = int(6 + 22 * (1.0 - mid))
            pygame.draw.polygon(depth_surface, (*BG, alpha), self._hand_depth_band(p0, p1))
        self.screen.blit(depth_surface, (0, 0))

        fill_surface = self._scratch_surface("_alpha_scratch", alpha=True)
        for lane in range(1, 5):
            if enabled:
                pygame.draw.polygon(
                    fill_surface,
                    (*MAGENTA, 58 if lane in occupied else 8),
                    self._hand_sector_polygon(lane),
                )
        self.screen.blit(fill_surface, (0, 0))

        rail_color = GRID if enabled else disabled
        for boundary, along in enumerate(_HAND_BOUNDARIES):
            p0 = self._hand_point(along, 0.0)
            p1 = self._hand_point(along, 1.0)
            active_boundary = enabled and (
                (boundary > 0 and boundary in occupied)
                or (boundary < 4 and boundary + 1 in occupied)
            )
            if active_boundary:
                color, width = MAGENTA, 3
            elif enabled and boundary in (0, 4):
                color, width = MAGENTA, 2
            else:
                color, width = rail_color, 1
            pygame.draw.line(self.screen, color, p0, p1, width)

        inner_arc = self._hand_arc_points(0.0, 1.0, 0.0, samples=64)
        pygame.draw.lines(self.screen, _blend(rail_color, WHITE, 0.10), False, inner_arc, 2)

        pulse = max(0.0, min(1.0, beat_pulse))
        pulse_position = pulse ** 0.5 if pulse > 0.005 else -1.0
        for step in range(1, 9):
            progress = step / 9.0
            ring_color = rail_color
            width = 1
            if enabled and pulse_position >= 0.0:
                proximity = max(0.0, 1.0 - abs(progress - pulse_position) / 0.18)
                if proximity > 0.0:
                    amount = proximity * (0.14 + 0.26 * (pulse ** 0.5))
                    ring_color = _blend(rail_color, MAGENTA, amount)
                    width = 2 if amount > 0.18 else 1
            arc = self._hand_arc_points(0.0, 1.0, progress, samples=64)
            pygame.draw.lines(self.screen, ring_color, False, arc, width)

        for lane in range(1, 5):
            active = enabled and lane in occupied
            receptor = self._hand_lane_arc(lane, 1.0, 1.0)
            pygame.draw.lines(
                self.screen,
                MAGENTA if active else (DIM if enabled else disabled),
                False,
                receptor,
                6 if active else 2,
            )

        self._draw_floor_gutter_structure(GRID if enabled else disabled)

        if not enabled:
            cx, cy = self._hand_point(0.5, 0.0)
            off = self.small_font.render("NO HAND NOTES", True, _blend(DIM, BG, 0.30))
            self.screen.blit(off, off.get_rect(center=(int(cx), int(cy - 20))))

    def _draw_foot_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        downbeat: bool,
        enabled: bool,
        overdrive: bool,
        animate_buzz: bool,
    ) -> None:
        if self._lane_fill_surface is None or self._lane_fill_surface.get_size() != self.size:
            self._lane_fill_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        self._lane_fill_surface.fill((0, 0, 0, 0))
        if enabled:
            for lane in body.foot_lanes:
                self._draw_active_lane_fill(
                    self._lane_fill_surface,
                    NoteKind.FOOT,
                    lane,
                    CYAN,
                    beat_pulse,
                )
        self.screen.blit(self._lane_fill_surface, (0, 0))

        occupied = body.foot_lanes if enabled else frozenset()
        disabled_grid = _blend(GRID, BG, 0.62)
        local_grid = GRID if enabled else disabled_grid
        outer_color = CYAN if enabled else _blend(DIM, BG, 0.55)
        outer_width = 2 if enabled else 1

        for i in range(5):
            x0 = self._lane_boundary_x(NoteKind.FOOT, i, 0.0)
            x1 = self._lane_boundary_x(NoteKind.FOOT, i, 1.0)
            y0 = self._field_y(NoteKind.FOOT, 0.0)
            y1 = self._field_y(NoteKind.FOOT, 1.0)
            if i in (0, 4):
                pygame.draw.line(self.screen, outer_color, (x0, y0), (x1, y1), outer_width)
            else:
                pygame.draw.line(self.screen, local_grid, (x0, y0), (x1, y1), 1)

        if enabled:
            for lane in occupied:
                for boundary in (lane - 1, lane):
                    x0 = self._lane_boundary_x(NoteKind.FOOT, boundary, 0.0)
                    x1 = self._lane_boundary_x(NoteKind.FOOT, boundary, 1.0)
                    y0 = self._field_y(NoteKind.FOOT, 0.0)
                    y1 = self._field_y(NoteKind.FOOT, 1.0)
                    pygame.draw.line(self.screen, CYAN, (x0, y0), (x1, y1), 3)

        for j in range(1, 8):
            p = j / 8.0
            left = self._lane_boundary_x(NoteKind.FOOT, 0, p)
            right = self._lane_boundary_x(NoteKind.FOOT, 4, p)
            y = self._field_y(NoteKind.FOOT, p)
            pygame.draw.line(self.screen, local_grid, (left, y), (right, y), 1)

        if enabled:
            self._draw_buzz_rails(
                NoteKind.FOOT,
                CYAN,
                song_time,
                beat_pulse,
                downbeat,
                overdrive,
                animated=animate_buzz,
            )

    def _foot_outside_strengths(self, body: BodyState) -> tuple[float, float]:
        lane_width = (FOOT_PLAYFIELD_RIGHT - FOOT_PLAYFIELD_LEFT) / 4.0
        extension = lane_width * OUTER_LANE_EDGE_EXTENSION
        left_limit = FOOT_PLAYFIELD_LEFT - extension
        right_limit = FOOT_PLAYFIELD_RIGHT + extension
        ramp = max(lane_width * 0.55, 1e-6)
        left_strength = 0.0
        right_strength = 0.0

        for control in (body.left_foot_control, body.right_foot_control):
            if not control.visible:
                continue
            adjusted = perspective_adjusted_x(
                control.x,
                control.y,
                playfield_left=FOOT_PLAYFIELD_LEFT,
                playfield_right=FOOT_PLAYFIELD_RIGHT,
                hit_y=FOOT_HIT_Y,
                vanish_y=VANISH_Y,
                vanish_half_width=VANISH_HALF_WIDTH,
                strength=LANE_PERSPECTIVE_STRENGTH,
            )
            if adjusted < left_limit:
                left_strength = max(left_strength, min(1.0, (left_limit - adjusted) / ramp))
            elif adjusted > right_limit:
                right_strength = max(right_strength, min(1.0, (adjusted - right_limit) / ramp))
        return left_strength, right_strength

    @staticmethod
    def _scaled_additive_color(color, amount: float) -> tuple[int, int, int]:
        amount = max(0.0, min(1.0, amount))
        return tuple(max(0, min(255, int(channel * amount))) for channel in color)

    def _draw_foot_boundary_warning(self, body: BodyState) -> None:
        left_strength, right_strength = self._foot_outside_strengths(body)
        if max(left_strength, right_strength) <= 0.0:
            return

        fill = self._scratch_surface("_alpha_scratch", alpha=True)
        glow = self._scratch_surface("_additive_scratch")
        for side, strength in (("left", left_strength), ("right", right_strength)):
            if strength <= 0.0:
                continue
            polygon = self._floor_gutter_polygon(side)
            pygame.draw.polygon(fill, (*RED, int(42 + 78 * strength)), polygon)
            glow_color = self._scaled_additive_color(RED, 0.18 + 0.28 * strength)
            pygame.draw.polygon(glow, glow_color, polygon)

        self.screen.blit(fill, (0, 0))
        self.screen.blit(glow, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _draw_key_labels(self, hand_enabled: bool, foot_enabled: bool) -> None:
        if hand_enabled:
            for lane in range(1, 5):
                x, y = self._hand_target_point(lane, 0.955)
                label = self.small_font.render(
                    label_for_lane(NoteKind.HANDS, lane),
                    True,
                    DIM,
                )
                self.screen.blit(label, label.get_rect(center=(int(x), int(y))))

        if foot_enabled:
            y = self._field_y(NoteKind.FOOT, 1.0) - 24
            for lane in range(1, 5):
                left, right = self._lane_bounds(NoteKind.FOOT, lane, 1.0)
                center_x = (left + right) * 0.5
                label = self.small_font.render(
                    label_for_lane(NoteKind.FOOT, lane),
                    True,
                    DIM,
                )
                self.screen.blit(label, label.get_rect(center=(int(center_x), int(y))))

    def _draw_playfields(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        downbeat: bool,
        hand_enabled: bool,
        foot_enabled: bool,
        overdrive: bool = False,
        animate_buzz: bool = True,
    ) -> None:
        self._draw_foot_playfield(
            body,
            song_time,
            beat_pulse,
            downbeat,
            foot_enabled,
            overdrive,
            animate_buzz,
        )
        self._draw_hand_playfield(body, song_time, beat_pulse, hand_enabled)
        if foot_enabled:
            self._draw_foot_boundary_warning(body)
        self._draw_key_labels(hand_enabled, foot_enabled)

    def _timed_glow_state(
        self,
        event_time: float,
        event_beat: float | None,
        song_time: float,
        song_beat: float,
    ) -> tuple[float, float, bool] | None:
        if event_beat is not None:
            distance = float(event_beat) - song_beat
            if distance > LOOKAHEAD_BEATS:
                extra = distance - LOOKAHEAD_BEATS
                if extra > _TARGET_PREENTRY_BEATS:
                    return None
                strength = 1.0 - extra / _TARGET_PREENTRY_BEATS
                return 0.0, 0.30 * strength, True
        else:
            distance = event_time - song_time
            if distance > LOOKAHEAD_SECONDS:
                extra = distance - LOOKAHEAD_SECONDS
                if extra > _TARGET_PREENTRY_SECONDS:
                    return None
                strength = 1.0 - extra / _TARGET_PREENTRY_SECONDS
                return 0.0, 0.30 * strength, True

        progress = timed_progress(event_time, event_beat, song_time, song_beat)
        return progress, 0.24 + 0.48 * (progress ** 0.85), False

    @staticmethod
    def _note_breathe(note: GameNote, song_time: float) -> float:
        """Return a target-time-anchored pulse with a BPM-independent period."""
        phase = (note.time - song_time) / _NOTE_BREATHE_CYCLE_SECONDS
        return 0.5 + 0.5 * math.cos(phase * math.tau)

    @staticmethod
    def _breathing_note_color(base, breathe: float, progress: float):
        """Apply an obvious but readable target-time brightness pulse."""
        pulse = max(0.0, min(1.0, breathe))
        near_receptor = max(0.0, min(1.0, progress))
        trough = 0.48 + 0.18 * near_receptor
        intensity = trough + (1.0 - trough) * pulse
        color = _blend(BG, base, intensity)
        return _blend(color, WHITE, 0.12 * pulse * pulse)

    def _target_glow_state(
        self,
        note: GameNote,
        song_time: float,
        song_beat: float,
    ) -> tuple[float, float, bool] | None:
        if note.judged:
            return None
        return self._timed_glow_state(note.time, note.beat, song_time, song_beat)

    def _target_points(
        self,
        kind: NoteKind,
        lane: int,
        progress: float,
    ) -> tuple[list[tuple[int, int]], int]:
        p = max(0.0, min(1.0, progress))
        if kind == NoteKind.HANDS:
            return (
                self._hand_note_arc_points(
                    lane,
                    p,
                    _HAND_NOTE_ARC_FRACTION,
                    samples=18,
                ),
                max(5, int(5 + 12 * p)),
            )

        left, right = self._lane_bounds(NoteKind.FOOT, lane, p)
        y = self._field_y(NoteKind.FOOT, p)
        pad = max(2.0, (right - left) * 0.08)
        return (
            [(int(left + pad), int(y)), (int(right - pad), int(y))],
            max(4, int(4 + 12 * p)),
        )

    @classmethod
    def _draw_preentry_glow(
        cls,
        surface: pygame.Surface,
        points: list[tuple[int, int]],
        color,
        intensity: float,
        core_width: int,
    ) -> None:
        if len(points) < 2 or intensity <= 0.0:
            return
        for extra, scale in ((20, 0.11), (9, 0.22)):
            glow_color = cls._scaled_additive_color(color, intensity * scale)
            pygame.draw.lines(
                surface,
                glow_color,
                False,
                points,
                max(1, core_width + extra),
            )

    def _draw_outward_glow(
        self,
        surface: pygame.Surface,
        kind: NoteKind,
        lane: int,
        progress: float,
        color,
        intensity: float,
    ) -> None:
        p0 = max(0.0, min(1.0, progress))
        p1 = min(1.0, p0 + 0.065)
        if p1 <= p0 + 1e-6:
            return

        source, _ = self._target_points(kind, lane, p0)
        projected, _ = self._target_points(kind, lane, p1)
        if len(source) < 2 or len(projected) != len(source):
            return

        polygon = [*source, *reversed(projected)]
        light = self._scaled_additive_color(color, intensity * 0.34)
        pygame.draw.polygon(surface, light, polygon)
        edge = self._scaled_additive_color(color, intensity * 0.18)
        pygame.draw.lines(surface, edge, False, projected, 2)

    def _aperture_target_points(
        self,
        kind: NoteKind,
        lane: int,
    ) -> tuple[list[tuple[int, int]], int]:
        """Return a pre-entry cue that sits inside the tunnel opening."""
        inner, _, _ = self._hand_tunnel_geometry()
        cx, base_y, rx, ry = inner

        if kind == NoteKind.HANDS:
            start = _HAND_BOUNDARIES[lane - 1]
            end = _HAND_BOUNDARIES[lane]
            center = _HAND_CENTERS[lane - 1]
            half = (end - start) * 0.5 * _HAND_NOTE_ARC_FRACTION
            inset = 0.16
            points = []
            samples = 18
            for i in range(samples + 1):
                along = center - half + (2.0 * half) * i / samples
                x, y = self._ellipse_upper_point(inner, along)
                points.append((
                    int(cx + (x - cx) * (1.0 - inset)),
                    int(base_y + (y - base_y) * (1.0 - inset)),
                ))
            return points, 5

        left = cx - rx * 0.84
        right = cx + rx * 0.84
        lane_width = (right - left) / 4.0
        lane_left = left + (lane - 1) * lane_width
        lane_right = lane_left + lane_width
        pad = max(2.0, lane_width * 0.08)
        y = base_y - max(5.0, ry * 0.12)
        return (
            [(int(lane_left + pad), int(y)), (int(lane_right - pad), int(y))],
            5,
        )

    def _draw_source_glow(
        self,
        surface: pygame.Surface,
        kind: NoteKind,
        lane: int,
        progress: float,
        intensity: float,
        *,
        preentry: bool = False,
    ) -> None:
        theme = MAGENTA if kind == NoteKind.HANDS else CYAN
        if preentry:
            points, core_width = self._aperture_target_points(kind, lane)
            boost = 1.15 if kind == NoteKind.FOOT else 0.92
            self._draw_preentry_glow(
                surface,
                points,
                theme,
                intensity * boost,
                core_width,
            )
            return

        self._draw_outward_glow(
            surface,
            kind,
            lane,
            max(0.0, min(1.0, progress)),
            theme,
            intensity,
        )

    def _draw_target_glows(
        self,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
    ) -> None:
        glow_surface = self._scratch_surface("_additive_scratch")
        any_glow = False

        for note in notes:
            if note.end_time is not None and note.chain_id is not None:
                continue
            if note.chain_id is not None and chain_mode == ChainMode.BLOCKS:
                continue

            state = self._target_glow_state(note, song_time, song_beat)
            if state is None:
                continue
            progress, intensity, preentry = state
            for lane in note.lanes:
                self._draw_source_glow(
                    glow_surface,
                    note.kind,
                    lane,
                    progress,
                    intensity,
                    preentry=preentry,
                )
                any_glow = True

        if any_glow:
            self.screen.blit(glow_surface, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _draw_chain_head_glows(
        self,
        chains: tuple[RuntimeChain, ...],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
    ) -> None:
        glow_surface = self._scratch_surface("_additive_scratch")
        any_glow = False

        for chain in chains:
            definition = chain.definition
            is_hold = definition.source == SustainSource.EXPLICIT_HOLD
            if not is_hold and chain_mode == ChainMode.OFF:
                continue
            if chain.state in (ChainState.BROKEN, ChainState.COMPLETE):
                continue

            state = self._timed_glow_state(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            )
            if state is None:
                continue
            progress, intensity, preentry = state
            for lane in definition.lanes:
                self._draw_source_glow(
                    glow_surface,
                    definition.kind,
                    lane,
                    progress,
                    intensity,
                    preentry=preentry,
                )
                any_glow = True

        if any_glow:
            self.screen.blit(glow_surface, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _draw_foot_notes(
        self,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
    ) -> None:
        for note in notes:
            if note.kind != NoteKind.FOOT:
                continue
            if note.end_time is not None and note.chain_id is not None:
                continue
            if note.chain_id is not None and chain_mode == ChainMode.BLOCKS:
                continue
            dt = note.time - song_time
            if not note_is_within_lookahead(note, song_time, song_beat):
                continue
            if note.judged and note.judged_at is not None:
                age = song_time - note.judged_at
                if age > _base.HIT_FLASH_SECONDS:
                    continue
                if note.hit and age > HIT_BRICK_POP_SECONDS:
                    continue
            elif dt < -_base.HIT_WINDOW_SECONDS:
                continue

            if note.judged and note.hit:
                quality = note.judgement or HitQuality.HIT
                color = WHITE if quality != HitQuality.PERFECT else _blend(AMBER, WHITE, 0.55)
            elif note.judged:
                color = RED
            else:
                color = CYAN

            progress = self._note_progress(note, song_time, song_beat)
            if not note.judged:
                breathe = self._note_breathe(note, song_time)
                color = self._breathing_note_color(color, breathe, progress)

            for lane in note.lanes:
                if note.judged and note.hit and note.judged_at is not None:
                    self._draw_hit_pop_bar(
                        NoteKind.FOOT,
                        lane,
                        max(0.0, song_time - note.judged_at),
                        note.judgement or HitQuality.HIT,
                    )
                else:
                    self._draw_note_bar(NoteKind.FOOT, lane, progress, color, False)

    def _draw_notes(
        self,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode = ChainMode.OFF,
        beat_pulse: float = 0.0,
        downbeat: bool = False,
    ) -> None:
        self._draw_target_glows(notes, song_time, song_beat, chain_mode)
        self._draw_foot_notes(notes, song_time, song_beat, chain_mode)

        for note in notes:
            if note.kind != NoteKind.HANDS:
                continue
            if note.end_time is not None and note.chain_id is not None:
                continue
            if note.chain_id is not None and chain_mode == ChainMode.BLOCKS:
                continue
            if not note_is_within_lookahead(note, song_time, song_beat):
                continue
            dt = note.time - song_time
            if note.judged and note.judged_at is not None:
                age = song_time - note.judged_at
                if age > _base.HIT_FLASH_SECONDS:
                    continue
                if note.hit and age > HIT_BRICK_POP_SECONDS:
                    continue
            elif dt < -_base.HIT_WINDOW_SECONDS:
                continue

            progress = self._note_progress(note, song_time, song_beat)
            if note.judged and note.hit:
                for lane in note.lanes:
                    self._draw_hand_hit_pop(
                        lane,
                        max(0.0, song_time - float(note.judged_at or song_time)),
                        note.judgement or HitQuality.HIT,
                    )
                continue

            if note.judged:
                color = RED
                connector_color = RED
            else:
                breathe = self._note_breathe(note, song_time)
                color = self._breathing_note_color(MAGENTA, breathe, progress)
                connector_color = MAGENTA

            self._draw_hand_note_connector(
                note.lanes,
                progress,
                connector_color,
                song_time,
                beat_pulse,
                downbeat,
            )
            for lane in note.lanes:
                self._draw_hand_note_arc(lane, progress, color)

    def _draw_foot_chains(
        self,
        chains: tuple[RuntimeChain, ...],
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
    ) -> None:
        if not chains or not notes:
            return
        for chain in chains:
            definition = chain.definition
            if definition.kind != NoteKind.FOOT:
                continue
            is_hold = definition.source == SustainSource.EXPLICIT_HOLD
            if not is_hold and chain_mode == ChainMode.OFF:
                continue
            if not timed_is_within_lookahead(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            ):
                continue
            if chain.state == ChainState.COMPLETE and song_time > definition.end_time + 0.10:
                continue
            if song_time > definition.end_time + _base.HIT_FLASH_SECONDS:
                continue

            head_progress = timed_progress(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            )
            tail_progress = timed_progress(
                definition.end_time,
                definition.end_beat,
                song_time,
                song_beat,
            )
            lo = min(head_progress, tail_progress)
            hi = max(head_progress, tail_progress)
            if hi <= 0.0:
                continue

            if chain.state == ChainState.BROKEN:
                fill = _blend(BG, DIM, 0.56)
                edge = _blend(DIM, WHITE, 0.10)
            elif chain.state == ChainState.ACTIVE:
                fill = _blend(BG, CYAN, 0.52)
                edge = _blend(CYAN, WHITE, 0.30)
            else:
                fill = _blend(BG, CYAN, 0.27)
                edge = _blend(BG, CYAN, 0.66)

            for lane in definition.lanes:
                left0, right0 = self._lane_bounds(NoteKind.FOOT, lane, lo)
                left1, right1 = self._lane_bounds(NoteKind.FOOT, lane, hi)
                y0 = self._field_y(NoteKind.FOOT, lo)
                y1 = self._field_y(NoteKind.FOOT, hi)
                pad0 = max(2.0, (right0 - left0) * 0.10)
                pad1 = max(2.0, (right1 - left1) * 0.10)
                polygon = [
                    (int(left0 + pad0), int(y0)),
                    (int(right0 - pad0), int(y0)),
                    (int(right1 - pad1), int(y1)),
                    (int(left1 + pad1), int(y1)),
                ]
                pygame.draw.polygon(self.screen, fill, polygon)
                pygame.draw.lines(
                    self.screen,
                    edge,
                    True,
                    polygon,
                    2 if chain.state == ChainState.ACTIVE else 1,
                )

                center0 = (left0 + right0) * 0.5
                center1 = (left1 + right1) * 0.5
                center_color = WHITE if chain.state == ChainState.ACTIVE else edge
                pygame.draw.line(
                    self.screen,
                    center_color,
                    (int(center0), int(y0)),
                    (int(center1), int(y1)),
                    2 if chain.state == ChainState.ACTIVE else 1,
                )

                head_p = max(0.0, min(1.0, head_progress))
                head_left, head_right = self._lane_bounds(NoteKind.FOOT, lane, head_p)
                head_y = self._field_y(NoteKind.FOOT, head_p)
                head_pad = max(2.0, (head_right - head_left) * 0.08)
                head_thickness = max(5, int(4 + 12 * head_p))
                if chain.state == ChainState.BROKEN:
                    head_color = _blend(BG, DIM, 0.72)
                else:
                    head_color = CYAN
                pygame.draw.line(
                    self.screen,
                    BG,
                    (head_left + head_pad, head_y),
                    (head_right - head_pad, head_y),
                    head_thickness + 8,
                )
                pygame.draw.line(
                    self.screen,
                    head_color,
                    (head_left + head_pad, head_y),
                    (head_right - head_pad, head_y),
                    head_thickness,
                )
                if chain.state != ChainState.BROKEN:
                    pygame.draw.line(
                        self.screen,
                        WHITE,
                        (head_left + head_pad, head_y - max(1, head_thickness // 4)),
                        (head_right - head_pad, head_y - max(1, head_thickness // 4)),
                        1,
                    )

                if chain.state == ChainState.ACTIVE:
                    left, right = self._lane_bounds(NoteKind.FOOT, lane, 1.0)
                    y = self._field_y(NoteKind.FOOT, 1.0)
                    cap_pad = max(2.0, (right - left) * 0.08)
                    pygame.draw.line(
                        self.screen,
                        CYAN,
                        (left + cap_pad, y),
                        (right - cap_pad, y),
                        9,
                    )
                    pygame.draw.line(
                        self.screen,
                        WHITE,
                        (left + cap_pad, y),
                        (right - cap_pad, y),
                        2,
                    )

    def _draw_chains(
        self,
        chains: tuple[RuntimeChain, ...],
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
    ) -> None:
        self._draw_chain_head_glows(chains, song_time, song_beat, chain_mode)
        self._draw_foot_chains(chains, notes, song_time, song_beat, chain_mode)

        if notes:
            for chain in chains:
                definition = chain.definition
                if definition.kind != NoteKind.HANDS:
                    continue
                is_hold = definition.source == SustainSource.EXPLICIT_HOLD
                if not is_hold and chain_mode == ChainMode.OFF:
                    continue
                if not timed_is_within_lookahead(
                    definition.start_time,
                    definition.start_beat,
                    song_time,
                    song_beat,
                ):
                    continue
                if song_time > definition.end_time + _base.HIT_FLASH_SECONDS:
                    continue

                head = timed_progress(
                    definition.start_time,
                    definition.start_beat,
                    song_time,
                    song_beat,
                )
                tail = timed_progress(
                    definition.end_time,
                    definition.end_beat,
                    song_time,
                    song_beat,
                )
                lo, hi = min(head, tail), max(head, tail)
                if hi <= 0.0:
                    continue
                if chain.state == ChainState.BROKEN:
                    color = _blend(DIM, BG, 0.25)
                elif chain.state == ChainState.ACTIVE:
                    color = _blend(MAGENTA, WHITE, 0.25)
                else:
                    color = _blend(BG, MAGENTA, 0.55)

                for lane in definition.lanes:
                    p0 = self._hand_target_point(lane, lo)
                    p1 = self._hand_target_point(lane, hi)
                    pygame.draw.line(self.screen, _blend(BG, color, 0.45), p0, p1, 16)
                    pygame.draw.line(self.screen, color, p0, p1, 6)
                    self._draw_hand_note_arc(
                        lane,
                        max(0.0, min(1.0, head)),
                        color,
                    )

        for chain in chains:
            definition = chain.definition
            if definition.kind != NoteKind.HANDS:
                continue
            if chain.state not in (ChainState.PENDING, ChainState.ACTIVE):
                continue
            is_hold = definition.source == SustainSource.EXPLICIT_HOLD
            if not is_hold and chain_mode == ChainMode.OFF:
                continue
            if not timed_is_within_lookahead(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            ):
                continue

            head = timed_progress(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            )
            if head < 0.0 or head > 1.0:
                continue
            for lane in definition.lanes:
                self._draw_hand_note_arc(
                    lane,
                    head,
                    MAGENTA,
                    highlight=chain.state == ChainState.ACTIVE,
                )

    def _draw_hand_receptor_feedback(
        self,
        body: BodyState,
        notes: list[GameNote],
        song_time: float,
        enabled: bool,
        strike_events: tuple[MotionEvent, ...],
    ) -> None:
        if not enabled:
            return

        occupied = body.hand_lanes
        for lane in range(1, 5):
            receptor = self._hand_lane_arc(lane, 1.0, 1.0)
            active = lane in occupied
            near = self._target_is_near(notes, song_time, NoteKind.HANDS, lane)
            judgement, age = self._judgement_for_lane(
                notes,
                song_time,
                NoteKind.HANDS,
                lane,
            )

            if active:
                pygame.draw.lines(self.screen, MAGENTA, False, receptor, 6)
            if near:
                pygame.draw.lines(
                    self.screen,
                    _blend(MAGENTA, WHITE, 0.35),
                    False,
                    receptor,
                    3,
                )

            matching = [
                event
                for event in strike_events
                if event.kind == NoteKind.HANDS
                and event.lane == lane
                and 0.0 <= song_time - event.song_time <= MOTION_EVENT_VISUAL_SECONDS
            ]
            if matching:
                latest = max(matching, key=lambda e: e.song_time)
                input_age = song_time - latest.song_time
                input_phase = 1.0 - min(
                    1.0,
                    input_age / MOTION_EVENT_VISUAL_SECONDS,
                )
                pygame.draw.lines(
                    self.screen,
                    _blend(MAGENTA, WHITE, 0.85 * input_phase),
                    False,
                    receptor,
                    max(3, int(4 + 6 * input_phase)),
                )

            if judgement is None:
                continue
            phase = 1.0 - min(age / _base.HIT_FLASH_SECONDS, 1.0)
            if judgement == "perfect":
                jcolor, power = _blend(AMBER, WHITE, 0.35), 1.65
            elif judgement == "great":
                jcolor, power = _blend(MAGENTA, WHITE, 0.55), 1.30
            elif judgement == "hit":
                jcolor, power = GREEN, 1.0
            else:
                jcolor, power = RED, 0.0

            if judgement != "miss":
                head_p = max(
                    0.08,
                    1.0 - (age / _base.HIT_FLASH_SECONDS) * 0.90,
                )
                trail = self._hand_lane_arc(lane, head_p, 0.44)
                pygame.draw.lines(
                    self.screen,
                    _blend(
                        MAGENTA,
                        WHITE,
                        min(0.95, 0.50 + 0.20 * power),
                    ),
                    False,
                    trail,
                    max(4, int(5 * power * phase + 2)),
                )
            else:
                pygame.draw.lines(
                    self.screen,
                    RED,
                    False,
                    receptor,
                    max(2, int(5 * phase)),
                )

            word = self.hit_font.render(judgement.upper(), True, jcolor)
            tx, ty = self._hand_target_point(lane, 0.90)
            self.screen.blit(word, word.get_rect(center=(int(tx), int(ty))))

    def _draw_foot_receptors(
        self,
        body: BodyState,
        notes: list[GameNote],
        song_time: float,
        enabled: bool,
        strike_events: tuple[MotionEvent, ...],
    ) -> None:
        occupied = body.foot_lanes if enabled else frozenset()
        y = self._field_y(NoteKind.FOOT, 1.0)
        left, right = self._field_bounds(NoteKind.FOOT, 1.0)
        line_color = _blend(WHITE, BG, 0.30) if enabled else _blend(DIM, BG, 0.55)
        pygame.draw.line(self.screen, line_color, (left, y), (right, y), 1)

        for lane in range(1, 5):
            l, r = self._lane_bounds(NoteKind.FOOT, lane, 1.0)
            pad = max(5, int((r - l) * 0.08))
            gate_l = l + pad
            gate_r = r - pad
            center_x = (gate_l + gate_r) / 2.0
            is_occupied = enabled and lane in occupied
            near = enabled and self._target_is_near(notes, song_time, NoteKind.FOOT, lane)
            judgement, age = (
                self._judgement_for_lane(notes, song_time, NoteKind.FOOT, lane)
                if enabled
                else (None, 999.0)
            )
            strike_age: float | None = None
            strike_strength = 0.0
            if enabled and strike_events:
                matching = [
                    e
                    for e in strike_events
                    if e.kind == NoteKind.FOOT
                    and e.lane == lane
                    and 0.0
                    <= song_time - e.song_time
                    <= MOTION_EVENT_VISUAL_SECONDS + 0.04
                ]
                if matching:
                    latest = max(matching, key=lambda e: e.song_time)
                    strike_age = song_time - latest.song_time
                    strike_strength = max(1.0, min(2.2, float(latest.strength)))

            idle_color = DIM if enabled else _blend(DIM, BG, 0.58)
            base_gate_color = CYAN if is_occupied else idle_color
            input_flash = 0.0
            if strike_age is not None:
                life = min(1.0, strike_age / MOTION_EVENT_VISUAL_SECONDS)
                input_flash = (1.0 - life) ** 1.45
                input_flash *= min(1.0, 0.82 + 0.08 * strike_strength)

            gate_color = _blend(base_gate_color, WHITE, 0.90 * input_flash)
            gate_width = max(1, (4 if is_occupied else 1) + int(round(2.0 * input_flash)))
            tick = 9 + int(round(5.0 * input_flash))
            arm = max(10, int((gate_r - gate_l) * (0.15 + 0.035 * input_flash)))

            if input_flash > 0.02:
                halo_color = _blend(
                    BG,
                    _blend(CYAN, WHITE, 0.62),
                    0.30 + 0.52 * input_flash,
                )
                halo_pad = 4 + int(5 * input_flash)
                halo_tick = tick + 4 + int(4 * input_flash)
                pygame.draw.line(
                    self.screen,
                    halo_color,
                    (gate_l - halo_pad, y - halo_tick),
                    (gate_l - halo_pad, y + halo_tick),
                    2,
                )
                pygame.draw.line(
                    self.screen,
                    halo_color,
                    (gate_r + halo_pad, y - halo_tick),
                    (gate_r + halo_pad, y + halo_tick),
                    2,
                )

            pygame.draw.line(self.screen, gate_color, (gate_l, y - tick), (gate_l, y + tick), gate_width)
            pygame.draw.line(self.screen, gate_color, (gate_l, y), (gate_l + arm, y), gate_width)
            pygame.draw.line(self.screen, gate_color, (gate_r, y - tick), (gate_r, y + tick), gate_width)
            pygame.draw.line(self.screen, gate_color, (gate_r - arm, y), (gate_r, y), gate_width)

            base_diamond = CYAN if is_occupied else idle_color
            diamond_color = _blend(base_diamond, WHITE, 0.96 * input_flash)
            radius = (6 if is_occupied else 3) + int(round(5.0 * input_flash))
            pygame.draw.polygon(
                self.screen,
                diamond_color,
                [
                    (center_x, y - radius),
                    (center_x + radius, y),
                    (center_x, y + radius),
                    (center_x - radius, y),
                ],
                0 if (is_occupied or input_flash > 0.02) else 1,
            )

            if input_flash > 0.08:
                core_r = max(2, int(3 + 4 * input_flash))
                pygame.draw.circle(self.screen, WHITE, (int(center_x), int(y)), core_r)

            if near:
                outer_tick = 14
                near_color = _blend(WHITE, CYAN, 0.25)
                pygame.draw.line(
                    self.screen,
                    near_color,
                    (gate_l - 4, y - outer_tick),
                    (gate_l - 4, y + outer_tick),
                    1,
                )
                pygame.draw.line(
                    self.screen,
                    near_color,
                    (gate_r + 4, y - outer_tick),
                    (gate_r + 4, y + outer_tick),
                    1,
                )

            if judgement is not None:
                phase = 1.0 - min(age / _base.HIT_FLASH_SECONDS, 1.0)
                is_hit = judgement != "miss"
                if judgement == "perfect":
                    jcolor = _blend(AMBER, WHITE, 0.35)
                    pulse_power = 1.65
                elif judgement == "great":
                    jcolor = _blend(CYAN, WHITE, 0.55)
                    pulse_power = 1.30
                elif judgement == "hit":
                    jcolor = GREEN
                    pulse_power = 1.0
                else:
                    jcolor = RED
                    pulse_power = 0.0

                if is_hit:
                    travel = min(1.0, age / _base.HIT_FLASH_SECONDS)
                    head_p = max(0.03, 1.0 - travel * 0.97)
                    tail_p = min(1.0, head_p + 0.22 + 0.06 * pulse_power)
                    pulse_color = _blend(CYAN, WHITE, min(0.96, 0.64 + 0.16 * pulse_power))
                    trail_color = _blend(BG, CYAN, min(0.75, 0.34 * pulse_power * phase))
                    for boundary in (lane - 1, lane):
                        frac = boundary / 4.0
                        hl, hr = self._field_bounds(NoteKind.FOOT, head_p)
                        tl, tr = self._field_bounds(NoteKind.FOOT, tail_p)
                        el, er = self._field_bounds(NoteKind.FOOT, 1.0)
                        x_head = hl + (hr - hl) * frac
                        x_tail = tl + (tr - tl) * frac
                        x_end = el + (er - el) * frac
                        y_head = self._field_y(NoteKind.FOOT, head_p)
                        y_tail = self._field_y(NoteKind.FOOT, tail_p)
                        y_end = self._field_y(NoteKind.FOOT, 1.0)
                        pygame.draw.line(
                            self.screen,
                            trail_color,
                            (x_head, y_head),
                            (x_end, y_end),
                            max(2, int(2 * pulse_power)),
                        )
                        pygame.draw.line(
                            self.screen,
                            pulse_color,
                            (x_head, y_head),
                            (x_tail, y_tail),
                            max(6, int(6 * pulse_power)),
                        )
                        pygame.draw.line(
                            self.screen,
                            WHITE,
                            (x_head, y_head),
                            (x_tail, y_tail),
                            max(2, int(2 * pulse_power)),
                        )

                    center_frac = (lane - 0.5) / 4.0
                    hl, hr = self._field_bounds(NoteKind.FOOT, head_p)
                    tl, tr = self._field_bounds(NoteKind.FOOT, tail_p)
                    cx_head = hl + (hr - hl) * center_frac
                    cx_tail = tl + (tr - tl) * center_frac
                    pygame.draw.line(
                        self.screen,
                        _blend(CYAN, WHITE, min(0.92, 0.48 + 0.22 * pulse_power)),
                        (cx_head, self._field_y(NoteKind.FOOT, head_p)),
                        (cx_tail, self._field_y(NoteKind.FOOT, tail_p)),
                        max(3, int(3 * pulse_power)),
                    )

                    ring_r = int(12 + (22 + 8 * pulse_power) * (1.0 - phase))
                    pygame.draw.circle(
                        self.screen,
                        jcolor,
                        (int(center_x), int(y)),
                        ring_r,
                        max(2, int(4 * phase * pulse_power)),
                    )
                    pygame.draw.circle(
                        self.screen,
                        WHITE,
                        (int(center_x), int(y)),
                        max(3, int(6 * phase * pulse_power)),
                        1,
                    )
                else:
                    cross = int(7 + 7 * (1.0 - phase))
                    pygame.draw.line(
                        self.screen,
                        jcolor,
                        (center_x - cross, y - cross),
                        (center_x + cross, y + cross),
                        3,
                    )
                    pygame.draw.line(
                        self.screen,
                        jcolor,
                        (center_x - cross, y + cross),
                        (center_x + cross, y - cross),
                        3,
                    )

                surf = self.hit_font.render(judgement.upper(), True, jcolor)
                self.screen.blit(surf, surf.get_rect(center=(center_x, y + 31)))

        if not enabled:
            off = self.small_font.render(
                "NO FOOT NOTES",
                True,
                _blend(DIM, BG, 0.30),
            )
            self.screen.blit(off, off.get_rect(center=((left + right) / 2, y - 48)))

    def _draw_receptors(
        self,
        body: BodyState,
        notes: list[GameNote],
        song_time: float,
        hand_enabled: bool,
        foot_enabled: bool,
        strike_events: tuple[MotionEvent, ...],
    ) -> None:
        foot_notes = [note for note in notes if note.kind == NoteKind.FOOT]
        foot_events = tuple(
            event for event in strike_events if event.kind == NoteKind.FOOT
        )
        self._draw_foot_receptors(
            body,
            foot_notes,
            song_time,
            foot_enabled,
            foot_events,
        )
        self._draw_hand_receptor_feedback(
            body,
            notes,
            song_time,
            hand_enabled,
            strike_events,
        )

        if not foot_enabled:
            return

        foot_y = self._field_y(NoteKind.FOOT, 1.0)
        foot_left = self._lane_boundary_x(NoteKind.FOOT, 0, 1.0)
        foot_right = self._lane_boundary_x(NoteKind.FOOT, 4, 1.0)
        wall_left = self._floor_gutter_outer_point("left", 1.0)[0]
        wall_right = self._floor_gutter_outer_point("right", 1.0)[0]
        line_color = _blend(WHITE, BG, 0.30)
        pygame.draw.line(self.screen, line_color, (wall_left, foot_y), (foot_left, foot_y), 1)
        pygame.draw.line(self.screen, line_color, (foot_right, foot_y), (wall_right, foot_y), 1)

    def _spawn_note_effects(self, notes: list[GameNote]) -> None:
        for note in notes:
            ident = id(note)
            if not note.judged or note.judged_at is None:
                continue
            if not note.hit:
                if ident not in self._seen_misses:
                    self._seen_misses.add(ident)
                    for lane in note.lanes:
                        self._miss_impacts.append(
                            {
                                "kind": note.kind,
                                "lane": lane,
                                "born": note.judged_at,
                                "life": 0.34,
                            }
                        )
                continue
            if ident in self._seen_hits:
                continue
            self._seen_hits.add(ident)
            quality = note.judgement or HitQuality.HIT
            power = {
                HitQuality.HIT: 1.0,
                HitQuality.GREAT: 1.35,
                HitQuality.PERFECT: 1.75,
            }[quality]
            base_color = MAGENTA if note.kind == NoteKind.HANDS else CYAN
            shard_color = _blend(
                base_color,
                WHITE,
                {
                    HitQuality.HIT: 0.10,
                    HitQuality.GREAT: 0.35,
                    HitQuality.PERFECT: 0.60,
                }[quality],
            )
            count = {
                HitQuality.HIT: 11,
                HitQuality.GREAT: 17,
                HitQuality.PERFECT: 25,
            }[quality]
            for lane in note.lanes:
                self._impact_bursts.append(
                    {
                        "kind": note.kind,
                        "lane": lane,
                        "born": note.judged_at,
                        "life": {
                            HitQuality.HIT: 0.18,
                            HitQuality.GREAT: 0.23,
                            HitQuality.PERFECT: 0.29,
                        }[quality],
                        "power": power,
                        "color": shard_color,
                    }
                )
                outward_count = {
                    HitQuality.HIT: 4,
                    HitQuality.GREAT: 6,
                    HitQuality.PERFECT: 9,
                }[quality]
                for _ in range(outward_count):
                    self._outbound_particles.append(
                        {
                            "kind": note.kind,
                            "lane": lane,
                            "born": note.judged_at,
                            "life": self._rng.uniform(0.20, 0.34),
                            "vx": self._rng.uniform(-48.0, 48.0) * power,
                            "vy": self._rng.uniform(150.0, 280.0) * power,
                            "length": self._rng.uniform(7.0, 18.0) * power,
                            "size": self._rng.randint(1, 3),
                            "color": shard_color,
                        }
                    )
                for _ in range(count):
                    self._particles.append(
                        {
                            "kind": note.kind,
                            "lane": lane,
                            "born": note.judged_at,
                            "life": self._rng.uniform(0.38, 0.66)
                            * (0.95 + 0.12 * power),
                            "speed": self._rng.uniform(1.05, 2.15)
                            * (0.90 + 0.12 * power),
                            "jitter": self._rng.uniform(-0.12, 0.12),
                            "lateral": self._rng.uniform(-0.95, 0.95),
                            "drift": self._rng.uniform(-0.20, 0.20),
                            "length": self._rng.uniform(0.10, 0.24) * power,
                            "size": self._rng.randint(2, max(3, int(3 + power))),
                            "color": shard_color,
                        }
                    )

    def _draw_particles(self, song_time: float) -> None:
        w, h = self.size

        burst_alive = []
        for burst in self._impact_bursts:
            age = song_time - float(burst["born"])
            life = float(burst["life"])
            if age < 0.0 or age > life:
                continue
            phase = age / max(life, 1e-6)
            lane = int(burst["lane"])
            power = float(burst["power"])
            fade = (1.0 - phase) ** 1.4
            color = _blend(BG, burst["color"], fade)

            if burst["kind"] == NoteKind.FOOT:
                left, right = self._lane_bounds(NoteKind.FOOT, lane, 1.0)
                cx = int((left + right) * 0.5)
                cy = int(self._field_y(NoteKind.FOOT, 1.0))
                radius = int(max(4.0, right - left) * (0.10 + 0.30 * phase) * power)
                diamond = [
                    (cx, cy - radius),
                    (cx + radius, cy),
                    (cx, cy + radius),
                    (cx - radius, cy),
                ]
                pygame.draw.polygon(self.screen, _blend(BG, color, 0.24 * fade), diamond)
                pygame.draw.polygon(
                    self.screen,
                    _blend(BG, color, 0.70),
                    diamond,
                    max(1, int(5 * fade)),
                )
                arm = int(radius * 0.72)
                pygame.draw.line(
                    self.screen, color, (cx - arm, cy), (cx + arm, cy),
                    max(1, int(3 * fade)),
                )
                pygame.draw.line(
                    self.screen, color, (cx, cy - arm), (cx, cy + arm),
                    max(1, int(3 * fade)),
                )
            else:
                cx, cy = self._hand_target_point(lane, 1.0)
                radius = int((18 + 48 * phase) * power)
                pygame.draw.circle(
                    self.screen,
                    _blend(BG, color, 0.25 * fade),
                    (int(cx), int(cy)),
                    radius,
                )
                pygame.draw.circle(
                    self.screen,
                    color,
                    (int(cx), int(cy)),
                    radius,
                    max(1, int(5 * fade)),
                )
            burst_alive.append(burst)
        self._impact_bursts = burst_alive

        particle_alive = []
        for particle in self._particles:
            age = song_time - float(particle["born"])
            life = float(particle["life"])
            if age < 0.0 or age > life:
                continue
            phase = age / max(life, 1e-6)
            progress = max(0.03, 1.0 - age * float(particle["speed"]))
            lane = int(particle["lane"])
            fade = 1.0 - phase
            color = _blend(BG, particle["color"], fade)

            if particle["kind"] == NoteKind.FOOT:
                left, right = self._lane_bounds(NoteKind.FOOT, lane, progress)
                lane_width = max(1.0, right - left)
                center = (left + right) * 0.5
                offset = (
                    float(particle["jitter"])
                    + float(particle["drift"]) * phase
                    + float(particle.get("lateral", 0.0)) * (phase ** 0.72) * 0.72
                )
                x = center + offset * lane_width
                y = self._field_y(NoteKind.FOOT, progress)
                length = max(
                    2.0,
                    lane_width * float(particle["length"]) * (0.35 + 0.65 * fade),
                )
                thickness = max(1, int(int(particle["size"]) * (0.65 + fade)))
                dx = length * 0.5
                dy = dx * float(particle["jitter"]) * 0.35
                pygame.draw.line(
                    self.screen,
                    _blend(BG, color, 0.42),
                    (int(x - dx), int(y - dy)),
                    (int(x + dx), int(y + dy)),
                    thickness + 3,
                )
                pygame.draw.line(
                    self.screen,
                    color,
                    (int(x - dx), int(y - dy)),
                    (int(x + dx), int(y + dy)),
                    thickness,
                )
            else:
                lane_span = _HAND_BOUNDARIES[lane] - _HAND_BOUNDARIES[lane - 1]
                along = _HAND_CENTERS[lane - 1] + (
                    float(particle["jitter"])
                    + float(particle.get("lateral", 0.0)) * phase * 0.45
                ) * lane_span
                x, y = self._hand_point(along, progress)
                before = self._hand_point(max(0.0, along - 0.006), progress)
                after = self._hand_point(min(1.0, along + 0.006), progress)
                tx, ty = after[0] - before[0], after[1] - before[1]
                magnitude = max(1.0, math.hypot(tx, ty))
                tx, ty = tx / magnitude, ty / magnitude
                length = float(particle["length"]) * 70.0 * (0.4 + 0.6 * fade)
                pygame.draw.line(
                    self.screen,
                    color,
                    (int(x - tx * length), int(y - ty * length)),
                    (int(x + tx * length), int(y + ty * length)),
                    max(1, int(particle["size"])),
                )
            particle_alive.append(particle)
        self._particles = particle_alive

        outbound_alive = []
        for particle in self._outbound_particles:
            age = song_time - float(particle["born"])
            life = float(particle["life"])
            if age < 0.0 or age > life:
                continue
            phase = age / max(life, 1e-6)
            lane = int(particle["lane"])
            fade = (1.0 - phase) ** 1.25
            color = _blend(BG, particle["color"], fade)
            length = float(particle["length"]) * (0.55 + 0.45 * fade)

            if particle["kind"] == NoteKind.FOOT:
                left, right = self._lane_bounds(NoteKind.FOOT, lane, 1.0)
                x = (left + right) * 0.5 + float(particle["vx"]) * age
                y = self._field_y(NoteKind.FOOT, 1.0) + float(particle["vy"]) * age
                pygame.draw.line(
                    self.screen,
                    color,
                    (int(x), int(y - length * 0.5)),
                    (int(x), int(y + length * 0.5)),
                    max(1, int(particle["size"])),
                )
            else:
                start = self._hand_target_point(lane, 1.0)
                ux, uy = self._hand_lane_direction(lane)
                tangent_x, tangent_y = -uy, ux
                radial = float(particle["vy"]) * age
                lateral = float(particle["vx"]) * age * 0.45
                x = start[0] + ux * radial + tangent_x * lateral
                y = start[1] + uy * radial + tangent_y * lateral
                pygame.draw.line(
                    self.screen,
                    color,
                    (int(x - ux * length * 0.5), int(y - uy * length * 0.5)),
                    (int(x + ux * length * 0.5), int(y + uy * length * 0.5)),
                    max(1, int(particle["size"])),
                )
            outbound_alive.append(particle)
        self._outbound_particles = outbound_alive

        miss_alive = []
        for impact in self._miss_impacts:
            age = song_time - float(impact["born"])
            life = float(impact["life"])
            if age < 0.0 or age > life:
                continue
            phase = age / max(life, 1e-6)
            pulse = math.sin(math.pi * min(1.0, phase)) * (1.0 - 0.32 * phase)
            lane = int(impact["lane"])
            edge = _blend(BG, RED, 0.48 + 0.42 * pulse)

            if impact["kind"] == NoteKind.FOOT:
                left, right = self._lane_bounds(NoteKind.FOOT, lane, 1.0)
                pad = max(8.0, (right - left) * 0.15)
                hit_y = self._field_y(NoteKind.FOOT, 1.0)
                pygame.draw.polygon(
                    self.screen,
                    _blend(BG, RED, 0.18 + 0.42 * pulse),
                    [
                        (left, hit_y),
                        (right, hit_y),
                        (right + pad, h),
                        (left - pad, h),
                    ],
                )
                pygame.draw.line(
                    self.screen,
                    edge,
                    (int(max(0, left - pad)), h - 3),
                    (int(min(w, right + pad)), h - 3),
                    max(2, int(5 * pulse)),
                )
            else:
                pygame.draw.lines(
                    self.screen,
                    edge,
                    False,
                    self._hand_lane_arc(lane, 1.0, 1.0),
                    max(2, int(7 * pulse)),
                )
            miss_alive.append(impact)
        self._miss_impacts = miss_alive

    def _draw_hand_tracking_markers(self, body: BodyState, enabled: bool) -> None:
        if not enabled:
            return
        w, h = self.size
        for control in (body.left_hand_control, body.right_hand_control):
            if not control.visible or control.lane is None:
                continue

            along = hand_control_perimeter_along(control)
            outer = self._hand_point(along, 1.0)
            inner = self._hand_point(along, 0.94)
            dx, dy = outer[0] - inner[0], outer[1] - inner[1]
            length = max(1.0, math.hypot(dx, dy))
            mx = outer[0] + dx / length * _HAND_TRACKER_OFFSET_PX
            my = outer[1] + dy / length * _HAND_TRACKER_OFFSET_PX
            mx = max(8.0, min(float(w - 8), mx))
            my = max(8.0, min(float(h - 8), my))

            pygame.draw.circle(self.screen, BG, (int(mx), int(my)), 9)
            pygame.draw.circle(self.screen, MAGENTA, (int(mx), int(my)), 6)
            pygame.draw.circle(
                self.screen,
                _blend(MAGENTA, WHITE, 0.34),
                (int(mx), int(my)),
                6,
                1,
            )

    def _draw_body_markers(
        self,
        body: BodyState,
        show_labels: bool = False,
        hand_enabled: bool = True,
        foot_enabled: bool = True,
        show_lower_body_sources: bool = False,
    ) -> None:
        if foot_enabled:
            left_control = (
                body.left_foot_control
                if body.left_foot_control.visible
                else body.left_knee
            )
            right_control = (
                body.right_foot_control
                if body.right_foot_control.visible
                else body.right_knee
            )

            if show_lower_body_sources:
                source_color = _blend(BG, CYAN, 0.42)
                for knee, ankle, control in (
                    (body.left_knee, body.left_ankle, left_control),
                    (body.right_knee, body.right_ankle, right_control),
                ):
                    if knee.visible and ankle.visible:
                        pygame.draw.line(
                            self.screen,
                            _blend(BG, CYAN, 0.25),
                            self._screen_point(knee),
                            self._screen_point(ankle),
                            1,
                        )
                    for source in (knee, ankle):
                        if source.visible:
                            pos = self._screen_point(source)
                            pygame.draw.circle(self.screen, BG, pos, 5)
                            pygame.draw.circle(self.screen, source_color, pos, 4, 1)
                    if control.visible:
                        pygame.draw.circle(
                            self.screen,
                            WHITE,
                            self._screen_point(control),
                            11,
                            1,
                        )

            for control in (left_control, right_control):
                if not control.visible:
                    continue
                pos = self._screen_point(control)
                pygame.draw.circle(self.screen, BG, pos, 9)
                pygame.draw.circle(self.screen, CYAN, pos, 7, 2)
                if show_labels and control.lane is not None:
                    label = self.small_font.render(str(control.lane), True, WHITE)
                    self.screen.blit(label, label.get_rect(center=pos))

        self._draw_hand_tracking_markers(body, hand_enabled)
