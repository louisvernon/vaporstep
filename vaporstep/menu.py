from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math

from .song import ChartInfo, SongInfo, difficulty_rank


class MenuAction(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    NEXT_PACK = "next_pack"
    PREVIOUS_PACK = "previous_pack"
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
    if event.key == pygame.K_TAB:
        return MenuAction.PREVIOUS_PACK if event.mod & pygame.KMOD_SHIFT else MenuAction.NEXT_PACK
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
    LETTER_MODE_DELAY = 5.0

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

    def long_hold_action(self, now: float) -> MenuAction | None:
        """Return the held direction once it is ready to enter letter paging."""
        if (
            self.action in (MenuAction.UP, MenuAction.DOWN)
            and float(now) - self.pressed_at >= self.LETTER_MODE_DELAY
        ):
            return self.action
        return None

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
class DoubleTapDetector:
    """Recognize a deliberate double press without delaying another action."""

    window_seconds: float = 0.35
    _at: float | None = None

    def clear(self) -> None:
        self._at = None

    def register(self, now: float) -> bool:
        now = float(now)
        if self._at is not None and 0.0 <= now - self._at <= self.window_seconds:
            self.clear()
            return True
        self._at = now
        return False


def _song_letter(song: SongInfo) -> str:
    for character in song.display_title.strip():
        if character.isalpha():
            return character.upper()
        if character.isdigit():
            return "#"
    return "#"


@dataclass
class SongMenu:
    songs: list[SongInfo]
    song_index: int = 0
    chart_index: int = 0
    scroll_target: int = 0
    visual_position: float = 0.0
    preferred_difficulty: str = "Medium"
    letter_page: str | None = field(default=None, init=False)
    _all_songs: list[SongInfo] = field(default_factory=list, init=False, repr=False)
    pack_index: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._all_songs = list(self.songs)
        if self.songs:
            self.song_index %= len(self.songs)
            self.scroll_target = self.song_index
            self.visual_position = float(self.song_index)
            self._select_preferred_chart()

    @property
    def packs(self) -> tuple[str, ...]:
        names = sorted({song.pack_name for song in self._all_songs}, key=str.casefold)
        return ("ALL", *names)

    @property
    def active_pack(self) -> str:
        packs = self.packs
        return packs[self.pack_index % len(packs)] if packs else "ALL"

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

    @staticmethod
    def _difficulty_rank(value: str) -> int | None:
        return difficulty_rank(value)

    def _preferred_chart_index(self, song: SongInfo) -> int:
        if not song.charts:
            return 0
        preferred = (self.preferred_difficulty or "Medium").strip().casefold()
        exact = [i for i, chart in enumerate(song.charts) if chart.difficulty.strip().casefold() == preferred]
        if exact:
            return exact[0]

        target_rank = difficulty_rank(preferred)
        if target_rank is None:
            return 0

        ranked = []
        for i, chart in enumerate(song.charts):
            rank = difficulty_rank(chart.difficulty)
            if rank is None:
                continue
            ranked.append((abs(rank - target_rank), rank, chart.meter, i))
        return min(ranked)[-1] if ranked else 0

    def _select_preferred_chart(self) -> None:
        song = self.song
        self.chart_index = 0 if song is None else self._preferred_chart_index(song)

    def _apply_pack(self, preserve_song: SongInfo | None = None) -> None:
        self.letter_page = None
        active = self.active_pack
        self.songs = list(self._all_songs) if active == "ALL" else [
            song for song in self._all_songs if song.pack_name == active
        ]
        self.song_index = 0
        if preserve_song is not None and self.songs:
            try:
                self.song_index = self.songs.index(preserve_song)
            except ValueError:
                self.song_index = 0
        self.scroll_target = self.song_index
        self.visual_position = float(self.song_index)
        self._select_preferred_chart()

    def cycle_pack(self, delta: int) -> None:
        packs = self.packs
        if len(packs) <= 1:
            return
        current = self.song
        self.pack_index = (self.pack_index + delta) % len(packs)
        self._apply_pack(current)

    def select_song_index(self, index: int) -> None:
        if not self.songs:
            return
        self.song_index = index % len(self.songs)
        self.scroll_target = self.song_index
        self.visual_position = float(self.song_index)
        self._select_preferred_chart()

    @property
    def letter_pages(self) -> tuple[str, ...]:
        pages = {_song_letter(song) for song in self.songs}
        return tuple(sorted(pages, key=lambda page: (page != "#", page.casefold())))

    def enter_letter_paging(self, delta: int = 0) -> None:
        """Freeze on the current song and expose its title-initial page."""
        if self.song is None:
            return
        self.select_song_index(self.song_index)
        self.letter_page = _song_letter(self.song)
        if delta:
            self.page_letter(delta)

    def page_letter(self, delta: int) -> None:
        pages = self.letter_pages
        if not pages or not delta:
            return
        current = self.letter_page or (_song_letter(self.song) if self.song else pages[0])
        try:
            page_index = pages.index(current)
        except ValueError:
            page_index = 0
        target = pages[(page_index + int(delta)) % len(pages)]
        song_index = next(
            index for index, song in enumerate(self.songs) if _song_letter(song) == target
        )
        self.select_song_index(song_index)
        self.letter_page = target

    def exit_letter_paging(self) -> None:
        self.letter_page = None

    def animate(self, dt: float) -> None:
        alpha = 1.0 - math.exp(-max(0.0, dt) * 14.0)
        self.visual_position += (self.scroll_target - self.visual_position) * alpha
        if abs(self.scroll_target - self.visual_position) < 0.001:
            self.visual_position = float(self.scroll_target)

    def handle(self, action: MenuAction) -> tuple[SongInfo, ChartInfo] | None:
        if action == MenuAction.NEXT_PACK:
            self.cycle_pack(1)
            return None
        if action == MenuAction.PREVIOUS_PACK:
            self.cycle_pack(-1)
            return None
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
