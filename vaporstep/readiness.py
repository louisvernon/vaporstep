from __future__ import annotations

from .domain import BodyState
from .session import GameSession


def readiness_for_session(body: BodyState, session: GameSession) -> str:
    required = []
    labels = []
    if session.has_hand_notes:
        required.extend((body.left_wrist, body.right_wrist))
        labels.append("wrists")
    if session.has_foot_notes:
        required.extend((body.left_knee, body.right_knee))
        labels.append("legs")
    if not required:
        return "READY"
    if not all(point.visible for point in required):
        joined = " and both ".join(labels)
        return f"Keep both {joined} visible"
    if any(point.lane is None for point in required):
        areas = " / ".join("hand" if label == "wrists" else "foot" for label in labels)
        suffix = "s" if len(labels) > 1 else ""
        return f"Move into the {areas} play area{suffix}"
    return "READY"


def camera_ready_prompt(status: str) -> str:
    if status == "READY":
        return status
    return f"{status}\nOR PRESS INPUT KEY TO START"
