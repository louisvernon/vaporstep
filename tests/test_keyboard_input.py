import pygame

from vaporstep.domain import BodyPoint, BodyState, NoteKind
from vaporstep.keyboard_input import (
    FOOT_KEY_LABELS,
    HAND_KEY_LABELS,
    KeyboardBodyInput,
    add_keyboard_lanes,
    label_for_lane,
    lane_for_key,
)


def test_home_row_layout_maps_left_to_right():
    assert lane_for_key(pygame.K_a) == (NoteKind.HANDS, 1)
    assert lane_for_key(pygame.K_f) == (NoteKind.HANDS, 4)
    assert lane_for_key(pygame.K_j) == (NoteKind.FOOT, 1)
    assert lane_for_key(pygame.K_SEMICOLON) == (NoteKind.FOOT, 4)
    assert HAND_KEY_LABELS == ("A", "S", "D", "F")
    assert FOOT_KEY_LABELS == ("J", "K", "L", ";")
    assert label_for_lane(NoteKind.HANDS, 3) == "D"
    assert label_for_lane(NoteKind.FOOT, 4) == ";"


def test_short_tap_remains_occupied_for_one_update():
    keyboard = KeyboardBodyInput()

    assert keyboard.press(pygame.K_a) == (NoteKind.HANDS, 1)
    keyboard.release(pygame.K_a)

    assert keyboard.body_state().hand_lanes == frozenset((1,))
    assert keyboard.body_state().hand_lanes == frozenset()


def test_held_key_occupies_lane_without_repeating_timing_press():
    keyboard = KeyboardBodyInput()

    assert keyboard.press(pygame.K_k) == (NoteKind.FOOT, 2)
    assert keyboard.press(pygame.K_k, repeat=True) is None
    assert keyboard.body_state().foot_lanes == frozenset((2,))
    assert keyboard.body_state().foot_lanes == frozenset((2,))

    keyboard.release(pygame.K_k)
    assert keyboard.body_state().foot_lanes == frozenset()


def test_keyboard_lanes_supplement_camera_without_replacing_pose():
    camera = BodyState(
        left_wrist=BodyPoint(x=0.2, y=0.3, lane=1, visible=True),
        left_foot_control=BodyPoint(x=0.3, y=0.8, lane=2, visible=True),
        pose_visible=True,
        timestamp=12.5,
    )
    keyboard = KeyboardBodyInput()
    keyboard.press(pygame.K_f)
    keyboard.press(pygame.K_l)

    combined = add_keyboard_lanes(camera, keyboard.body_state())

    assert combined.left_wrist == camera.left_wrist
    assert combined.timestamp == camera.timestamp
    assert combined.hand_lanes == frozenset((1, 4))
    assert combined.foot_lanes == frozenset((2, 3))
