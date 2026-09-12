from __future__ import annotations

from pathlib import Path
import time

import pygame

from .domain import BodyState, ChainMode, ChainState, GameplayEventType, NoteKind
from .session import GameSession
from .simfile_loader import load_chart, scan_song
from .web_vaportap import (
    CYAN,
    HOLD_RADIUS,
    TOUCH_RADIUS,
    RuntimeNote,
    VaporTapPlaytest,
    _distance,
    _pair_color,
)


class SessionVaporTapPlaytest(VaporTapPlaytest):
    """VaporTap touch frontend backed by VaporStep's real gameplay session.

    The touch layer only translates screen gestures into logical lane occupancy
    and timing impulses. Note judgement, score/combo, explicit holds, timing
    windows, failure state, and gameplay events remain owned by GameSession.
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
        self._item_by_note = {id(item.note): item for item in self.notes}

    @property
    def elapsed(self) -> float:
        session = getattr(self, "session", None)
        return 0.0 if session is None else session.time

    def _record_touch_impulse(self, kind: NoteKind, lane: int) -> None:
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
        await __import__("asyncio").sleep(0)

    pygame.quit()
