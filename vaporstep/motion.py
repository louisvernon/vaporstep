from __future__ import annotations

from dataclasses import dataclass

from .domain import BodyPoint, BodyState, HitQuality, NoteKind


PERFECT_WINDOW_SECONDS = 1.0 / 15.0
GREAT_EARLY_WINDOW_SECONDS = 0.20
GREAT_LATE_WINDOW_SECONDS = 0.10
# Compatibility/export value for code that only needs the largest extent.
GREAT_WINDOW_SECONDS = max(GREAT_EARLY_WINDOW_SECONDS, GREAT_LATE_WINDOW_SECONDS)
MOTION_EVENT_LOCKOUT_SECONDS = 0.16
MOTION_REARM_SECONDS = 0.07
MOTION_EVENT_VISUAL_SECONDS = 0.80

# Signed velocity in normalized image coordinates per second. Hand gesture lanes
# use motion toward their body-relative target; feet remain downward knee stomps.
HAND_STRIKE_SPEED = 0.24
HAND_RESET_SPEED = 0.12
KNEE_STRIKE_SPEED = 0.17
KNEE_RESET_SPEED = 0.085


@dataclass
class MotionEvent:
    kind: NoteKind
    lane: int
    song_time: float
    limb: str
    strength: float
    source: str = "motion"
    consumed: bool = False


@dataclass
class _LimbState:
    point: BodyPoint | None = None
    body_timestamp: float = 0.0
    horizontal_velocity_ema: float = 0.0
    vertical_velocity_ema: float = 0.0
    armed: bool = True
    last_event_body_time: float = -999.0
    active_strike: MotionEvent | None = None


