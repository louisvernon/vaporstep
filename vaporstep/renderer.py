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
from .scroll import timed_is_within_lookahead, timed_progress


# Public renderer palette/helpers used by sibling UI modules.
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
_HAND_TUNNEL_VERTICAL_SCALE = 0.86
_HAND_TRACKER_OFFSET_PX = 10.0
_TARGET_PREENTRY_BEATS = 1.5
_TARGET_PREENTRY_SECONDS = 0.75


class _ReceptorLabelFilter:
    """Suppress captions and the base renderer's late foot key labels."""

    def __init__(self, font) -> None:
        self._font = font

    def render(self, text, antialias, color, *args, **kwargs):
        if text in {"FEET", "HANDS", "J", "K", "L", ";"}:
            return pygame.Surface((1, 1), pygame.SRCALPHA)
        return self._font.render(text, antialias, color, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._font, name)


class Renderer(_tunnel.Renderer):
    """Body-relative tunnel renderer with the validated visual-polish behavior."""

    def _hand_tunnel_geometry(self):
        inner, old_outer = super()._hand_arc_geometry()
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
        outer_rx = max(inner_rx + 20.0, (shoulder_right[0] - shoulder_left[0]) * 0.5)
        outer = (
            (shoulder_left[0] + shoulder_right[0]) * 0.5,
            outer_base_y,
            outer_rx,
            old_ry * _HAND_TUNNEL_VERTICAL_SCALE,
        )
        shelves = (seam_left, seam_right, shoulder_left, shoulder_right)
        return inner, outer, shelves

    def _hand_point(self, along: float, progress: float) -> tuple[float, float]:
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
        floor_surface = pygame.Surface(self.size, pygame.SRCALPHA)
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
        for boundary, along in enumerate(_tunnel._HAND_BOUNDARIES):
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

        fill = pygame.Surface(self.size, pygame.SRCALPHA)
        glow = pygame.Surface(self.size)
        glow.fill((0, 0, 0))
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
                    _tunnel._HAND_NOTE_ARC_FRACTION,
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
        if preentry and kind == NoteKind.FOOT:
            points, core_width = self._target_points(kind, lane, 0.08)
            self._draw_preentry_glow(
                surface,
                points,
                CYAN,
                intensity * 1.15,
                core_width,
            )
            return

        theme = MAGENTA if kind == NoteKind.HANDS else CYAN
        if preentry:
            points, core_width = self._target_points(kind, lane, 0.0)
            self._draw_preentry_glow(
                surface,
                points,
                theme,
                intensity * 0.92,
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
        glow_surface = pygame.Surface(self.size)
        glow_surface.fill((0, 0, 0))
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
        glow_surface = pygame.Surface(self.size)
        glow_surface.fill((0, 0, 0))
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

    def _draw_chains(
        self,
        chains: tuple[RuntimeChain, ...],
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
    ) -> None:
        self._draw_chain_head_glows(chains, song_time, song_beat, chain_mode)
        super()._draw_chains(chains, notes, song_time, song_beat, chain_mode)

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

    def _draw_receptors(
        self,
        body: BodyState,
        notes,
        song_time: float,
        hand_enabled: bool,
        foot_enabled: bool,
        strike_events,
    ) -> None:
        original_font = self.small_font
        self.small_font = _ReceptorLabelFilter(original_font)
        try:
            super()._draw_receptors(
                body,
                notes,
                song_time,
                hand_enabled,
                foot_enabled,
                strike_events,
            )
        finally:
            self.small_font = original_font

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
