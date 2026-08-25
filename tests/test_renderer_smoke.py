from __future__ import annotations

import importlib

import pygame


PUBLIC_RENDERER_EXPORTS = (
    "BG",
    "CYAN",
    "MAGENTA",
    "PURPLE",
    "WHITE",
    "DIM",
    "GRID",
    "GREEN",
    "RED",
    "AMBER",
    "ELECTRIC_YELLOW",
    "HIT_BRICK_POP_SECONDS",
    "_blend",
)


def test_renderer_module_imports() -> None:
    module = importlib.import_module("vaporstep.renderer")
    assert module.Renderer is not None
    for name in PUBLIC_RENDERER_EXPORTS:
        assert hasattr(module, name), name


def test_song_menu_module_imports_with_renderer() -> None:
    renderer_module = importlib.import_module("vaporstep.renderer")
    menu_module = importlib.import_module("vaporstep.menu")
    song_menu_renderer = importlib.import_module("vaporstep.song_menu_renderer")
    assert renderer_module.Renderer is not None
    assert menu_module.SongMenu is not None
    assert song_menu_renderer.install_song_menu_renderer is not None


def test_renderer_constructs_and_draws_startup_smoke() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    renderer.draw_startup_splash("TEST")

    assert screen.get_size() == (1280, 720)
