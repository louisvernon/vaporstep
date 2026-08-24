from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import threading

from .simfile_loader import MAX_SIMFILE_BYTES, scan_song
from .song import ChartInfo, SongInfo
from .user_paths import song_index_path


# Version 3 forces a reparse after VaporStep's legacy simfile encoding
# detection changed. Version 2 caches may contain metadata decoded by
# simfile's CP1252-before-CP949 fallback and must not be reused.
INDEX_VERSION = 3


@dataclass(frozen=True)
class LibraryScanSnapshot:
    running: bool = False
    complete: bool = False
    phase: str = "idle"
    folders_scanned: int = 0
    stepfiles_found: int = 0
    files_processed: int = 0
    songs_found: int = 0
    charts_found: int = 0
    cached_songs: int = 0
    parsed_songs: int = 0
    errors: tuple[str, ...] = ()
    songs: tuple[SongInfo, ...] = ()
    root: Path | None = None

    @property
    def progress_ratio(self) -> float | None:
        if self.phase == "discovering" or self.stepfiles_found <= 0:
            return None
        return min(1.0, self.files_processed / self.stepfiles_found)


class LibraryIndexer:
    """Build and refresh a song-library index without blocking the UI thread."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or song_index_path()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._snapshot = LibraryScanSnapshot()

    def snapshot(self) -> LibraryScanSnapshot:
        with self._lock:
            return self._snapshot

    def start(self, root: Path) -> None:
        root = root.expanduser().resolve()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._snapshot = LibraryScanSnapshot(
                running=True,
                phase="discovering",
                root=root,
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(root, generation),
                name="VaporStepLibraryIndexer",
                daemon=True,
            )
            self._thread.start()

    def cached_songs(self, root: Path) -> list[SongInfo]:
        root = root.expanduser().resolve()
        cache = self._load_cache(root)
        songs: list[SongInfo] = []
        for entry in cache.values():
            try:
                songs.append(self._song_from_json(root, entry["song"]))
            except Exception:
                continue
        songs.sort(key=lambda s: (s.display_title.casefold(), s.artist.casefold()))
        return songs

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _publish(self, generation: int, **changes) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            self._snapshot = replace(self._snapshot, **changes)
            return True

    def _run(self, root: Path, generation: int | None = None) -> None:
        # Tests may invoke _run directly; reserve a generation for that call.
        if generation is None:
            with self._lock:
                self._generation += 1
                generation = self._generation
                self._snapshot = LibraryScanSnapshot(running=True, phase="discovering", root=root)

        errors: list[str] = []
        cache = self._load_cache(root)
        paths, folders = self._discover(root, errors, generation)
        if not self._publish(
            generation,
            phase="indexing",
            folders_scanned=folders,
            stepfiles_found=len(paths),
            errors=tuple(errors),
        ):
            return

        songs: list[SongInfo] = []
        new_entries: dict[str, dict] = {}
        cached_count = 0
        parsed_count = 0
        charts_found = 0

        for processed, path in enumerate(paths, start=1):
            if not self._is_current(generation):
                return
            try:
                stat = path.stat()
                relative = path.relative_to(root).as_posix()
                fingerprint = {
                    "mtime_ns": int(stat.st_mtime_ns),
                    "size": int(stat.st_size),
                }
                entry = cache.get(relative)
                song = None
                if (
                    entry is not None
                    and entry.get("mtime_ns") == fingerprint["mtime_ns"]
                    and entry.get("size") == fingerprint["size"]
                ):
                    try:
                        song = self._song_from_json(root, entry["song"])
                        cached_count += 1
                    except Exception:
                        song = None

                if song is None:
                    song = scan_song(path)
                    if song is not None:
                        parsed_count += 1

                if song is not None:
                    songs.append(song)
                    charts_found += len(song.charts)
                    new_entries[relative] = {
                        **fingerprint,
                        "song": self._song_to_json(root, song),
                    }
            except Exception as exc:
                errors.append(f"{path}: {exc}")

            ordered = tuple(sorted(songs, key=lambda s: (s.display_title.casefold(), s.artist.casefold())))
            if not self._publish(
                generation,
                files_processed=processed,
                songs_found=len(songs),
                charts_found=charts_found,
                cached_songs=cached_count,
                parsed_songs=parsed_count,
                errors=tuple(errors),
                songs=ordered,
            ):
                return

        if not self._is_current(generation):
            return
        songs.sort(key=lambda s: (s.display_title.casefold(), s.artist.casefold()))
        try:
            self._save_cache(root, new_entries)
        except OSError as exc:
            errors.append(f"Could not save song index: {exc}")

        self._publish(
            generation,
            running=False,
            complete=True,
            phase="complete",
            files_processed=len(paths),
            songs_found=len(songs),
            charts_found=sum(len(song.charts) for song in songs),
            cached_songs=cached_count,
            parsed_songs=parsed_count,
            errors=tuple(errors),
            songs=tuple(songs),
        )

    def _discover(
        self,
        root: Path,
        errors: list[str],
        generation: int,
    ) -> tuple[list[Path], int]:
        if not root.exists():
            return [], 0
        by_dir: dict[Path, list[Path]] = {}
        folders = 0
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if not self._is_current(generation):
                return [], folders
            folders += 1
            directory = Path(dirpath)
            dirnames[:] = [name for name in dirnames if not (directory / name).is_symlink()]
            candidates: list[Path] = []
            for filename in filenames:
                path = directory / filename
                if path.suffix.lower() not in (".sm", ".ssc"):
                    continue
                try:
                    resolved = path.resolve()
                    resolved.relative_to(root)
                    if not resolved.is_file() or resolved.stat().st_size > MAX_SIMFILE_BYTES:
                        continue
                    candidates.append(resolved)
                except (OSError, RuntimeError, ValueError) as exc:
                    errors.append(f"{path}: {exc}")
            if candidates:
                by_dir[directory.resolve()] = candidates
            if not self._publish(generation, folders_scanned=folders, errors=tuple(errors)):
                return [], folders

        result: list[Path] = []
        for candidates in by_dir.values():
            ssc = sorted(path for path in candidates if path.suffix.lower() == ".ssc")
            sm = sorted(path for path in candidates if path.suffix.lower() == ".sm")
            chosen = ssc[0] if ssc else (sm[0] if sm else None)
            if chosen is not None:
                result.append(chosen)
        return sorted(result), folders

    def _load_cache(self, root: Path) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict) or data.get("version") != INDEX_VERSION:
            return {}
        if data.get("root") != str(root):
            return {}
        entries = data.get("entries", {})
        return entries if isinstance(entries, dict) else {}

    def _save_cache(self, root: Path, entries: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "root": str(root),
            "entries": entries,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _relative(root: Path, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return path.resolve().relative_to(root).as_posix()
        except (OSError, RuntimeError, ValueError):
            return None

    @classmethod
    def _song_to_json(cls, root: Path, song: SongInfo) -> dict:
        return {
            "simfile_path": cls._relative(root, song.simfile_path),
            "song_dir": cls._relative(root, song.song_dir),
            "title": song.title,
            "subtitle": song.subtitle,
            "artist": song.artist,
            "music_path": cls._relative(root, song.music_path),
            "banner_path": cls._relative(root, song.banner_path),
            "background_path": cls._relative(root, song.background_path),
            "charts": [asdict(chart) for chart in song.charts],
            "sample_start": song.sample_start,
            "sample_length": song.sample_length,
        }

    @staticmethod
    def _resolve_relative(root: Path, value: str | None) -> Path | None:
        if not value:
            return None
        candidate = (root / value).resolve()
        candidate.relative_to(root)
        return candidate

    @classmethod
    def _song_from_json(cls, root: Path, data: dict) -> SongInfo:
        simfile_path = cls._resolve_relative(root, data.get("simfile_path"))
        song_dir = cls._resolve_relative(root, data.get("song_dir"))
        if simfile_path is None or song_dir is None:
            raise ValueError("cached song is missing its path")
        charts = tuple(ChartInfo(**item) for item in data.get("charts", []))
        if not charts:
            raise ValueError("cached song has no charts")
        return SongInfo(
            simfile_path=simfile_path,
            song_dir=song_dir,
            title=str(data.get("title", "")),
            subtitle=str(data.get("subtitle", "")),
            artist=str(data.get("artist", "")),
            music_path=cls._resolve_relative(root, data.get("music_path")),
            banner_path=cls._resolve_relative(root, data.get("banner_path")),
            background_path=cls._resolve_relative(root, data.get("background_path")),
            charts=charts,
            sample_start=float(data.get("sample_start", 0.0)),
            sample_length=float(data.get("sample_length", 15.0)),
        )
