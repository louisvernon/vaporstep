from datetime import date, timedelta
from pathlib import Path
import sqlite3

from vaporstep.activity import (
    ActivityStore,
    DAILY_ACTIVITY_GOAL,
    RunActivity,
    counts_as_song,
    run_progress,
    target_activity,
    week_start,
)
from vaporstep.domain import GameNote, NoteKind


def _hit(kind: NoteKind, lanes: tuple[int, ...]) -> GameNote:
    note = GameNote(time=1.0, lanes=lanes, kind=kind)
    note.judged = True
    note.hit = True
    return note


def _miss(kind: NoteKind, lanes: tuple[int, ...]) -> GameNote:
    note = GameNote(time=1.0, lanes=lanes, kind=kind)
    note.judged = True
    note.hit = False
    return note


def test_target_activity_counts_successful_target_lanes_only():
    notes = [
        _hit(NoteKind.FOOT, (1,)),
        _hit(NoteKind.FOOT, (2, 3)),
        _hit(NoteKind.HANDS, (1, 4)),
        _miss(NoteKind.FOOT, (4,)),
        GameNote(time=2.0, lanes=(2,), kind=NoteKind.HANDS),
    ]
    assert target_activity(notes) == (3, 2)


def test_progress_threshold_is_twenty_five_percent():
    assert run_progress(25.0, 100.0) == 0.25
    assert counts_as_song(0.249) is False
    assert counts_as_song(0.25) is True
    assert run_progress(200.0, 100.0) == 1.0
    assert run_progress(-5.0, 100.0) == 0.0


def test_profiles_are_dynamic_and_last_active_is_restored(tmp_path: Path):
    store = ActivityStore(tmp_path / "activity.sqlite3")
    assert store.active_profile() is None

    first = store.create_profile("Max")
    second = store.create_profile("Hailey")
    assert [profile.name for profile in store.profiles()] == ["Max", "Hailey"]
    assert store.active_profile() == second

    store.set_active_profile(first.id)
    store.close()

    reopened = ActivityStore(tmp_path / "activity.sqlite3")
    assert reopened.active_profile().name == "Max"
    assert reopened.rename_profile(first.id, "Max V").name == "Max V"
    reopened.close()


def test_failed_and_escaped_runs_keep_activity_but_song_requires_progress(tmp_path: Path):
    store = ActivityStore(tmp_path / "activity.sqlite3")
    profile = store.create_profile("Player")

    store.record_run(
        RunActivity(
            profile_id=profile.id,
            started_at_utc="2026-08-19T10:00:00+00:00",
            local_date="2026-08-19",
            duration_seconds=90,
            song_key="song-a",
            chart_key="chart-a",
            outcome="failed",
            progress=0.60,
            counts_as_song=True,
            stomps=30,
            punches=20,
            score=1234,
        )
    )
    store.record_run(
        RunActivity(
            profile_id=profile.id,
            started_at_utc="2026-08-19T11:00:00+00:00",
            local_date="2026-08-19",
            duration_seconds=20,
            song_key="song-b",
            chart_key="chart-b",
            outcome="escaped",
            progress=0.10,
            counts_as_song=False,
            stomps=8,
            punches=3,
            score=300,
        )
    )

    day = store.week(profile.id, date(2026, 8, 19))[2]
    assert day.day == date(2026, 8, 19)
    assert day.duration_seconds == 110
    assert day.stomps == 38
    assert day.punches == 23
    assert day.songs == 1
    store.close()


def test_camera_and_keyboard_activity_are_aggregated_separately(tmp_path: Path):
    store = ActivityStore(tmp_path / "activity.sqlite3")
    profile = store.create_profile("Player")
    common = dict(
        profile_id=profile.id,
        started_at_utc="2026-08-19T10:00:00+00:00",
        local_date="2026-08-19",
        duration_seconds=60,
        song_key="song",
        chart_key="chart",
        outcome="completed",
        progress=1.0,
        counts_as_song=True,
        punches=0,
        score=1000,
    )
    store.record_run(RunActivity(**common, stomps=20, input_mode="camera"))
    store.record_run(RunActivity(**common, stomps=80, input_mode="keyboard"))

    camera = store.week(profile.id, date(2026, 8, 19), input_mode="camera")[2]
    keyboard = store.week(profile.id, date(2026, 8, 19), input_mode="keyboard")[2]

    assert camera.actions == 20
    assert keyboard.actions == 80
    assert store.totals(profile.id, input_mode="camera").actions == 20
    assert store.totals(profile.id, input_mode="keyboard").actions == 80
    store.close()


