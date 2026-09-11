from __future__ import annotations

import pygame

from vaporstep.calibration_renderer import Renderer
from vaporstep.domain import BodyState, PoseFigure


def _pose() -> PoseFigure:
    points = tuple((0.5, 0.5, True) for _ in range(33))
    return PoseFigure(points=points)


def test_player_visual_renders_after_playfield_and_before_notes(monkeypatch) -> None:
    pygame.font.init()
    renderer = Renderer(pygame.Surface((640, 360)))
    calls: list[str] = []

    monkeypatch.setattr(renderer, "_draw_background", lambda *args, **kwargs: calls.append("background"))
    monkeypatch.setattr(renderer, "_draw_playfields", lambda *args, **kwargs: calls.append("playfields"))
    monkeypatch.setattr(renderer, "_draw_pose_figure", lambda *args, **kwargs: calls.append("player"))
    monkeypatch.setattr(renderer, "_draw_chains", lambda *args, **kwargs: calls.append("chains"))
    monkeypatch.setattr(renderer, "_draw_notes", lambda *args, **kwargs: calls.append("notes"))
    monkeypatch.setattr(renderer, "_draw_receptors", lambda *args, **kwargs: calls.append("receptors"))
    monkeypatch.setattr(renderer, "_draw_status", lambda *args, **kwargs: calls.append("status"))
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
