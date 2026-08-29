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
class PoseFigure:
    """Display-ready copy of MediaPipe's already-computed pose landmarks."""

    landmarks: tuple[BodyPoint, ...] = ()

    def point(self, index: int) -> BodyPoint:
        if 0 <= index < len(self.landmarks):
            return self.landmarks[index]
        return BodyPoint()


@dataclass(frozen=True)
class BodyState:
    left_wrist: BodyPoint = field(default_factory=BodyPoint)
    right_wrist: BodyPoint = field(default_factory=BodyPoint)
    left_hand_control: BodyPoint = field(default_factory=BodyPoint)
    right_hand_control: BodyPoint = field(default_factory=BodyPoint)
    left_knee: BodyPoint = field(default_factory=BodyPoint)
    right_knee: BodyPoint = field(default_factory=BodyPoint)
    left_ankle: BodyPoint = field(default_factory=BodyPoint)
    right_ankle: BodyPoint = field(default_factory=BodyPoint)
    left_foot_control: BodyPoint = field(default_factory=BodyPoint)
    right_foot_control: BodyPoint = field(default_factory=BodyPoint)
    supplemental_hand_lanes: frozenset[int] = field(default_factory=frozenset)
    supplemental_foot_lanes: frozenset[int] = field(default_factory=frozenset)
    pose_visible: bool = False
    timestamp: float = 0.0

    @property
    def hand_lanes(self) -> frozenset[int]:
        controls = (self.left_hand_control, self.right_hand_control)
        if any(p.visible for p in controls):
            points = controls
        else:
            # Keyboard/synthetic states from older code can still supply wrist
            # lanes directly. Webcam tracking now uses body-relative controls.
            points = (self.left_wrist, self.right_wrist)
        tracked = frozenset(
            p.lane
            for p in points
            if p.visible and p.lane is not None
        )
        return tracked | self.supplemental_hand_lanes

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
        tracked = frozenset(
            p.lane
            for p in points
            if p.visible and p.lane is not None
        )
        return tracked | self.supplemental_foot_lanes


class NoteKind(str, Enum):
    FOOT = "foot"
    HANDS = "hands"


class HitQuality(str, Enum):
    HIT = "hit"
    GREAT = "great"
    PERFECT = "perfect"


class ChainMode(str, Enum):
    BLOCKS = "blocks"
    OFF = "off"

    @property
    def label(self) -> str:
        return "ON" if self == ChainMode.BLOCKS else "OFF"

    def shifted(self, delta: int = 1) -> "ChainMode":
        return ChainMode.OFF if self == ChainMode.BLOCKS else ChainMode.BLOCKS


class GameplayEventType(str, Enum):
    INPUT = "input"
    JUDGEMENT = "judgement"
    SUSTAIN_COMPLETE = "sustain_complete"
    SUSTAIN_BREAK = "sustain_break"


@dataclass(frozen=True)
class GameplayEvent:
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
    visual_ordinal: int | None = None


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
    # Assigned by GameSession so a renderer receiving only the current time
    # window can preserve authored alternating hand colors.
    visual_ordinal: int | None = None

    def is_satisfied(self, body: BodyState) -> bool:
        required = set(self.lanes)
        occupied = body.foot_lanes if self.kind == NoteKind.FOOT else body.hand_lanes
        return required.issubset(occupied)


def occupancy_is_fresh(last_occupancy_at: float | None, now: float, grace_seconds: float) -> bool:
    return (
        last_occupancy_at is not None
        and 0.0 <= now - last_occupancy_at <= grace_seconds
    )


def lanes_tuple(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted(set(values)))