def test_existing_activity_database_migrates_runs_to_camera_mode(tmp_path: Path):
    path = tmp_path / "activity.sqlite3"
    db = sqlite3.connect(path)
    db.execute(
        """
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY,
            profile_id INTEGER NOT NULL,
            started_at_utc TEXT NOT NULL,
            local_date TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            song_key TEXT NOT NULL,
            chart_key TEXT NOT NULL,
            outcome TEXT NOT NULL,
            progress REAL NOT NULL,
            counts_as_song INTEGER NOT NULL,
            stomps INTEGER NOT NULL,
            punches INTEGER NOT NULL,
            score INTEGER NOT NULL
        )
        """
    )
    db.commit()
    db.close()

    store = ActivityStore(path)
    columns = {
        row["name"] for row in store._db.execute("PRAGMA table_info(runs)").fetchall()
    }

    assert "input_mode" in columns
    store.close()


def test_streak_keeps_yesterdays_run_until_today_reaches_goal(tmp_path: Path):
    store = ActivityStore(tmp_path / "activity.sqlite3")
    profile = store.create_profile("Player")
    today = date(2026, 8, 19)

    for offset in (2, 1):
        day = today - timedelta(days=offset)
        store.record_run(
            RunActivity(
                profile_id=profile.id,
                started_at_utc=f"{day.isoformat()}T12:00:00+00:00",
                local_date=day.isoformat(),
                duration_seconds=60,
                song_key="song",
                chart_key="chart",
                outcome="completed",
                progress=1.0,
                counts_as_song=True,
                stomps=DAILY_ACTIVITY_GOAL,
                punches=0,
                score=1000,
            )
        )

    # Today is below goal; the two-day streak through yesterday still stands.
    store.record_run(
        RunActivity(
            profile_id=profile.id,
            started_at_utc=f"{today.isoformat()}T12:00:00+00:00",
            local_date=today.isoformat(),
            duration_seconds=30,
            song_key="song",
            chart_key="chart",
            outcome="escaped",
            progress=0.30,
            counts_as_song=True,
            stomps=DAILY_ACTIVITY_GOAL - 1,
            punches=0,
            score=0,
        )
    )
    assert store.streaks(profile.id, today=today) == (2, 2)

    # A second run pushes today over the target and extends the streak.
    store.record_run(
        RunActivity(
            profile_id=profile.id,
            started_at_utc=f"{today.isoformat()}T13:00:00+00:00",
            local_date=today.isoformat(),
            duration_seconds=10,
            song_key="song",
            chart_key="chart",
            outcome="escaped",
            progress=0.05,
            counts_as_song=False,
            stomps=1,
            punches=0,
            score=0,
        )
    )
    assert store.streaks(profile.id, today=today) == (3, 3)
    store.close()


def test_week_starts_on_monday():
    assert week_start(date(2026, 8, 19)) == date(2026, 8, 17)


def test_weekly_records_compare_the_same_number_of_days(tmp_path: Path):
    store = ActivityStore(tmp_path / "activity.sqlite3")
    profile = store.create_profile("Player")

    runs = (
        # Monday and Wednesday count in a three-day comparison; Friday does not.
        ("2026-07-27", 60, 10, 1),
        ("2026-07-29", 30, 5, 1),
        ("2026-07-31", 900, 500, 5),
        # This later week holds the comparable time and action records.
        ("2026-08-03", 120, 20, 1),
        ("2026-08-04", 60, 20, 2),
    )
    for local_date, duration, actions, songs in runs:
        store.record_run(
            RunActivity(
                profile_id=profile.id,
                started_at_utc=f"{local_date}T12:00:00+00:00",
                local_date=local_date,
                duration_seconds=duration,
                song_key="song",
                chart_key="chart",
                outcome="completed",
                progress=1.0,
                counts_as_song=bool(songs),
                stomps=actions,
                punches=0,
                score=1000,
            )
        )
        for song_index in range(1, songs):
            store.record_run(
                RunActivity(
                    profile_id=profile.id,
                    started_at_utc=f"{local_date}T12:0{song_index}:00+00:00",
                    local_date=local_date,
                    duration_seconds=0,
                    song_key=f"song-{song_index}",
                    chart_key=f"chart-{song_index}",
                    outcome="completed",
                    progress=1.0,
                    counts_as_song=True,
                    stomps=0,
                    punches=0,
                    score=0,
                )
            )

    records = store.weekly_records(profile.id, before=date(2026, 8, 10), day_count=3)
    assert records.has_history is True
    assert records.duration_seconds == 180
    assert records.actions == 40
    assert records.songs == 3
    store.close()
