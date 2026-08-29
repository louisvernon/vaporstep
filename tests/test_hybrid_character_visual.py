from __future__ import annotations

import pygame

from vaporstep.domain import BodyPoint, PoseFigure
from vaporstep.hybrid_character_renderer import Renderer
from vaporstep.player_visual_runtime import _set_active_player_visual


def _pose_figure() -> PoseFigure:
    points = [BodyPoint() for _ in range(33)]
    coords = {
        0: (0.50, 0.20),
        7: (0.47, 0.20),
        8: (0.53, 0.20),
        11: (0.43, 0.32),
        12: (0.57, 0.32),
        13: (0.36, 0.45),
        14: (0.64, 0.45),
        15: (0.31, 0.58),
        16: (0.69, 0.58),
        23: (0.46, 0.56),
        24: (0.54, 0.56),
        25: (0.43, 0.73),
        26: (0.57, 0.73),
        27: (0.41, 0.89),
        28: (0.59, 0.89),
        31: (0.38, 0.93),
        32: (0.62, 0.93),
    }
    for index, (x, y) in coords.items():
        points[index] = BodyPoint(x=x, y=y, visible=True)
    return PoseFigure(tuple(points))


def test_skeleton_slot_uses_procedural_character(monkeypatch) -> None:
    pygame.font.init()
    renderer = Renderer(pygame.Surface((640, 480)))
    calls = []
    monkeypatch.setattr(renderer, "_draw_character_figure", lambda figure: calls.append(figure))
    monkeypatch.setattr(renderer, "_draw_hybrid_character", lambda figure: calls.append("hybrid"))

    _set_active_player_visual("skeleton")
    renderer._draw_pose_figure(_pose_figure())

    assert len(calls) == 1
    assert isinstance(calls[0], PoseFigure)


def test_character_slot_uses_hybrid_renderer(monkeypatch) -> None:
    pygame.font.init()
    renderer = Renderer(pygame.Surface((640, 480)))
    calls = []
    monkeypatch.setattr(renderer, "_draw_character_figure", lambda figure: calls.append("procedural"))
    monkeypatch.setattr(renderer, "_draw_hybrid_character", lambda figure: calls.append(figure))

    _set_active_player_visual("character")
    renderer._draw_pose_figure(_pose_figure())

    assert len(calls) == 1
    assert isinstance(calls[0], PoseFigure)


def test_hybrid_character_draws_when_assets_are_unavailable(monkeypatch) -> None:
    pygame.font.init()
    screen = pygame.Surface((640, 480))
    renderer = Renderer(screen)
    monkeypatch.setattr(renderer, "_avatar_part", lambda name: None)
    before = pygame.image.tostring(screen, "RGBA")

    renderer._draw_hybrid_character(_pose_figure())

    assert pygame.image.tostring(screen, "RGBA") != before
