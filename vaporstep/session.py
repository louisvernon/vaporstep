from __future__ import annotations

from bisect import bisect_right
from fractions import Fraction
import math
import time
from typing import Iterable

import pygame

from .audio_fx import GAMEPLAY_MUSIC_VOLUME
from .chains import HOLD_OCCUPANCY_GRACE_SECONDS
from .config import HIT_WINDOW_SECONDS, LOOKAHEAD_BEATS, LOOKAHEAD_SECONDS, OCCUPANCY_GRACE_SECONDS
from .domain import (
    BodyState,
    ChainMode,
    ChainState,
    GameNote,
    GameplayEvent,
    GameplayEventType,
    HitQuality,
    NoteKind,
    RuntimeChain,
    SustainSource,
)
from .motion import GREAT_WINDOW_SECONDS, MOTION_EVENT_VISUAL_SECONDS, MotionEvent, MotionTracker
from .scoring import RunStats
from .song import LoadedChart


READY_HOLD_SECONDS = 0.8
MIN_WARNING_BEFORE_FAIL_SECONDS = 5.0
FAIL_HOLD_SECONDS = 3.0
SUSTAIN_TAIL_SCORE_WEIGHT = 2.0


def fresh_notes(notes: Iterable[GameNote]) -> list[GameNote]:
    return [
        GameNote(
            time=n.time,
            lanes=n.lanes,
            kind=n.kind,
            end_time=n.end_time,
            beat=n.beat,
            end_beat=n.end_beat,
            chain_id=n.chain_id,
            chain_index=n.chain_index,
            chain_length=n.chain_length,
        )
        for n in notes
    ]


def _stop_music() -> None:
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except pygame.error:
        pass


