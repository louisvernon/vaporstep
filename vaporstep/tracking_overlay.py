from __future__ import annotations

import pygame

from .config import LOWER_BODY_ANKLE_BLEND
from .domain import BodyState


BG = (2, 2, 8)
CYAN = (70, 245, 255)
WHITE = (235, 245, 255)


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, float(amount)))
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def draw_lower_body_tracking_overlay(renderer, body: BodyState) -> None:
    """Make the active ankle contribution obvious during calibration.

    The renderer already shows the raw knee/ankle source points in calibration.
    Redraw the actual lane-control marker last so knee-only fallback is one cyan
    ring, while an ankle contribution adds a second outer ring whose brightness
    reflects the effective blend weight.
    """
    for control, knee in (
        (body.left_foot_control, body.left_knee),
        (body.right_foot_control, body.right_knee),
    ):
        point = control if control.visible else knee
        if not point.visible:
            continue
        pos = renderer._screen_point(point)
        # Clear the renderer's generic calibration outer ring locally, then draw
        # the tracking-specific marker on top. This keeps the diagnostic limited
        # to calibration without changing normal gameplay marker rendering.
        pygame.draw.circle(renderer.screen, BG, pos, 12)
        pygame.draw.circle(renderer.screen, CYAN, pos, 7, 2)

        weight = max(0.0, float(getattr(control, "source_weight", 0.0)))
        if weight <= 0.01:
            continue
        strength = min(1.0, weight / max(LOWER_BODY_ANKLE_BLEND, 1e-6))
        outer = _blend(BG, WHITE, 0.30 + 0.70 * strength)
        pygame.draw.circle(renderer.screen, outer, pos, 11, 1 if strength < 0.55 else 2)
