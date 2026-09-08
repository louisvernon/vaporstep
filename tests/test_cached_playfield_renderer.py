from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pygame

from vaporstep.cached_character_renderer import Renderer as CachedRenderer
from vaporstep.character_renderer import Renderer as CharacterRenderer


def _body():
    return SimpleNamespace(
        foot_lanes=frozenset({1, 3}),
        hand_lanes=frozenset({2, 4}),
    )


def _draw_playfields(renderer, body) -> None:
    renderer._draw_foot_playfield(
        body,
        song_time=1.234,
        beat_pulse=0.61,
        downbeat=False,
        enabled=True,
        overdrive=False,
        animate_buzz=True,
    )
    renderer._draw_hand_playfield(
        body,
        song_time=1.234,
        beat_pulse=0.61,
        enabled=True,
    )


def test_cached_playfields_match_existing_renderer_pixels() -> None:
    pygame.font.init()
    base_screen = pygame.Surface((640, 360), depth=32)
    cached_screen = pygame.Surface((640, 360), depth=32)
    base_screen.fill((7, 9, 13))
    cached_screen.fill((7, 9, 13))

    body = _body()
    base = CharacterRenderer(base_screen)
    cached = CachedRenderer(cached_screen)

    _draw_playfields(base, body)
    _draw_playfields(cached, body)

    assert np.array_equal(
        pygame.surfarray.array3d(base_screen),
        pygame.surfarray.array3d(cached_screen),
    )


def test_cached_playfield_rasters_are_reused_and_cleared_on_resize() -> None:
    pygame.font.init()
    renderer = CachedRenderer(pygame.Surface((640, 360), depth=32))
    body = _body()

    _draw_playfields(renderer, body)
    foot_fill = renderer._foot_fill_raster(body.foot_lanes)
    hand_rings = renderer._hand_ring_raster(True)
    hand_fill = renderer._hand_fill_raster(True, body.hand_lanes)

    assert renderer._foot_fill_raster(body.foot_lanes) is foot_fill
    assert renderer._hand_ring_raster(True) is hand_rings
    assert renderer._hand_fill_raster(True, body.hand_lanes) is hand_fill

    renderer.replace_screen(pygame.Surface((800, 450), depth=32))

    assert renderer._foot_fill_rasters == {}
    assert renderer._hand_ring_rasters == {}
    assert renderer._hand_fill_rasters == {}
