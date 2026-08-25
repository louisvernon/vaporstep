from __future__ import annotations

import math

import pygame

from . import renderer_tunnel_base as _tunnel
from .config import LOOKAHEAD_BEATS, LOOKAHEAD_SECONDS
from .domain import BodyState, ChainMode, GameNote, HitQuality, NoteKind
from .hand_control import hand_control_perimeter_along
from .keyboard_input import label_for_lane


BG = _tunnel.BG
CYAN = _tunnel.CYAN
MAGENTA = _tunnel.MAGENTA
PURPLE = _tunnel.PURPLE
WHITE = _tunnel.WHITE
DIM = _tunnel.DIM
GRID = _tunnel.GRID
GREEN = _tunnel.GREEN
RED = _tunnel.RED
AMBER = _tunnel.AMBER
ELECTRIC_YELLOW = _tunnel.ELECTRIC_YELLOW
HIT_BRICK_POP_SECONDS = _tunnel.HIT_BRICK_POP_SECONDS
_blend = _tunnel._blend

_HAND_SHOULDER_EXTENSION = 0.12
_HAND_SHOULDER_PATH_FRACTION = 0.075
_HAND_TRACKER_OFFSET_PX = 10.0
_HAND_PREENTRY_BEATS = 1.0
_HAND_PREENTRY_SECONDS = 0.50


