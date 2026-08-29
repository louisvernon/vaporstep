from __future__ import annotations

from pathlib import Path

import pygame

from vaporstep.character_renderer import Renderer
from vaporstep.domain import BodyPoint, PoseFigure
from vaporstep.player_visual_runtime import (
    SettingsStore,
    _set_active_player_visual,
    current_player_visual,
)


def _pose() -> PoseFigure:
    points = [BodyPoint() for _ in range(33)]
    visible = {
        0: (0.50, 0.18),
        7: (0.47, 0.19),
        8: (0.53, 0.19),
        11: (0.43, 0.31),
        12: (0.57, 0.31),
        13: (0.37, 0.45),
        14: (0.63, 0.45),
        15: (0.31, 0.57),
        16: (0.69, 0.57),
        23: (0.46, 0.55),
        24: (0.54, 0.55),
        25: (0.44, 0.73),
        26: (0.56, 0.73),
        27: (0.42, 0.90),
        28: (0.58, 0.90),
        31: (0.39, 0.94),
        32: (0.61, 0.94),
    }
    for index, (x, y) in visible.items():
        points[index] = BodyPoint(x=x, y=y, visible=True)
    return PoseFigure(tuple(points))


def test_character_setting_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.settings.player_visual = "character"
    store.save()

    reloaded = SettingsStore(path)
    assert str(reloaded.settings.player_visual) == "character"
    assert current_player_visual() == "character"


def test_existing_v_toggle_cycles_silhouette_skeleton_character(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    assert str(store.settings.player_visual) == "silhouette"
    store.settings.player_visual = (
        "skeleton" if store.settings.player_visual == "silhouette" else "silhouette"
    )
    assert str(store.settings.player_visual) == "skeleton"

    store.settings.player_visual = (
        "skeleton" if store.settings.player_visual == "silhouette" else "silhouette"
    )
    assert str(store.settings.player_visual) == "character"

    store.settings.player_visual = (
        "skeleton" if store.settings.player_visual == "silhouette" else "silhouette"
    )
    assert str(store.settings.player_visual) == "silhouette"


def test_character_visual_draws_from_pose_landmarks() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer = Renderer(screen)
    _set_active_player_visual("character")

    before = pygame.image.tostring(screen, "RGBA")
    renderer._draw_pose_figure(_pose())
    after = pygame.image.tostring(screen, "RGBA")

    assert after != before


def test_skeleton_visual_still_uses_base_pose_renderer(monkeypatch) -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer = Renderer(screen)
    called = []
    _set_active_player_visual("skeleton")

    base = Renderer.__mro__[1]
    monkeypatch.setattr(base, "_draw_pose_figure", lambda self, figure: called.append(figure))
    renderer._draw_pose_figure(_pose())

    assert len(called) == 1
