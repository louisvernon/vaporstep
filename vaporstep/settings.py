from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path

from .config import PLAYER_HORIZONTAL_ZOOM
from .model_asset import DEFAULT_POSE_MODEL_MODE, normalize_pose_model_mode
from .user_paths import settings_path, songs_dir


MIN_HORIZONTAL_REACH = 1.00
MAX_HORIZONTAL_REACH = 2.00
HORIZONTAL_REACH_STEP = 0.05
PRIVACY_NOTICE_VERSION = 2
PLAYER_VISUALS = ("silhouette", "character")
DEFAULT_PLAYER_VISUAL = "character"


def default_settings_path() -> Path:
    return settings_path()


def default_song_folder() -> str:
    return str(songs_dir())


def clamp_horizontal_reach(value: float) -> float:
    value = max(MIN_HORIZONTAL_REACH, min(MAX_HORIZONTAL_REACH, float(value)))
    # Avoid accumulating float noise when repeatedly stepping in the UI.
    return round(value, 2)


def normalize_player_visual(value: object) -> str:
    visual = str(value or "").strip().casefold()
    if visual == "skeleton":
        return "character"
    return visual if visual in PLAYER_VISUALS else DEFAULT_PLAYER_VISUAL


def normalize_player_character_filename(value: object) -> str:
    """Return a safe user-character basename, or empty for built-in/fallback."""
    filename = str(value or "").strip()
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or not filename.casefold().endswith(".svg")
    ):
        return ""
    return filename


@dataclass
class AppSettings:
    song_folder: str = field(default_factory=default_song_folder)
    camera_index: int = 0
    camera_enabled: bool = True
    horizontal_reach: float = PLAYER_HORIZONTAL_ZOOM
    player_visual: str = DEFAULT_PLAYER_VISUAL
    player_character_filename: str = ""
    pose_model_mode: str = DEFAULT_POSE_MODEL_MODE
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
            song_folder=str(self.song_folder or default_song_folder()),
            camera_index=max(0, int(self.camera_index)),
            camera_enabled=bool(self.camera_enabled),
            horizontal_reach=clamp_horizontal_reach(self.horizontal_reach),
            player_visual=normalize_player_visual(self.player_visual),
            player_character_filename=normalize_player_character_filename(
                self.player_character_filename
            ),
            pose_model_mode=normalize_pose_model_mode(self.pose_model_mode),
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
        self._restore_player_character_selection()
        default_path = Path(default_song_folder())
        if self.settings.song_path == default_path:
            try:
                default_path.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    def _restore_player_character_selection(self) -> None:
        """Restore a saved SVG selection, falling back safely to built-in."""
        from .svg_character_renderer import (
            discover_character_files,
            set_active_character_filename,
        )

        filename = normalize_player_character_filename(
            self.settings.player_character_filename
        )
        if self.settings.player_visual != "character" or not filename:
            self.settings.player_character_filename = ""
            set_active_character_filename(None)
            return

        available = {path.name for path in discover_character_files()}
        if filename in available:
            self.settings.player_character_filename = filename
            set_active_character_filename(filename)
            return

        # The file may have been renamed/deleted while VaporStep was closed.
        # Keep character mode but fall back to the built-in procedural character.
        self.settings.player_character_filename = ""
        set_active_character_filename(None)

    def _sync_player_character_selection(self) -> None:
        """Capture the live custom-character selection before writing settings."""
        from .svg_character_renderer import (
            active_character_filename,
            discover_character_files,
            set_active_character_filename,
        )

        if self.settings.player_visual != "character":
            self.settings.player_character_filename = ""
            set_active_character_filename(None)
            return

        filename = normalize_player_character_filename(active_character_filename())
        if not filename:
            self.settings.player_character_filename = ""
            return

        available = {path.name for path in discover_character_files()}
        if filename in available:
            self.settings.player_character_filename = filename
            return

        # If an SVG disappears during the current run, do not persist a stale
        # path. The next draw/save uses the built-in character instead.
        self.settings.player_character_filename = ""
        set_active_character_filename(None)

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
                song_folder=str(raw.get("song_folder") or default_song_folder()),
                camera_index=int(raw.get("camera_index", 0)),
                camera_enabled=bool(raw.get("camera_enabled", True)),
                horizontal_reach=float(raw.get("horizontal_reach", PLAYER_HORIZONTAL_ZOOM)),
                player_visual=normalize_player_visual(
                    raw.get("player_visual", DEFAULT_PLAYER_VISUAL)
                ),
                player_character_filename=normalize_player_character_filename(
                    raw.get("player_character_filename", "")
                ),
                pose_model_mode=normalize_pose_model_mode(
                    raw.get("pose_model_mode", DEFAULT_POSE_MODEL_MODE)
                ),
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
        self._sync_player_character_selection()
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