class Renderer(_tunnel.Renderer):
    """Tunnel renderer with a wider shouldered shell and lightweight feedback."""

    def _hand_tunnel_geometry(self):
        inner, old_outer = super()._hand_arc_geometry()
        viewport = self._camera_rect()
        cx, base_y, rx, _ = old_outer

        seam_left = (cx - rx, base_y)
        seam_right = (cx + rx, base_y)
        extension = viewport.width * _HAND_SHOULDER_EXTENSION
        shoulder_left = (
            max(float(viewport.left + 10), seam_left[0] - extension),
            base_y,
        )
        shoulder_right = (
            min(float(viewport.right - 10), seam_right[0] + extension),
            base_y,
        )
        outer_top = float(viewport.top) + max(26.0, viewport.height * 0.035)
        return inner, (seam_left, seam_right, shoulder_left, shoulder_right, outer_top)

    @staticmethod
    def _outer_tunnel_point(outer, along: float) -> tuple[float, float]:
        seam_left, seam_right, shoulder_left, shoulder_right, outer_top = outer
        t = max(0.0, min(1.0, along))
        shelf = _HAND_SHOULDER_PATH_FRACTION

        if t <= shelf:
            u = t / max(shelf, 1e-6)
            return (
                seam_left[0] + (shoulder_left[0] - seam_left[0]) * u,
                seam_left[1] + (shoulder_left[1] - seam_left[1]) * u,
            )
        if t >= 1.0 - shelf:
            u = (t - (1.0 - shelf)) / max(shelf, 1e-6)
            return (
                shoulder_right[0] + (seam_right[0] - shoulder_right[0]) * u,
                shoulder_right[1] + (seam_right[1] - shoulder_right[1]) * u,
            )

        u = (t - shelf) / max(1.0 - 2.0 * shelf, 1e-6)
        arch_cx = (shoulder_left[0] + shoulder_right[0]) * 0.5
        arch_base_y = (shoulder_left[1] + shoulder_right[1]) * 0.5
        arch_rx = max(10.0, (shoulder_right[0] - shoulder_left[0]) * 0.5)
        arch_ry = max(20.0, arch_base_y - outer_top)
        angle = math.pi + math.pi * u
        return (
            arch_cx + arch_rx * math.cos(angle),
            arch_base_y + arch_ry * math.sin(angle),
        )

    @staticmethod
    def _smooth_outer_tunnel_point(outer, along: float) -> tuple[float, float]:
        """Smooth guide for moving note bars; ignores decorative flat shelves."""
        _, _, shoulder_left, shoulder_right, outer_top = outer
        t = max(0.0, min(1.0, along))
        cx = (shoulder_left[0] + shoulder_right[0]) * 0.5
        base_y = (shoulder_left[1] + shoulder_right[1]) * 0.5
        rx = max(10.0, (shoulder_right[0] - shoulder_left[0]) * 0.5)
        ry = max(20.0, base_y - outer_top)
        angle = math.pi + math.pi * t
        return cx + rx * math.cos(angle), base_y + ry * math.sin(angle)

    def _hand_point(self, along: float, progress: float) -> tuple[float, float]:
        inner, outer = self._hand_tunnel_geometry()
        p = max(0.0, min(1.0, progress)) ** 1.25
        ix, iy = self._ellipse_upper_point(inner, along)
        ox, oy = self._outer_tunnel_point(outer, along)
        return ix + (ox - ix) * p, iy + (oy - iy) * p

    def _smooth_hand_point(self, along: float, progress: float) -> tuple[float, float]:
        inner, outer = self._hand_tunnel_geometry()
        p = max(0.0, min(1.0, progress)) ** 1.25
        ix, iy = self._ellipse_upper_point(inner, along)
        ox, oy = self._smooth_outer_tunnel_point(outer, along)
        return ix + (ox - ix) * p, iy + (oy - iy) * p

    def _hand_note_arc_points(
        self,
        lane: int,
        progress: float,
        fraction: float,
        *,
        samples: int = 14,
    ) -> list[tuple[int, int]]:
        boundaries = _tunnel._HAND_BOUNDARIES
        centers = _tunnel._HAND_CENTERS
        start = boundaries[lane - 1]
        end = boundaries[lane]
        center_along = centers[lane - 1]
        half = (end - start) * 0.5 * max(0.05, min(1.0, fraction))

        actual_center = self._hand_target_point(lane, progress)
        smooth_center = self._smooth_hand_point(center_along, progress)
        shift_x = actual_center[0] - smooth_center[0]
        shift_y = actual_center[1] - smooth_center[1]

        points: list[tuple[int, int]] = []
        for i in range(samples + 1):
            along = center_along - half + 2.0 * half * i / samples
            x, y = self._smooth_hand_point(along, progress)
            points.append((int(x + shift_x), int(y + shift_y)))
        return points

    def _draw_hand_note_arc(
        self,
        lane: int,
        progress: float,
        color,
        *,
        highlight: bool = False,
    ) -> None:
        p = max(0.0, min(1.0, progress))
        arc = self._hand_note_arc_points(lane, p, _tunnel._HAND_NOTE_ARC_FRACTION)
        thickness = max(5, int(5 + 12 * p))
        pygame.draw.lines(self.screen, BG, False, arc, thickness + 9)
        pygame.draw.lines(self.screen, color, False, arc, thickness)
        if highlight:
            pygame.draw.lines(self.screen, WHITE, False, arc, max(1, thickness // 5))

    def _draw_hand_hit_pop(self, lane: int, age: float, quality: HitQuality) -> None:
        phase = max(0.0, min(1.0, age / HIT_BRICK_POP_SECONDS))
        power = {HitQuality.HIT: 1.0, HitQuality.GREAT: 1.28, HitQuality.PERFECT: 1.60}[quality]
        fade = (1.0 - phase) ** 0.72
        hot = _blend(MAGENTA, WHITE, min(0.92, 0.40 + 0.24 * power))
        color = _blend(BG, hot, fade)
        fraction = min(
            0.88,
            _tunnel._HAND_NOTE_ARC_FRACTION
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

    def _hand_lane_light_band(
        self,
        lane: int,
        p0: float,
        p1: float,
        fraction: float = 0.90,
    ) -> list[tuple[int, int]]:
        boundaries = _tunnel._HAND_BOUNDARIES
        centers = _tunnel._HAND_CENTERS
        start = boundaries[lane - 1]
        end = boundaries[lane]
        center = centers[lane - 1]
        half = (end - start) * 0.5 * max(0.05, min(1.0, fraction))
        a0, a1 = center - half, center + half
        outer = self._hand_arc_points(a0, a1, p1, samples=18)
        inner = self._hand_arc_points(a1, a0, p0, samples=18)
        return [*outer, *inner]

    def _draw_hand_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        enabled: bool,
    ) -> None:
        occupied = body.hand_lanes if enabled else frozenset()
        disabled = _blend(DIM, BG, 0.58)

        depth_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        for band in range(8):
            p0 = band / 8.0
            p1 = (band + 1) / 8.0
            mid = (p0 + p1) * 0.5
            alpha = int(6 + 22 * (1.0 - mid))
            pygame.draw.polygon(depth_surface, (*BG, alpha), self._hand_depth_band(p0, p1))
        self.screen.blit(depth_surface, (0, 0))

        fill_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        for lane in range(1, 5):
            if enabled:
                pygame.draw.polygon(
                    fill_surface,
                    (*MAGENTA, 58 if lane in occupied else 8),
                    self._hand_sector_polygon(lane),
                )
        self.screen.blit(fill_surface, (0, 0))

        rail_color = GRID if enabled else disabled
        boundaries = _tunnel._HAND_BOUNDARIES
        for boundary, along in enumerate(boundaries):
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

        # Beat ripple now recedes from the receptor into the tunnel.
        pulse = max(0.0, min(1.0, beat_pulse))
        pulse_position = math.sqrt(pulse) if pulse > 0.005 else -1.0
        for step in range(1, 9):
            progress = step / 9.0
            ring_color = rail_color
            width = 1
            if enabled and pulse_position >= 0.0:
                proximity = max(0.0, 1.0 - abs(progress - pulse_position) / 0.18)
                if proximity > 0.0:
                    amount = proximity * (0.14 + 0.26 * math.sqrt(pulse))
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
            if enabled:
                lx, ly = self._hand_target_point(lane, 0.955)
                label = self.small_font.render(
                    label_for_lane(NoteKind.HANDS, lane),
                    True,
                    WHITE if active else DIM,
                )
                self.screen.blit(label, label.get_rect(center=(int(lx), int(ly))))

        if not enabled:
            cx, cy = self._hand_point(0.5, 0.0)
            off = self.small_font.render("NO HAND NOTES", True, _blend(DIM, BG, 0.30))
            self.screen.blit(off, off.get_rect(center=(int(cx), int(cy - 20))))

    def _note_light_state(
        self,
        note: GameNote,
        song_time: float,
        song_beat: float,
    ) -> tuple[float, float, bool] | None:
        if note.kind != NoteKind.HANDS or note.judged:
            return None

        if note.beat is not None:
            distance = float(note.beat) - song_beat
            if distance > LOOKAHEAD_BEATS:
                extra = distance - LOOKAHEAD_BEATS
                if extra > _HAND_PREENTRY_BEATS:
                    return None
                return 0.0, 0.20 * (1.0 - extra / _HAND_PREENTRY_BEATS), True
        else:
            distance = note.time - song_time
            if distance > LOOKAHEAD_SECONDS:
                extra = distance - LOOKAHEAD_SECONDS
                if extra > _HAND_PREENTRY_SECONDS:
                    return None
                return 0.0, 0.20 * (1.0 - extra / _HAND_PREENTRY_SECONDS), True

        progress = max(0.0, min(1.0, self._note_progress(note, song_time, song_beat)))
        return progress, 0.16 + 0.38 * (progress ** 0.85), False

    def _draw_hand_target_lighting(
        self,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
    ) -> None:
        light_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        any_light = False
        for note in notes:
            state = self._note_light_state(note, song_time, song_beat)
            if state is None:
                continue
            progress, intensity, preentry = state
            for lane in note.lanes:
                if preentry:
                    x, y = self._hand_target_point(lane, 0.0)
                    for radius, scale in ((22, 0.18), (14, 0.30), (7, 0.48)):
                        pygame.draw.circle(
                            light_surface,
                            (*MAGENTA, int(255 * intensity * scale)),
                            (int(x), int(y)),
                            radius,
                        )
                    pygame.draw.lines(
                        light_surface,
                        (*MAGENTA, int(255 * intensity * 0.75)),
                        False,
                        self._hand_lane_arc(lane, 0.0, 0.62),
                        5,
                    )
                    any_light = True
                    continue

                spread = 0.045 + 0.045 * progress
                p0 = max(0.0, progress - spread)
                p1 = min(1.0, progress + spread)
                pygame.draw.polygon(
                    light_surface,
                    (*MAGENTA, int(255 * intensity * 0.16)),
                    self._hand_lane_light_band(lane, p0, p1),
                )
                pygame.draw.lines(
                    light_surface,
                    (*MAGENTA, int(255 * intensity * 0.42)),
                    False,
                    self._hand_lane_arc(lane, progress, 0.84),
                    max(5, int(7 + 8 * progress)),
                )
                any_light = True

        if any_light:
            self.screen.blit(light_surface, (0, 0))

    def _draw_notes(
        self,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode = ChainMode.OFF,
    ) -> None:
        self._draw_hand_target_lighting(notes, song_time, song_beat)
        super()._draw_notes(notes, song_time, song_beat, chain_mode)

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
        super()._draw_body_markers(
            body,
            show_labels=show_labels,
            hand_enabled=hand_enabled,
            foot_enabled=foot_enabled,
            show_lower_body_sources=show_lower_body_sources,
        )
        self._draw_hand_tracking_markers(body, hand_enabled)
