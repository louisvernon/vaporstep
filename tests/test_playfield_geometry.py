from __future__ import annotations

import math

from vaporstep.domain import NoteKind
from vaporstep import playfield_geometry as geo


def test_reference_1280x720_geometry_matches_vaporstep_camera_viewport() -> None:
    viewport = geo.camera_rect((1280, 720))
    assert viewport.left == 160
    assert viewport.top == 0
    assert viewport.width == 960
    assert viewport.height == 720

    vanish_left, vanish_right = geo.vanish_bounds((1280, 720))
    assert math.isclose(vanish_left, 587.2)
    assert math.isclose(vanish_right, 692.8)
    assert math.isclose(geo.field_y((1280, 720), NoteKind.FOOT, 0.0), 360.0)
    assert math.isclose(geo.field_y((1280, 720), NoteKind.FOOT, 1.0), 648.0)


def test_hand_tunnel_and_foot_field_are_symmetric() -> None:
    size = (1280, 720)
    center = geo.camera_rect(size).centerx

    foot1 = geo.lane_center(size, NoteKind.FOOT, 1, 1.0)
    foot4 = geo.lane_center(size, NoteKind.FOOT, 4, 1.0)
    assert math.isclose(center - foot1[0], foot4[0] - center, abs_tol=1e-6)

    hand1 = geo.hand_target_point(size, 1)
    hand4 = geo.hand_target_point(size, 4)
    hand2 = geo.hand_target_point(size, 2)
    hand3 = geo.hand_target_point(size, 3)
    assert math.isclose(center - hand1[0], hand4[0] - center, abs_tol=1e-6)
    assert math.isclose(center - hand2[0], hand3[0] - center, abs_tol=1e-6)
    assert math.isclose(hand1[1], hand4[1], abs_tol=1e-6)
    assert math.isclose(hand2[1], hand3[1], abs_tol=1e-6)


def test_hand_sector_polygons_and_note_arcs_share_outer_shell() -> None:
    size = (1280, 720)
    for lane in range(1, 5):
        sector = geo.hand_sector_polygon(size, lane)
        note_arc = geo.hand_lane_arc(size, lane, 1.0, geo.HAND_NOTE_ARC_FRACTION)
        assert len(sector) == 38
        assert len(note_arc) == 15
        target = geo.hand_target_point(size, lane)
        midpoint = note_arc[len(note_arc) // 2]
        assert math.hypot(midpoint[0] - target[0], midpoint[1] - target[1]) < 3.0
