from __future__ import annotations

import pygame

from .renderer_previous import *
from . import renderer_previous as _previous
from .domain import BodyState, NoteKind
from .keyboard_input import label_for_lane


_blend = _previous._blend

_HAND_TUNNEL_VERTICAL_SCALE = 0.86


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


class Renderer(_previous.Renderer):
    """Small visual-polish layer over the validated body-relative tunnel."""

    def _hand_tunnel_geometry(self):
        inner, old_outer = super(_previous.Renderer, self)._hand_arc_geometry()
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
        extension = viewport.width * _previous._HAND_SHOULDER_EXTENSION
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

    def _draw_hand_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        enabled: bool,
    ) -> None:
        occupied = body.hand_lanes if enabled else frozenset()
        disabled = _previous._blend(_previous.DIM, _previous.BG, 0.58)

        depth_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        for band in range(8):
            p0 = band / 8.0
            p1 = (band + 1) / 8.0
            mid = (p0 + p1) * 0.5
            alpha = int(6 + 22 * (1.0 - mid))
            pygame.draw.polygon(depth_surface, (*_previous.BG, alpha), self._hand_depth_band(p0, p1))
        self.screen.blit(depth_surface, (0, 0))

        fill_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        for lane in range(1, 5):
            if enabled:
                pygame.draw.polygon(
                    fill_surface,
                    (*_previous.MAGENTA, 58 if lane in occupied else 8),
                    self._hand_sector_polygon(lane),
                )
        self.screen.blit(fill_surface, (0, 0))

        rail_color = _previous.GRID if enabled else disabled
        boundaries = _previous._tunnel._HAND_BOUNDARIES
        for boundary, along in enumerate(boundaries):
            p0 = self._hand_point(along, 0.0)
            p1 = self._hand_point(along, 1.0)
            active_boundary = enabled and (
                (boundary > 0 and boundary in occupied)
                or (boundary < 4 and boundary + 1 in occupied)
            )
            if active_boundary:
                color, width = _previous.MAGENTA, 3
            elif enabled and boundary in (0, 4):
                color, width = _previous.MAGENTA, 2
            else:
                color, width = rail_color, 1
            pygame.draw.line(self.screen, color, p0, p1, width)

        inner_arc = self._hand_arc_points(0.0, 1.0, 0.0, samples=64)
        pygame.draw.lines(
            self.screen,
            _previous._blend(rail_color, _previous.WHITE, 0.10),
            False,
            inner_arc,
            2,
        )

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
                    ring_color = _previous._blend(rail_color, _previous.MAGENTA, amount)
                    width = 2 if amount > 0.18 else 1
            arc = self._hand_arc_points(0.0, 1.0, progress, samples=64)
            pygame.draw.lines(self.screen, ring_color, False, arc, width)

        for lane in range(1, 5):
            active = enabled and lane in occupied
            receptor = self._hand_lane_arc(lane, 1.0, 1.0)
            pygame.draw.lines(
                self.screen,
                _previous.MAGENTA if active else (_previous.DIM if enabled else disabled),
                False,
                receptor,
                6 if active else 2,
            )

        self._draw_floor_gutter_structure(_previous.GRID if enabled else disabled)

        if not enabled:
            cx, cy = self._hand_point(0.5, 0.0)
            off = self.small_font.render(
                "NO HAND NOTES",
                True,
                _previous._blend(_previous.DIM, _previous.BG, 0.30),
            )
            self.screen.blit(off, off.get_rect(center=(int(cx), int(cy - 20))))

    def _draw_key_labels(self, hand_enabled: bool, foot_enabled: bool) -> None:
        if hand_enabled:
            for lane in range(1, 5):
                x, y = self._hand_target_point(lane, 0.955)
                label = self.small_font.render(
                    label_for_lane(NoteKind.HANDS, lane),
                    True,
                    _previous.DIM,
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
                    _previous.DIM,
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
        self._draw_key_labels(hand_enabled, foot_enabled)

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
            # The foot lanes are tightly packed at the literal vanishing point;
            # draw only the anticipation light a little inside the floor mouth
            # so each lane cue is visible while the actual note remains absent.
            points, core_width = self._target_points(kind, lane, 0.08)
            self._draw_preentry_glow(
                surface,
                points,
                _previous.CYAN,
                intensity * 1.15,
                core_width,
            )
            return
        super()._draw_source_glow(
            surface,
            kind,
            lane,
            progress,
            intensity,
            preentry=preentry,
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

    def _draw_chains(
        self,
        chains,
        notes,
        song_time: float,
        song_beat: float,
        chain_mode,
    ) -> None:
        # Preserve the original muted sustain-body styling, then redraw only
        # the leading edge of a live hand hold at ordinary note brightness.
        super()._draw_chains(chains, notes, song_time, song_beat, chain_mode)

        for chain in chains:
            definition = chain.definition
            if definition.kind != NoteKind.HANDS:
                continue
            if chain.state not in (_previous.ChainState.PENDING, _previous.ChainState.ACTIVE):
                continue
            is_hold = definition.source == _previous.SustainSource.EXPLICIT_HOLD
            if not is_hold and chain_mode == _previous.ChainMode.OFF:
                continue
            if not _previous.timed_is_within_lookahead(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            ):
                continue

            head = _previous.timed_progress(
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
                    _previous.MAGENTA,
                    highlight=chain.state == _previous.ChainState.ACTIVE,
                )

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
        line_color = _previous._blend(_previous.WHITE, _previous.BG, 0.30)
        pygame.draw.line(self.screen, line_color, (wall_left, foot_y), (foot_left, foot_y), 1)
        pygame.draw.line(self.screen, line_color, (foot_right, foot_y), (wall_right, foot_y), 1)
