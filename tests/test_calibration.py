import pygame
import pytest

from vaporstep.app import _audio_sync_adjustment_for_event, _route_keyboard_press
from vaporstep.demo import make_demo_notes
from vaporstep.domain import BodyState, GameNote, NoteKind
from vaporstep.keyboard_input import HAND_KEYS, FOOT_KEYS, KeyboardBodyInput
from vaporstep.readiness import readiness_for_session
from vaporstep.session import GameSession


@pytest.mark.parametrize("key", HAND_KEYS + FOOT_KEYS)
def test_calibration_keyboard_start_bypasses_unready_camera(key):
    session = GameSession(demo_notes=make_demo_notes())
    keyboard = KeyboardBodyInput()
    press = keyboard.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
    body = BodyState()  # Camera is active but no valid start pose is visible.
    camera_ready = readiness_for_session(body, session) == "READY"

    requested = _route_keyboard_press(session, press)
    session.set_keyboard_mode(True)
    session.update(
        body, ready_to_start=camera_ready or requested, start_immediately=requested
    )

    assert not camera_ready
    assert requested
    assert session.running
    assert session.input_mode == "keyboard"


def test_calibration_without_input_still_waits_for_camera_pose():
    session = GameSession(demo_notes=make_demo_notes())
    keyboard = KeyboardBodyInput()
    press = keyboard.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))

    requested = _route_keyboard_press(session, press)
    session.update(BodyState(), ready_to_start=requested, start_immediately=requested)

    assert not requested
    assert not session.running
    assert session.ready_since is None


def test_running_session_routes_keyboard_press_as_gameplay(monkeypatch):
    monkeypatch.setattr(GameSession, "time", property(lambda self: 1.0))
    session = GameSession(demo_notes=[GameNote(1.0, (2,), NoteKind.FOOT)])
    session.running = True
    session.set_keyboard_mode(True)

    assert not _route_keyboard_press(session, (NoteKind.FOOT, 2))
    assert len(session.recent_motion_events) == 1
    assert session.recent_motion_events[0].lane == 2


@pytest.mark.parametrize(
    ("key", "unicode", "expected"),
    (
        (pygame.K_EQUALS, "+", 5),
        (pygame.K_KP_PLUS, "+", 5),
        (pygame.K_MINUS, "-", -5),
        (pygame.K_KP_MINUS, "-", -5),
        (pygame.K_LEFT, "", 0),
    ),
)
def test_calibration_audio_sync_keys(key, unicode, expected):
    event = pygame.event.Event(pygame.KEYDOWN, key=key, unicode=unicode)

    assert _audio_sync_adjustment_for_event(event) == expected
