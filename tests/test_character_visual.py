from __future__ import annotations

import math
from pathlib import Path

import pygame

from vaporstep.app import _next_player_visual
from vaporstep.character_renderer import Renderer
from vaporstep.domain import BodyPoint, PoseFigure
from vaporstep.settings import SettingsStore


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
    assert reloaded.settings.player_visual == "character"


def test_visual_toggle_cycles_silhouette_and_character(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    assert store.settings.player_visual == "silhouette"
    store.settings.player_visual = _next_player_visual(store.settings.player_visual)
    assert store.settings.player_visual == "character"
    store.settings.player_visual = _next_player_visual(store.settings.player_visual)
    assert store.settings.player_visual == "silhouette"


def test_character_visual_draws_from_pose_landmarks() -> None:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer = Renderer(screen)

    before = pygame.image.tostring(screen, "RGBA")
    renderer._draw_pose_figure(_pose())
    after = pygame.image.tostring(screen, "RGBA")

    assert after != before


def test_character_torso_is_narrower_and_uses_four_sided_depth_face(monkeypatch) -> None:
    pygame.font.init()
    renderer = Renderer(pygame.Surface((1280, 720)))
    polygons = []
    line_loops = []
    monkeypatch.setattr(
        pygame.draw,
        "polygon",
        lambda surface, color, points, *args, **kwargs: polygons.append(tuple(points)),
    )
    monkeypatch.setattr(
        pygame.draw,
        "lines",
        lambda surface, color, closed, points, *args, **kwargs: line_loops.append(
            (closed, tuple(points))
        ),
    )
    monkeypatch.setattr(pygame.draw, "line", lambda *args, **kwargs: None)
    monkeypatch.setattr(pygame.draw, "arc", lambda *args, **kwargs: None)

    figure = _pose()
    renderer._draw_torso(figure, float(renderer._camera_rect().width))

    left_shoulder = renderer._screen_point(figure.point(11))
    right_shoulder = renderer._screen_point(figure.point(12))
    torso = polygons[0]
    assert math.dist(torso[0], torso[1]) < math.dist(left_shoulder, right_shoulder)
    assert len(polygons) == 2
    assert len(polygons[1]) == 4
    assert not any(closed and len(points) == 3 for closed, points in line_loops)
