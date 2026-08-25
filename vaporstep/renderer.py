from __future__ import annotations

import math

import pygame

from . import renderer_base as _base
from .domain import BodyState, ChainMode, ChainState, GameNote, HitQuality, NoteKind, RuntimeChain, SustainSource
from .motion import MOTION_EVENT_VISUAL_SECONDS, MotionEvent
from .scroll import note_is_within_lookahead, timed_is_within_lookahead, timed_progress

# Preserve the renderer module's public constants/helpers for the song-library
# renderer and other callers while specializing gameplay hands below.
BG = _base.BG
CYAN = _base.CYAN
MAGENTA = _base.MAGENTA
PURPLE = _base.PURPLE
WHITE = _base.WHITE
DIM = _base.DIM
GRID = _base.GRID
GREEN = _base.GREEN
RED = _base.RED
AMBER = _base.AMBER
ELECTRIC_YELLOW = _base.ELECTRIC_YELLOW
HIT_BRICK_POP_SECONDS = _base.HIT_BRICK_POP_SECONDS
_blend = _base._blend


# Hand lanes retain their authored 1..4 identities but occupy radial gestures.
# Angles are screen-space degrees: 0 right, 90 down, -90 up.
_HAND_ANGLES = {
    1: -165.0,  # left/out
    2: -120.0,  # left/high
    3: -60.0,   # right/high
    4: -15.0,   # right/out
}
_HAND_HALF_ARC = 18.0


