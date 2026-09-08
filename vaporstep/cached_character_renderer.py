from __future__ import annotations

import math

import pygame

from .character_renderer import Renderer as CharacterRenderer
from .domain import BodyState, NoteKind
from .renderer import BG, CYAN, DIM, GRID, MAGENTA, WHITE, _blend


class Renderer(CharacterRenderer):
    """Character renderer with cached raster layers for static playfield work.

    The gameplay geometry is unchanged. Static rails/rings and the small finite
    set of lane-occupancy fills are rasterized once per screen size and reused.
    Dynamic beat highlights, active boundaries, electrical traces and warnings
    remain live every rendered frame.
    """

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._clear_playfield_raster_cache()

    def _clear_playfield_raster_cache(self) -> None:
        self._foot_static_rasters: dict[tuple[tuple[int, int], bool], tuple[pygame.Surface, tuple[int, int]]] = {}
        self._foot_fill_rasters: dict[tuple[tuple[int, int], tuple[int, ...]], tuple[pygame.Surface, tuple[int, int]] | None] = {}
        self._hand_static_rasters: dict[tuple[tuple[int, int], bool], tuple[pygame.Surface, tuple[int, int]]] = {}
        self._hand_fill_rasters: dict[tuple[tuple[int, int], bool, tuple[int, ...]], tuple[pygame.Surface, tuple[int, int]] | None] = {}

    def replace_screen(self, screen: pygame.Surface) -> None:
        super().replace_screen(screen)
        self._clear_playfield_raster_cache()

    @staticmethod
    def _crop_alpha_surface(
        surface: pygame.Surface,
    ) -> tuple[pygame.Surface, tuple[int, int]] | None:
        rect = surface.get_bounding_rect(min_alpha=1)
        if rect.width <= 0 or rect.height <= 0:
            return None
        return surface.subsurface(rect).copy(), rect.topleft

    @staticmethod
    def _blit_cached(
        screen: pygame.Surface,
        cached: tuple[pygame.Surface, tuple[int, int]] | None,
    ) -> None:
        if cached is not None:
            surface, position = cached
            screen.blit(surface, position)

    def _foot_fill_raster(
        self,
        occupied: frozenset[int],
    ) -> tuple[pygame.Surface, tuple[int, int]] | None:
        key = (self.size, tuple(sorted(occupied)))
        if key in self._foot_fill_rasters:
            return self._foot_fill_rasters[key]

        if not occupied:
            self._foot_fill_rasters[key] = None
            return None

        surface = pygame.Surface(self.size, pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        for lane in occupied:
            self._draw_active_lane_fill(
                surface,
                NoteKind.FOOT,
                lane,
                CYAN,
                0.0,
            )
        cached = self._crop_alpha_surface(surface)
        self._foot_fill_rasters[key] = cached
        return cached

    def _foot_static_raster(
        self,
        enabled: bool,
    ) -> tuple[pygame.Surface, tuple[int, int]]:
        key = (self.size, bool(enabled))
        cached = self._foot_static_rasters.get(key)
        if cached is not None:
            return cached

        surface = pygame.Surface(self.size, pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        disabled_grid = _blend(GRID, BG, 0.62)
        local_grid = GRID if enabled else disabled_grid
        outer_color = CYAN if enabled else _blend(DIM, BG, 0.55)
        outer_width = 2 if enabled else 1

        y0 = self._field_y(NoteKind.FOOT, 0.0)
        y1 = self._field_y(NoteKind.FOOT, 1.0)
        for boundary in range(5):
            x0 = self._lane_boundary_x(NoteKind.FOOT, boundary, 0.0)
            x1 = self._lane_boundary_x(NoteKind.FOOT, boundary, 1.0)
            pygame.draw.line(
                surface,
                outer_color if boundary in (0, 4) else local_grid,
                (x0, y0),
                (x1, y1),
                outer_width if boundary in (0, 4) else 1,
            )

        for step in range(1, 8):
            progress = step / 8.0
            left = self._lane_boundary_x(NoteKind.FOOT, 0, progress)
            right = self._lane_boundary_x(NoteKind.FOOT, 4, progress)
            y = self._field_y(NoteKind.FOOT, progress)
            pygame.draw.line(surface, local_grid, (left, y), (right, y), 1)

        result = self._crop_alpha_surface(surface)
        assert result is not None
        self._foot_static_rasters[key] = result
        return result

    def _hand_fill_raster(
        self,
        enabled: bool,
        occupied: frozenset[int],
    ) -> tuple[pygame.Surface, tuple[int, int]] | None:
        key = (self.size, bool(enabled), tuple(sorted(occupied)))
        if key in self._hand_fill_rasters:
            return self._hand_fill_rasters[key]

        if not enabled:
            self._hand_fill_rasters[key] = None
            return None

        surface = pygame.Surface(self.size, pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        for lane in range(1, 5):
            pygame.draw.polygon(
                surface,
                (*MAGENTA, 58 if lane in occupied else 8),
                self._hand_sector_polygon(lane),
            )
        cached = self._crop_alpha_surface(surface)
        self._hand_fill_rasters[key] = cached
        return cached

    def _hand_static_raster(
        self,
        enabled: bool,
    ) -> tuple[pygame.Surface, tuple[int, int]]:
        key = (self.size, bool(enabled))
        cached = self._hand_static_rasters.get(key)
        if cached is not None:
            return cached

        surface = pygame.Surface(self.size, pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        disabled = _blend(DIM, BG, 0.58)
        rail_color = GRID if enabled else disabled

        for boundary, along in enumerate((0.0, 0.20, 0.50, 0.80, 1.0)):
            p0 = self._hand_point(along, 0.0)
            p1 = self._hand_point(along, 1.0)
            if enabled and boundary in (0, 4):
                color, width = MAGENTA, 2
            else:
                color, width = rail_color, 1
            pygame.draw.line(surface, color, p0, p1, width)

        inner_arc = self._static_hand_arc_points(0.0, 1.0, 0.0, samples=64)
        pygame.draw.lines(
            surface,
            _blend(rail_color, WHITE, 0.10),
            False,
            inner_arc,
            2,
        )

        for step in range(1, 9):
            progress = step / 9.0
            arc = self._static_hand_arc_points(0.0, 1.0, progress, samples=64)
            pygame.draw.lines(surface, rail_color, False, arc, 1)

        receptor_color = DIM if enabled else disabled
        for lane in range(1, 5):
            receptor = self._hand_lane_arc(lane, 1.0, 1.0)
            pygame.draw.lines(surface, receptor_color, False, receptor, 2)

        result = self._crop_alpha_surface(surface)
        assert result is not None
        self._hand_static_rasters[key] = result
        return result

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
        occupied = body.foot_lanes if enabled else frozenset()

        self._blit_cached(self.screen, self._foot_fill_raster(occupied))
        self._blit_cached(self.screen, self._foot_static_raster(enabled))

        if enabled:
            y0 = self._field_y(NoteKind.FOOT, 0.0)
            y1 = self._field_y(NoteKind.FOOT, 1.0)
            for lane in occupied:
                for boundary in (lane - 1, lane):
                    x0 = self._lane_boundary_x(NoteKind.FOOT, boundary, 0.0)
                    x1 = self._lane_boundary_x(NoteKind.FOOT, boundary, 1.0)
                    pygame.draw.line(self.screen, CYAN, (x0, y0), (x1, y1), 3)

            self._draw_buzz_rails(
                NoteKind.FOOT,
                CYAN,
                song_time,
                beat_pulse,
                downbeat,
                overdrive,
                animated=animate_buzz,
            )

    def _draw_hand_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        enabled: bool,
    ) -> None:
        occupied = body.hand_lanes if enabled else frozenset()
        disabled = _blend(DIM, BG, 0.58)

        self.screen.blit(self._hand_depth_surface(), (0, 0))
        self._blit_cached(self.screen, self._hand_fill_raster(enabled, occupied))
        self._blit_cached(self.screen, self._hand_static_raster(enabled))

        if enabled:
            for boundary, along in enumerate((0.0, 0.20, 0.50, 0.80, 1.0)):
                active_boundary = (
                    (boundary > 0 and boundary in occupied)
                    or (boundary < 4 and boundary + 1 in occupied)
                )
                if not active_boundary:
                    continue
                p0 = self._hand_point(along, 0.0)
                p1 = self._hand_point(along, 1.0)
                pygame.draw.line(self.screen, MAGENTA, p0, p1, 3)

        pulse = max(0.0, min(1.0, beat_pulse))
        pulse_position = math.sqrt(pulse) if pulse > 0.005 else -1.0
        if enabled and pulse_position >= 0.0:
            for step in range(1, 9):
                progress = step / 9.0
                proximity = max(0.0, 1.0 - abs(progress - pulse_position) / 0.18)
                if proximity <= 0.0:
                    continue
                amount = proximity * (0.14 + 0.26 * math.sqrt(pulse))
                ring_color = _blend(GRID, MAGENTA, amount)
                width = 2 if amount > 0.18 else 1
                arc = self._static_hand_arc_points(0.0, 1.0, progress, samples=64)
                pygame.draw.lines(self.screen, ring_color, False, arc, width)

        if enabled:
            for lane in occupied:
                receptor = self._hand_lane_arc(lane, 1.0, 1.0)
                pygame.draw.lines(self.screen, MAGENTA, False, receptor, 6)

        self._draw_floor_gutter_structure(GRID if enabled else disabled)

        if not enabled:
            cx, cy = self._hand_point(0.5, 0.0)
            off = self.small_font.render("NO HAND NOTES", True, _blend(DIM, BG, 0.30))
            self.screen.blit(off, off.get_rect(center=(int(cx), int(cy - 20))))
