from __future__ import annotations

"""Desktop renderer adapter for the platform-neutral playfield geometry.

The gameplay renderer predates :mod:`playfield_geometry` and still contains its
original projection helpers.  This mixin lets the concrete desktop renderer
consume the shared geometry without a risky wholesale renderer rewrite.  The
old methods can be deleted incrementally once this adapter has been play-tested.
"""

import math

import pygame

from .domain import NoteKind
from . import playfield_geometry as geo


class SharedPlayfieldGeometryMixin:
    """Route desktop playfield projection through the shared geometry module."""

    @property
    def size(self) -> tuple[int, int]:  # pragma: no cover - supplied by renderer
        raise NotImplementedError

    def _camera_rect(self) -> pygame.Rect:
        viewport = geo.camera_rect(self.size)
        return pygame.Rect(
            int(viewport.left),
            int(viewport.top),
            int(viewport.width),
            int(viewport.height),
        )

    def _camera_x(self, normalized_x: float) -> float:
        return geo.camera_x(self.size, normalized_x)

    def _camera_y(self, normalized_y: float) -> float:
        return geo.camera_y(self.size, normalized_y)

    def _hit_bounds(self, kind: NoteKind) -> tuple[float, float]:
        return geo.hit_bounds(self.size, kind)

    def _vanish_bounds(self) -> tuple[float, float]:
        return geo.vanish_bounds(self.size)

    def _field_bounds(self, kind: NoteKind, progress: float) -> tuple[float, float]:
        return geo.field_bounds(self.size, kind, progress)

    def _field_y(self, kind: NoteKind, progress: float) -> float:
        return geo.field_y(self.size, kind, progress)

    def _lane_boundary_x(self, kind: NoteKind, boundary: int, progress: float) -> float:
        return geo.lane_boundary_x(self.size, kind, boundary, progress)

    def _lane_bounds(
        self,
        kind: NoteKind,
        lane: int,
        progress: float,
    ) -> tuple[float, float]:
        return (
            geo.lane_boundary_x(self.size, kind, lane - 1, progress),
            geo.lane_boundary_x(self.size, kind, lane, progress),
        )

    def _hand_tunnel_geometry(self):
        return geo.hand_tunnel_geometry(self.size)

    def _hand_point(self, along: float, progress: float) -> tuple[float, float]:
        return geo.hand_point(self.size, along, progress)

    def _hand_target_point(self, lane: int, progress: float) -> tuple[float, float]:
        return geo.hand_target_point(self.size, lane, progress)

    def _hand_arc_points(
        self,
        start: float,
        end: float,
        progress: float,
        *,
        samples: int = 12,
    ) -> list[tuple[int, int]]:
        # Preserve desktop's historical int/truncate rasterization exactly.
        # VaporTap rounds the same floating-point geometry to the nearest pixel;
        # raster quantization belongs to each presentation layer, not the shared
        # projection model.
        inner, outer, _ = geo.hand_tunnel_geometry(self.size)
        p = geo.clamp(progress) ** 1.25
        points: list[tuple[int, int]] = []
        for i in range(samples + 1):
            along = start + (end - start) * i / samples
            ix, iy = geo.ellipse_upper_point(inner, along)
            ox, oy = geo.ellipse_upper_point(outer, along)
            points.append(
                (
                    int(ix + (ox - ix) * p),
                    int(iy + (oy - iy) * p),
                )
            )
        return points

    def _hand_lane_arc(
        self,
        lane: int,
        progress: float,
        fraction: float = 1.0,
    ) -> list[tuple[int, int]]:
        start = geo.HAND_BOUNDARIES[lane - 1]
        end = geo.HAND_BOUNDARIES[lane]
        center = (start + end) * 0.5
        half = (end - start) * 0.5 * max(0.05, min(1.0, fraction))
        if progress == 1.0 and fraction == 1.0:
            return self._static_hand_arc_points(
                center - half,
                center + half,
                progress,
                samples=14,
            )
        return self._hand_arc_points(
            center - half,
            center + half,
            progress,
            samples=14,
        )

    def _hand_sector_polygon(self, lane: int) -> list[tuple[int, int]]:
        cache = self._playfield_geometry()
        key = ("hand_sector", lane)
        polygon = cache.get(key)
        if polygon is not None:
            return polygon
        start = geo.HAND_BOUNDARIES[lane - 1]
        end = geo.HAND_BOUNDARIES[lane]
        outer = self._static_hand_arc_points(start, end, 1.0, samples=18)
        inner = self._static_hand_arc_points(end, start, 0.0, samples=18)
        polygon = [*outer, *inner]
        cache[key] = polygon
        return polygon

    def _hand_note_arc_points(
        self,
        lane: int,
        progress: float,
        fraction: float,
        *,
        samples: int = 14,
    ) -> list[tuple[int, int]]:
        start = geo.HAND_BOUNDARIES[lane - 1]
        end = geo.HAND_BOUNDARIES[lane]
        center = geo.HAND_CENTERS[lane - 1]
        half = (end - start) * 0.5 * max(0.05, min(1.0, fraction))
        return self._hand_arc_points(
            center - half,
            center + half,
            progress,
            samples=samples,
        )

    def _hand_lane_direction(self, lane: int) -> tuple[float, float]:
        inner = self._hand_target_point(lane, 0.0)
        outer = self._hand_target_point(lane, 1.0)
        dx, dy = outer[0] - inner[0], outer[1] - inner[1]
        length = max(1.0, math.hypot(dx, dy))
        return dx / length, dy / length
