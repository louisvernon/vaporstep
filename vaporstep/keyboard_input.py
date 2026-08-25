from __future__ import annotations

from dataclasses import replace
import time

import pygame

from .config import (
    FOOT_PLAYFIELD_LEFT,
    FOOT_PLAYFIELD_RIGHT,
    HAND_PLAYFIELD_LEFT,
    HAND_PLAYFIELD_RIGHT,
)
from .domain import BodyPoint, BodyState, NoteKind


HAND_KEYS = (pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_f)
FOOT_KEYS = (pygame.K_j, pygame.K_k, pygame.K_l, pygame.K_SEMICOLON)
HAND_KEY_LABELS = ("A", "S", "D", "F")
FOOT_KEY_LABELS = ("J", "K", "L", ";")
KEY_REPRESS_GUARD_SECONDS = 0.05

_KEY_LANES = {
    **{key: (NoteKind.HANDS, lane) for lane, key in enumerate(HAND_KEYS, start=1)},
    **{key: (NoteKind.FOOT, lane) for lane, key in enumerate(FOOT_KEYS, start=1)},
}


def lane_for_key(key: int) -> tuple[NoteKind, int] | None:
    return _KEY_LANES.get(int(key))


def label_for_lane(kind: NoteKind, lane: int) -> str:
    labels = HAND_KEY_LABELS if kind == NoteKind.HANDS else FOOT_KEY_LABELS
    return labels[int(lane) - 1]


def add_keyboard_lanes(camera_body: BodyState, keyboard_body: BodyState) -> BodyState:
    return replace(
        camera_body,
        supplemental_hand_lanes=(
            camera_body.supplemental_hand_lanes | keyboard_body.hand_lanes
        ),
        supplemental_foot_lanes=(
            camera_body.supplemental_foot_lanes | keyboard_body.foot_lanes
        ),
    )


def _point_for_lane(lane: int | None, y: float, left: float, right: float) -> BodyPoint:
    if lane is None:
        return BodyPoint()
    lane_width = (right - left) / 4.0
    x = left + (lane - 0.5) * lane_width
    return BodyPoint(x=x, y=y, lane=lane, visible=True)


class KeyboardBodyInput:
    """Keyboard lane occupancy plus discrete, non-repeating timing presses."""

    def __init__(self) -> None:
        self._pressed: set[int] = set()
        self._latched: set[int] = set()
        self._last_press_at: dict[int, float] = {}

    def reset(self) -> None:
        self._pressed.clear()
        self._latched.clear()
        self._last_press_at.clear()

    def press(self, key: int, *, repeat: bool = False) -> tuple[NoteKind, int] | None:
        mapping = lane_for_key(key)
        if mapping is None:
            return None
        key = int(key)
        now = time.monotonic()
        first_press = key not in self._pressed and not repeat
        self._pressed.add(key)
        if first_press:
            self._latched.add(key)
            previous = self._last_press_at.get(key, -999.0)
            self._last_press_at[key] = now
            if now - previous >= KEY_REPRESS_GUARD_SECONDS:
                return mapping
        return None

    def release(self, key: int) -> None:
        self._pressed.discard(int(key))

    def handle_event(self, event) -> tuple[NoteKind, int] | None:
        if event.type == pygame.KEYDOWN:
            return self.press(event.key, repeat=bool(getattr(event, "repeat", False)))
        if event.type == pygame.KEYUP:
            self.release(event.key)
        elif event.type == getattr(pygame, "WINDOWFOCUSLOST", -1):
            self.reset()
        return None

    def body_state(self) -> BodyState:
        active = self._pressed | self._latched
        feet = [i + 1 for i, key in enumerate(FOOT_KEYS) if key in active][:2]
        hands = [i + 1 for i, key in enumerate(HAND_KEYS) if key in active][:2]
        self._latched.clear()
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
            timestamp=0.0,
        )
