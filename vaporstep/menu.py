from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math

from .song import ChartInfo, SongInfo


class MenuAction(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    SELECT = "select"
    BACK = "back"


def action_for_event(event) -> MenuAction | None:
    """Keyboard adapter for abstract menu actions.

    A future camera/hand menu provider can emit these same actions without
    changing SongMenu or the renderer.
    """
    import pygame

    if event.type != pygame.KEYDOWN:
        return None
    return {
        pygame.K_UP: MenuAction.UP,
        pygame.K_w: MenuAction.UP,
        pygame.K_DOWN: MenuAction.DOWN,
        pygame.K_s: MenuAction.DOWN,
        pygame.K_LEFT: MenuAction.LEFT,
        pygame.K_a: MenuAction.LEFT,
        pygame.K_RIGHT: MenuAction.RIGHT,
        pygame.K_d: MenuAction.RIGHT,
        pygame.K_RETURN: MenuAction.SELECT,
        pygame.K_SPACE: MenuAction.SELECT,
        pygame.K_ESCAPE: MenuAction.BACK,
        pygame.K_BACKSPACE: MenuAction.BACK,
    }.get(event.key)


class HeldMenuRepeater:
    """Deterministic held-key repeat with a scroll-wheel-style acceleration."""

    INITIAL_DELAY = 0.28

    def __init__(self) -> None:
        self.action: MenuAction | None = None
        self.pressed_at = 0.0
        self.next_repeat = 0.0

    def press(self, action: MenuAction, now: float) -> None:
        if action not in (MenuAction.UP, MenuAction.DOWN):
            return
        self.action = action
        self.pressed_at = now
        self.next_repeat = now + self.INITIAL_DELAY

    def release(self, action: MenuAction) -> None:
        if self.action == action:
            self.action = None

    def clear(self) -> None:
        self.action = None

    @staticmethod
    def _interval(held_for: float) -> float:
        if held_for >= 2.0:
            return 0.040
        if held_for >= 1.0:
            return 0.055
        return 0.075

    def update(self, now: float) -> list[MenuAction]:
        if self.action is None or now < self.next_repeat:
            return []
        emitted: list[MenuAction] = []
        # Catch up safely if a frame stalls, but cap work to avoid a burst.
        for _ in range(5):
            if now < self.next_repeat or self.action is None:
                break
            emitted.append(self.action)
            held_for = max(0.0, self.next_repeat - self.pressed_at)
            self.next_repeat += self._interval(held_for)
        return emitted


@dataclass
class SongMenu:
    songs: list[SongInfo]
    song_index: int = 0
    chart_index: int = 0
    scroll_target: int = 0
    visual_position: float = 0.0
    preferred_difficulty: str = "Medium"

    _DIFFICULTY_ORDER = {
        "beginner": 0,
        "novice": 0,
        "easy": 1,
        "basic": 1,
        "medium": 2,
        "normal": 2,
        "standard": 2,
        "hard": 3,
        "difficult": 3,
        "challenge": 4,
        "expert": 4,
        "edit": 5,
    }

    def __post_init__(self) -> None:
        if self.songs:
            self.song_index %= len(self.songs)
            self.scroll_target = self.song_index
            self.visual_position = float(self.song_index)
            self._select_preferred_chart()

    @property
    def song(self) -> SongInfo | None:
        if not self.songs:
            return None
        return self.songs[self.song_index]

    @property
    def chart(self) -> ChartInfo | None:
        song = self.song
        if song is None or not song.charts:
            return None
        return song.charts[self.chart_index]

    @classmethod
    def _difficulty_rank(cls, value: str) -> int | None:
        return cls._DIFFICULTY_ORDER.get((value or "").strip().casefold())

    def _preferred_chart_index(self, song: SongInfo) -> int:
        if not song.charts:
            return 0
        preferred = (self.preferred_difficulty or "Medium").strip().casefold()
        exact = [i for i, chart in enumerate(song.charts) if chart.difficulty.strip().casefold() == preferred]
        if exact:
            return exact[0]

        target_rank = self._difficulty_rank(preferred)
        if target_rank is None:
            return 0

        ranked = []
        for i, chart in enumerate(song.charts):
            rank = self._difficulty_rank(chart.difficulty)
            if rank is None:
                continue
            ranked.append((abs(rank - target_rank), rank, chart.meter, i))
        return min(ranked)[-1] if ranked else 0

    def _select_preferred_chart(self) -> None:
        song = self.song
        self.chart_index = 0 if song is None else self._preferred_chart_index(song)

    def select_song_index(self, index: int) -> None:
        if not self.songs:
            return
        self.song_index = index % len(self.songs)
        self.scroll_target = self.song_index
        self.visual_position = float(self.song_index)
        self._select_preferred_chart()

    def animate(self, dt: float) -> None:
        alpha = 1.0 - math.exp(-max(0.0, dt) * 14.0)
        self.visual_position += (self.scroll_target - self.visual_position) * alpha
        if abs(self.scroll_target - self.visual_position) < 0.001:
            self.visual_position = float(self.scroll_target)

    def handle(self, action: MenuAction) -> tuple[SongInfo, ChartInfo] | None:
        if not self.songs:
            return None
        if action == MenuAction.UP:
            self.scroll_target -= 1
            self.song_index = self.scroll_target % len(self.songs)
            self._select_preferred_chart()
        elif action == MenuAction.DOWN:
            self.scroll_target += 1
            self.song_index = self.scroll_target % len(self.songs)
            self._select_preferred_chart()
        elif action == MenuAction.LEFT:
            self.chart_index = (self.chart_index - 1) % len(self.song.charts)
            self.preferred_difficulty = self.chart.difficulty
        elif action == MenuAction.RIGHT:
            self.chart_index = (self.chart_index + 1) % len(self.song.charts)
            self.preferred_difficulty = self.chart.difficulty
        elif action == MenuAction.SELECT:
            assert self.song is not None and self.chart is not None
            return self.song, self.chart
        return None

