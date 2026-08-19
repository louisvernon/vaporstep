from __future__ import annotations

from pathlib import Path


def vaporstep_home() -> Path:
    return Path.home() / "VaporStep"


def songs_dir() -> Path:
    return vaporstep_home() / "Songs"


def state_dir() -> Path:
    return vaporstep_home() / "State"


def settings_path() -> Path:
    return state_dir() / "settings.json"


def highscores_path() -> Path:
    return state_dir() / "highscores.json"


def activity_path() -> Path:
    return state_dir() / "activity.sqlite3"


def song_index_path() -> Path:
    return state_dir() / "song_index.json"


def cache_dir() -> Path:
    return state_dir() / "Cache"


def recordings_dir() -> Path:
    return vaporstep_home() / "Recordings"
