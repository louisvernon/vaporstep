from __future__ import annotations

import importlib

import pygame


def test_renderer_module_imports() -> None:
    module = importlib.import_module("vaporstep.renderer")
    assert module.Renderer is not None


def test_song_menu_module_imports_with_renderer() -> None:
    renderer_module = importlib.import_module("vaporstep.renderer")
    menu_module = importlib.import_module("vaporstep.menu")
    assert renderer_module.Renderer is not None
    assert menu_module.SongMenu is not None


def test_renderer_constructs_and_draws_startup_smoke() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    renderer.draw_startup_splash("TEST")

    assert screen.get_size() == (1280, 720)
