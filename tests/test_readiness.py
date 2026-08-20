from vaporstep.domain import BodyPoint, BodyState, GameNote, NoteKind
from vaporstep.readiness import camera_ready_prompt, readiness_for_session
from vaporstep.session import GameSession


def _mixed_session() -> GameSession:
    return GameSession(
        demo_notes=[
            GameNote(time=1.0, lanes=(1,), kind=NoteKind.HANDS),
            GameNote(time=2.0, lanes=(1,), kind=NoteKind.FOOT),
        ]
    )


def test_camera_prompt_names_required_limbs_and_keyboard_alternative():
    status = readiness_for_session(BodyState(), _mixed_session())

    assert status == "Keep both wrists and both legs visible"
    assert camera_ready_prompt(status) == (
        "Keep both wrists and both legs visible\nOR PRESS INPUT KEY TO START"
    )


def test_ready_camera_does_not_show_redundant_keyboard_alternative():
    visible = BodyPoint(lane=1, visible=True)
    body = BodyState(
        left_wrist=visible,
        right_wrist=visible,
        left_knee=visible,
        right_knee=visible,
    )

    assert camera_ready_prompt(readiness_for_session(body, _mixed_session())) == "READY"
