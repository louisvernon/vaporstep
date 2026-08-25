from __future__ import annotations

import math

import pygame

from . import renderer_tunnel_base as _tunnel
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
from .domain import BodyState, ChainMode, GameNote, HitQuality, NoteKind
from .hand_control import hand_control_perimeter_along
from .keyboard_input import label_for_lane
from .lanes import perspective_adjusted_x


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
_HAND_TRACKER_OFFSET_PX = 10.0
_TARGET_PREENTRY_BEATS = 1.0
_TARGET_PREENTRY_SECONDS = 0.50


class Renderer(_tunnel.Renderer):
    """Body-relative hand tunnel with one canonical smooth gameplay surface."""

    def _hand_tunnel_geometry(self):
        """Return smooth gameplay arcs plus decorative side-shelf anchors."""
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

        outer_cx = (shoulder_left[0] + shoulder_right[0]) * 0.5
        outer_base_y = (shoulder_left[1] + shoulder_right[1]) * 0.5
        outer_rx = max(10.0, (shoulder_right[0] - shoulder_left[0]) * 0.5)
        outer_ry = max(20.0, outer_base_y - outer_top)
        outer = (outer_cx, outer_base_y, outer_rx, outer_ry)
        shelves = (seam_left, seam_right, shoulder_left, shoulder_right)
        return inner, outer, shelves

    def _hand_point(self, along: float, progress: float) -> tuple[float, float]:
        """The one surface used by rails, notes, holds, effects and markers."""
        inner, outer, _ = self._hand_tunnel_geometry()
        p = max(0.0, min(1.0, progress)) ** 1.25
        ix, iy = self._ellipse_upper_point(inner, along)
        ox, oy = self._ellipse_upper_point(outer, along)
        return ix + (ox - ix) * p, iy + (oy - iy) * p

    def _hand_note_arc_points(
        self,
        lane: int,
        progress: float,
        fraction: float,
        *,
        samples: int = 14,
    ) -> list[tuple[int, int]]:
        """A target is an exact cross-section of the tunnel surface."""
        boundaries = _tunnel._HAND_BOUNDARIES
        centers = _tunnel._HAND_CENTERS
        start = boundaries[lane - 1]
        end = boundaries[lane]
        center = centers[lane - 1]
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

    def _draw_hand_side_shelves(self, rail_color) -> None:
        """Draw neutral structural shelves outside the note-bearing surface."""
        _, _, shelves = self._hand_tunnel_geometry()
        seam_left, seam_right, shoulder_left, shoulder_right = shelves
        pygame.draw.line(self.screen, rail_color, seam_left, shoulder_left, 2)
        pygame.draw.line(self.screen, rail_color, shoulder_right, seam_right, 2)

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

        # Experimental BPM ripple recedes from the player into the tunnel.
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

        # These floor shelves are deliberately not a continuation of the pink
        # hand receptor. Color here is reserved for foot out-of-bounds feedback.
        self._draw_hand_side_shelves(rail_color)

        if not enabled:
            cx, cy = self._hand_point(0.5, 0.0)
            off = self.small_font.render("NO HAND NOTES", True, _blend(DIM, BG, 0.30))
            self.screen.blit(off, off.get_rect(center=(int(cx), int(cy - 20))))

    def _foot_outside_strengths(self, body: BodyState) -> tuple[float, float]:
        """Return left/right warning strength using the real foot resolver geometry."""
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
                left_strength = max(
                    left_strength,
                    min(1.0, (left_limit - adjusted) / ramp),
                )
            elif adjusted > right_limit:
                right_strength = max(
                    right_strength,
                    min(1.0, (adjusted - right_limit) / ramp),
                )
        return left_strength, right_strength

    @staticmethod
    def _scaled_additive_color(color, amount: float) -> tuple[int, int, int]:
        amount = max(0.0, min(1.0, amount))
        return tuple(max(0, min(255, int(channel * amount))) for channel in color)

    def _draw_foot_boundary_warning(self, body: BodyState) -> None:
        left_strength, right_strength = self._foot_outside_strengths(body)
        if max(left_strength, right_strength) <= 0.0:
            return

        _, _, shelves = self._hand_tunnel_geometry()
        seam_left, seam_right, shoulder_left, shoulder_right = shelves
        warning_surface = pygame.Surface(self.size)
        warning_surface.fill((0, 0, 0))

        # Light the flat floor shelf itself rather than the playable foot lanes.
        # Successive strips make the warning read as a soft red floor glow.
        for start, end, strength in (
            (shoulder_left, seam_left, left_strength),
            (seam_right, shoulder_right, right_strength),
        ):
            if strength <= 0.0:
                continue
            x0, x1 = sorted((float(start[0]), float(end[0])))
            base_y = float(start[1])
            for depth, scale in ((42.0, 0.12), (28.0, 0.20), (14.0, 0.34)):
                color = self._scaled_additive_color(RED, strength * scale)
                pygame.draw.polygon(
                    warning_surface,
                    color,
                    [
                        (int(x0), int(base_y)),
                        (int(x1), int(base_y)),
                        (int(x1), int(base_y - depth)),
                        (int(x0), int(base_y - depth)),
                    ],
                )
            edge_color = self._scaled_additive_color(RED, 0.55 * strength)
            pygame.draw.line(warning_surface, edge_color, start, end, 3)

        self.screen.blit(warning_surface, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

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
        super()._draw_playfields(
            body,
            song_time,
            beat_pulse,
            downbeat,
            hand_enabled,
            foot_enabled,
            overdrive,
            animate_buzz,
        )
        if foot_enabled:
            self._draw_foot_boundary_warning(body)

    def _target_glow_state(
        self,
        note: GameNote,
        song_time: float,
        song_beat: float,
    ) -> tuple[float, float, bool] | None:
        if note.judged:
            return None

        if note.beat is not None:
            distance = float(note.beat) - song_beat
            if distance > LOOKAHEAD_BEATS:
                extra = distance - LOOKAHEAD_BEATS
                if extra > _TARGET_PREENTRY_BEATS:
                    return None
                strength = 1.0 - extra / _TARGET_PREENTRY_BEATS
                return 0.0, 0.18 * strength, True
        else:
            distance = note.time - song_time
            if distance > LOOKAHEAD_SECONDS:
                extra = distance - LOOKAHEAD_SECONDS
                if extra > _TARGET_PREENTRY_SECONDS:
                    return None
                strength = 1.0 - extra / _TARGET_PREENTRY_SECONDS
                return 0.0, 0.18 * strength, True

        progress = max(0.0, min(1.0, self._note_progress(note, song_time, song_beat)))
        return progress, 0.18 + 0.38 * (progress ** 0.85), False

    def _foot_note_points(self, lane: int, progress: float) -> list[tuple[int, int]]:
        left, right = self._lane_bounds(NoteKind.FOOT, lane, progress)
        y = self._field_y(NoteKind.FOOT, progress)
        pad = max(2.0, (right - left) * 0.08)
        return [(int(left + pad), int(y)), (int(right - pad), int(y))]

    @classmethod
    def _draw_glow_stroke(
        cls,
        surface: pygame.Surface,
        points: list[tuple[int, int]],
        color,
        intensity: float,
        core_width: int,
    ) -> None:
        """Broad additive source glow with no reflected surface band."""
        if len(points) < 2 or intensity <= 0.0:
            return
        for extra, scale in ((42, 0.10), (28, 0.16), (16, 0.26), (8, 0.38)):
            glow_color = cls._scaled_additive_color(color, intensity * scale)
            pygame.draw.lines(
                surface,
                glow_color,
                False,
                points,
                max(1, core_width + extra),
            )

    def _draw_target_glows(
        self,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
    ) -> None:
        # Additive light behaves like illumination over the dark tunnel/camera,
        # unlike the previous very-low-alpha overlay which was effectively lost.
        glow_surface = pygame.Surface(self.size)
        glow_surface.fill((0, 0, 0))
        any_glow = False

        for note in notes:
            # Match the normal note renderer: don't advertise source notes that
            # are currently represented by a hold/chain block instead.
            if note.end_time is not None and note.chain_id is not None:
                continue
            if note.chain_id is not None and chain_mode == ChainMode.BLOCKS:
                continue

            state = self._target_glow_state(note, song_time, song_beat)
            if state is None:
                continue
            progress, intensity, preentry = state
            theme = MAGENTA if note.kind == NoteKind.HANDS else CYAN

            for lane in note.lanes:
                if note.kind == NoteKind.HANDS:
                    points = self._hand_note_arc_points(
                        lane,
                        0.0 if preentry else progress,
                        _tunnel._HAND_NOTE_ARC_FRACTION,
                        samples=18,
                    )
                    core_width = max(5, int(5 + 12 * (0.0 if preentry else progress)))
                else:
                    points = self._foot_note_points(lane, 0.0 if preentry else progress)
                    core_width = max(4, int(4 + 12 * (0.0 if preentry else progress)))

                # The pre-entry hint is intentionally softer, but uses exactly
                # the same source shape as the target when it first appears.
                local_intensity = intensity * (0.82 if preentry else 1.0)
                self._draw_glow_stroke(
                    glow_surface,
                    points,
                    theme,
                    local_intensity,
                    core_width,
                )
                any_glow = True

        if any_glow:
            self.screen.blit(glow_surface, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _draw_notes(
        self,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode = ChainMode.OFF,
    ) -> None:
        self._draw_target_glows(notes, song_time, song_beat, chain_mode)
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
