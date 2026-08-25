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


def test_renderer_prototype_layers_and_compatibility_hacks_are_gone() -> None:
    module = importlib.import_module("vaporstep.renderer")
    base_module = importlib.import_module("vaporstep.renderer_base")
    source_path = Path(module.__file__)
    source = source_path.read_text(encoding="utf-8")

    assert module.Renderer.__bases__ == (base_module.Renderer,)
    for removed in ("renderer_previous", "renderer_tunnel_base"):
        assert removed not in source
        assert not source_path.with_name(f"{removed}.py").exists()

    assert "_suppress_legacy_hands" not in source
    assert "_ReceptorLabelFilter" not in source


def test_renderer_constructs_and_draws_startup_smoke() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer_module = importlib.import_module("vaporstep.renderer")
    renderer = renderer_module.Renderer(screen)

    renderer.draw_startup_splash("TEST")

    assert screen.get_size() == (1280, 720)