class Renderer(_base.Renderer):
    """Base VaporStep renderer with a body-relative radial hand playfield."""

    def _hand_geometry(self) -> tuple[tuple[float, float], float, float]:
        viewport = self._camera_rect()
        center = (float(viewport.centerx), float(self._camera_y(_base.VANISH_Y)))
        outer = min(viewport.width * 0.185, viewport.height * 0.235)
        inner = outer * 0.39
        return center, inner, outer

    @staticmethod
    def _polar(center, radius: float, angle_deg: float) -> tuple[float, float]:
        a = math.radians(angle_deg)
        return center[0] + math.cos(a) * radius, center[1] + math.sin(a) * radius

    def _hand_sector_polygon(self, lane: int, inner: float, outer: float, *, samples: int = 8):
        center, _, _ = self._hand_geometry()
        angle = _HAND_ANGLES[lane]
        points = [
            self._polar(center, outer, angle - _HAND_HALF_ARC + (2 * _HAND_HALF_ARC * i / samples))
            for i in range(samples + 1)
        ]
        points.extend(
            self._polar(center, inner, angle + _HAND_HALF_ARC - (2 * _HAND_HALF_ARC * i / samples))
            for i in range(samples + 1)
        )
        return [(int(x), int(y)) for x, y in points]

    def _hand_target_point(self, lane: int, progress: float) -> tuple[float, float]:
        center, inner, outer = self._hand_geometry()
        p = max(0.0, min(1.0, progress)) ** 1.15
        radius = inner * 0.35 + (outer - inner * 0.35) * p
        return self._polar(center, radius, _HAND_ANGLES[lane])

    def _draw_hand_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        enabled: bool,
        strike_events: tuple[MotionEvent, ...] = (),
    ) -> None:
        center, inner, outer = self._hand_geometry()
        occupied = body.hand_lanes if enabled else frozenset()
        neutral_color = _blend(GRID, BG, 0.22 if enabled else 0.62)
        pygame.draw.circle(self.screen, neutral_color, (int(center[0]), int(center[1])), int(inner), 1)

        for lane in range(1, 5):
            active = lane in occupied
            polygon = self._hand_sector_polygon(lane, inner, outer)
            fill = _blend(BG, MAGENTA, 0.32 if active else 0.07)
            edge = MAGENTA if active else (_blend(DIM, BG, 0.12) if enabled else _blend(DIM, BG, 0.58))
            if enabled:
                pygame.draw.polygon(self.screen, fill, polygon)
            pygame.draw.lines(self.screen, edge, True, polygon, 3 if active else 1)

            target = self._hand_target_point(lane, 1.0)
            pygame.draw.circle(
                self.screen,
                WHITE if active else edge,
                (int(target[0]), int(target[1])),
                5 if active else 3,
                0 if active else 1,
            )

            matching = [
                event
                for event in strike_events
                if event.kind == NoteKind.HANDS
                and event.lane == lane
                and 0.0 <= song_time - event.song_time <= MOTION_EVENT_VISUAL_SECONDS
            ]
            if matching:
                latest = max(matching, key=lambda e: e.song_time)
                age = song_time - latest.song_time
                phase = 1.0 - min(1.0, age / MOTION_EVENT_VISUAL_SECONDS)
                ring_r = int(8 + 18 * (1.0 - phase))
                pygame.draw.circle(
                    self.screen,
                    _blend(MAGENTA, WHITE, 0.55),
                    (int(target[0]), int(target[1])),
                    ring_r,
                    max(1, int(3 * phase)),
                )

        # Two continuous state dots show what the body-relative resolver sees.
        # They are intentionally controller-space positions, not camera-space
        # wrist markers, so the player is not encouraged to align raw X/Y.
        for control, color in (
            (body.left_hand_control, CYAN),
            (body.right_hand_control, MAGENTA),
        ):
            if not control.visible:
                continue
            vx = (control.x - 0.5) * 2.0
            vy = (control.y - 0.5) * 2.0
            length = math.hypot(vx, vy)
            if length > 1.0:
                vx /= length
                vy /= length
            radius = inner * 0.72 + (outer - inner) * 0.78 * min(1.0, length)
            angle = math.degrees(math.atan2(vy, vx)) if length > 1e-4 else -90.0
            if length < 0.16:
                radius = inner * 0.42
                angle = -90.0 if control is body.left_hand_control else -90.0
            x, y = self._polar(center, radius, angle)
            pygame.draw.circle(self.screen, BG, (int(x), int(y)), 7)
            pygame.draw.circle(self.screen, color, (int(x), int(y)), 5, 2)

        if not enabled:
            off = self.small_font.render("NO HAND NOTES", True, _blend(DIM, BG, 0.30))
            self.screen.blit(off, off.get_rect(center=(int(center[0]), int(center[1] - outer - 18))))

    def _draw_playfields(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        downbeat: bool,
        hand_enabled: bool,
        foot_enabled: bool,
        overdrive: bool = False,
        animate_buzz: bool = True,
    ) -> None:
        # Feet keep the proven perspective floor. Suppress only the old hand
        # rails and draw the radial controller in their place.
        super()._draw_playfields(
            body,
            song_time,
            beat_pulse,
            downbeat,
            False,
            foot_enabled,
            overdrive,
            animate_buzz,
        )
        self._draw_hand_playfield(body, song_time, beat_pulse, hand_enabled)

    def _draw_notes(
        self,
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode = ChainMode.OFF,
    ) -> None:
        foot_notes = [note for note in notes if note.kind == NoteKind.FOOT]
        super()._draw_notes(foot_notes, song_time, song_beat, chain_mode)

        for note in notes:
            if note.kind != NoteKind.HANDS:
                continue
            if note.end_time is not None and note.chain_id is not None:
                continue
            if note.chain_id is not None and chain_mode == ChainMode.BLOCKS:
                continue
            if not note_is_within_lookahead(note, song_time, song_beat):
                continue
            dt = note.time - song_time
            if note.judged and note.judged_at is not None:
                age = song_time - note.judged_at
                if age > _base.HIT_FLASH_SECONDS:
                    continue
            elif dt < -_base.HIT_WINDOW_SECONDS:
                continue

            progress = self._note_progress(note, song_time, song_beat)
            if note.judged and note.hit:
                color = WHITE
            elif note.judged:
                color = RED
            else:
                beat_phase = song_beat - math.floor(song_beat)
                breathe = 0.5 + 0.5 * math.cos(beat_phase * math.tau)
                color = _blend(BG, MAGENTA, 0.78 + 0.22 * breathe)

            for lane in note.lanes:
                x, y = self._hand_target_point(lane, progress)
                radius = max(5, int(7 + 5 * max(0.0, min(1.0, progress))))
                pygame.draw.circle(self.screen, BG, (int(x), int(y)), radius + 5)
                pygame.draw.circle(self.screen, color, (int(x), int(y)), radius)
                pygame.draw.circle(self.screen, WHITE if note.judged and note.hit else color, (int(x), int(y)), max(2, radius // 2), 1)

    def _draw_chains(
        self,
        chains: tuple[RuntimeChain, ...],
        notes: list[GameNote],
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
    ) -> None:
        foot_chains = tuple(chain for chain in chains if chain.definition.kind == NoteKind.FOOT)
        foot_notes = [note for note in notes if note.kind == NoteKind.FOOT]
        super()._draw_chains(foot_chains, foot_notes, song_time, song_beat, chain_mode)

        if not notes:
            return
        for chain in chains:
            definition = chain.definition
            if definition.kind != NoteKind.HANDS:
                continue
            is_hold = definition.source == SustainSource.EXPLICIT_HOLD
            if not is_hold and chain_mode == ChainMode.OFF:
                continue
            if not timed_is_within_lookahead(definition.start_time, definition.start_beat, song_time, song_beat):
                continue
            if song_time > definition.end_time + _base.HIT_FLASH_SECONDS:
                continue

            head = timed_progress(definition.start_time, definition.start_beat, song_time, song_beat)
            tail = timed_progress(definition.end_time, definition.end_beat, song_time, song_beat)
            lo, hi = min(head, tail), max(head, tail)
            if hi <= 0.0:
                continue
            if chain.state == ChainState.BROKEN:
                color = _blend(DIM, BG, 0.25)
            elif chain.state == ChainState.ACTIVE:
                color = _blend(MAGENTA, WHITE, 0.25)
            else:
                color = _blend(BG, MAGENTA, 0.55)

            for lane in definition.lanes:
                p0 = self._hand_target_point(lane, lo)
                p1 = self._hand_target_point(lane, hi)
                pygame.draw.line(self.screen, _blend(BG, color, 0.45), p0, p1, 13)
                pygame.draw.line(self.screen, color, p0, p1, 5)

    def _draw_receptors(
        self,
        body: BodyState,
        notes: list[GameNote],
        song_time: float,
        hand_enabled: bool,
        foot_enabled: bool,
        strike_events: tuple[MotionEvent, ...],
    ) -> None:
        foot_notes = [note for note in notes if note.kind == NoteKind.FOOT]
        foot_events = tuple(event for event in strike_events if event.kind == NoteKind.FOOT)
        super()._draw_receptors(body, foot_notes, song_time, False, foot_enabled, foot_events)
        # Redraw hand sectors here so timing-entry pulses sit above notes/holds.
        self._draw_hand_playfield(body, song_time, 0.0, hand_enabled, strike_events)

    def _draw_body_markers(
        self,
        body: BodyState,
        show_labels: bool = False,
        hand_enabled: bool = True,
        foot_enabled: bool = True,
        show_lower_body_sources: bool = False,
    ) -> None:
        # Raw wrist markers belong to the old absolute-position model. The two
        # controller-space dots in the radial field are now the hand feedback.
        super()._draw_body_markers(
            body,
            show_labels=show_labels,
            hand_enabled=False,
            foot_enabled=foot_enabled,
            show_lower_body_sources=show_lower_body_sources,
        )
