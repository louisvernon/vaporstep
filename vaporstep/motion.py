from __future__ import annotations

from dataclasses import dataclass
import time

from .domain import BodyPoint, BodyState, HitQuality, NoteKind


PERFECT_WINDOW_SECONDS = 0.10
GREAT_WINDOW_SECONDS = 0.30
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
    sample_song_time: float | None = None
    horizontal_velocity_ema: float = 0.0
    vertical_velocity_ema: float = 0.0
    strike_speed: float = 0.0
    armed: bool = True
    last_event_body_time: float = -999.0


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

    @staticmethod
    def _sample_song_time(body: BodyState, song_time: float | None) -> float | None:
        if song_time is None:
            return None
        if not body.timestamp_is_capture:
            return float(song_time)
        # The session's song clock and time.monotonic() advance at the same rate.
        # Move the musical timestamp back by the age of this camera sample so
        # inference latency affects feedback latency, not judgement timing.
        age = max(0.0, time.monotonic() - body.timestamp)
        return float(song_time) - age

    @staticmethod
    def _interpolate_time(
        previous_time: float | None,
        current_time: float | None,
        fraction: float,
    ) -> float | None:
        if current_time is None:
            return None
        if previous_time is None:
            return current_time
        fraction = max(0.0, min(1.0, float(fraction)))
        return previous_time + (current_time - previous_time) * fraction

    def update(self, body: BodyState, song_time: float | None) -> list[MotionEvent]:
        if body.timestamp <= 0.0 or body.timestamp == self._last_body_timestamp:
            return []
        self._last_body_timestamp = body.timestamp
        current_song_time = self._sample_song_time(body, song_time)
        generated: list[MotionEvent] = []

        for name, kind, point in self._limbs(body):
            state = self._states[name]
            previous = state.point
            prev_time = state.body_timestamp
            previous_song_time = state.sample_song_time

            entered_lane = (
                current_song_time is not None
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

            event: MotionEvent | None = None
            if entered_lane:
                # We only know that the categorical transition happened between
                # these two pose samples. The midpoint is an unbiased estimate
                # until lane resolvers expose a continuous boundary crossing.
                event_time = self._interpolate_time(previous_song_time, current_song_time, 0.5)
                event = MotionEvent(
                    kind=kind,
                    lane=int(point.lane),
                    song_time=float(event_time),
                    limb=name,
                    strength=max(1.0, strike_speed / max(strike_threshold, 1e-6)),
                    source="entry",
                )
                state.armed = False
            elif (
                current_song_time is not None
                and state.armed
                and point.visible
                and point.lane is not None
                and strike_speed >= strike_threshold
                and since_event >= MOTION_EVENT_LOCKOUT_SECONDS
            ):
                # Interpolate the threshold crossing when the previous sample was
                # below threshold. This avoids quantising a strike to the later
                # inferred pose while remaining bounded by two real samples.
                fraction = 1.0
                if state.strike_speed < strike_threshold and strike_speed > state.strike_speed:
                    fraction = (strike_threshold - state.strike_speed) / (strike_speed - state.strike_speed)
                event_time = self._interpolate_time(previous_song_time, current_song_time, fraction)
                event = MotionEvent(
                    kind=kind,
                    lane=int(point.lane),
                    song_time=float(event_time),
                    limb=name,
                    strength=strike_speed / strike_threshold,
                    source="strike",
                )
                state.armed = False

            if event is not None:
                state.last_event_body_time = body.timestamp
                self._events.append(event)
                generated.append(event)

            if (
                event is None
                and not state.armed
                and since_event >= MOTION_REARM_SECONDS
                and strike_speed <= reset_threshold
            ):
                state.armed = True

            state.point = point
            state.body_timestamp = body.timestamp
            state.sample_song_time = current_song_time
            state.strike_speed = strike_speed

        if current_song_time is not None:
            cutoff = current_song_time - (GREAT_WINDOW_SECONDS + 0.50)
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
                and abs(e.song_time - note_time) <= GREAT_WINDOW_SECONDS
            ]
            if not candidates:
                return None
            event = min(candidates, key=lambda e: abs(e.song_time - note_time))
            chosen.append(event)
            used_ids.add(id(event))

        worst_delta = max(abs(e.song_time - note_time) for e in chosen)
        quality = HitQuality.PERFECT if worst_delta <= PERFECT_WINDOW_SECONDS else HitQuality.GREAT
        for event in chosen:
            event.consumed = True
        self._events = [e for e in self._events if not e.consumed]
        return quality, worst_delta

    @property
    def pending_events(self) -> tuple[MotionEvent, ...]:
        return tuple(self._events)
