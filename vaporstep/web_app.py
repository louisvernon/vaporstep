from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import time

import pygame

from .domain import GameNote, NoteKind


WIDTH = 1280
HEIGHT = 720
TARGET_FPS = 60
BPM = 120.0
BEAT_SECONDS = 60.0 / BPM
SPAWN_LEAD = 2.0
SPLIT_LEAD = BEAT_SECONDS
HIT_WINDOW = 0.18
TOUCH_RADIUS = 78.0
CORE_RADIUS = 68.0
HOLD_RADIUS = 92.0
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


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _lane_x(lane: int, width: int) -> float:
    left = width * 0.17
    right = width * 0.83
    return left + (lane - 1) * (right - left) / 3.0


def _target_y(height: int) -> float:
    return height * 0.79


def _spawn_y(height: int) -> float:
    return height * 0.13


def _hand_core_y(height: int) -> float:
    return height * 0.49


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


def _demo_notes() -> list[GameNote]:
    # This deliberately uses the same GameNote vocabulary as converted DDR
    # dance-single charts: one source head -> FOOT, two heads -> HANDS.
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

    @property
    def finished(self) -> bool:
        return self.state in {"complete", "missed", "dropped"}


@dataclass
class VaporTapPrototype:
    screen: pygame.Surface
    font: pygame.font.Font = field(init=False)
    small_font: pygame.font.Font = field(init=False)
    big_font: pygame.font.Font = field(init=False)
    cycle_started: float = field(default_factory=time.monotonic)
    notes: list[RuntimeNote] = field(default_factory=list)
    pointers: dict[int, tuple[float, float]] = field(default_factory=dict)
    last_touch_at: float = -999.0

    def __post_init__(self) -> None:
        self.font = pygame.font.Font(None, 31)
        self.small_font = pygame.font.Font(None, 23)
        self.big_font = pygame.font.Font(None, 48)
        self.reset()

    def reset(self) -> None:
        self.cycle_started = time.monotonic() + 0.6
        self.pointers.clear()
        hand_index = 0
        self.notes = []
        for note in _demo_notes():
            if note.kind == NoteKind.HANDS:
                color = _pair_color(hand_index)
                hand_index += 1
            else:
                color = CYAN
            self.notes.append(RuntimeNote(note=note, color=color))

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.cycle_started

    def _core_position(self, item: RuntimeNote) -> tuple[float, float]:
        width, height = self.screen.get_size()
        x = sum(_lane_x(lane, width) for lane in item.note.lanes) / len(item.note.lanes)
        remaining = item.note.time - self.elapsed
        if remaining <= SPLIT_LEAD:
            return x, _hand_core_y(height)
        travel = _clamp((SPAWN_LEAD - remaining) / max(SPAWN_LEAD - SPLIT_LEAD, 0.001))
        y = _spawn_y(height) + (_hand_core_y(height) - _spawn_y(height)) * travel
        return x, y

    def _endpoint(self, lane: int) -> tuple[float, float]:
        width, height = self.screen.get_size()
        return _lane_x(lane, width), _target_y(height)

    def _foot_position(self, item: RuntimeNote) -> tuple[float, float]:
        width, height = self.screen.get_size()
        progress = _clamp((SPAWN_LEAD - (item.note.time - self.elapsed)) / SPAWN_LEAD)
        return (
            _lane_x(item.note.lanes[0], width),
            _spawn_y(height) + (_target_y(height) - _spawn_y(height)) * progress,
        )

    def _pair_assignment_ok(self, item: RuntimeNote, *, radius: float) -> bool:
        if len(item.pointer_ids) != 2 or len(item.note.lanes) != 2:
            return False
        a = self.pointers.get(item.pointer_ids[0])
        b = self.pointers.get(item.pointer_ids[1])
        if a is None or b is None:
            return False
        left = self._endpoint(item.note.lanes[0])
        right = self._endpoint(item.note.lanes[1])
        direct = _distance(a, left) <= radius and _distance(b, right) <= radius
        crossed = _distance(a, right) <= radius and _distance(b, left) <= radius
        return direct or crossed

    def _foot_hold_ok(self, item: RuntimeNote, *, radius: float) -> bool:
        if len(item.pointer_ids) != 1:
            return False
        point = self.pointers.get(item.pointer_ids[0])
        return point is not None and _distance(point, self._endpoint(item.note.lanes[0])) <= radius

    def pointer_down(self, pointer_id: int, position: tuple[float, float]) -> None:
        self.pointers[pointer_id] = position
        now = self.elapsed

        # Singles remain literal DDR lane taps. Pick the nearest eligible note.
        candidates = [
            item
            for item in self.notes
            if item.state == "pending"
            and item.note.kind == NoteKind.FOOT
            and abs(item.note.time - now) <= HIT_WINDOW
            and _distance(position, self._endpoint(item.note.lanes[0])) <= TOUCH_RADIUS
        ]
        if candidates:
            item = min(candidates, key=lambda candidate: abs(candidate.note.time - now))
            item.pointer_ids = (pointer_id,)
            item.state_at = now
            if item.note.end_time is None:
                item.state = "complete"
            else:
                item.state = "holding"
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
            core = self._core_position(item)
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

        # A second finger may arrive after the first pointer-down event.
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

    def _draw_background(self) -> None:
        screen = self.screen
        width, height = screen.get_size()
        screen.fill(BG)
        target_y = round(_target_y(height))
        vanish_y = round(height * 0.11)
        center = width // 2

        # Familiar VaporStep perspective language without importing the desktop
        # renderer (which currently depends on OpenCV/NumPy).
        for lane in range(1, 5):
            x = round(_lane_x(lane, width))
            vanish_x = round(center + (x - center) * 0.18)
            pygame.draw.line(screen, GRID, (vanish_x, vanish_y), (x, target_y + 70), 2)
        for i in range(9):
            p = i / 8.0
            y = round(vanish_y + (target_y + 70 - vanish_y) * (p * p))
            half = round(width * (0.05 + 0.39 * p))
            pygame.draw.line(screen, GRID, (center - half, y), (center + half, y), 1)

        pygame.draw.line(screen, CYAN, (round(width * 0.12), target_y), (round(width * 0.88), target_y), 3)
        for lane in range(1, 5):
            x = round(_lane_x(lane, width))
            pygame.draw.circle(screen, DIM, (x, target_y), 42, 2)
            label = self.small_font.render(str(lane), True, DIM)
            screen.blit(label, label.get_rect(center=(x, target_y + 64)))

    def _draw_hand_guides(self, item: RuntimeNote, core: tuple[float, float]) -> None:
        if len(item.note.lanes) != 2:
            return
        endpoints = [self._endpoint(lane) for lane in item.note.lanes]
        separation = abs(endpoints[1][0] - endpoints[0][0])
        width, height = self.screen.get_size()
        sep_norm = separation / max(width * 0.66, 1.0)
        extra_bow = height * (0.16 - 0.07 * _clamp(sep_norm))

        for endpoint in endpoints:
            control = (
                (core[0] + endpoint[0]) * 0.5,
                min(core[1], endpoint[1]) - extra_bow,
            )
            points = _quadratic_points(core, endpoint, control)
            pygame.draw.lines(self.screen, item.color, False, points, 4)
            pygame.draw.circle(self.screen, item.color, (round(endpoint[0]), round(endpoint[1])), 48, 3)

    def _draw_pair_tether(self, item: RuntimeNote, *, launch_offset: float = 0.0) -> None:
        a = self._endpoint(item.note.lanes[0])
        b = self._endpoint(item.note.lanes[1])
        a = (a[0], a[1] - launch_offset)
        b = (b[0], b[1] - launch_offset)
        width, height = self.screen.get_size()
        separation = abs(b[0] - a[0])
        sep_norm = separation / max(width * 0.66, 1.0)
        bow = height * (0.10 + 0.10 * (1.0 - _clamp(sep_norm)))
        control = ((a[0] + b[0]) * 0.5, min(a[1], b[1]) - bow)
        pygame.draw.lines(self.screen, item.color, False, _quadratic_points(a, b, control, samples=36), 5)
        for point in (a, b):
            rect = pygame.Rect(0, 0, 82, 34)
            rect.center = (round(point[0]), round(point[1]))
            pygame.draw.rect(self.screen, item.color, rect, border_radius=8)
            pygame.draw.rect(self.screen, WHITE, rect, 2, border_radius=8)

    def _draw_notes(self) -> None:
        now = self.elapsed
        for item in self.notes:
            note = item.note
            if now < note.time - SPAWN_LEAD:
                continue

            if item.state in {"missed", "dropped"}:
                age = now - item.state_at
                if age < 0.55:
                    pos = self._endpoint(note.lanes[0]) if note.kind == NoteKind.FOOT else self._core_position(item)
                    size = 22
                    x, y = round(pos[0]), round(pos[1])
                    pygame.draw.line(self.screen, RED, (x - size, y - size), (x + size, y + size), 6)
                    pygame.draw.line(self.screen, RED, (x + size, y - size), (x - size, y + size), 6)
                continue

            if note.kind == NoteKind.FOOT:
                if item.state == "pending":
                    x, y = self._foot_position(item)
                    pygame.draw.circle(self.screen, WHITE, (round(x), round(y)), 27)
                    pygame.draw.circle(self.screen, CYAN, (round(x), round(y)), 27, 5)
                elif item.state == "holding":
                    x, y = self._endpoint(note.lanes[0])
                    rect = pygame.Rect(0, 0, 86, 38)
                    rect.center = (round(x), round(y))
                    pygame.draw.rect(self.screen, CYAN, rect, border_radius=8)
                    remaining = max(0.0, (note.end_time or now) - now)
                    pygame.draw.circle(self.screen, WHITE, (round(x), round(y)), 50, 3)
                    text = self.small_font.render(f"HOLD {remaining:.1f}", True, WHITE)
                    self.screen.blit(text, text.get_rect(center=(round(x), round(y - 65))))
                elif item.state == "complete" and now - item.state_at < 0.45:
                    x, y = self._endpoint(note.lanes[0])
                    launch = 160.0 * _clamp((now - item.state_at) / 0.45)
                    rect = pygame.Rect(0, 0, 86, 38)
                    rect.center = (round(x), round(y - launch))
                    pygame.draw.rect(self.screen, CYAN, rect, border_radius=8)
                    pygame.draw.rect(self.screen, WHITE, rect, 2, border_radius=8)
                continue

            core = self._core_position(item)
            remaining = note.time - now
            if item.state == "pending":
                pygame.draw.circle(self.screen, item.color, (round(core[0]), round(core[1])), 31)
                pygame.draw.circle(self.screen, WHITE, (round(core[0]), round(core[1])), 31, 2)
                if remaining <= SPLIT_LEAD:
                    pulse = 7 + int(4 * (1.0 + math.sin(now * 16.0)))
                    pygame.draw.circle(self.screen, item.color, (round(core[0]), round(core[1])), 39 + pulse, 3)
                    self._draw_hand_guides(item, core)
            elif item.state == "captured":
                self._draw_hand_guides(item, core)
                pygame.draw.circle(self.screen, item.color, (round(core[0]), round(core[1])), 26)
                for pointer_id in item.pointer_ids:
                    point = self.pointers.get(pointer_id)
                    if point is not None:
                        pygame.draw.line(self.screen, item.color, (round(core[0]), round(core[1])), (round(point[0]), round(point[1])), 5)
            elif item.state == "holding":
                self._draw_pair_tether(item)
                remaining_hold = max(0.0, (note.end_time or now) - now)
                label = self.small_font.render(f"HOLD {remaining_hold:.1f}", True, WHITE)
                self.screen.blit(label, label.get_rect(center=(self.screen.get_width() // 2, round(_target_y(self.screen.get_height()) - 115))))
            elif item.state == "complete" and now - item.state_at < 0.5:
                launch = 150.0 * _clamp((now - item.state_at) / 0.5)
                self._draw_pair_tether(item, launch_offset=launch)

    def draw(self) -> None:
        self._draw_background()
        self._draw_notes()
        width, height = self.screen.get_size()

        title = self.big_font.render("VAPORTAP  •  WASM INPUT PROTOTYPE", True, MAGENTA)
        self.screen.blit(title, title.get_rect(midtop=(width // 2, 18)))
        hint = self.small_font.render(
            "Singles: tap the circle on the beat   •   Jumps: two fingers on the core, pull apart to the two lanes   •   Holds: keep contact",
            True,
            WHITE,
        )
        self.screen.blit(hint, hint.get_rect(midtop=(width // 2, 68)))
        sub = self.small_font.render("120 BPM synthetic loop — audio and simfile loading come next", True, DIM)
        self.screen.blit(sub, sub.get_rect(midtop=(width // 2, 94)))

        beat = max(0.0, self.elapsed) / BEAT_SECONDS
        pulse = 0.5 + 0.5 * math.cos((beat % 1.0) * math.tau)
        pygame.draw.circle(self.screen, CYAN, (width - 38, 38), round(7 + 7 * pulse))

        for point in self.pointers.values():
            pygame.draw.circle(self.screen, WHITE, (round(point[0]), round(point[1])), 18, 2)

        if width < height:
            shade = pygame.Surface((width, height), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 180))
            self.screen.blit(shade, (0, 0))
            rotate = self.big_font.render("ROTATE TO LANDSCAPE", True, WHITE)
            self.screen.blit(rotate, rotate.get_rect(center=(width // 2, height // 2)))

    def handle_event(self, event: pygame.event.Event) -> bool:
        now = time.monotonic()
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
            self.reset()
            return True

        width, height = self.screen.get_size()
        if event.type == pygame.FINGERDOWN:
            self.last_touch_at = now
            self.pointer_down(int(event.finger_id), (event.x * width, event.y * height))
        elif event.type == pygame.FINGERMOTION:
            self.last_touch_at = now
            self.pointer_move(int(event.finger_id), (event.x * width, event.y * height))
        elif event.type == pygame.FINGERUP:
            self.last_touch_at = now
            self.pointer_up(int(event.finger_id))
        elif now - self.last_touch_at > 0.35 and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.pointer_down(-1, event.pos)
        elif now - self.last_touch_at > 0.35 and event.type == pygame.MOUSEMOTION and -1 in self.pointers:
            self.pointer_move(-1, event.pos)
        elif now - self.last_touch_at > 0.35 and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.pointer_up(-1)
        return True


async def main() -> None:
    pygame.init()
    pygame.display.set_caption("VaporTap WASM Prototype")
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    prototype = VaporTapPrototype(screen)
    clock = pygame.time.Clock()
    running = True

    while running:
        for event in pygame.event.get():
            running = prototype.handle_event(event)
            if not running:
                break
        prototype.update()
        prototype.draw()
        pygame.display.flip()

        # Pygbag/Emscripten requires the Python loop to yield to the browser on
        # every frame. On desktop this still behaves like a normal 60 Hz loop.
        if hasattr(pygame, "IS_CE") and pygame.IS_CE:
            clock.tick(TARGET_FPS)
        await asyncio.sleep(0)

    pygame.quit()
