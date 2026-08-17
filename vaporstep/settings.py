from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import sys

from .config import PLAYER_HORIZONTAL_ZOOM


MIN_HORIZONTAL_REACH = 1.00
MAX_HORIZONTAL_REACH = 1.35
HORIZONTAL_REACH_STEP = 0.05
PRIVACY_NOTICE_VERSION = 2


def default_settings_path() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "VaporStep" / "settings.json"
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or home)
        return base / "VaporStep" / "settings.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
    return base / "vaporstep" / "settings.json"


def clamp_horizontal_reach(value: float) -> float:
    value = max(MIN_HORIZONTAL_REACH, min(MAX_HORIZONTAL_REACH, float(value)))
    # Avoid accumulating float noise when repeatedly stepping in the UI.
    return round(value, 2)


@dataclass
class AppSettings:
    song_folder: str = ""
    camera_index: int = 0
    horizontal_reach: float = PLAYER_HORIZONTAL_ZOOM
    favorite_song_keys: list[str] = field(default_factory=list)
    played_song_keys: list[str] = field(default_factory=list)
    last_song_key: str = ""
    preferred_difficulty: str = "Medium"
    privacy_notice_version: int = 0

    @property
    def song_path(self) -> Path | None:
        if not self.song_folder:
            return None
        return Path(self.song_folder).expanduser()

    def normalized(self) -> "AppSettings":
        def clean_keys(values) -> list[str]:
            if not isinstance(values, (list, tuple, set)):
                return []
            return sorted({str(value) for value in values if str(value)})

        return AppSettings(
            song_folder=str(self.song_folder or ""),
            camera_index=max(0, int(self.camera_index)),
            horizontal_reach=clamp_horizontal_reach(self.horizontal_reach),
            favorite_song_keys=clean_keys(self.favorite_song_keys),
            played_song_keys=clean_keys(self.played_song_keys),
            last_song_key=str(self.last_song_key or ""),
            preferred_difficulty=str(self.preferred_difficulty or "Medium"),
            privacy_notice_version=max(0, int(self.privacy_notice_version)),
        )


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()
        self.settings = AppSettings()
        self.load()

    def load(self) -> AppSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            self.settings = AppSettings()
            return self.settings

        if not isinstance(raw, dict):
            self.settings = AppSettings()
            return self.settings

        try:
            self.settings = AppSettings(
                song_folder=str(raw.get("song_folder", "") or ""),
                camera_index=int(raw.get("camera_index", 0)),
                horizontal_reach=float(raw.get("horizontal_reach", PLAYER_HORIZONTAL_ZOOM)),
                favorite_song_keys=raw.get("favorite_song_keys", []),
                played_song_keys=raw.get("played_song_keys", []),
                last_song_key=str(raw.get("last_song_key", "") or ""),
                preferred_difficulty=str(raw.get("preferred_difficulty", "Medium") or "Medium"),
                privacy_notice_version=int(raw.get("privacy_notice_version", 0)),
            ).normalized()
        except (TypeError, ValueError):
            self.settings = AppSettings()
        return self.settings

    def save(self) -> None:
        self.settings = self.settings.normalized()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self.settings), indent=2, sort_keys=True), encoding="utf-8")
        if os.name == "posix":
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        tmp.replace(self.path)
