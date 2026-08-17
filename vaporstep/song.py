from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .domain import GameNote, ImplicitChain


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