class GameSession:
    def __init__(
        self,
        chart: LoadedChart | None = None,
        demo_notes: Iterable[GameNote] = (),
        best_score: int = 0,
        chain_mode: ChainMode = ChainMode.BLOCKS,
    ) -> None:
        self.chart = chart
        source = chart.notes if chart is not None else tuple(demo_notes)
        self._source_notes = tuple(source)
        self.best_score = int(best_score)
        self.chain_mode = ChainMode(chain_mode)
        self._beat_times = tuple(marker.time for marker in chart.beat_markers) if chart is not None else ()
        self._beat_numbers = tuple(marker.beat for marker in chart.beat_markers) if chart is not None else ()
        self.notes: list[GameNote] = []
        self.chains: list[RuntimeChain] = []
        self._chain_by_id: dict[int, RuntimeChain] = {}
        self.stats = RunStats(total_notes=len(self._source_notes))
        self.running = False
        self.ready_since: float | None = None
        self.started = time.monotonic()
        self.audio_loaded = False
        self.audio_started = False
        self.lead_in_start_time = 0.0
        self.audio_error: str | None = None
        self.finished = False
        self.failed = False
        self.warning_since: float | None = None
        self.failed_at: float | None = None
        self.failed_song_time: float | None = None
        self.motion = MotionTracker()
        self.recent_motion_events: list[MotionEvent] = []
        self._gameplay_events: list[GameplayEvent] = []
        self.keyboard_mode = False
        self.restart()

    def _music_path(self):
        if self.chart is None:
            return None
        return self.chart.song.music_path

    def set_chain_mode(self, mode: ChainMode) -> bool:
        """Change implicit-chain behavior before the song has started.

        Mid-song changes would make already-judged continuation notes ambiguous,
        so chain mode is deliberately locked once audio/gameplay is running.
        """
        if self.running:
            return False
        self.chain_mode = ChainMode(mode)
        self.restart()
        return True

    def set_best_score(self, value: int) -> None:
        self.best_score = int(value)

    def set_keyboard_mode(self, enabled: bool) -> None:
        self.keyboard_mode = bool(enabled)

    def register_keyboard_press(self, kind: NoteKind, lane: int) -> MotionEvent | None:
        """Queue one keyboard timing impulse at the current chart time."""
        if not self.running or not self.keyboard_mode:
            return None
        event = self.motion.record_input(
            kind,
            lane,
            self.time,
            source="keyboard",
            limb="keyboard",
        )
        self.recent_motion_events.append(event)
        return event

    def _sustain_enabled(self, chain: RuntimeChain) -> bool:
        return (
            chain.definition.source == SustainSource.EXPLICIT_HOLD
            or self.chain_mode != ChainMode.OFF
        )

    def _effective_score_weights(self) -> tuple[float, ...]:
        """Return the ordered scoring timeline after applying chain mode.

        Authored holds always become head + weighted tail. When generated chains
        are enabled, only their first source note remains a timed head; the
        intermediate repeated notes are ignored and the chain end becomes the
        same weighted tail judgement used by authored holds.
        """
        suppressed_indices: set[int] = set()
        timeline: list[tuple[float, int, int, float]] = []

        for chain in self.chains:
            if not self._sustain_enabled(chain):
                continue
            definition = chain.definition
            if definition.source == SustainSource.IMPLICIT_CHAIN:
                suppressed_indices.update(definition.note_indices[1:])
            # Runtime updates process sustain tails before source notes at the
            # same song time, so preserve that ordering in the theoretical max.
            timeline.append(
                (definition.end_time, 0, definition.id, SUSTAIN_TAIL_SCORE_WEIGHT)
            )

        for index, note in enumerate(self._source_notes):
            if index in suppressed_indices:
                continue
            timeline.append((note.time, 1, index, 1.0))

        timeline.sort(key=lambda item: (item[0], item[1], item[2]))
        return tuple(item[3] for item in timeline)

    def restart(self) -> None:
        _stop_music()
        self.notes = fresh_notes(self._source_notes)
        definitions = ()
        if self.chart is not None:
            definitions = self.chart.sustains or self.chart.chains
        self.chains = [RuntimeChain(definition=chain) for chain in definitions]
        self._chain_by_id = {chain.definition.id: chain for chain in self.chains}
        score_weights = self._effective_score_weights()
        self.stats = RunStats(total_notes=len(score_weights), score_weights=score_weights)
        self.running = False
        self.ready_since = None
        self.started = time.monotonic()
        self.audio_loaded = False
        self.audio_started = False
        self.lead_in_start_time = 0.0
        self.audio_error = None
        self.finished = False
        self.failed = False
        self.warning_since = None
        self.failed_at = None
        self.failed_song_time = None
        self.motion.reset()
        self.recent_motion_events = []
        self._gameplay_events = []

    def drain_gameplay_events(self) -> tuple[GameplayEvent, ...]:
        events = tuple(self._gameplay_events)
        self._gameplay_events.clear()
        return events

    @property
    def has_hand_notes(self) -> bool:
        return any(note.kind == NoteKind.HANDS for note in self._source_notes)

    @property
    def has_foot_notes(self) -> bool:
        return any(note.kind == NoteKind.FOOT for note in self._source_notes)

    @property
    def performance_state(self) -> str:
        if self.failed:
            return "failed"
        raw = self.stats.performance_state
        # Once the statistical fail threshold is crossed, keep showing DANGER
        # during the guaranteed recovery grace period.
        return "danger" if raw == "failed" else raw

    def stop(self) -> None:
        _stop_music()
        self.running = False

    def _compute_lead_in_start_time(self) -> float:
        """Virtual chart time where the pre-roll should begin.

        Begin far enough back that the earliest target enters from the central
        origin rather than appearing partway through the playfield at time 0.
        Real charts use the timing engine so BPM and chart offset are respected.
        """
        if not self._source_notes:
            return 0.0

        first = min(self._source_notes, key=lambda n: n.time)
        if self.chart is not None and self.chart.timing_engine is not None and first.beat is not None:
            target_beat = float(first.beat) - LOOKAHEAD_BEATS
            try:
                beat_fraction = Fraction(target_beat).limit_denominator(192)
                start_time = float(self.chart.timing_engine.time_at(beat_fraction))
                return min(0.0, start_time)
            except Exception:
                pass

        return min(0.0, first.time - LOOKAHEAD_SECONDS)

    def _start_audio_clock(self, now: float) -> None:
        """Begin chart time zero and start audio if the chart has music."""
        self.started = now
        self.audio_started = True
        self.audio_loaded = False
        music_path = self._music_path()
        if music_path is not None:
            try:
                pygame.mixer.music.load(str(music_path))
                pygame.mixer.music.set_volume(GAMEPLAY_MUSIC_VOLUME)
                pygame.mixer.music.play()
                self.audio_loaded = True
            except pygame.error as exc:
                self.audio_error = str(exc)

    def _start(self, now: float) -> None:
        self.running = True
        self.started = now
        self.audio_loaded = False
        self.audio_started = False
        self.audio_error = None
        self.lead_in_start_time = self._compute_lead_in_start_time()
        if self.lead_in_start_time >= -1e-6:
            self._start_audio_clock(now)

    @property
    def time(self) -> float:
        if self.failed_song_time is not None:
            return self.failed_song_time
        if not self.running:
            return 0.0
        if not self.audio_started:
            return self.lead_in_start_time + (time.monotonic() - self.started)
        if self.audio_loaded:
            pos_ms = pygame.mixer.music.get_pos()
            if pos_ms >= 0:
                return pos_ms / 1000.0
        return time.monotonic() - self.started

    @property
    def beat_position(self) -> float:
        """Current musical beat used for beat-relative visual scrolling.

        Real charts delegate to simfile's timing engine, so BPM changes, stops,
        delays, and warps affect visual motion consistently with note timing.
        The synthetic demo falls back to a fixed 120 BPM clock.
        """
        t = self.time
        if self.chart is not None and self.chart.timing_engine is not None:
            try:
                return float(self.chart.timing_engine.beat_at(t))
            except Exception:
                pass
        return t * 2.0  # 120 BPM fallback

    def beat_pulse(self) -> tuple[float, bool]:
        """Return a short 0..1 pulse and whether the most recent beat is a downbeat."""
        t = self.time
        if (
            self.chart is not None
            and self.chart.timing_engine is not None
            and self._beat_times
            and t < self._beat_times[0]
        ):
            # Pre-roll can precede the precomputed marker table. Ask the timing
            # engine for the previous integer beat so tempo feedback is already
            # alive before the music itself starts.
            try:
                beat_index = math.floor(self.beat_position)
                marker_time = float(self.chart.timing_engine.time_at(Fraction(beat_index, 1)))
                age = t - marker_time
                strength = max(0.0, 1.0 - age / 0.22) ** 2
                return strength, beat_index % 4 == 0
            except Exception:
                pass
        if self._beat_times:
            idx = bisect_right(self._beat_times, t) - 1
            if idx < 0:
                return 0.0, False
            age = t - self._beat_times[idx]
            strength = max(0.0, 1.0 - age / 0.22) ** 2
            downbeat = self._beat_numbers[idx] % 4 == 0
            return strength, downbeat

        # Demo/no-chart fallback: 120 BPM.
        beat_duration = 0.5
        beat_index = math.floor(t / beat_duration)
        age = t - beat_index * beat_duration
        return max(0.0, 1.0 - age / 0.22) ** 2, beat_index % 4 == 0

    def _judge(
        self,
        note: GameNote,
        hit: bool,
        t: float,
        quality: HitQuality = HitQuality.HIT,
        timing_delta: float | None = None,
    ) -> None:
        note.judged = True
        note.hit = hit
        note.judged_at = t
        note.judgement = quality if hit else None
        note.timing_delta = timing_delta
        if hit:
            self.stats.register_hit(quality)
        else:
            self.stats.register_miss()

        # Keep live/exported audio sparse and musical: only GREAT/PERFECT
        # confirmations get a cue, and both use the same sound. Record the
        # event at the authored note time so reconstructed clips reinforce the
        # beat rather than raw camera/motion timing.
        if hit and quality in (HitQuality.GREAT, HitQuality.PERFECT):
            self._gameplay_events.append(
                GameplayEvent(
                    time=note.time,
                    event_type=GameplayEventType.JUDGEMENT,
                    kind=note.kind,
                    quality=quality,
                    hit=True,
                )
            )

    def _update_regular_note(self, note: GameNote, body: BodyState, t: float) -> None:
        delta = t - note.time
        if (
            -OCCUPANCY_GRACE_SECONDS <= delta <= HIT_WINDOW_SECONDS
            and note.is_satisfied(body)
        ):
            note.last_occupancy_at = t

        if delta >= 0.0 and self.keyboard_mode:
            timed = self.motion.match(
                note.kind,
                note.lanes,
                note.time,
                sources=frozenset(("keyboard",)),
            )
            if timed is not None:
                quality, timing_delta = timed
                self._judge(note, True, t, quality=quality, timing_delta=timing_delta)
                return

        settle_window = GREAT_WINDOW_SECONDS if self.keyboard_mode else HIT_WINDOW_SECONDS
        if delta >= 0.0 and note.last_occupancy_at is not None:
            timed = self.motion.match(note.kind, note.lanes, note.time)
            if timed is not None:
                quality, timing_delta = timed
                self._judge(note, True, t, quality=quality, timing_delta=timing_delta)
                return
            if delta >= settle_window:
                self._judge(note, True, t, quality=HitQuality.HIT)
                return

        if delta > settle_window:
            self._judge(note, False, t)

    @staticmethod
    def _chain_satisfied(chain: RuntimeChain, body: BodyState) -> bool:
        required = set(chain.definition.lanes)
        occupied = body.foot_lanes if chain.definition.kind == NoteKind.FOOT else body.hand_lanes
        return required.issubset(occupied)

    def _update_active_chains(self, body: BodyState, t: float) -> None:
        for chain in self.chains:
            if not self._sustain_enabled(chain):
                continue

            definition = chain.definition
            if chain.state == ChainState.ACTIVE:
                if self._chain_satisfied(chain, body):
                    chain.last_occupancy_at = t
                elif (
                    chain.last_occupancy_at is not None
                    and t - chain.last_occupancy_at > HOLD_OCCUPANCY_GRACE_SECONDS
                ):
                    chain.state = ChainState.BROKEN
                    chain.broken_at = t
                    self._gameplay_events.append(
                        GameplayEvent(
                            time=t,
                            event_type=GameplayEventType.SUSTAIN_BREAK,
                            kind=definition.kind,
                            quality=None,
                            hit=False,
                        )
                    )

                if chain.state == ChainState.ACTIVE and t >= definition.end_time:
                    chain.state = ChainState.COMPLETE
                    if not chain.completion_judged:
                        self.stats.register_hit(
                            chain.quality,
                            score_weight=SUSTAIN_TAIL_SCORE_WEIGHT,
                        )
                        chain.completion_judged = True
                        self._gameplay_events.append(
                            GameplayEvent(
                                time=t,
                                event_type=GameplayEventType.SUSTAIN_COMPLETE,
                                kind=definition.kind,
                                quality=chain.quality,
                                hit=True,
                            )
                        )
                        # Reuse the renderer's existing receptor pulse as visual
                        # feedback for a successful sustain tail. These events are
                        # visual-only: they do not enter MotionTracker and cannot
                        # satisfy or upgrade a later note judgement.
                        for lane in definition.lanes:
                            self.recent_motion_events.append(
                                MotionEvent(
                                    kind=definition.kind,
                                    lane=int(lane),
                                    song_time=t,
                                    limb="sustain",
                                    strength=2.2,
                                    source="sustain_complete",
                                )
                            )

            # A broken sustain still owns one failed tail judgement, but it is a
            # scoring/performance penalty only. It must never destroy a combo
            # rebuilt after the head or after the player left the sustain.
            if (
                chain.state == ChainState.BROKEN
                and not chain.completion_judged
                and t >= definition.end_time
            ):
                self.stats.register_miss(break_combo=False)
                chain.completion_judged = True

    def update(
        self,
        body: BodyState,
        ready_to_start: bool,
        *,
        start_immediately: bool = False,
    ) -> None:
        now = time.monotonic()

        # Hold the failed playfield on screen for a moment before results.
        if self.failed:
            if self.failed_at is not None and now - self.failed_at >= FAIL_HOLD_SECONDS:
                self.finished = True
            return

        if not self.running:
            # Keep motion baselines warm while positioning, but deliberately do
            # not emit timing events before the song starts.
            self.motion.update(body, None)
            self.recent_motion_events = []
            if ready_to_start:
                if start_immediately:
                    self._start(now)
                    self.motion.reset()
                    self.recent_motion_events = []
                    self.motion.update(body, None)
                elif self.ready_since is None:
                    self.ready_since = now
                elif now - self.ready_since >= READY_HOLD_SECONDS:
                    self._start(now)
                    self.motion.reset()
                    self.recent_motion_events = []
                    self.motion.update(body, None)
            else:
                self.ready_since = None
            return

        t = self.time
        if not self.audio_started and t >= 0.0:
            self._start_audio_clock(now)
            t = self.time
        generated = self.motion.update(body, t)
        if generated:
            self.recent_motion_events.extend(generated)
        self.recent_motion_events = [
            e for e in self.recent_motion_events if t - e.song_time <= MOTION_EVENT_VISUAL_SECONDS + 0.04
        ]
        self._update_active_chains(body, t)

        for note in self.notes:
            if note.judged:
                continue
            chain = self._chain_by_id.get(note.chain_id) if note.chain_id is not None else None
            if chain is not None and not self._sustain_enabled(chain):
                chain = None

            if chain is None:
                self._update_regular_note(note, body, t)
                continue

            if note.chain_index == 0:
                self._update_regular_note(note, body, t)
                if note.judged:
                    if note.hit:
                        chain.state = ChainState.ACTIVE
                        chain.last_occupancy_at = t
                        chain.quality = note.judgement or HitQuality.HIT
                    else:
                        chain.state = ChainState.BROKEN
                        chain.broken_at = t
                continue

            # Generated-chain intermediate notes remain available to DEBUG
            # rendering but are not gameplay judgements while chaining is on.
            # The shared sustain owns the single weighted tail judgement.
            continue

        raw_performance = self.stats.performance_state
        if raw_performance in ("warning", "danger", "failed"):
            if self.warning_since is None:
                self.warning_since = now
        else:
            self.warning_since = None

        if raw_performance == "failed":
            warned_for = 0.0 if self.warning_since is None else now - self.warning_since
            if warned_for >= MIN_WARNING_BEFORE_FAIL_SECONDS:
                self.failed = True
                self.failed_at = now
                self.failed_song_time = t
                _stop_music()
                self.running = False
                return

        last = self.chart.last_note_time if self.chart is not None else max((n.time for n in self.notes), default=0.0)
        if t > last + 2.0 and (not self.audio_loaded or not pygame.mixer.music.get_busy()):
            self.finished = True
