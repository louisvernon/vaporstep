from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .scoring import RunStats
from .song import LoadedChart


_FINGERPRINT_HEX_CHARS = 12
_AUDIO_HASH_CACHE: dict[tuple[str, int, int], str] = {}


@dataclass(frozen=True)
class ResultProvenance:
    artist: str = ""
    chart_creator: str = ""
    song_chart_digest: str = ""


_current = ResultProvenance()


def _sha256_file(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        stat = path.stat()
        key = (str(path), int(stat.st_size), int(stat.st_mtime_ns))
    except OSError:
        return ""

    cached = _AUDIO_HASH_CACHE.get(key)
    if cached is not None:
        return cached

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""

    value = digest.hexdigest()
    _AUDIO_HASH_CACHE[key] = value
    return value


def _stable_time(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{float(value):.9f}"


def song_chart_fingerprint(chart: LoadedChart) -> str:
    """Hash the exact audio plus VaporStep's effective loaded chart."""
    payload = {
        "schema": "vaporstep-song-chart-v1",
        "audio_sha256": _sha256_file(chart.song.music_path),
        "notes": [
            {
                "kind": note.kind.value,
                "lanes": list(note.lanes),
                "time": _stable_time(note.time),
                "beat": _stable_time(note.beat),
                "end_time": _stable_time(note.end_time),
                "end_beat": _stable_time(note.end_beat),
            }
            for note in chart.notes
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def play_fingerprint(song_chart_digest: str, stats: RunStats) -> str:
    """Hash the visible score summary, bound to the song/chart fingerprint."""
    payload = {
        "schema": "vaporstep-play-v1",
        "song_chart": song_chart_digest,
        "score": int(stats.score),
        "perfect": int(stats.perfects),
        "great": int(stats.greats),
        "hit": int(stats.basic_hits),
        "missed": int(stats.misses),
        "dropped_holds": int(stats.dropped_holds),
        "max_combo": int(stats.max_combo),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def display_fingerprint(digest: str) -> str:
    compact = digest[:_FINGERPRINT_HEX_CHARS].upper()
    return " ".join(compact[index : index + 4] for index in range(0, len(compact), 4))


def register_loaded_chart(chart: LoadedChart, *, chart_creator: str = "") -> ResultProvenance:
    global _current
    _current = ResultProvenance(
        artist=chart.song.artist or "",
        chart_creator=(chart_creator or "").strip(),
        song_chart_digest=song_chart_fingerprint(chart),
    )
    return _current


def current_result_provenance() -> ResultProvenance:
    return _current
