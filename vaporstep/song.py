from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .domain import GameNote, ImplicitChain


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


def difficulty_rank(value: str) -> int | None:
    """Return VaporStep's semantic difficulty tier for a StepMania label."""
    return _DIFFICULTY_ORDER.get((value or "").strip().casefold())


@dataclass(frozen=True)
class ChartInfo:
    index: int
    difficulty: str
    meter: int
    description: str = ""
    chart_name: str = ""
    target_count: int = 0
    foot_count: int = 0
    hand_count: int = 0
    bpm_min: float = 0.0
    bpm_max: float = 0.0
    chain_count: int = 0
    native_8_lane: bool = False

    @property
    def label(self) -> str:
        name = self.chart_name or self.description
        suffix = f" · {name}" if name else ""
        return f"{self.difficulty or 'Unknown'} {self.meter}{suffix}"

    @property
    def bpm_label(self) -> str:
        if self.bpm_min <= 0.0 and self.bpm_max <= 0.0:
            return "—"
        lo = self.bpm_min or self.bpm_max
        hi = self.bpm_max or self.bpm_min
        if abs(hi - lo) < 0.05:
            return f"{hi:.0f}"
        return f"{lo:.0f}–{hi:.0f}"


def chart_sort_key(chart: ChartInfo) -> tuple[int, int, str, int]:
    """Sort named difficulties first, then meter within each difficulty tier.

    The familiar StepMania progression is more useful in the song browser than
    globally sorting by meter: Beginner, Easy, Medium, Hard, Challenge, Edit.
    Legacy aliases share the corresponding tier. Unknown labels follow those
    tiers and remain deterministic by meter/name/source index.
    """
    rank = difficulty_rank(chart.difficulty)
    return (
        rank if rank is not None else 6,
        chart.meter,
        (chart.difficulty or "").strip().casefold(),
        chart.index,
    )


@dataclass(frozen=True)
class SongInfo:
    simfile_path: Path
    song_dir: Path
    title: str
    subtitle: str
    artist: str
    music_path: Path | None
    banner_path: Path | None
    background_path: Path | None
    charts: tuple[ChartInfo, ...]
    sample_start: float = 0.0
    sample_length: float = 15.0

    @property
    def display_title(self) -> str:
        return self.title or self.song_dir.name

    @property
    def pack_name(self) -> str:
        """Best-effort StepMania pack name for the conventional root/pack/song layout."""
        return self.song_dir.parent.name or "Ungrouped"

    @property
    def has_native_8_lane(self) -> bool:
        return any(chart.native_8_lane for chart in self.charts)

    @property
    def has_foot_targets(self) -> bool:
        return any(chart.foot_count > 0 for chart in self.charts)

    @property
    def has_hand_targets(self) -> bool:
        return any(chart.hand_count > 0 for chart in self.charts)


@dataclass(frozen=True)
class BeatMarker:
    time: float
    beat: int

    @property
    def downbeat(self) -> bool:
        return self.beat % 4 == 0


@dataclass(frozen=True)
class LoadedChart:
    song: SongInfo
    chart: ChartInfo
    notes: tuple[GameNote, ...]
    initial_bpm: float
    last_note_time: float
    beat_markers: tuple[BeatMarker, ...] = ()
    skipped_rows: int = 0
    timing_engine: object | None = None
    chains: tuple[ImplicitChain, ...] = ()
    sustains: tuple[ImplicitChain, ...] = ()
