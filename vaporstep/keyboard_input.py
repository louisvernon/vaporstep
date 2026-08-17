from __future__ import annotations

import time

import pygame

from .config import (
    FOOT_PLAYFIELD_LEFT,
    FOOT_PLAYFIELD_RIGHT,
    HAND_PLAYFIELD_LEFT,
    HAND_PLAYFIELD_RIGHT,
)
from .domain import BodyPoint, BodyState


FOOT_KEYS = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4)
HAND_KEYS = (pygame.K_q, pygame.K_w, pygame.K_e, pygame.K_r)


def _point_for_lane(lane: int | None, y: float, left: float, right: float) -> BodyPoint:
    if lane is None:
        return BodyPoint()
    lane_width = (right - left) / 4.0
    x = left + (lane - 0.5) * lane_width
    return BodyPoint(x=x, y=y, lane=lane, visible=True)


class KeyboardBodyInput:
    def body_state(self) -> BodyState:
        keys = pygame.key.get_pressed()
        feet = [i + 1 for i, key in enumerate(FOOT_KEYS) if keys[key]][:2]
        hands = [i + 1 for i, key in enumerate(HAND_KEYS) if keys[key]][:2]
        feet += [None] * (2 - len(feet))
        hands += [None] * (2 - len(hands))
        return BodyState(
            left_wrist=_point_for_lane(
                hands[0], 0.31, HAND_PLAYFIELD_LEFT, HAND_PLAYFIELD_RIGHT
            ),
            right_wrist=_point_for_lane(
                hands[1], 0.31, HAND_PLAYFIELD_LEFT, HAND_PLAYFIELD_RIGHT
            ),
            left_knee=_point_for_lane(
                feet[0], 0.69, FOOT_PLAYFIELD_LEFT, FOOT_PLAYFIELD_RIGHT
            ),
            right_knee=_point_for_lane(
                feet[1], 0.69, FOOT_PLAYFIELD_LEFT, FOOT_PLAYFIELD_RIGHT
            ),
            pose_visible=bool(any(x is not None for x in feet + hands)),
            timestamp=time.monotonic(),
        )
