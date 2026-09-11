from __future__ import annotations

import pygame

from vaporstep.calibration_renderer import Renderer
from vaporstep.domain import BodyState, PoseFigure
from vaporstep.svg_character_orientation import Renderer as CharacterRenderer


def _pose() -> PoseFigure:
    points = tuple((0.5, 0.5, True) for _ in range(33))
    return PoseFigure(points=points)


def test_character_renders_after_gameplay_scene(monkeypatch) -> None:
    pygame.font.init()
    renderer = Renderer(pygame.Surface((640, 360)))
    calls: list[str] = []

    monkeypatch.setattr(renderer, "_draw_background", lambda *args, **kwargs: None)
    monkeypatch.setattr(renderer, "_draw_playfields", lambda *args, **kwargs: calls.append("playfields"))
    monkeypatch.setattr(renderer, "_draw_chains", lambda *args, **kwargs: None)
    monkeypatch.setattr(renderer, "_draw_notes", lambda *args, **kwargs: calls.append("notes"))
    monkeypatch.setattr(renderer, "_draw_receptors", lambda *args, **kwargs: calls.append("receptors"))
    monkeypatch.setattr(renderer, "_draw_status", lambda *args, **kwargs: calls.append("hud"))
    monkeypatch.setattr(renderer, "_draw_body_markers", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        renderer,
        "_render_deferred_character",
        lambda *args, **kwargs: calls.append("character"),
    )

    renderer.draw(
        body=BodyState(),
        mask=None,
        notes=[],
        song_time=0.0,
        song_beat=0.0,
        status="READY",
        debug=False,
        pose_fps=0.0,
        input_name="webcam",
        pose_figure=_pose(),
        show_body_markers=False,
    )

    assert calls.index("playfields") < calls.index("notes")
    assert calls.index("notes") < calls.index("receptors")
    assert calls.index("receptors") < calls.index("hud") < calls.index("character")


def test_character_layer_draws_without_global_alpha(monkeypatch) -> None:
    pygame.font.init()
    background = (24, 48, 72)
    character = (224, 128, 64)
    screen = pygame.Surface((640, 360))
    screen.fill(background)
    renderer = Renderer(screen)
    point = renderer._camera_rect().center

    def draw_character(self, _figure) -> None:
        self.screen.set_at(point, (*character, 255))

    monkeypatch.setattr(CharacterRenderer, "_draw_pose_figure", draw_character)

    renderer._render_deferred_character(_pose())

    assert screen.get_at(point)[:3] == character
