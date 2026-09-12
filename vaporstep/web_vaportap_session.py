from __future__ import annotations

import asyncio
from pathlib import Path
import time

import pygame

from .config import LOOKAHEAD_BEATS, LOOKAHEAD_SECONDS
from .domain import BodyState, ChainMode, ChainState, GameplayEventType, NoteKind
from .scroll import note_progress
from .session import GameSession
from .simfile_loader import load_chart, scan_song
from .web_vaportap import (
    CYAN,
    HIT_WINDOW,
    HOLD_RADIUS,
    SPLIT_LEAD,
    TOUCH_RADIUS,
    RuntimeNote,
    VaporTapPlaytest,
    _distance,
    _pair_color,
)
from . import playfield_geometry as geo


class SessionVaporTapPlaytest(VaporTapPlaytest):
    """VaporTap touch frontend backed by VaporStep's real gameplay session.

    The touch layer only translates screen gestures into logical lane occupancy
    and timing impulses. Chart parsing, note conversion, note travel timing,
    judgement, score/combo, explicit holds, failure state, and gameplay events
    remain owned by the shared VaporStep stack.
    """

    def reset(self) -> None:
        self.pointers.clear()
        self.impact_strength = 0.0
        self._seen_judgements: set[int] = set()
        self._hand_impulses: set[int] = set()
        self._finished_at: float | None = None

        stepfile = Path(__file__).with_name("web_demo.sm")
        song = scan_song(stepfile)
        if song is None or not song.charts:
            raise RuntimeError(f"No playable dance-single chart in {stepfile}")
        chart_info = next((chart for chart in song.charts if not chart.native_8_lane), song.charts[0])
        chart = load_chart(song, chart_info)

        self.session = GameSession(chart=chart, chain_mode=ChainMode.OFF)
        self.session.update(BodyState(), ready_to_start=True, start_immediately=True)

        self.notes = []
        for note in self.session.notes:
            color = (
                _pair_color(note.visual_ordinal or 0)
                if note.kind == NoteKind.HANDS
                else CYAN
            )
            self.notes.append(RuntimeNote(note=note, color=color))

    @property
    def elapsed(self) -> float:
        session = getattr(self, "session", None)
        return 0.0 if session is None else session.time

    def _shared_note_progress(self, item: RuntimeNote) -> float:
        return note_progress(
            item.note,
            self.session.time,
            self.session.beat_position,
            self.session.note_travel_speed,
        )

    def _foot_position(self, item: RuntimeNote) -> tuple[float, float]:
        """Use VaporStep's beat-relative scroll model for incoming foot material."""
        return geo.lane_center(
            self.size,
            NoteKind.FOOT,
            item.note.lanes[0],
            self._shared_note_progress(item),
        )

    def _hand_core_position(self, item: RuntimeNote) -> tuple[float, float]:
        """Move the raw hand core using the same chart progress as VaporStep.

        VaporTap still owns the final split gesture, but its precursor no longer
        has a separate fixed-seconds travel clock. Real charts therefore inherit
        BPM changes/stops/warps from GameSession's TimingEngine.
        """
        viewport = geo.camera_rect(self.size)
        source = (viewport.centerx, geo.field_y(self.size, NoteKind.FOOT, 0.0))
        target = (viewport.centerx, geo.field_y(self.size, NoteKind.FOOT, 0.22))
        progress = self._shared_note_progress(item)
        if item.note.beat is not None:
            capture_progress = 1.0 - 1.0 / max(LOOKAHEAD_BEATS, 1.0)
        else:
            capture_progress = 1.0 - SPLIT_LEAD / max(LOOKAHEAD_SECONDS, SPLIT_LEAD)
        travel = geo.clamp(progress / max(capture_progress, 0.001))
        eased = travel * travel * (3.0 - 2.0 * travel)
        return (
            source[0] + (target[0] - source[0]) * eased,
            source[1] + (target[1] - source[1]) * eased,
        )

    def _try_capture_pair(self) -> None:
        """Keep VaporTap's gesture window musical for real beat-based charts."""
        if len(self.pointers) < 2:
            return
        now = self.session.time
        song_beat = self.session.beat_position
        for item in self.notes:
            if item.state != "pending" or item.note.kind != NoteKind.HANDS:
                continue
            if now > item.note.time + HIT_WINDOW:
                continue
            if item.note.beat is not None:
                if float(item.note.beat) - song_beat > 1.0:
                    continue
            elif item.note.time - now > SPLIT_LEAD:
                continue
            core = self._hand_core_position(item)
            nearby = [
                pointer_id
                for pointer_id, point in self.pointers.items()
                if _distance(point, core) <= 72.0 * 1.35
            ]
            if len(nearby) >= 2:
                item.pointer_ids = (nearby[0], nearby[1])
                item.state = "captured"
                item.state_at = now
                return

    def _record_touch_impulse(self, kind: NoteKind, lane: int) -> None:
        # MotionTracker.record_input is already the shared logical-input path
        # used by keyboard timing. Keep touch as a source label rather than
        # inventing a second timing/judgement implementation.
        event = self.session.motion.record_input(
            kind,
            lane,
            self.session.time,
            source="touch",
            limb="touch",
            strength=1.0,
        )
        self.session.recent_motion_events.append(event)

    def _nearest_foot_lane(self, position: tuple[float, float], radius: float) -> int | None:
        candidates = [
            (lane, _distance(position, self._foot_endpoint(lane)))
            for lane in range(1, 5)
        ]
        lane, distance = min(candidates, key=lambda pair: pair[1])
        return lane if distance <= radius else None

    def pointer_down(self, pointer_id: int, position: tuple[float, float]) -> None:
        self.pointers[pointer_id] = position
        lane = self._nearest_foot_lane(position, TOUCH_RADIUS)
        if lane is not None:
            self._record_touch_impulse(NoteKind.FOOT, lane)
        self._try_capture_pair()

    def pointer_move(self, pointer_id: int, position: tuple[float, float]) -> None:
        if pointer_id in self.pointers:
            self.pointers[pointer_id] = position

    def pointer_up(self, pointer_id: int) -> None:
        for item in self.notes:
            if pointer_id not in item.pointer_ids:
                continue
            if item.state == "captured" and not item.note.judged:
                item.state = "pending"
                item.pointer_ids = ()
                self._hand_impulses.discard(id(item.note))
        self.pointers.pop(pointer_id, None)

    def _occupied_foot_lanes(self) -> frozenset[int]:
        occupied: set[int] = set()
        for point in self.pointers.values():
            lane = self._nearest_foot_lane(point, HOLD_RADIUS)
            if lane is not None:
                occupied.add(lane)
        return frozenset(occupied)

    def _occupied_hand_lanes(self) -> frozenset[int]:
        occupied: set[int] = set()
        for item in self.notes:
            if item.note.kind != NoteKind.HANDS or item.state not in {"captured", "holding"}:
                continue
            if self._pair_assignment_ok(item, radius=HOLD_RADIUS):
                occupied.update(item.note.lanes)
                key = id(item.note)
                if key not in self._hand_impulses:
                    for lane in item.note.lanes:
                        self._record_touch_impulse(NoteKind.HANDS, lane)
                    self._hand_impulses.add(key)
        return frozenset(occupied)

    def _body_state(self) -> BodyState:
        return BodyState(
            supplemental_hand_lanes=self._occupied_hand_lanes(),
            supplemental_foot_lanes=self._occupied_foot_lanes(),
            timestamp=time.monotonic(),
        )

    def _sync_visual_states(self) -> None:
        chains = {chain.definition.id: chain for chain in self.session.chains}
        now = self.elapsed

        for item in self.notes:
            note = item.note
            previous = item.state
            if not note.judged:
                continue

            if not note.hit:
                item.state = "missed"
            else:
                chain = chains.get(note.chain_id) if note.chain_id is not None else None
                if chain is None:
                    item.state = "complete"
                elif chain.state == ChainState.ACTIVE:
                    item.state = "holding"
                elif chain.state == ChainState.BROKEN:
                    item.state = "dropped"
                elif chain.state == ChainState.COMPLETE:
                    item.state = "complete"
                else:
                    item.state = "complete"

            if item.state != previous:
                item.state_at = now

            key = id(note)
            if note.hit and key not in self._seen_judgements:
                self._trigger_impact(8.0 if note.kind == NoteKind.HANDS else 4.5)
            if note.judged:
                self._seen_judgements.add(key)

    def update(self) -> None:
        if self.session.finished:
            if self._finished_at is None:
                self._finished_at = time.monotonic()
            elif time.monotonic() - self._finished_at >= 2.5:
                self.reset()
            return

        self._try_capture_pair()
        self.session.update(
            self._body_state(),
            ready_to_start=True,
            start_immediately=True,
        )
        self._sync_visual_states()

        for event in self.session.drain_gameplay_events():
            if event.event_type == GameplayEventType.SUSTAIN_COMPLETE:
                self._trigger_impact(4.5 if event.kind == NoteKind.HANDS else 3.0)

    def draw(self) -> None:
        super().draw()
        stats = self.session.stats
        width, height = self.screen.get_size()
        line = self.small_font.render(
            (
                f"REAL SESSION  score {stats.score:,}  combo {stats.combo}  "
                f"P {stats.perfects}  G {stats.greats}  H {stats.basic_hits}  "
                f"M {stats.misses}  drops {stats.dropped_holds}"
            ),
            True,
            CYAN,
        )
        self.screen.blit(line, line.get_rect(midbottom=(width // 2, height - 14)))

        if self.session.finished:
            result = self.big_font.render(
                f"{stats.grade}  {stats.score:,}",
                True,
                CYAN,
            )
            self.screen.blit(result, result.get_rect(center=(width // 2, height // 2)))


async def main() -> None:
    pygame.init()
    pygame.display.set_caption("VaporTap WASM Shared-Session Playtest")
    screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
    playtest = SessionVaporTapPlaytest(screen)
    clock = pygame.time.Clock()
    running = True

    while running:
        for event in pygame.event.get():
            running = playtest.handle_event(event)
            if not running:
                break

        playtest.update()
        playtest.draw()
        pygame.display.flip()

        if hasattr(pygame, "IS_CE") and pygame.IS_CE:
            clock.tick(60)
        await asyncio.sleep(0)

    pygame.quit()
