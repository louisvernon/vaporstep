from __future__ import annotations

import math

import pygame

from . import renderer_base as _base
from .domain import BodyState, ChainMode, ChainState, GameNote, NoteKind, RuntimeChain, SustainSource
from .motion import MOTION_EVENT_VISUAL_SECONDS, MotionEvent
from .scroll import note_is_within_lookahead, timed_is_within_lookahead, timed_progress

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

# Four contiguous projected hand segments. The shared boundaries guarantee no
# dead visual space between authored hand lanes 1..4.
_HAND_BOUNDARY_ANGLES = (-168.0, -129.0, -90.0, -51.0, -12.0)
_HAND_CENTER_ANGLES = tuple(
    (_HAND_BOUNDARY_ANGLES[i] + _HAND_BOUNDARY_ANGLES[i + 1]) * 0.5
    for i in range(4)
)


class Renderer(_base.Renderer):
    """VaporStep renderer with a body-relative projected hand fan."""

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._suppress_legacy_hands = False

    # The inherited renderer owns the mature foot implementation. During its
    # foot-only passes, route the disabled legacy hand coordinates off-screen so
    # the projected fan is the only visible hand playfield.
    def _field_bounds(self, kind: NoteKind, progress: float) -> tuple[float, float]:
        if self._suppress_legacy_hands and kind == NoteKind.HANDS:
            return (-2000.0, -1999.0)
        return super()._field_bounds(kind, progress)

    def _field_y(self, kind: NoteKind, progress: float) -> float:
        if self._suppress_legacy_hands and kind == NoteKind.HANDS:
            return -2000.0
        return super()._field_y(kind, progress)

    def _lane_boundary_x(self, kind: NoteKind, boundary: int, progress: float) -> float:
        if self._suppress_legacy_hands and kind == NoteKind.HANDS:
            return -2000.0 + boundary * 0.1
        return super()._lane_boundary_x(kind, boundary, progress)

    def _hand_geometry(self) -> tuple[tuple[float, float], float, float]:
        viewport = self._camera_rect()
        center = (float(viewport.centerx), float(self._camera_y(_base.VANISH_Y)))
        # Span almost the full camera-width projection and most of the upper
        # half of the screen, while leaving the shared center open for feet.
        radius_x = viewport.width * 0.49
        radius_y = viewport.height * 0.46
        return center, radius_x, radius_y

    def _hand_point(self, angle_deg: float, progress: float) -> tuple[float, float]:
        center, radius_x, radius_y = self._hand_geometry()
        p = max(0.0, min(1.0, progress)) ** 1.25
        angle = math.radians(angle_deg)
        return (
            center[0] + math.cos(angle) * radius_x * p,
            center[1] + math.sin(angle) * radius_y * p,
        )

    def _hand_target_point(self, lane: int, progress: float) -> tuple[float, float]:
        return self._hand_point(_HAND_CENTER_ANGLES[lane - 1], progress)

    def _hand_arc_points(
        self,
        start_angle: float,
        end_angle: float,
        progress: float,
        *,
        samples: int = 12,
    ) -> list[tuple[int, int]]:
        return [
            tuple(
                int(v)
                for v in self._hand_point(
                    start_angle + (end_angle - start_angle) * i / samples,
                    progress,
                )
            )
            for i in range(samples + 1)
        ]

    def _hand_sector_polygon(self, lane: int) -> list[tuple[int, int]]:
        center, _, _ = self._hand_geometry()
        arc = self._hand_arc_points(
            _HAND_BOUNDARY_ANGLES[lane - 1],
            _HAND_BOUNDARY_ANGLES[lane],
            1.0,
        )
        return [(int(center[0]), int(center[1])), *arc]

    def _draw_hand_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        enabled: bool,
        strike_events: tuple[MotionEvent, ...] = (),
    ) -> None:
        center, _, _ = self._hand_geometry()
        occupied = body.hand_lanes if enabled else frozenset()
        disabled = _blend(DIM, BG, 0.58)

        # Whole-segment occupancy is the primary hand-position feedback.
        for lane in range(1, 5):
            active = lane in occupied
            polygon = self._hand_sector_polygon(lane)
            if enabled:
                fill_strength = 0.25 if active else 0.035
                pygame.draw.polygon(self.screen, (*MAGENTA, int(255 * fill_strength)), polygon)
                if active:
                    overlay = pygame.Surface(self.size, pygame.SRCALPHA)
                    pygame.draw.polygon(overlay, (*MAGENTA, 52), polygon)
                    self.screen.blit(overlay, (0, 0))

        # Perspective rails: five shared boundaries from the same vanishing
        # point, exactly like the foot field conceptually but projected radially.
        rail_color = GRID if enabled else disabled
        for boundary, angle in enumerate(_HAND_BOUNDARY_ANGLES):
            end = self._hand_point(angle, 1.0)
            color = MAGENTA if enabled and boundary in (0, 4) else rail_color
            width = 2 if enabled and boundary in (0, 4) else 1
            pygame.draw.line(self.screen, color, center, end, width)

        # Concentric progress lines give the same distance/depth cues as the
        # horizontal grid lines on the foot track.
        for step in range(1, 8):
            progress = step / 8.0
            arc = self._hand_arc_points(
                _HAND_BOUNDARY_ANGLES[0],
                _HAND_BOUNDARY_ANGLES[-1],
                progress,
                samples=36,
            )
            pygame.draw.lines(self.screen, rail_color, False, arc, 1)

        # Outer receptor arc is segmented but contiguous; active lanes brighten
        # their entire receptor boundary rather than requiring a tracking dot.
        for lane in range(1, 5):
            active = enabled and lane in occupied
            receptor = self._hand_arc_points(
                _HAND_BOUNDARY_ANGLES[lane - 1],
                _HAND_BOUNDARY_ANGLES[lane],
                1.0,
                samples=14,
            )
            color = MAGENTA if active else (DIM if enabled else disabled)
            pygame.draw.lines(self.screen, color, False, receptor, 5 if active else 2)

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
                flash = _blend(MAGENTA, WHITE, 0.78 * phase)
                pygame.draw.lines(
                    self.screen,
                    flash,
                    False,
                    receptor,
                    max(2, int(3 + 5 * phase)),
                )

        if enabled:
            label = self.small_font.render("HANDS", True, MAGENTA)
            self.screen.blit(label, label.get_rect(center=(int(center[0]), int(center[1] - 24))))
        else:
            off = self.small_font.render("NO HAND NOTES", True, _blend(DIM, BG, 0.30))
            self.screen.blit(off, off.get_rect(center=(int(center[0]), int(center[1] - 24))))

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
        self._suppress_legacy_hands = True
        try:
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
        finally:
            self._suppress_legacy_hands = False
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

            # Notes stay compact and centered within the much larger segments.
            for lane in note.lanes:
                x, y = self._hand_target_point(lane, progress)
                radius = max(6, int(8 + 5 * max(0.0, min(1.0, progress))))
                pygame.draw.circle(self.screen, BG, (int(x), int(y)), radius + 6)
                pygame.draw.circle(self.screen, color, (int(x), int(y)), radius)
                pygame.draw.circle(
                    self.screen,
                    WHITE if note.judged and note.hit else color,
                    (int(x), int(y)),
                    max(2, radius // 2),
                    1,
                )

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
                pygame.draw.line(self.screen, _blend(BG, color, 0.45), p0, p1, 15)
                pygame.draw.line(self.screen, color, p0, p1, 6)

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
        self._suppress_legacy_hands = True
        try:
            super()._draw_receptors(body, foot_notes, song_time, False, foot_enabled, foot_events)
        finally:
            self._suppress_legacy_hands = False
        # Redraw only the fan edges/occupancy after notes so entry/strike flashes
        # sit above the moving targets. No wrist-position dots are shown.
        self._draw_hand_playfield(body, song_time, 0.0, hand_enabled, strike_events)

    def _spawn_note_effects(self, notes: list[GameNote]) -> None:
        # Keep the mature particle system for feet while the hand presentation
        # settles; the fan provides direct receptor feedback for hand timing.
        super()._spawn_note_effects([note for note in notes if note.kind == NoteKind.FOOT])

    def _draw_body_markers(
        self,
        body: BodyState,
        show_labels: bool = False,
        hand_enabled: bool = True,
        foot_enabled: bool = True,
        show_lower_body_sources: bool = False,
    ) -> None:
        # Hand positioning feedback is intentionally tabled for now. Whole
        # segment highlighting is the only hand-state cue during gameplay.
        super()._draw_body_markers(
            body,
            show_labels=show_labels,
            hand_enabled=False,
            foot_enabled=foot_enabled,
            show_lower_body_sources=show_lower_body_sources,
        )
