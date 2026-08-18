from __future__ import annotations

import pygame

from .domain import BodyState


BG = (2, 2, 8)
CYAN = (70, 245, 255)


def draw_lower_body_tracking_overlay(renderer, body: BodyState) -> None:
    """Show ankle contribution with a compact cyan double-ring marker.

    One cyan ring means the control is effectively knee-only. A second tight
    cyan ring means the ankle is contributing to the virtual lower-leg point.
    The cue is intentionally binary and visually quiet; source weighting can
    still vary smoothly internally without changing marker brightness.
    """
    for control, knee in (
        (body.left_foot_control, body.left_knee),
        (body.right_foot_control, body.right_knee),
    ):
        point = control if control.visible else knee
        if not point.visible:
            continue
        pos = renderer._screen_point(point)
        pygame.draw.circle(renderer.screen, BG, pos, 11)
        pygame.draw.circle(renderer.screen, CYAN, pos, 7, 2)

        weight = max(0.0, float(getattr(control, "source_weight", 0.0)))
        if weight > 0.01:
            pygame.draw.circle(renderer.screen, CYAN, pos, 10, 1)
