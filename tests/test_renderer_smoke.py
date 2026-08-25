from __future__ import annotations

import importlib
from pathlib import Path

import pygame


def test_renderer_module_imports() -> None:
    module = importlib.import_module("vaporstep.renderer")
    assert module.Renderer is not None


def test_renderer_public_ui_exports() -> None:
    module = importlib.import_module("vaporstep.renderer")
    for name in (
        "BG",
        "CYAN",
        "DIM",
        "GRID",
        "MAGENTA",
        "PURPLE",
        "RED",
        "WHITE",
        "_blend",
    ):
        assert hasattr(module, name)


def test_song_menu_module_imports_with_renderer() -> None:
    renderer_module = importlib.import_module("vaporstep.renderer")
    menu_module = importlib.import_module("vaporstep.menu")
    song_menu_renderer = importlib.import_module("vaporstep.song_menu_renderer")
    assert renderer_module.Renderer is not None
    assert menu_module.SongMenu is not None
    assert song_menu_renderer.install_song_menu_renderer is not None


def test_renderer_previous_layer_is_gone() -> None:
    module = importlib.import_module("vaporstep.renderer")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "renderer_previous" not in source
    assert not Path(module.__file__).with_name("renderer_previous.py").exists()


def test_renderer_constructs_and_draws_startup_smoke() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    renderer.draw_startup_splash("TEST")

    assert screen.get_size() == (1280, 720)
