from __future__ import annotations

"""Cross-platform runtime binding for rigged SVG characters.

The character schema/pose implementation lives in ``svg_character_renderer``.
Pygame's bundled SDL_image feature set varies by platform, so SVG decoding is
kept explicit here: resvg renders each isolated body-part SVG to PNG bytes once
at character load, and Pygame only has to decode PNG.
"""

from io import BytesIO

import pygame
import resvg_py

from . import svg_character_renderer as _base


# Re-export the public character API so tests and callers use the same runtime
# path as gameplay.
SvgCharacterError = _base.SvgCharacterError
SvgCharacterDefinition = _base.SvgCharacterDefinition
REQUIRED_PARTS = _base.REQUIRED_PARTS
REQUIRED_ANCHORS = _base.REQUIRED_ANCHORS
parse_svg_character = _base.parse_svg_character
discover_character_files = _base.discover_character_files
select_custom_character_file = _base.select_custom_character_file


def _rasterize_part(
    definition: SvgCharacterDefinition,
    part_name: str,
) -> _base._RasterPart:
    try:
        svg = _base._fragment_svg(definition, part_name).decode("utf-8")
        png = resvg_py.svg_to_bytes(
            svg_string=svg,
            skip_system_fonts=True,
            width=_base.RASTER_WIDTH,
        )
        surface = pygame.image.load(BytesIO(png), f"{part_name}.png")
    except (pygame.error, OSError, UnicodeError, RuntimeError, ValueError) as exc:
        raise SvgCharacterError(f"could not rasterize {part_name}: {exc}") from exc

    alpha_rect = surface.get_bounding_rect(min_alpha=1)
    if alpha_rect.width <= 0 or alpha_rect.height <= 0:
        raise SvgCharacterError(f"artwork group {part_name!r} is empty")
    cropped = surface.subsurface(alpha_rect).copy()

    view_x, view_y, view_w, view_h = definition.view_box
    scale_x = surface.get_width() / view_w
    scale_y = surface.get_height() / view_h
    anchors = {
        name: (
            (x - view_x) * scale_x - alpha_rect.left,
            (y - view_y) * scale_y - alpha_rect.top,
        )
        for name, (x, y) in definition.anchors.items()
    }
    return _base._RasterPart(cropped, anchors, surface.get_width())


# SvgCharacter resolves this module-global helper when a character instance is
# constructed, so replacing it once gives the existing rig implementation the
# deterministic rasterizer without duplicating any pose/rendering code.
_base._rasterize_part = _rasterize_part

SvgCharacter = _base.SvgCharacter
Renderer = _base.Renderer
