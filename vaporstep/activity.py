from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .domain import GameNote, NoteKind


SONG_PROGRESS_THRESHOLD = 0.25
DAILY_ACTIVITY_GOAL = 100


@dataclass(frozen=True)
class Profile:
    id: int
    name: str
    settings: dict[str, object]


@dataclass(frozen=True)
class RunActivity:
    profile_id: int
    started_at_utc: str
    local_date: str
    duration_seconds: float
    song_key: str
    chart_key: str
    outcome: str
    progress: float
    counts_as_song: bool
    stomps: int
    punches: int
    score: int

    @property
    def actions(self) -> int:
        return self.stomps + self.punches


@dataclass(frozen=True)
class DayActivity:
    day: date
    duration_seconds: float = 0.0
    stomps: int = 0
    punches: int = 0
    songs: int = 0

    @property
    def actions(self) -> int:
        return self.stomps + self.punches


@dataclass(frozen=True)
class ActivityTotals:
    duration_seconds: float = 0.0
    stomps: int = 0
    punches: int = 0
    songs: int = 0
    current_streak: int = 0
    best_streak: int = 0

    @property
    def actions(self) -> int:
        return self.stomps + self.punches


@dataclass(frozen=True)
class WeeklyRecords:
    duration_seconds: float = 0.0
    actions: int = 0
    songs: int = 0
    has_history: bool = False


def target_activity(notes: Iterable[GameNote]) -> tuple[int, int]:
    """Return target-driven stomp and punch counts for successful note heads.

    Multi-lane targets count one action per lane. Sustain tails are not GameNote
    judgements, and generated-chain continuation notes remain unjudged while
    Virtual Holds are enabled, so neither can inflate the activity total.
    """
    stomps = 0
    punches = 0
    for note in notes:
        if not note.judged or not note.hit:
            continue
        count = len(note.lanes)
        if note.kind == NoteKind.FOOT:
            stomps += count
        elif note.kind == NoteKind.HANDS:
            punches += count
    return stomps, punches


def run_progress(song_time: float, last_note_time: float) -> float:
    if last_note_time <= 0.0:
        return 1.0 if song_time > 0.0 else 0.0
    return max(0.0, min(1.0, float(song_time) / float(last_note_time)))


def counts_as_song(progress: float) -> bool:
    return float(progress) >= SONG_PROGRESS_THRESHOLD


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


class ActivityStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        self._db.close()

    def _initialize(self) -> None:
        self._db.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                settings_json TEXT NOT NULL DEFAULT '{}',
                created_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chart_records (
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                chart_key TEXT NOT NULL,
                score INTEGER NOT NULL,
                score_ratio REAL NOT NULL,
                grade TEXT NOT NULL,
                max_combo INTEGER NOT NULL,
                hits INTEGER NOT NULL,
                misses INTEGER NOT NULL,
                played_at_utc TEXT NOT NULL,
                PRIMARY KEY (profile_id, chart_key)
            );

            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                started_at_utc TEXT NOT NULL,
                local_date TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                song_key TEXT NOT NULL,
                chart_key TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('completed', 'failed', 'escaped')),
                progress REAL NOT NULL,
                counts_as_song INTEGER NOT NULL,
                stomps INTEGER NOT NULL,
                punches INTEGER NOT NULL,
                score INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS runs_profile_date_idx
                ON runs(profile_id, local_date);
            """
        )
        self._db.commit()

    def profiles(self) -> list[Profile]:
        rows = self._db.execute("SELECT id, name, settings_json FROM profiles ORDER BY id").fetchall()
        return [self._profile_from_row(row) for row in rows]

    def create_profile(self, name: str, *, settings: dict[str, object] | None = None) -> Profile:
        clean = self._clean_name(name)
        created = datetime.now(timezone.utc).isoformat()
        cur = self._db.execute(
            "INSERT INTO profiles(name, settings_json, created_at_utc) VALUES (?, ?, ?)",
            (clean, json.dumps(settings or {}, sort_keys=True), created),
        )
        profile_id = int(cur.lastrowid)
        self.set_active_profile(profile_id)
        self._db.commit()
        return Profile(profile_id, clean, dict(settings or {}))

    def rename_profile(self, profile_id: int, name: str) -> Profile:
        clean = self._clean_name(name)
        self._db.execute("UPDATE profiles SET name = ? WHERE id = ?", (clean, int(profile_id)))
        self._db.commit()
        return self.get_profile(profile_id)

    def get_profile(self, profile_id: int) -> Profile:
        row = self._db.execute(
            "SELECT id, name, settings_json FROM profiles WHERE id = ?", (int(profile_id),)
        ).fetchone()
        if row is None:
            raise KeyError(profile_id)
        return self._profile_from_row(row)

    def update_profile_settings(self, profile_id: int, settings: dict[str, object]) -> None:
        self._db.execute(
            "UPDATE profiles SET settings_json = ? WHERE id = ?",
            (json.dumps(settings, sort_keys=True), int(profile_id)),
        )
        self._db.commit()

    def active_profile(self) -> Profile | None:
        row = self._db.execute("SELECT value FROM app_meta WHERE key = 'active_profile_id'").fetchone()
        if row is not None:
            try:
                return self.get_profile(int(row["value"]))
            except (KeyError, TypeError, ValueError):
                pass
        profiles = self.profiles()
        return profiles[0] if profiles else None

    def set_active_profile(self, profile_id: int) -> None:
        self.get_profile(profile_id)
        self._db.execute(
            "INSERT INTO app_meta(key, value) VALUES ('active_profile_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(int(profile_id)),),
        )
        self._db.commit()

    def record_run(self, activity: RunActivity) -> int:
        cur = self._db.execute(
            """
            INSERT INTO runs(
                profile_id, started_at_utc, local_date, duration_seconds,
                song_key, chart_key, outcome, progress, counts_as_song,
                stomps, punches, score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                activity.profile_id,
                activity.started_at_utc,
                activity.local_date,
                max(0.0, activity.duration_seconds),
                activity.song_key,
                activity.chart_key,
                activity.outcome,
                max(0.0, min(1.0, activity.progress)),
                1 if activity.counts_as_song else 0,
                max(0, activity.stomps),
                max(0, activity.punches),
                max(0, activity.score),
            ),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def week(self, profile_id: int, start: date) -> list[DayActivity]:
        start = week_start(start)
        end = start + timedelta(days=7)
        rows = self._db.execute(
            """
            SELECT local_date,
                   COALESCE(SUM(duration_seconds), 0) AS duration_seconds,
                   COALESCE(SUM(stomps), 0) AS stomps,
                   COALESCE(SUM(punches), 0) AS punches,
                   COALESCE(SUM(counts_as_song), 0) AS songs
            FROM runs
            WHERE profile_id = ? AND local_date >= ? AND local_date < ?
            GROUP BY local_date
            """,
            (int(profile_id), start.isoformat(), end.isoformat()),
        ).fetchall()
        by_day = {date.fromisoformat(row["local_date"]): row for row in rows}
        result: list[DayActivity] = []
        for offset in range(7):
            day = start + timedelta(days=offset)
            row = by_day.get(day)
            result.append(
                DayActivity(
                    day=day,
                    duration_seconds=float(row["duration_seconds"]) if row else 0.0,
                    stomps=int(row["stomps"]) if row else 0,
                    punches=int(row["punches"]) if row else 0,
                    songs=int(row["songs"]) if row else 0,
                )
            )
        return result

    def totals(self, profile_id: int, *, today: date | None = None) -> ActivityTotals:
        row = self._db.execute(
            """
            SELECT COALESCE(SUM(duration_seconds), 0) AS duration_seconds,
                   COALESCE(SUM(stomps), 0) AS stomps,
                   COALESCE(SUM(punches), 0) AS punches,
                   COALESCE(SUM(counts_as_song), 0) AS songs
            FROM runs WHERE profile_id = ?
            """,
            (int(profile_id),),
        ).fetchone()
        current, best = self.streaks(profile_id, today=today)
        return ActivityTotals(
            duration_seconds=float(row["duration_seconds"]),
            stomps=int(row["stomps"]),
            punches=int(row["punches"]),
            songs=int(row["songs"]),
            current_streak=current,
            best_streak=best,
        )

    def weekly_records(
        self,
        profile_id: int,
        *,
        before: date,
        day_count: int = 7,
    ) -> WeeklyRecords:
        """Return the best comparable partial-week totals before ``before``.

        For example, a Wednesday dashboard compares Monday-through-Wednesday
        with the same three days from every earlier week. Each metric keeps its
        own record, so a single unusual week does not define all three badges.
        """
        before = week_start(before)
        day_count = max(1, min(7, int(day_count)))
        rows = self._db.execute(
            """
            SELECT local_date,
                   COALESCE(SUM(duration_seconds), 0) AS duration_seconds,
                   COALESCE(SUM(stomps + punches), 0) AS actions,
                   COALESCE(SUM(counts_as_song), 0) AS songs
            FROM runs
            WHERE profile_id = ? AND local_date < ?
            GROUP BY local_date
            ORDER BY local_date
            """,
            (int(profile_id), before.isoformat()),
        ).fetchall()

        weeks: dict[date, list[float]] = {}
        for row in rows:
            day = date.fromisoformat(row["local_date"])
            start = week_start(day)
            if (day - start).days >= day_count:
                continue
            values = weeks.setdefault(start, [0.0, 0.0, 0.0])
            values[0] += float(row["duration_seconds"])
            values[1] += int(row["actions"])
            values[2] += int(row["songs"])

        if not weeks:
            return WeeklyRecords()
        return WeeklyRecords(
            duration_seconds=max(values[0] for values in weeks.values()),
            actions=int(max(values[1] for values in weeks.values())),
            songs=int(max(values[2] for values in weeks.values())),
            has_history=True,
        )

    def streaks(self, profile_id: int, *, today: date | None = None) -> tuple[int, int]:
        today = today or date.today()
        rows = self._db.execute(
            """
            SELECT local_date, COALESCE(SUM(stomps + punches), 0) AS actions
            FROM runs WHERE profile_id = ?
            GROUP BY local_date ORDER BY local_date
            """,
            (int(profile_id),),
        ).fetchall()
        qualifying = {
            date.fromisoformat(row["local_date"])
            for row in rows
            if int(row["actions"]) >= DAILY_ACTIVITY_GOAL
        }
        if not qualifying:
            return 0, 0

        best = 0
        run = 0
        previous: date | None = None
        for day in sorted(qualifying):
            run = run + 1 if previous is not None and day == previous + timedelta(days=1) else 1
            best = max(best, run)
            previous = day

        # An unfinished current day does not erase the streak earned through yesterday.
        cursor = today if today in qualifying else today - timedelta(days=1)
        current = 0
        while cursor in qualifying:
            current += 1
            cursor -= timedelta(days=1)
        return current, best

    @staticmethod
    def _clean_name(name: str) -> str:
        clean = " ".join(str(name).strip().split())
        if not clean:
            raise ValueError("Profile name cannot be empty")
        return clean[:32]

    @staticmethod
    def _profile_from_row(row: sqlite3.Row) -> Profile:
        try:
            settings = json.loads(row["settings_json"])
        except (TypeError, json.JSONDecodeError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        return Profile(id=int(row["id"]), name=str(row["name"]), settings=settings)
