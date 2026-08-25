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

_HAND_BOUNDARIES = (0.0, 0.25, 0.50, 0.75, 1.0)
_HAND_CENTERS = (0.125, 0.375, 0.625, 0.875)
_HAND_NOTE_ARC_FRACTION = 0.62
_HAND_FOOT_GAP_PX = 7.0


class Renderer(_base.Renderer):
    """VaporStep renderer with a body-relative projected hand tunnel."""

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self._suppress_legacy_hands = False

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

    @staticmethod
    def _offset_rail(
        inner: tuple[float, float],
        outer: tuple[float, float],
        *,
        side: str,
        gap: float,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        dx = outer[0] - inner[0]
        dy = outer[1] - inner[1]
        length = max(1.0, math.hypot(dx, dy))
        if side == "left":
            nx, ny = -dy / length, dx / length
        else:
            nx, ny = dy / length, -dx / length
        return (
            (inner[0] + nx * gap, inner[1] + ny * gap),
            (outer[0] + nx * gap, outer[1] + ny * gap),
        )

    def _hand_arc_geometry(self):
        viewport = self._camera_rect()
        foot_y0 = self._field_y(NoteKind.FOOT, 0.0)
        foot_y1 = self._field_y(NoteKind.FOOT, 1.0)
        foot_left0 = self._lane_boundary_x(NoteKind.FOOT, 0, 0.0)
        foot_left1 = self._lane_boundary_x(NoteKind.FOOT, 0, 1.0)
        foot_right0 = self._lane_boundary_x(NoteKind.FOOT, 4, 0.0)
        foot_right1 = self._lane_boundary_x(NoteKind.FOOT, 4, 1.0)

        inner_left, outer_left = self._offset_rail(
            (foot_left0, foot_y0),
            (foot_left1, foot_y1),
            side="left",
            gap=_HAND_FOOT_GAP_PX,
        )
        inner_right, outer_right = self._offset_rail(
            (foot_right0, foot_y0),
            (foot_right1, foot_y1),
            side="right",
            gap=_HAND_FOOT_GAP_PX,
        )

        inner_cx = (inner_left[0] + inner_right[0]) * 0.5
        inner_base_y = (inner_left[1] + inner_right[1]) * 0.5
        inner_rx = max(8.0, (inner_right[0] - inner_left[0]) * 0.5)
        inner_ry = viewport.height * 0.105

        outer_cx = (outer_left[0] + outer_right[0]) * 0.5
        outer_base_y = (outer_left[1] + outer_right[1]) * 0.5
        outer_rx = max(inner_rx + 20.0, (outer_right[0] - outer_left[0]) * 0.5)
        outer_top = viewport.top + max(8.0, viewport.height * 0.018)
        outer_ry = max(inner_ry + 20.0, outer_base_y - outer_top)

        return (
            (inner_cx, inner_base_y, inner_rx, inner_ry),
            (outer_cx, outer_base_y, outer_rx, outer_ry),
        )

    @staticmethod
    def _ellipse_upper_point(
        geometry: tuple[float, float, float, float],
        along: float,
    ) -> tuple[float, float]:
        cx, base_y, rx, ry = geometry
        t = max(0.0, min(1.0, along))
        angle = math.pi + math.pi * t
        return cx + rx * math.cos(angle), base_y + ry * math.sin(angle)

    def _hand_point(self, along: float, progress: float) -> tuple[float, float]:
        inner, outer = self._hand_arc_geometry()
        p = max(0.0, min(1.0, progress)) ** 1.25
        ix, iy = self._ellipse_upper_point(inner, along)
        ox, oy = self._ellipse_upper_point(outer, along)
        return ix + (ox - ix) * p, iy + (oy - iy) * p

    def _hand_target_point(self, lane: int, progress: float) -> tuple[float, float]:
        return self._hand_point(_HAND_CENTERS[lane - 1], progress)

    def _hand_arc_points(
        self,
        start: float,
        end: float,
        progress: float,
        *,
        samples: int = 12,
    ) -> list[tuple[int, int]]:
        return [
            tuple(
                int(v)
                for v in self._hand_point(
                    start + (end - start) * i / samples,
                    progress,
                )
            )
            for i in range(samples + 1)
        ]

    def _hand_lane_arc(
        self,
        lane: int,
        progress: float,
        fraction: float = 1.0,
    ) -> list[tuple[int, int]]:
        start = _HAND_BOUNDARIES[lane - 1]
        end = _HAND_BOUNDARIES[lane]
        center = (start + end) * 0.5
        half = (end - start) * 0.5 * max(0.05, min(1.0, fraction))
        return self._hand_arc_points(center - half, center + half, progress, samples=14)

    def _hand_sector_polygon(self, lane: int) -> list[tuple[int, int]]:
        start = _HAND_BOUNDARIES[lane - 1]
        end = _HAND_BOUNDARIES[lane]
        outer = self._hand_arc_points(start, end, 1.0, samples=18)
        inner = self._hand_arc_points(end, start, 0.0, samples=18)
        return [*outer, *inner]

    def _hand_lane_direction(self, lane: int) -> tuple[float, float]:
        inner = self._hand_target_point(lane, 0.0)
        outer = self._hand_target_point(lane, 1.0)
        dx, dy = outer[0] - inner[0], outer[1] - inner[1]
        length = max(1.0, math.hypot(dx, dy))
        return dx / length, dy / length

    def _draw_hand_playfield(
        self,
        body: BodyState,
        song_time: float,
        beat_pulse: float,
        enabled: bool,
    ) -> None:
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
        for boundary, along in enumerate(_HAND_BOUNDARIES):
            p0 = self._hand_point(along, 0.0)
            p1 = self._hand_point(along, 1.0)
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
            pygame.draw.line(self.screen, color, p0, p1, width)

        inner_arc = self._hand_arc_points(0.0, 1.0, 0.0, samples=64)
        pygame.draw.lines(self.screen, _blend(rail_color, WHITE, 0.10), False, inner_arc, 2)

        for step in range(1, 9):
            progress = step / 9.0
            arc = self._hand_arc_points(0.0, 1.0, progress, samples=64)
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
            cx, cy = self._hand_point(0.5, 0.0)
            off = self.small_font.render("NO HAND NOTES", True, _blend(DIM, BG, 0.30))
            self.screen.blit(off, off.get_rect(center=(int(cx), int(cy - 20))))

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
        fraction = min(
            0.88,
            _HAND_NOTE_ARC_FRACTION
            + 0.12 * math.sin(min(1.0, phase * 1.5) * math.pi),
        )
        arc = self._hand_lane_arc(lane, 1.0, fraction)
        thickness = max(3, int((14 + 4 * power) * (0.72 + 0.28 * fade)))
        pygame.draw.lines(self.screen, BG, False, arc, thickness + 10)
        pygame.draw.lines(self.screen, color, False, arc, thickness)
        if fade > 0.15:
            pygame.draw.lines(
                self.screen,
                _blend(color, WHITE, 0.68 * fade),
                False,
                arc,
                2,
            )

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
        foot_chains = tuple(
            chain for chain in chains if chain.definition.kind == NoteKind.FOOT
        )
        foot_notes = [note for note in notes if note.kind == NoteKind.FOOT]
        super()._draw_chains(
            foot_chains,
            foot_notes,
            song_time,
            song_beat,
            chain_mode,
        )

        if not notes:
            return
        for chain in chains:
            definition = chain.definition
            if definition.kind != NoteKind.HANDS:
                continue
            is_hold = definition.source == SustainSource.EXPLICIT_HOLD
            if not is_hold and chain_mode == ChainMode.OFF:
                continue
            if not timed_is_within_lookahead(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            ):
                continue
            if song_time > definition.end_time + _base.HIT_FLASH_SECONDS:
                continue

            head = timed_progress(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            )
            tail = timed_progress(
                definition.end_time,
                definition.end_beat,
                song_time,
                song_beat,
            )
            lo, hi = min(head, tail), max(head, tail)
            if hi <= 0.0:
                continue
            if chain.state == ChainState.BROKEN:
                color = _blend(DIM, BG, 0.25)
                halo = _blend(BG, color, 0.45)
                width = 6
            elif chain.state == ChainState.ACTIVE:
                color = _blend(MAGENTA, WHITE, 0.25)
                halo = _blend(BG, color, 0.72)
                width = 8
            else:
                # Pending hand holds should read with the same visual priority as
                # ordinary hand targets. The older muted sustain treatment made
                # authored holds look like background geometry.
                color = _blend(BG, MAGENTA, 0.86)
                halo = _blend(BG, MAGENTA, 0.62)
                width = 7

            for lane in definition.lanes:
                p0 = self._hand_target_point(lane, lo)
                p1 = self._hand_target_point(lane, hi)
                pygame.draw.line(self.screen, halo, p0, p1, 17)
                pygame.draw.line(self.screen, color, p0, p1, width)
                self._draw_hand_note_arc(
                    lane,
                    max(0.0, min(1.0, head)),
                    DIM if chain.state == ChainState.BROKEN else MAGENTA,
                    highlight=chain.state == ChainState.ACTIVE,
                )

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
            judgement, age = self._judgement_for_lane(
                notes,
                song_time,
                NoteKind.HANDS,
                lane,
            )

            if active:
                pygame.draw.lines(self.screen, MAGENTA, False, receptor, 6)
            if near:
                pygame.draw.lines(
                    self.screen,
                    _blend(MAGENTA, WHITE, 0.35),
                    False,
                    receptor,
                    3,
                )

            matching = [
                event
                for event in strike_events
                if event.kind == NoteKind.HANDS
                and event.lane == lane
                and 0.0
                <= song_time - event.song_time
                <= MOTION_EVENT_VISUAL_SECONDS
            ]
            if matching:
                latest = max(matching, key=lambda e: e.song_time)
                input_age = song_time - latest.song_time
                input_phase = 1.0 - min(
                    1.0,
                    input_age / MOTION_EVENT_VISUAL_SECONDS,
                )
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
                head_p = max(
                    0.08,
                    1.0 - (age / _base.HIT_FLASH_SECONDS) * 0.90,
                )
                trail = self._hand_lane_arc(lane, head_p, 0.44)
                pygame.draw.lines(
                    self.screen,
                    _blend(
                        MAGENTA,
                        WHITE,
                        min(0.95, 0.50 + 0.20 * power),
                    ),
                    False,
                    trail,
                    max(4, int(5 * power * phase + 2)),
                )
            else:
                pygame.draw.lines(
                    self.screen,
                    RED,
                    False,
                    receptor,
                    max(2, int(5 * phase)),
                )

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
        foot_events = tuple(
            event for event in strike_events if event.kind == NoteKind.FOOT
        )
        self._suppress_legacy_hands = True
        try:
            super()._draw_receptors(
                body,
                foot_notes,
                song_time,
                False,
                foot_enabled,
                foot_events,
            )
        finally:
            self._suppress_legacy_hands = False
        self._draw_hand_receptor_feedback(
            body,
            notes,
            song_time,
            hand_enabled,
            strike_events,
        )

    def _spawn_note_effects(self, notes: list[GameNote]) -> None:
        super()._spawn_note_effects(notes)

    def _draw_particles(self, song_time: float) -> None:
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
        self._outbound_particles = [
            x for x in all_outbound if x["kind"] != NoteKind.HANDS
        ]
        self._miss_impacts = [x for x in all_misses if x["kind"] != NoteKind.HANDS]
        super()._draw_particles(song_time)
        foot_bursts = self._impact_bursts
        foot_particles = self._particles
        foot_outbound = self._outbound_particles
        foot_misses = self._miss_impacts

        self._impact_bursts = hand_bursts
        self._particles = hand_particles
        self._outbound_particles = hand_outbound
        self._miss_impacts = hand_misses
        self._draw_hand_particles(song_time)

        self._impact_bursts.extend(foot_bursts)
        self._particles.extend(foot_particles)
        self._outbound_particles.extend(foot_outbound)
        self._miss_impacts.extend(foot_misses)

    def _draw_hand_particles(self, song_time: float) -> None:
        burst_alive: list[dict[str, object]] = []
        for burst in self._impact_bursts:
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
            radius = int(12 + 30 * phase * power)
            diamond = [
                (int(cx), int(cy - radius)),
                (int(cx + radius), int(cy)),
                (int(cx), int(cy + radius)),
                (int(cx - radius), int(cy)),
            ]
            pygame.draw.polygon(self.screen, _blend(BG, color, 0.24 * fade), diamond, 0)
            pygame.draw.polygon(self.screen, _blend(BG, color, 0.70), diamond, max(1, int(5 * fade)))
            burst_alive.append(burst)
        self._impact_bursts = burst_alive

        alive: list[dict[str, object]] = []
        for particle in self._particles:
            age = song_time - float(particle["born"])
            life = float(particle["life"])
            if age < 0.0 or age > life:
                continue
            progress = max(0.03, 1.0 - age * float(particle["speed"]))
            lane = int(particle["lane"])
            cx, cy = self._hand_target_point(lane, progress)
            tangent_a = self._hand_target_point(lane, max(0.0, progress - 0.02))
            tangent_b = self._hand_target_point(lane, min(1.0, progress + 0.02))
            tx = tangent_b[0] - tangent_a[0]
            ty = tangent_b[1] - tangent_a[1]
            length = max(1.0, math.hypot(tx, ty))
            nx, ny = -ty / length, tx / length
            fade = 1.0 - age / life
            lateral = float(particle.get("lateral", 0.0)) * 28.0 * (age / life) ** 0.72
            jitter = float(particle["jitter"]) * 14.0
            x = cx + nx * (lateral + jitter)
            y = cy + ny * (lateral + jitter)
            color = _blend(BG, particle["color"], fade)
            size = max(1, int(int(particle["size"]) * (0.65 + fade)))
            pygame.draw.circle(self.screen, color, (int(x), int(y)), size)
            alive.append(particle)
        self._particles = alive

        outward_alive: list[dict[str, object]] = []
        for particle in self._outbound_particles:
            age = song_time - float(particle["born"])
            life = float(particle["life"])
            if age < 0.0 or age > life:
                continue
            lane = int(particle["lane"])
            cx, cy = self._hand_target_point(lane, 1.0)
            dx, dy = self._hand_lane_direction(lane)
            phase = age / max(life, 1e-6)
            fade = (1.0 - phase) ** 1.25
            x = cx + dx * float(particle["vy"]) * age + float(particle["vx"]) * age * 0.4
            y = cy + dy * float(particle["vy"]) * age
            color = _blend(BG, particle["color"], fade)
            pygame.draw.circle(self.screen, color, (int(x), int(y)), max(1, int(particle["size"])))
            outward_alive.append(particle)
        self._outbound_particles = outward_alive

        miss_alive: list[dict[str, object]] = []
        for impact in self._miss_impacts:
            age = song_time - float(impact["born"])
            life = float(impact["life"])
            if age < 0.0 or age > life:
                continue
            lane = int(impact["lane"])
            phase = age / max(life, 1e-6)
            pulse = math.sin(math.pi * min(1.0, phase)) * (1.0 - 0.32 * phase)
            arc = self._hand_lane_arc(lane, 1.0, 1.0)
            pygame.draw.lines(self.screen, _blend(BG, RED, 0.18 + 0.42 * pulse), False, arc, max(2, int(7 * pulse)))
            miss_alive.append(impact)
        self._miss_impacts = miss_alive
