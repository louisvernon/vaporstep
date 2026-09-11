from __future__ import annotations

import pygame

from vaporstep.calibration_renderer import CHARACTER_PLAYFIELD_ALPHA, Renderer
from vaporstep.domain import BodyState, PoseFigure
from vaporstep.svg_character_orientation import Renderer as CharacterRenderer


def _pose() -> PoseFigure:
    points = tuple((0.5, 0.5, True) for _ in range(33))
    return PoseFigure(points=points)


def test_player_visual_renders_after_playfield_and_before_notes(monkeypatch) -> None:
    pygame.font.init()
    renderer = Renderer(pygame.Surface((640, 360)))
    calls: list[str] = []

    monkeypatch.setattr(renderer, "_draw_background", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        renderer,
        "_draw_foot_playfield",
        lambda *args, **kwargs: calls.append("playfields"),
    )
    monkeypatch.setattr(renderer, "_draw_hand_playfield", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        renderer,
        "_render_deferred_player_visual",
        lambda *args, **kwargs: calls.append("player"),
    )
    monkeypatch.setattr(renderer, "_draw_chains", lambda *args, **kwargs: None)
    monkeypatch.setattr(renderer, "_draw_notes", lambda *args, **kwargs: calls.append("notes"))
    monkeypatch.setattr(renderer, "_draw_receptors", lambda *args, **kwargs: None)
    monkeypatch.setattr(renderer, "_draw_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(renderer, "_draw_body_markers", lambda *args, **kwargs: None)

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

    assert calls.index("playfields") < calls.index("player") < calls.index("notes")


def test_character_layer_is_half_transparent_over_playfield(monkeypatch) -> None:
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

    renderer._render_deferred_player_visual(("pose", _pose()))

    actual = screen.get_at(point)[:3]
    alpha = CHARACTER_PLAYFIELD_ALPHA / 255.0
    expected = tuple(
        round(bg * (1.0 - alpha) + fg * alpha)
        for bg, fg in zip(background, character)
    )
    assert all(abs(a - e) <= 2 for a, e in zip(actual, expected))
