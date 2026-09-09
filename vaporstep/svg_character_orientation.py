from __future__ import annotations

import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from . import svg_character_renderer as _base
from .domain import PoseFigure
from .user_paths import characters_dir


_HAND_LANDMARKS = {
    "left-hand": (15, 17, 19),   # wrist, pinky, index
    "right-hand": (16, 18, 20),
}
_HAND_TIP_ANCHORS = {
    "left-hand": "left-hand-tip",
    "right-hand": "right-hand-tip",
}


active_character_filename = _base.active_character_filename


def _optional_hand_tip_anchors(path: Path) -> dict[str, _base.Point]:
    """Read optional source-orientation anchors after the base SVG has validated."""

    root = ET.parse(path).getroot()
    ids = {
        element.attrib["id"]: element
        for element in root.iter()
        if element.attrib.get("id")
    }
    anchors: dict[str, _base.Point] = {}
    for part_name, anchor_name in _HAND_TIP_ANCHORS.items():
        element = ids.get(f"anchor-{anchor_name}")
        if element is None:
            continue
        if "transform" in element.attrib:
            raise _base.SvgCharacterError(
                f"anchor-{anchor_name} must use cx/cy coordinates, not an SVG transform"
            )
        if _base._local_name(element.tag) not in {"circle", "ellipse"}:
            raise _base.SvgCharacterError(f"anchor-{anchor_name} must be a circle or ellipse")
        anchors[part_name] = (
            _base._number(element.attrib.get("cx"), field=f"anchor-{anchor_name} cx"),
            _base._number(element.attrib.get("cy"), field=f"anchor-{anchor_name} cy"),
        )
    return anchors


def _map_oriented_point(
    point: _base.Point,
    source_anchor: _base.Point,
    source_tip: _base.Point,
    live_anchor: _base.Point,
    live_tip: _base.Point,
    scale: float,
) -> _base.Point:
    """Rotate/scale one source point from a hand's source axis onto its live axis."""

    source_dx = source_tip[0] - source_anchor[0]
    source_dy = source_tip[1] - source_anchor[1]
    source_length = math.hypot(source_dx, source_dy)
    live_dx = live_tip[0] - live_anchor[0]
    live_dy = live_tip[1] - live_anchor[1]
    live_length = math.hypot(live_dx, live_dy)
    if source_length < 1e-6 or live_length < 1e-6:
        return live_anchor

    source_forward = (source_dx / source_length, source_dy / source_length)
    source_across = (-source_forward[1], source_forward[0])
    live_forward = (live_dx / live_length, live_dy / live_length)
    live_across = (-live_forward[1], live_forward[0])

    rel_x = point[0] - source_anchor[0]
    rel_y = point[1] - source_anchor[1]
    along = (rel_x * source_forward[0] + rel_y * source_forward[1]) * scale
    across = (rel_x * source_across[0] + rel_y * source_across[1]) * scale
    return (
        live_anchor[0] + live_forward[0] * along + live_across[0] * across,
        live_anchor[1] + live_forward[1] * along + live_across[1] * across,
    )


class SvgCharacter(_base.SvgCharacter):
    """SVG character whose optional hand artwork follows live palm orientation."""

    def __init__(
        self,
        definition: _base.SvgCharacterDefinition,
        hand_tip_anchors: dict[str, _base.Point] | None = None,
    ) -> None:
        super().__init__(definition)
        self._hand_tip_anchors = hand_tip_anchors or {}
        self._drawing_figure: PoseFigure | None = None

    @classmethod
    def from_file(cls, path: Path) -> "SvgCharacter":
        path = Path(path)
        definition = _base.parse_svg_character(path)
        return cls(definition, _optional_hand_tip_anchors(path))

    def draw(self, renderer: _base.CachedCharacterRenderer, figure: PoseFigure) -> None:
        self._drawing_figure = figure
        try:
            super().draw(renderer, figure)
        finally:
            self._drawing_figure = None

    def _draw_point_part(
        self,
        renderer: _base.CachedCharacterRenderer,
        part_name: str,
        live_anchor: tuple[int, int] | None,
    ) -> None:
        figure = self._drawing_figure
        landmarks = _HAND_LANDMARKS.get(part_name)
        if figure is None or landmarks is None or live_anchor is None:
            super()._draw_point_part(renderer, part_name, live_anchor)
            return

        _, pinky_index, index_index = landmarks
        pinky = renderer._visible_screen_point(figure, pinky_index)
        index = renderer._visible_screen_point(figure, index_index)
        visible_tips = [point for point in (pinky, index) if point is not None]
        if not visible_tips:
            super()._draw_point_part(renderer, part_name, live_anchor)
            return

        live_tip = (
            sum(point[0] for point in visible_tips) / len(visible_tips),
            sum(point[1] for point in visible_tips) / len(visible_tips),
        )
        if math.dist(live_anchor, live_tip) < 1.0:
            super()._draw_point_part(renderer, part_name, live_anchor)
            return

        part = self.definition.parts.get(part_name)
        if part is None:
            return
        wrist_anchor_name = _base.POINT_PARTS[part_name]
        source_anchor = self.definition.anchors[wrist_anchor_name]
        # Existing v1 characters did not define a hand-direction anchor. Treat
        # their hand artwork as pointing downward, matching the original
        # point-only renderer and preserving compatibility. New templates may
        # optionally provide anchor-left/right-hand-tip for an explicit axis.
        source_tip = self._hand_tip_anchors.get(
            part_name,
            (source_anchor[0], source_anchor[1] + 1.0),
        )
        scale = float(renderer._camera_rect().width) / self._view_width

        def mapper(point: _base.Point) -> _base.Point:
            return _map_oriented_point(
                point,
                source_anchor,
                source_tip,
                live_anchor,
                live_tip,
                scale,
            )

        _base._draw_vector_part(renderer.screen, part, mapper, scale)


class Renderer(_base.Renderer):
    """Custom-character renderer with pose-driven hand orientation."""

    def _refresh_custom_character(self) -> None:
        desired = _base.active_character_filename()
        if desired == self._loaded_character_filename:
            return
        self._loaded_character_filename = desired
        self._svg_character = None
        self._svg_character_error = None
        if desired is None:
            return
        path = characters_dir() / desired
        try:
            self._svg_character = SvgCharacter.from_file(path)
        except _base.SvgCharacterError as exc:
            self._svg_character_error = str(exc)
            print(
                f"VaporStep: could not load custom character {path.name}: {exc}; using built-in character",
                file=sys.stderr,
            )
