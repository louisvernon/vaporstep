from __future__ import annotations

import math

from vaporstep.calibration_renderer import Renderer as DesktopRenderer
from vaporstep.domain import NoteKind
from vaporstep.renderer import Renderer as LegacyGeometryRenderer
from vaporstep.renderer_geometry_adapter import SharedPlayfieldGeometryMixin


class _Screen:
    def __init__(self, size: tuple[int, int]) -> None:
        self._size = size

    def get_size(self) -> tuple[int, int]:
        return self._size


def _bare(renderer_type, size: tuple[int, int]):
    renderer = object.__new__(renderer_type)
    renderer.screen = _Screen(size)
    return renderer


def test_desktop_concrete_renderer_uses_shared_geometry_adapter() -> None:
    assert issubclass(DesktopRenderer, SharedPlayfieldGeometryMixin)
    assert DesktopRenderer._field_y is SharedPlayfieldGeometryMixin._field_y
    assert DesktopRenderer._hand_point is SharedPlayfieldGeometryMixin._hand_point


def test_shared_adapter_matches_legacy_field_projection_exactly() -> None:
    for size in ((1280, 720), (601, 601), (1920, 1080), (800, 1280)):
        legacy = _bare(LegacyGeometryRenderer, size)
        shared = _bare(DesktopRenderer, size)

        assert shared._camera_rect() == legacy._camera_rect()
        assert shared._vanish_bounds() == legacy._vanish_bounds()

        for kind in (NoteKind.FOOT, NoteKind.HANDS):
            assert shared._hit_bounds(kind) == legacy._hit_bounds(kind)
            for progress in (-0.2, 0.0, 0.13, 0.5, 0.91, 1.0, 1.2):
                assert shared._field_bounds(kind, progress) == legacy._field_bounds(
                    kind, progress
                )
                assert shared._field_y(kind, progress) == legacy._field_y(kind, progress)
                for boundary in range(5):
                    assert shared._lane_boundary_x(
                        kind, boundary, progress
                    ) == legacy._lane_boundary_x(kind, boundary, progress)


def test_shared_adapter_matches_legacy_hand_geometry_exactly() -> None:
    for size in ((1280, 720), (601, 601), (1920, 1080), (800, 1280)):
        legacy = _bare(LegacyGeometryRenderer, size)
        shared = _bare(DesktopRenderer, size)

        legacy_tunnel = legacy._hand_tunnel_geometry()
        shared_tunnel = shared._hand_tunnel_geometry()
        for legacy_part, shared_part in zip(legacy_tunnel[:2], shared_tunnel[:2]):
            for expected, actual in zip(legacy_part, shared_part):
                assert math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)
        for legacy_point, shared_point in zip(legacy_tunnel[2], shared_tunnel[2]):
            assert math.isclose(shared_point[0], legacy_point[0], rel_tol=0.0, abs_tol=1e-12)
            assert math.isclose(shared_point[1], legacy_point[1], rel_tol=0.0, abs_tol=1e-12)

        for progress in (0.0, 0.17, 0.5, 0.83, 1.0):
            for along in (0.0, 0.10, 0.31, 0.5, 0.69, 0.90, 1.0):
                expected = legacy._hand_point(along, progress)
                actual = shared._hand_point(along, progress)
                assert math.isclose(actual[0], expected[0], rel_tol=0.0, abs_tol=1e-12)
                assert math.isclose(actual[1], expected[1], rel_tol=0.0, abs_tol=1e-12)

            for lane in range(1, 5):
                assert shared._hand_lane_arc(lane, progress) == legacy._hand_lane_arc(
                    lane, progress
                )
                assert shared._hand_note_arc_points(
                    lane, progress, 0.62, samples=18
                ) == legacy._hand_note_arc_points(
                    lane, progress, 0.62, samples=18
                )

        for lane in range(1, 5):
            assert shared._hand_sector_polygon(lane) == legacy._hand_sector_polygon(lane)
