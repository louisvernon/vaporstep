from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


@dataclass(frozen=True)
class BodyPoint:
    x: float = 0.0
    y: float = 0.0
    lane: int | None = None
    visible: bool = False
    source_weight: float = 0.0


@dataclass(frozen=True)
class BodyState:
    left_wrist: BodyPoint = field(default_factory=BodyPoint)
    right_wrist: BodyPoint = field(default_factory=BodyPoint)
    left_knee: BodyPoint = field(default_factory=BodyPoint)
    right_knee: BodyPoint = field(default_factory=BodyPoint)
    left_ankle: BodyPoint = field(default_factory=BodyPoint)
    right_ankle: BodyPoint = field(default_factory=BodyPoint)
    left_foot_control: BodyPoint = field(default_factory=BodyPoint)
    right_foot_control: BodyPoint = field(default_factory=BodyPoint)
    pose_visible: bool = False
    timestamp: float = 0.0

    @property
    def hand_lanes(self) -> frozenset[int]:
        return frozenset(
            p.lane
            for p in (self.left_wrist, self.right_wrist)
            if p.visible and p.lane is not None
        )

    @property
    def foot_lanes(self) -> frozenset[int]:
        """Lower-body occupancy used for foot notes.

        Webcam pose input can provide a virtual control point part-way down the
        shin. That point is more stable for a planted foot than the knee while
        still falling back naturally when the ankle is not visible. Keyboard
        and older synthetic BodyState instances continue to use knee lanes.
        """
        controls = (self.left_foot_control, self.right_foot_control)
        if any(p.visible for p in controls):
            points = controls
        else:
            points = (self.left_knee, self.right_knee)
        return frozenset(
            p.lane
            for p in points
            if p.visible and p.lane is not None
        )


class NoteKind(str, Enum):
    FOOT = "foot"
    HANDS = "hands"


class HitQuality(str, Enum):
    HIT = "hit"
    GREAT = "great"
    PERFECT = "perfect"


class ChainMode(str, Enum):
    BLOCKS = "blocks"
    DEBUG = "debug"
    OFF = "off"

    @property
    def label(self) -> str:
        return {
            ChainMode.BLOCKS: "BLOCKS",
            ChainMode.DEBUG: "BLOCKS + NOTES",
            ChainMode.OFF: "OFF",
        }[self]

    def shifted(self, delta: int) -> "ChainMode":
        modes = (ChainMode.BLOCKS, ChainMode.DEBUG, ChainMode.OFF)
        return modes[(modes.index(self) + delta) % len(modes)]




class GameplayEventType(str, Enum):
    INPUT = "input"
    JUDGEMENT = "judgement"
    SUSTAIN_COMPLETE = "sustain_complete"
    SUSTAIN_BREAK = "sustain_break"


@dataclass(frozen=True)
class GameplayEvent:
    """Small immutable event used by live SFX and recording reconstruction."""

    time: float
    event_type: GameplayEventType
    kind: NoteKind
    quality: HitQuality | None = None
    hit: bool = True

class SustainSource(str, Enum):
    IMPLICIT_CHAIN = "implicit_chain"
    EXPLICIT_HOLD = "explicit_hold"


class ChainState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    BROKEN = "broken"
    COMPLETE = "complete"


@dataclass(frozen=True)
class ImplicitChain:
    id: int
    kind: NoteKind
    lanes: tuple[int, ...]
    note_indices: tuple[int, ...]
    start_time: float
    end_time: float
    start_beat: float
    end_beat: float
    source: SustainSource = SustainSource.IMPLICIT_CHAIN


@dataclass
class RuntimeChain:
    definition: ImplicitChain
    state: ChainState = ChainState.PENDING
    last_occupancy_at: float | None = None
    broken_at: float | None = None
    quality: HitQuality = HitQuality.HIT
    completion_judged: bool = False


@dataclass
class GameNote:
    time: float
    lanes: tuple[int, ...]
    kind: NoteKind
    end_time: float | None = None
    beat: float | None = None
    end_beat: float | None = None
    judged: bool = False
    hit: bool = False
    judged_at: float | None = None
    judgement: HitQuality | None = None
    timing_delta: float | None = None
    last_occupancy_at: float | None = None
    chain_id: int | None = None
    chain_index: int = 0
    chain_length: int = 1

    def is_satisfied(self, body: BodyState) -> bool:
        required = set(self.lanes)
        occupied = body.foot_lanes if self.kind == NoteKind.FOOT else body.hand_lanes
        return required.issubset(occupied)



def occupancy_is_fresh(last_occupancy_at: float | None, now: float, grace_seconds: float) -> bool:
    """Whether a lane was occupied recently enough to count at the receptor."""
    return (
        last_occupancy_at is not None
        and 0.0 <= now - last_occupancy_at <= grace_seconds
    )

def lanes_tuple(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted(set(values)))
