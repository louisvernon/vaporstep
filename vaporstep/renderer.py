from __future__ import annotations

import math

import pygame

from . import renderer_base as _base
from .domain import (
    BodyState,
    ChainMode,
    ChainState,
    GameNote,
    HitQuality,
    NoteKind,
    RuntimeChain,
    SustainSource,
)
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

# A 300-degree projected shell leaves only a 60-degree opening at the bottom for
# the foot field. Lanes remain 1 left/out, 2 left/high, 3 right/high, 4 right/out.
# The two outer boundaries finish close to the foot-field outer rails at FOOT_HIT_Y.
_HAND_BOUNDARY_ANGLES = (-240.0, -165.0, -90.0, -15.0, 60.0)
_HAND_CENTER_ANGLES = tuple(
    (_HAND_BOUNDARY_ANGLES[i] + _HAND_BOUNDARY_ANGLES[i + 1]) * 0.5
    for i in range(4)
)
_HAND_NOTE_ARC_FRACTION = 0.62


class Renderer(_base.Renderer):
    """VaporStep renderer with a body-relative projected hand shell."""

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._suppress_legacy_hands = False

    # The inherited renderer owns the mature foot implementation. During its
    # foot-only passes, route disabled legacy hand geometry off-screen.
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
        # Wide enough that the lower fan boundaries naturally meet the foot
        # playfield near its receptor while still fitting on a 16:9 display.
        radius_x = viewport.width * 0.62
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

    def _hand_lane_arc(self, lane: int, progress: float, fraction: float = 1.0) -> list[tuple[int, int]]:
        start = _HAND_BOUNDARY_ANGLES[lane - 1]
        end = _HAND_BOUNDARY_ANGLES[lane]
        center = (start + end) * 0.5
        half = (end - start) * 0.5 * max(0.05, min(1.0, fraction))
        return self._hand_arc_points(center - half, center + half, progress, samples=14)

    def _hand_sector_polygon(self, lane: int) -> list[tuple[int, int]]:
        center, _, _ = self._hand_geometry()
        arc = self._hand_lane_arc(lane, 1.0, 1.0)
        return [(int(center[0]), int(center[1])), *arc]

    def _draw_hand_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        enabled: bool,
    ) -> None:
        center, _, _ = self._hand_geometry()
        occupied = body.hand_lanes if enabled else frozenset()
        disabled = _blend(DIM, BG, 0.58)

        fill_surface = pygame.Surface(self.size, pygame.SRCALPHA)
        for lane in range(1, 5):
            if enabled:
                pygame.draw.polygon(
                    fill_surface,
                    (*MAGENTA, 58 if lane in occupied else 8),
                    self._hand_sector_polygon(lane),
                )
        self.screen.blit(fill_surface, (0, 0))

        rail_color = GRID if enabled else disabled
        for boundary, angle in enumerate(_HAND_BOUNDARY_ANGLES):
            end = self._hand_point(angle, 1.0)
            active_boundary = enabled and (
                (boundary > 0 and boundary in occupied)
                or (boundary < 4 and boundary + 1 in occupied)
            )
            if active_boundary:
                color, width = MAGENTA, 3
            elif enabled and boundary in (0, 4):
                color, width = MAGENTA, 2
            else:
                color, width = rail_color, 1
            pygame.draw.line(self.screen, color, center, end, width)

        # Depth grid: more lines near the receptor, using the same nonlinear
        # projection as notes so speed/distance can be read at a glance.
        for step in range(1, 9):
            progress = step / 9.0
            arc = self._hand_arc_points(
                _HAND_BOUNDARY_ANGLES[0],
                _HAND_BOUNDARY_ANGLES[-1],
                progress,
                samples=64,
            )
            pygame.draw.lines(self.screen, rail_color, False, arc, 1)

        for lane in range(1, 5):
            active = enabled and lane in occupied
            receptor = self._hand_lane_arc(lane, 1.0, 1.0)
            pygame.draw.lines(
                self.screen,
                MAGENTA if active else (DIM if enabled else disabled),
                False,
                receptor,
                6 if active else 2,
            )

        if not enabled:
            off = self.small_font.render("NO HAND NOTES", True, _blend(DIM, BG, 0.30))
            self.screen.blit(off, off.get_rect(center=(int(center[0]), int(center[1] - 24))))

    def _draw_hand_note_arc(
        self,
        lane: int,
        progress: float,
        color,
        *,
        highlight: bool = False,
    ) -> None:
        p = max(0.0, min(1.0, progress))
        arc = self._hand_lane_arc(lane, p, _HAND_NOTE_ARC_FRACTION)
        thickness = max(5, int(5 + 12 * p))
        pygame.draw.lines(self.screen, BG, False, arc, thickness + 9)
        pygame.draw.lines(self.screen, color, False, arc, thickness)
        if highlight:
            pygame.draw.lines(self.screen, WHITE, False, arc, max(1, thickness // 5))

    def _draw_hand_hit_pop(self, lane: int, age: float, quality: HitQuality) -> None:
        phase = max(0.0, min(1.0, age / HIT_BRICK_POP_SECONDS))
        power = {HitQuality.HIT: 1.0, HitQuality.GREAT: 1.28, HitQuality.PERFECT: 1.60}[quality]
        fade = (1.0 - phase) ** 0.72
        hot = _blend(MAGENTA, WHITE, min(0.92, 0.40 + 0.24 * power))
        color = _blend(BG, hot, fade)
        fraction = min(0.88, _HAND_NOTE_ARC_FRACTION + 0.12 * math.sin(min(1.0, phase * 1.5) * math.pi))
        arc = self._hand_lane_arc(lane, 1.0, fraction)
        thickness = max(3, int((14 + 4 * power) * (0.72 + 0.28 * fade)))
        pygame.draw.lines(self.screen, BG, False, arc, thickness + 10)
        pygame.draw.lines(self.screen, color, False, arc, thickness)
        if fade > 0.15:
            pygame.draw.lines(self.screen, _blend(color, WHITE, 0.68 * fade), False, arc, 2)

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
                if note.hit and age > HIT_BRICK_POP_SECONDS:
                    continue
            elif dt < -_base.HIT_WINDOW_SECONDS:
                continue

            progress = self._note_progress(note, song_time, song_beat)
            if note.judged and note.hit:
                for lane in note.lanes:
                    self._draw_hand_hit_pop(
                        lane,
                        max(0.0, song_time - float(note.judged_at or song_time)),
                        note.judgement or HitQuality.HIT,
                    )
                continue

            if note.judged:
                color = RED
            else:
                beat_phase = song_beat - math.floor(song_beat)
                breathe = 0.5 + 0.5 * math.cos(beat_phase * math.tau)
                near = max(0.0, min(1.0, progress))
                intensity = (0.72 + 0.14 * near) + (0.28 - 0.14 * near) * breathe
                color = _blend(BG, MAGENTA, intensity)
                color = _blend(color, WHITE, 0.05 * breathe)

            for lane in note.lanes:
                self._draw_hand_note_arc(lane, progress, color)

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
                pygame.draw.line(self.screen, _blend(BG, color, 0.45), p0, p1, 16)
                pygame.draw.line(self.screen, color, p0, p1, 6)
                self._draw_hand_note_arc(lane, max(0.0, min(1.0, head)), color)

    def _draw_hand_receptor_feedback(
        self,
        body: BodyState,
        notes: list[GameNote],
        song_time: float,
        enabled: bool,
        strike_events: tuple[MotionEvent, ...],
    ) -> None:
        if not enabled:
            return

        occupied = body.hand_lanes
        for lane in range(1, 5):
            receptor = self._hand_lane_arc(lane, 1.0, 1.0)
            active = lane in occupied
            near = self._target_is_near(notes, song_time, NoteKind.HANDS, lane)
            judgement, age = self._judgement_for_lane(notes, song_time, NoteKind.HANDS, lane)

            if active:
                pygame.draw.lines(self.screen, MAGENTA, False, receptor, 6)
            if near:
                pygame.draw.lines(self.screen, _blend(MAGENTA, WHITE, 0.35), False, receptor, 3)

            matching = [
                event
                for event in strike_events
                if event.kind == NoteKind.HANDS
                and event.lane == lane
                and 0.0 <= song_time - event.song_time <= MOTION_EVENT_VISUAL_SECONDS
            ]
            if matching:
                latest = max(matching, key=lambda e: e.song_time)
                input_age = song_time - latest.song_time
                input_phase = 1.0 - min(1.0, input_age / MOTION_EVENT_VISUAL_SECONDS)
                pygame.draw.lines(
                    self.screen,
                    _blend(MAGENTA, WHITE, 0.85 * input_phase),
                    False,
                    receptor,
                    max(3, int(4 + 6 * input_phase)),
                )

            if judgement is None:
                continue
            phase = 1.0 - min(age / _base.HIT_FLASH_SECONDS, 1.0)
            if judgement == "perfect":
                jcolor, power = _blend(AMBER, WHITE, 0.35), 1.65
            elif judgement == "great":
                jcolor, power = _blend(MAGENTA, WHITE, 0.55), 1.30
            elif judgement == "hit":
                jcolor, power = GREEN, 1.0
            else:
                jcolor, power = RED, 0.0

            if judgement != "miss":
                # Echo a short curved pulse inward from the receptor, analogous
                # to the foot hit pulse travelling back up its perspective lane.
                head_p = max(0.12, 1.0 - (age / _base.HIT_FLASH_SECONDS) * 0.88)
                trail = self._hand_lane_arc(lane, head_p, 0.44)
                pygame.draw.lines(
                    self.screen,
                    _blend(MAGENTA, WHITE, min(0.95, 0.50 + 0.20 * power)),
                    False,
                    trail,
                    max(4, int(5 * power * phase + 2)),
                )
            else:
                pygame.draw.lines(self.screen, RED, False, receptor, max(2, int(5 * phase)))

            word = self.hit_font.render(judgement.upper(), True, jcolor)
            tx, ty = self._hand_target_point(lane, 0.90)
            self.screen.blit(word, word.get_rect(center=(int(tx), int(ty))))

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
        self._draw_hand_receptor_feedback(body, notes, song_time, hand_enabled, strike_events)

    def _spawn_note_effects(self, notes: list[GameNote]) -> None:
        # Use the mature effect generator for both feet and hands. Drawing below
        # projects hand effects radially while feet keep their existing geometry.
        super()._spawn_note_effects(notes)

    def _draw_hand_effects(self, song_time: float, kind_key: str) -> None:
        # This helper is implemented by _draw_particles via list partitioning;
        # the name exists only to make that split explicit in the renderer.
        return None

    def _draw_particles(self, song_time: float) -> None:
        # Let the base renderer update/draw foot effects unchanged, then draw the
        # same generated hand effect objects through radial geometry.
        all_bursts = self._impact_bursts
        all_particles = self._particles
        all_outbound = self._outbound_particles
        all_misses = self._miss_impacts

        hand_bursts = [x for x in all_bursts if x["kind"] == NoteKind.HANDS]
        hand_particles = [x for x in all_particles if x["kind"] == NoteKind.HANDS]
        hand_outbound = [x for x in all_outbound if x["kind"] == NoteKind.HANDS]
        hand_misses = [x for x in all_misses if x["kind"] == NoteKind.HANDS]

        self._impact_bursts = [x for x in all_bursts if x["kind"] != NoteKind.HANDS]
        self._particles = [x for x in all_particles if x["kind"] != NoteKind.HANDS]
        self._outbound_particles = [x for x in all_outbound if x["kind"] != NoteKind.HANDS]
        self._miss_impacts = [x for x in all_misses if x["kind"] != NoteKind.HANDS]
        super()._draw_particles(song_time)
        foot_bursts = self._impact_bursts
        foot_particles = self._particles
        foot_outbound = self._outbound_particles
        foot_misses = self._miss_impacts

        burst_alive = []
        for burst in hand_bursts:
            age = song_time - float(burst["born"])
            life = float(burst["life"])
            if age < 0.0 or age > life:
                continue
            phase = age / max(life, 1e-6)
            lane = int(burst["lane"])
            cx, cy = self._hand_target_point(lane, 1.0)
            power = float(burst["power"])
            fade = (1.0 - phase) ** 1.4
            color = _blend(BG, burst["color"], fade)
            radius = int((18 + 48 * phase) * power)
            pygame.draw.circle(self.screen, _blend(BG, color, 0.25 * fade), (int(cx), int(cy)), radius)
            pygame.draw.circle(self.screen, color, (int(cx), int(cy)), radius, max(1, int(5 * fade)))
            burst_alive.append(burst)

        particle_alive = []
        for p in hand_particles:
            age = song_time - float(p["born"])
            life = float(p["life"])
            if age < 0.0 or age > life:
                continue
            lane = int(p["lane"])
            phase = age / max(life, 1e-6)
            progress = max(0.03, 1.0 - age * float(p["speed"]))
            angle_span = _HAND_BOUNDARY_ANGLES[lane] - _HAND_BOUNDARY_ANGLES[lane - 1]
            angle = _HAND_CENTER_ANGLES[lane - 1] + (float(p["jitter"]) + float(p.get("lateral", 0.0)) * phase * 0.45) * angle_span
            x, y = self._hand_point(angle, progress)
            fade = 1.0 - phase
            color = _blend(BG, p["color"], fade)
            center, _, _ = self._hand_geometry()
            dx, dy = x - center[0], y - center[1]
            mag = max(1.0, math.hypot(dx, dy))
            tx, ty = -dy / mag, dx / mag
            length = float(p["length"]) * 70.0 * (0.4 + 0.6 * fade)
            pygame.draw.line(
                self.screen,
                color,
                (int(x - tx * length), int(y - ty * length)),
                (int(x + tx * length), int(y + ty * length)),
                max(1, int(p["size"])),
            )
            particle_alive.append(p)

        outward_alive = []
        for p in hand_outbound:
            age = song_time - float(p["born"])
            life = float(p["life"])
            if age < 0.0 or age > life:
                continue
            lane = int(p["lane"])
            phase = age / max(life, 1e-6)
            start = self._hand_target_point(lane, 1.0)
            center, _, _ = self._hand_geometry()
            dx, dy = start[0] - center[0], start[1] - center[1]
            mag = max(1.0, math.hypot(dx, dy))
            ux, uy = dx / mag, dy / mag
            tangent_x, tangent_y = -uy, ux
            radial = float(p["vy"]) * age
            lateral = float(p["vx"]) * age * 0.45
            x = start[0] + ux * radial + tangent_x * lateral
            y = start[1] + uy * radial + tangent_y * lateral
            fade = (1.0 - phase) ** 1.25
            color = _blend(BG, p["color"], fade)
            length = float(p["length"]) * (0.55 + 0.45 * fade)
            pygame.draw.line(
                self.screen,
                color,
                (int(x - ux * length * 0.5), int(y - uy * length * 0.5)),
                (int(x + ux * length * 0.5), int(y + uy * length * 0.5)),
                max(1, int(p["size"])),
            )
            outward_alive.append(p)

        miss_alive = []
        for impact in hand_misses:
            age = song_time - float(impact["born"])
            life = float(impact["life"])
            if age < 0.0 or age > life:
                continue
            phase = age / max(life, 1e-6)
            pulse = math.sin(math.pi * min(1.0, phase)) * (1.0 - 0.32 * phase)
            lane = int(impact["lane"])
            arc = self._hand_lane_arc(lane, 1.0, 1.0)
            pygame.draw.lines(
                self.screen,
                _blend(BG, RED, 0.48 + 0.42 * pulse),
                False,
                arc,
                max(2, int(7 * pulse)),
            )
            miss_alive.append(impact)

        self._impact_bursts = [*foot_bursts, *burst_alive]
        self._particles = [*foot_particles, *particle_alive]
        self._outbound_particles = [*foot_outbound, *outward_alive]
        self._miss_impacts = [*foot_misses, *miss_alive]

    def _draw_body_markers(
        self,
        body: BodyState,
        show_labels: bool = False,
        hand_enabled: bool = True,
        foot_enabled: bool = True,
        show_lower_body_sources: bool = False,
    ) -> None:
        # Hand-position dots remain intentionally tabled. Segment highlighting
        # is the sole hand-position cue during gameplay for now.
        super()._draw_body_markers(
            body,
            show_labels=show_labels,
            hand_enabled=False,
            foot_enabled=foot_enabled,
            show_lower_body_sources=show_lower_body_sources,
        )
