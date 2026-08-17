from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from .scoring import RunStats, grade_for_ratio
from .song import ChartInfo, SongInfo


@dataclass(frozen=True)
class ChartRecord:
    score: int = 0
    score_ratio: float = 0.0
    grade: str = "-"
    max_combo: int = 0
    hits: int = 0
    misses: int = 0
    played_at: str = ""


def song_key(song: SongInfo) -> str:
    raw = "\x1f".join((song.title, song.subtitle, song.artist, song.simfile_path.stem))
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


def chart_key(song: SongInfo, chart: ChartInfo) -> str:
    # Stable across moving a song pack to another directory, while still
    # distinguishing charts/difficulties from the same song.
    raw = "\x1f".join(
        (
            "score-v2-timing",
            song.title,
            song.subtitle,
            song.artist,
            song.simfile_path.stem,
            str(chart.index),
            chart.difficulty,
            str(chart.meter),
            chart.description,
            chart.chart_name,
        )
    )
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


def default_records_path() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "VaporStep" / "highscores.json"
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        return base / "VaporStep" / "highscores.json"
    return home / ".local" / "share" / "vaporstep" / "highscores.json"


class RecordStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_records_path()
        self._records: dict[str, ChartRecord] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        records = data.get("records", data) if isinstance(data, dict) else {}
        if not isinstance(records, dict):
            return
        for key, value in records.items():
            if not isinstance(value, dict):
                continue
            try:
                score_ratio = float(value.get("score_ratio", 0.0))
                self._records[str(key)] = ChartRecord(
                    score=int(value.get("score", 0)),
                    score_ratio=score_ratio,
                    # Grade thresholds are presentation policy, so recompute old
                    # records under the current bands instead of leaving stale
                    # stale grades in the song browser.
                    grade=grade_for_ratio(score_ratio) if score_ratio > 0.0 else "-",
                    max_combo=int(value.get("max_combo", 0)),
                    hits=int(value.get("hits", 0)),
                    misses=int(value.get("misses", 0)),
                    played_at=str(value.get("played_at", "")),
                )
            except (TypeError, ValueError):
                continue

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
        payload = {
            "version": 1,
            "records": {key: asdict(value) for key, value in self._records.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        if os.name == "posix":
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        tmp.replace(self.path)

    def get(self, key: str) -> ChartRecord:
        return self._records.get(key, ChartRecord())

    def submit(self, key: str, stats: RunStats) -> tuple[ChartRecord, bool]:
        previous = self.get(key)
        if stats.score <= previous.score:
            return previous, False
        record = ChartRecord(
            score=stats.score,
            score_ratio=stats.score_ratio,
            grade=stats.grade,
            max_combo=stats.max_combo,
            hits=stats.hits,
            misses=stats.misses,
            played_at=datetime.now(timezone.utc).isoformat(),
        )
        self._records[key] = record
        try:
            self._save()
        except OSError:
            # A failed record write must never interrupt gameplay/results.
            pass
        return record, True