class MotionTracker:
    """Turn pose transitions and directional movement into sparse impulses."""

    def __init__(self) -> None:
        self._states = {name: _LimbState() for name in ("lw", "rw", "lk", "rk")}
        self._events: list[MotionEvent] = []
        self._last_body_timestamp = -1.0

    def reset(self) -> None:
        self._states = {name: _LimbState() for name in ("lw", "rw", "lk", "rk")}
        self._events.clear()
        self._last_body_timestamp = -1.0

    @staticmethod
    def _limbs(body: BodyState):
        return (
            ("lw", NoteKind.HANDS, body.left_wrist),
            ("rw", NoteKind.HANDS, body.right_wrist),
            ("lk", NoteKind.FOOT, body.left_knee),
            ("rk", NoteKind.FOOT, body.right_knee),
        )

    @staticmethod
    def _strike_speed(
        kind: NoteKind,
        lane: int | None,
        horizontal_velocity: float,
        vertical_velocity: float,
    ) -> float:
        if kind == NoteKind.FOOT:
            return max(0.0, vertical_velocity)
        # Hand lane semantics are now gestures, not screen-space columns:
        # 1 left/out, 2 left/high, 3 right/high, 4 right/out.
        if lane == 1:
            return max(0.0, -horizontal_velocity)
        if lane in (2, 3):
            return max(0.0, -vertical_velocity)
        if lane == 4:
            return max(0.0, horizontal_velocity)
        return 0.0

    def update(self, body: BodyState, song_time: float | None) -> list[MotionEvent]:
        if body.timestamp <= 0.0 or body.timestamp == self._last_body_timestamp:
            return []
        self._last_body_timestamp = body.timestamp
        generated: list[MotionEvent] = []

        for name, kind, point in self._limbs(body):
            state = self._states[name]
            previous = state.point
            prev_time = state.body_timestamp

            entered_lane = (
                song_time is not None
                and point.visible
                and point.lane is not None
                and previous is not None
                and previous.visible
                and previous.lane != point.lane
            )

            if (
                previous is not None
                and previous.visible
                and point.visible
                and prev_time > 0.0
                and body.timestamp > prev_time
            ):
                dt = max(body.timestamp - prev_time, 1e-4)
                instantaneous_vx = (point.x - previous.x) / dt
                instantaneous_vy = (point.y - previous.y) / dt
                state.horizontal_velocity_ema = 0.45 * state.horizontal_velocity_ema + 0.55 * instantaneous_vx
                state.vertical_velocity_ema = 0.45 * state.vertical_velocity_ema + 0.55 * instantaneous_vy
            else:
                state.horizontal_velocity_ema *= 0.35
                state.vertical_velocity_ema *= 0.35

            strike_threshold = HAND_STRIKE_SPEED if kind == NoteKind.HANDS else KNEE_STRIKE_SPEED
            reset_threshold = HAND_RESET_SPEED if kind == NoteKind.HANDS else KNEE_RESET_SPEED
            strike_speed = self._strike_speed(
                kind,
                point.lane,
                state.horizontal_velocity_ema,
                state.vertical_velocity_ema,
            )
            since_event = body.timestamp - state.last_event_body_time

            # Threshold crossing starts a strike, but the musically meaningful
            # moment can be the later landing/extension. Keep the same pending
            # event aligned with the ongoing movement until it slows, changes
            # lane, or is consumed by a note.
            if state.active_strike is not None and state.active_strike.consumed:
                state.active_strike = None
            if (
                state.active_strike is not None
                and song_time is not None
                and point.visible
                and point.lane == state.active_strike.lane
                and not entered_lane
            ):
                state.active_strike.song_time = float(song_time)
                state.active_strike.strength = max(
                    state.active_strike.strength,
                    strike_speed / max(strike_threshold, 1e-6),
                )
            elif entered_lane:
                state.active_strike = None

            event: MotionEvent | None = None
            if entered_lane:
                event = MotionEvent(
                    kind=kind,
                    lane=int(point.lane),
                    song_time=float(song_time),
                    limb=name,
                    strength=max(1.0, strike_speed / max(strike_threshold, 1e-6)),
                    source="entry",
                )
                state.armed = False
            elif (
                song_time is not None
                and state.armed
                and point.visible
                and point.lane is not None
                and strike_speed >= strike_threshold
                and since_event >= MOTION_EVENT_LOCKOUT_SECONDS
            ):
                event = MotionEvent(
                    kind=kind,
                    lane=int(point.lane),
                    song_time=float(song_time),
                    limb=name,
                    strength=strike_speed / strike_threshold,
                    source="strike",
                )
                state.armed = False

            if event is not None:
                state.last_event_body_time = body.timestamp
                self._events.append(event)
                generated.append(event)
                if event.source == "strike":
                    state.active_strike = event

            if (
                event is None
                and not state.armed
                and since_event >= MOTION_REARM_SECONDS
                and strike_speed <= reset_threshold
            ):
                state.armed = True
                state.active_strike = None

            state.point = point
            state.body_timestamp = body.timestamp

        if song_time is not None:
            cutoff = song_time - (GREAT_WINDOW_SECONDS + 0.50)
            self._events = [e for e in self._events if not e.consumed and e.song_time >= cutoff]
        return generated

    def record_input(
        self,
        kind: NoteKind,
        lane: int,
        song_time: float,
        *,
        source: str,
        limb: str,
        strength: float = 1.0,
    ) -> MotionEvent:
        event = MotionEvent(
            kind=NoteKind(kind),
            lane=int(lane),
            song_time=float(song_time),
            limb=str(limb),
            strength=float(strength),
            source=str(source),
        )
        self._events.append(event)
        return event

    def match(
        self,
        kind: NoteKind,
        lanes: tuple[int, ...],
        note_time: float,
        *,
        sources: frozenset[str] | None = None,
        perfect_only: bool = False,
        consume: bool = True,
    ) -> tuple[HitQuality, float] | None:
        chosen: list[MotionEvent] = []
        used_ids: set[int] = set()
        for lane in lanes:
            candidates = [
                e
                for e in self._events
                if not e.consumed
                and id(e) not in used_ids
                and e.kind == kind
                and e.lane == lane
                and (sources is None or e.source in sources)
                and -GREAT_EARLY_WINDOW_SECONDS
                <= e.song_time - note_time
                <= GREAT_LATE_WINDOW_SECONDS
            ]
            if not candidates:
                return None
            event = min(candidates, key=lambda e: abs(e.song_time - note_time))
            chosen.append(event)
            used_ids.add(id(event))

        worst_delta = max(abs(e.song_time - note_time) for e in chosen)
        if perfect_only and worst_delta > PERFECT_WINDOW_SECONDS:
            return None
        quality = HitQuality.PERFECT if worst_delta <= PERFECT_WINDOW_SECONDS else HitQuality.GREAT
        if consume:
            for event in chosen:
                event.consumed = True
            self._events = [e for e in self._events if not e.consumed]
        return quality, worst_delta

    @property
    def pending_events(self) -> tuple[MotionEvent, ...]:
        return tuple(self._events)
