from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import time

import pygame

from .domain import GameNote, NoteKind
from . import playfield_geometry as geo


WIDTH = 1280
HEIGHT = 720
TARGET_FPS = 60
BPM = 120.0
BEAT_SECONDS = 60.0 / BPM
SPAWN_LEAD = 2.0
SPLIT_LEAD = BEAT_SECONDS
HIT_WINDOW = 0.18
TOUCH_RADIUS = 78.0
CORE_RADIUS = 72.0
HOLD_RADIUS = 94.0
LOOP_SECONDS = 13.0

BG = (2, 2, 8)
CYAN = (70, 245, 255)
MAGENTA = (255, 55, 210)
PURPLE = (178, 108, 255)
WHITE = (235, 245, 255)
DIM = (70, 88, 115)
GRID = (25, 64, 88)
GREEN = (95, 255, 175)
RED = (255, 75, 110)


def _blend(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    t = geo.clamp(amount)
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _pair_color(index: int) -> tuple[int, int, int]:
    return MAGENTA if index % 2 == 0 else PURPLE


def _quadratic_points(
    start: tuple[float, float],
    end: tuple[float, float],
    control: tuple[float, float],
    *,
    samples: int = 28,
) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for i in range(samples + 1):
        t = i / samples
        u = 1.0 - t
        x = u * u * start[0] + 2.0 * u * t * control[0] + t * t * end[0]
        y = u * u * start[1] + 2.0 * u * t * control[1] + t * t * end[1]
        points.append((round(x), round(y)))
    return points


def _electric_points(
    points: list[tuple[int, int]],
    *,
    amplitude: float,
    phase: float,
) -> list[tuple[int, int]]:
    if len(points) < 3 or amplitude <= 0.0:
        return points
    result: list[tuple[int, int]] = []
    for index, point in enumerate(points):
        if index in (0, len(points) - 1):
            result.append(point)
            continue
        before = points[index - 1]
        after = points[index + 1]
        dx = after[0] - before[0]
        dy = after[1] - before[1]
        length = max(1.0, math.hypot(dx, dy))
        nx, ny = -dy / length, dx / length
        wave = math.sin(index * 2.7 + phase) + 0.55 * math.sin(index * 5.1 - phase * 1.7)
        offset = amplitude * wave / 1.55
        result.append((round(point[0] + nx * offset), round(point[1] + ny * offset)))
    return result


def _demo_notes() -> list[GameNote]:
    # Same vocabulary emitted by ordinary dance-single conversion:
    # one source head -> FOOT; two simultaneous heads -> HANDS.
    return [
        GameNote(1.5, (1,), NoteKind.FOOT),
        GameNote(2.0, (2,), NoteKind.FOOT),
        GameNote(2.5, (1, 4), NoteKind.HANDS),
        GameNote(3.5, (3,), NoteKind.FOOT),
        GameNote(4.0, (2,), NoteKind.FOOT, end_time=5.0),
        GameNote(5.5, (2, 3), NoteKind.HANDS),
        GameNote(6.5, (1, 4), NoteKind.HANDS, end_time=8.0),
        GameNote(8.75, (4,), NoteKind.FOOT),
        GameNote(9.25, (1, 2), NoteKind.HANDS),
        GameNote(10.25, (3, 4), NoteKind.HANDS),
    ]


@dataclass
class RuntimeNote:
    note: GameNote
    color: tuple[int, int, int]
    state: str = "pending"  # pending, captured, holding, complete, missed, dropped
    pointer_ids: tuple[int, ...] = ()
    state_at: float = 0.0
    outside_since: float | None = None


@dataclass
class VaporTapPlaytest:
    screen: pygame.Surface
    font: pygame.font.Font = field(init=False)
    small_font: pygame.font.Font = field(init=False)
    big_font: pygame.font.Font = field(init=False)
    cycle_started: float = field(default_factory=time.monotonic)
    notes: list[RuntimeNote] = field(default_factory=list)
    pointers: dict[int, tuple[float, float]] = field(default_factory=dict)
    last_touch_at: float = -999.0
    impact_started_at: float = -999.0
    impact_strength: float = 0.0

    def __post_init__(self) -> None:
        self.font = pygame.font.Font(None, 31)
        self.small_font = pygame.font.Font(None, 23)
        self.big_font = pygame.font.Font(None, 48)
        self.reset()

    @property
    def size(self) -> tuple[int, int]:
        return self.screen.get_size()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.cycle_started

    def reset(self) -> None:
        self.cycle_started = time.monotonic() + 0.7
        self.pointers.clear()
        self.impact_strength = 0.0
        hand_index = 0
        self.notes = []
        for note in _demo_notes():
            if note.kind == NoteKind.HANDS:
                color = _pair_color(hand_index)
                hand_index += 1
            else:
                color = CYAN
            self.notes.append(RuntimeNote(note=note, color=color))

    def _trigger_impact(self, strength: float) -> None:
        self.impact_started_at = time.monotonic()
        self.impact_strength = max(self.impact_strength, float(strength))

    def _shake_offset(self) -> tuple[int, int]:
        age = time.monotonic() - self.impact_started_at
        duration = 0.105
        if age < 0.0 or age >= duration or self.impact_strength <= 0.0:
            if age >= duration:
                self.impact_strength = 0.0
            return 0, 0
        decay = (1.0 - age / duration) ** 1.65
        amplitude = self.impact_strength * decay
        # Mostly vertical "cabinet thump", with a smaller horizontal kick.
        x = amplitude * 0.40 * math.sin(age * 215.0 + 0.7)
        y = amplitude * math.sin(age * 178.0)
        return round(x), round(y)

    def _foot_endpoint(self, lane: int) -> tuple[float, float]:
        return geo.lane_center(self.size, NoteKind.FOOT, lane, 1.0)

    def _hand_endpoint(self, lane: int) -> tuple[float, float]:
        return geo.hand_target_point(self.size, lane, 1.0)

    def _hand_core_position(self, item: RuntimeNote) -> tuple[float, float]:
        viewport = geo.camera_rect(self.size)
        source = (viewport.centerx, geo.field_y(self.size, NoteKind.FOOT, 0.0))
        target = (viewport.centerx, geo.field_y(self.size, NoteKind.FOOT, 0.22))
        remaining = item.note.time - self.elapsed
        if remaining <= SPLIT_LEAD:
            return target
        travel = geo.clamp((SPAWN_LEAD - remaining) / max(SPAWN_LEAD - SPLIT_LEAD, 0.001))
        eased = travel * travel * (3.0 - 2.0 * travel)
        return (
            source[0] + (target[0] - source[0]) * eased,
            source[1] + (target[1] - source[1]) * eased,
        )

    def _foot_position(self, item: RuntimeNote) -> tuple[float, float]:
        progress = geo.clamp((SPAWN_LEAD - (item.note.time - self.elapsed)) / SPAWN_LEAD)
        return geo.lane_center(self.size, NoteKind.FOOT, item.note.lanes[0], progress)

    def _pair_assignment_ok(self, item: RuntimeNote, *, radius: float) -> bool:
        if len(item.pointer_ids) != 2 or len(item.note.lanes) != 2:
            return False
        a = self.pointers.get(item.pointer_ids[0])
        b = self.pointers.get(item.pointer_ids[1])
        if a is None or b is None:
            return False
        left = self._hand_endpoint(item.note.lanes[0])
        right = self._hand_endpoint(item.note.lanes[1])
        direct = _distance(a, left) <= radius and _distance(b, right) <= radius
        crossed = _distance(a, right) <= radius and _distance(b, left) <= radius
        return direct or crossed

    def _foot_hold_ok(self, item: RuntimeNote, *, radius: float) -> bool:
        if len(item.pointer_ids) != 1:
            return False
        point = self.pointers.get(item.pointer_ids[0])
        return (
            point is not None
            and _distance(point, self._foot_endpoint(item.note.lanes[0])) <= radius
        )

    def pointer_down(self, pointer_id: int, position: tuple[float, float]) -> None:
        self.pointers[pointer_id] = position
        now = self.elapsed

        candidates = [
            item
            for item in self.notes
            if item.state == "pending"
            and item.note.kind == NoteKind.FOOT
            and abs(item.note.time - now) <= HIT_WINDOW
            and _distance(position, self._foot_endpoint(item.note.lanes[0])) <= TOUCH_RADIUS
        ]
        if candidates:
            item = min(candidates, key=lambda candidate: abs(candidate.note.time - now))
            item.pointer_ids = (pointer_id,)
            item.state_at = now
            item.state = "complete" if item.note.end_time is None else "holding"
            self._trigger_impact(4.5)
            return

        self._try_capture_pair()

    def pointer_move(self, pointer_id: int, position: tuple[float, float]) -> None:
        if pointer_id in self.pointers:
            self.pointers[pointer_id] = position

    def pointer_up(self, pointer_id: int) -> None:
        now = self.elapsed
        for item in self.notes:
            if pointer_id not in item.pointer_ids:
                continue
            if item.state == "captured" and now < item.note.time + HIT_WINDOW:
                item.state = "pending"
                item.pointer_ids = ()
                item.outside_since = None
            elif item.state == "holding" and item.note.end_time is not None and now < item.note.end_time:
                item.state = "dropped"
                item.state_at = now
        self.pointers.pop(pointer_id, None)

    def _try_capture_pair(self) -> None:
        now = self.elapsed
        if len(self.pointers) < 2:
            return
        for item in self.notes:
            if item.state != "pending" or item.note.kind != NoteKind.HANDS:
                continue
            remaining = item.note.time - now
            if remaining < -HIT_WINDOW or remaining > SPLIT_LEAD:
                continue
            core = self._hand_core_position(item)
            nearby = [
                pointer_id
                for pointer_id, point in self.pointers.items()
                if _distance(point, core) <= CORE_RADIUS * 1.35
            ]
            if len(nearby) >= 2:
                item.pointer_ids = (nearby[0], nearby[1])
                item.state = "captured"
                item.state_at = now
                return

    def update(self) -> None:
        now = self.elapsed
        if now > LOOP_SECONDS:
            self.reset()
            return

        self._try_capture_pair()

        for item in self.notes:
            note = item.note
            if item.state == "pending" and now > note.time + HIT_WINDOW:
                item.state = "missed"
                item.state_at = now
                continue

            if item.state == "captured":
                if now >= note.time:
                    if self._pair_assignment_ok(item, radius=TOUCH_RADIUS):
                        item.state = "holding" if note.end_time is not None else "complete"
                        item.state_at = now
                        item.outside_since = None
                        self._trigger_impact(8.0)
                    elif now > note.time + HIT_WINDOW:
                        item.state = "missed"
                        item.state_at = now
                continue

            if item.state != "holding" or note.end_time is None:
                continue

            occupancy_ok = (
                self._foot_hold_ok(item, radius=HOLD_RADIUS)
                if note.kind == NoteKind.FOOT
                else self._pair_assignment_ok(item, radius=HOLD_RADIUS)
            )
            if occupancy_ok:
                item.outside_since = None
            elif item.outside_since is None:
                item.outside_since = now
            elif now - item.outside_since > 0.12:
                item.state = "dropped"
                item.state_at = now
                continue

            if now >= note.end_time:
                item.state = "complete"
                item.state_at = now
                self._trigger_impact(3.0 if note.kind == NoteKind.FOOT else 4.5)

    def _draw_background(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        size = surface.get_size()
        viewport = geo.camera_rect(size)
        now = max(0.0, self.elapsed)

        for index in range(26):
            x = (index * 173 + 37) % max(size[0], 1)
            y = (index * 97 + int(now * (8 + index % 4))) % max(size[1] - 20, 1)
            pygame.draw.circle(surface, DIM, (x, y), 1)

        for lane in range(1, 5):
            fill = _blend(BG, CYAN, 0.035 if lane % 2 else 0.055)
            polygon = geo.foot_lane_polygon(size, lane)
            pygame.draw.polygon(surface, fill, polygon)

        for boundary in range(5):
            inner = (
                round(geo.lane_boundary_x(size, NoteKind.FOOT, boundary, 0.0)),
                round(geo.field_y(size, NoteKind.FOOT, 0.0)),
            )
            outer = (
                round(geo.lane_boundary_x(size, NoteKind.FOOT, boundary, 1.0)),
                round(geo.field_y(size, NoteKind.FOOT, 1.0)),
            )
            pygame.draw.line(surface, GRID, inner, outer, 2 if boundary in (0, 4) else 1)

        beat_phase = (max(0.0, self.elapsed) / BEAT_SECONDS) % 1.0
        for index in range(9):
            progress = geo.clamp((index + beat_phase) / 8.0)
            left = round(geo.lane_boundary_x(size, NoteKind.FOOT, 0, progress))
            right = round(geo.lane_boundary_x(size, NoteKind.FOOT, 4, progress))
            y = round(geo.field_y(size, NoteKind.FOOT, progress))
            strength = 0.38 if index % 4 else 0.72
            pygame.draw.line(surface, _blend(BG, GRID, strength), (left, y), (right, y), 1)

        for lane in range(1, 5):
            polygon = geo.hand_sector_polygon(size, lane)
            fill = _blend(BG, PURPLE if lane in (2, 3) else MAGENTA, 0.035)
            pygame.draw.polygon(surface, fill, polygon)
            pygame.draw.lines(surface, _blend(BG, GRID, 0.75), True, polygon, 1)

        pygame.draw.lines(
            surface,
            GRID,
            False,
            geo.hand_arc_points(size, 0.0, 1.0, 0.0, samples=42),
            2,
        )
        pygame.draw.lines(
            surface,
            _blend(GRID, CYAN, 0.22),
            False,
            geo.hand_arc_points(size, 0.0, 1.0, 1.0, samples=56),
            3,
        )
        for boundary in geo.HAND_BOUNDARIES:
            inner = geo.hand_point(size, boundary, 0.0)
            outer = geo.hand_point(size, boundary, 1.0)
            pygame.draw.line(
                surface,
                GRID,
                (round(inner[0]), round(inner[1])),
                (round(outer[0]), round(outer[1])),
                1,
            )

        # Receptors use the same outer shell and foot hit line as VaporStep.
        for lane in range(1, 5):
            foot = geo.lane_center(size, NoteKind.FOOT, lane, 1.0)
            lane_left = geo.lane_boundary_x(size, NoteKind.FOOT, lane - 1, 1.0)
            lane_right = geo.lane_boundary_x(size, NoteKind.FOOT, lane, 1.0)
            receptor_w = max(26, round((lane_right - lane_left) * 0.58))
            rect = pygame.Rect(0, 0, receptor_w, 10)
            rect.center = (round(foot[0]), round(foot[1]))
            pygame.draw.rect(surface, _blend(DIM, CYAN, 0.25), rect, 2, border_radius=4)

            hand_arc = geo.hand_lane_arc(size, lane, 1.0, geo.HAND_NOTE_ARC_FRACTION)
            pygame.draw.lines(surface, _blend(DIM, WHITE, 0.12), False, hand_arc, 7)

        vanish = (
            round(viewport.centerx),
            round(geo.field_y(size, NoteKind.FOOT, 0.0)),
        )
        pygame.draw.circle(surface, _blend(GRID, CYAN, 0.35), vanish, 8, 2)

    def _draw_foot_brick(
        self,
        surface: pygame.Surface,
        lane: int,
        progress: float,
        color: tuple[int, int, int],
        *,
        highlight: bool = True,
    ) -> None:
        p = geo.clamp(progress)
        span = 0.040 + 0.018 * p
        p0 = geo.clamp(p - span * 0.5)
        p1 = geo.clamp(p + span * 0.5)
        if abs(p1 - p0) < 0.002:
            p0 = max(0.0, p - 0.006)
            p1 = min(1.0, p + 0.006)
        polygon = geo.foot_lane_polygon(self.size, lane, p0, p1)
        center_left = geo.lane_boundary_x(self.size, NoteKind.FOOT, lane - 1, p)
        center_right = geo.lane_boundary_x(self.size, NoteKind.FOOT, lane, p)
        inset = max(2.0, (center_right - center_left) * 0.13)
        cx = sum(point[0] for point in polygon) / 4.0
        polygon = [
            (round(cx + (x - cx) * max(0.10, 1.0 - 2.0 * inset / max(center_right - center_left, 1.0))), y)
            for x, y in polygon
        ]
        pygame.draw.polygon(surface, color, polygon)
        pygame.draw.lines(surface, WHITE if highlight else _blend(color, WHITE, 0.25), True, polygon, 2)

    def _draw_hand_target(
        self,
        surface: pygame.Surface,
        item: RuntimeNote,
        progress: float,
        *,
        hold: bool = False,
    ) -> None:
        p = geo.clamp(progress)
        thickness = max(5, round(5 + 12 * p))
        for lane in item.note.lanes:
            arc = geo.hand_lane_arc(
                self.size,
                lane,
                p,
                geo.HAND_NOTE_ARC_FRACTION,
                samples=18,
            )
            pygame.draw.lines(surface, BG, False, arc, thickness + 9)
            pygame.draw.lines(surface, item.color, False, arc, thickness)
            pygame.draw.lines(surface, WHITE, False, arc, max(1, thickness // 5))

        connector = geo.hand_connector_points(self.size, item.note.lanes, p, samples=30)
        if connector:
            beat = max(0.0, self.elapsed) / BEAT_SECONDS
            amplitude = (4.0 + 3.0 * (0.5 + 0.5 * math.sin(beat * math.tau))) * p
            electric = _electric_points(connector, amplitude=amplitude, phase=self.elapsed * 13.0)
            pygame.draw.lines(surface, _blend(item.color, WHITE, 0.08), False, electric, 4 if hold else 3)

    def _draw_hand_guides(
        self,
        surface: pygame.Surface,
        item: RuntimeNote,
        core: tuple[float, float],
    ) -> None:
        endpoints = [self._hand_endpoint(lane) for lane in item.note.lanes]
        if len(endpoints) != 2:
            return
        separation = abs(endpoints[1][0] - endpoints[0][0])
        sep_norm = separation / max(self.size[0] * 0.70, 1.0)
        extra_bow = self.size[1] * (0.12 + 0.08 * (1.0 - geo.clamp(sep_norm)))
        for endpoint in endpoints:
            midpoint_y = min(core[1], endpoint[1]) - extra_bow
            control = ((core[0] + endpoint[0]) * 0.5, midpoint_y)
            guide = _quadratic_points(core, endpoint, control)
            pygame.draw.lines(surface, _blend(BG, item.color, 0.62), False, guide, 4)
            pygame.draw.circle(
                surface,
                item.color,
                (round(endpoint[0]), round(endpoint[1])),
                38,
                3,
            )

    def _draw_miss(self, surface: pygame.Surface, item: RuntimeNote) -> None:
        age = self.elapsed - item.state_at
        if age >= 0.55:
            return
        if item.note.kind == NoteKind.FOOT:
            pos = self._foot_endpoint(item.note.lanes[0])
        else:
            pos = self._hand_core_position(item)
        size = 22
        x, y = round(pos[0]), round(pos[1])
        pygame.draw.line(surface, RED, (x - size, y - size), (x + size, y + size), 6)
        pygame.draw.line(surface, RED, (x + size, y - size), (x - size, y + size), 6)

    def _draw_notes(self, surface: pygame.Surface) -> None:
        now = self.elapsed
        for item in self.notes:
            note = item.note
            if now < note.time - SPAWN_LEAD:
                continue

            if item.state in {"missed", "dropped"}:
                self._draw_miss(surface, item)
                continue

            if note.kind == NoteKind.FOOT:
                if item.state == "pending":
                    x, y = self._foot_position(item)
                    pygame.draw.circle(surface, WHITE, (round(x), round(y)), 27)
                    pygame.draw.circle(surface, CYAN, (round(x), round(y)), 27, 5)
                elif item.state == "holding":
                    self._draw_foot_brick(surface, note.lanes[0], 1.0, CYAN)
                    x, y = self._foot_endpoint(note.lanes[0])
                    remaining = max(0.0, (note.end_time or now) - now)
                    pulse = 48 + round(4 * math.sin(now * 10.0))
                    pygame.draw.circle(surface, WHITE, (round(x), round(y)), pulse, 3)
                    text = self.small_font.render(f"HOLD {remaining:.1f}", True, WHITE)
                    surface.blit(text, text.get_rect(center=(round(x), round(y - 58))))
                elif item.state == "complete" and now - item.state_at < 0.50:
                    age = geo.clamp((now - item.state_at) / 0.50)
                    progress = 1.0 - age * age
                    self._draw_foot_brick(surface, note.lanes[0], progress, CYAN)
                continue

            core = self._hand_core_position(item)
            remaining = note.time - now
            if item.state == "pending":
                pygame.draw.circle(surface, item.color, (round(core[0]), round(core[1])), 31)
                pygame.draw.circle(surface, WHITE, (round(core[0]), round(core[1])), 31, 2)
                if remaining <= SPLIT_LEAD:
                    pulse = 43 + round(6 * (0.5 + 0.5 * math.sin(now * 16.0)))
                    pygame.draw.circle(surface, item.color, (round(core[0]), round(core[1])), pulse, 3)
                    self._draw_hand_guides(surface, item, core)
            elif item.state == "captured":
                self._draw_hand_guides(surface, item, core)
                pygame.draw.circle(surface, item.color, (round(core[0]), round(core[1])), 25)
                for pointer_id in item.pointer_ids:
                    point = self.pointers.get(pointer_id)
                    if point is not None:
                        pygame.draw.line(
                            surface,
                            item.color,
                            (round(core[0]), round(core[1])),
                            (round(point[0]), round(point[1])),
                            5,
                        )
            elif item.state == "holding":
                self._draw_hand_target(surface, item, 1.0, hold=True)
                remaining_hold = max(0.0, (note.end_time or now) - now)
                viewport = geo.camera_rect(self.size)
                label = self.small_font.render(f"HOLD {remaining_hold:.1f}", True, WHITE)
                surface.blit(
                    label,
                    label.get_rect(
                        center=(
                            round(viewport.centerx),
                            round(geo.field_y(self.size, NoteKind.FOOT, 0.32)),
                        )
                    ),
                )
            elif item.state == "complete" and now - item.state_at < 0.52:
                age = geo.clamp((now - item.state_at) / 0.52)
                progress = 1.0 - age * age
                self._draw_hand_target(surface, item, progress)

    def _draw_scene(self) -> None:
        self._draw_background(self.screen)
        self._draw_notes(self.screen)
        for point in self.pointers.values():
            pygame.draw.circle(
                self.screen,
                WHITE,
                (round(point[0]), round(point[1])),
                18,
                2,
            )

    def draw(self) -> None:
        self._draw_scene()
        width, height = self.screen.get_size()

        shake_x, shake_y = self._shake_offset()
        if shake_x or shake_y:
            scene = self.screen.copy()
            self.screen.fill(BG)
            self.screen.blit(scene, (shake_x, shake_y))

        # Keep the HUD stable while the playfield receives the impact kick.
        title = self.big_font.render("VAPORTAP", True, MAGENTA)
        self.screen.blit(title, title.get_rect(midtop=(width // 2, 14)))
        hint = self.small_font.render(
            "Tap circles into foot targets  •  Pull hand cores apart to the upper receptors  •  Hold sustained notes",
            True,
            WHITE,
        )
        self.screen.blit(hint, hint.get_rect(midtop=(width // 2, 60)))
        sub = self.small_font.render(
            "VaporStep playfield geometry • synthetic 120 BPM playtest",
            True,
            DIM,
        )
        self.screen.blit(sub, sub.get_rect(midtop=(width // 2, 86)))

        beat = max(0.0, self.elapsed) / BEAT_SECONDS
        pulse = 0.5 + 0.5 * math.cos((beat % 1.0) * math.tau)
        pygame.draw.circle(self.screen, CYAN, (width - 38, 38), round(7 + 7 * pulse))

        if width < height:
            shade = pygame.Surface((width, height), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 180))
            self.screen.blit(shade, (0, 0))
            rotate = self.big_font.render("ROTATE TO LANDSCAPE", True, WHITE)
            self.screen.blit(rotate, rotate.get_rect(center=(width // 2, height // 2)))

    def handle_event(self, event: pygame.event.Event) -> bool:
        wall_now = time.monotonic()
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
            self.reset()
            return True

        width, height = self.screen.get_size()
        if event.type == pygame.FINGERDOWN:
            self.last_touch_at = wall_now
            self.pointer_down(int(event.finger_id), (event.x * width, event.y * height))
        elif event.type == pygame.FINGERMOTION:
            self.last_touch_at = wall_now
            self.pointer_move(int(event.finger_id), (event.x * width, event.y * height))
        elif event.type == pygame.FINGERUP:
            self.last_touch_at = wall_now
            self.pointer_up(int(event.finger_id))
        elif (
            wall_now - self.last_touch_at > 0.35
            and event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
        ):
            self.pointer_down(-1, event.pos)
        elif (
            wall_now - self.last_touch_at > 0.35
            and event.type == pygame.MOUSEMOTION
            and -1 in self.pointers
        ):
            self.pointer_move(-1, event.pos)
        elif (
            wall_now - self.last_touch_at > 0.35
            and event.type == pygame.MOUSEBUTTONUP
            and event.button == 1
        ):
            self.pointer_up(-1)
        return True


async def main() -> None:
    pygame.init()
    pygame.display.set_caption("VaporTap WASM Playtest")
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    playtest = VaporTapPlaytest(screen)
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
            clock.tick(TARGET_FPS)
        await asyncio.sleep(0)

    pygame.quit()
