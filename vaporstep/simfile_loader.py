from __future__ import annotations

from fractions import Fraction
import math
from pathlib import Path
from typing import Iterable, Sequence

from .chains import assign_implicit_chains, assign_sustains
from .domain import GameNote, NoteKind, lanes_tuple
from .song import BeatMarker, ChartInfo, LoadedChart, SongInfo


AUDIO_EXTENSIONS = (".ogg", ".mp3", ".wav", ".flac", ".m4a")
MAX_SIMFILE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_ASSET_BYTES = 32 * 1024 * 1024


def _safe_meter(value: str | None) -> int:
    try:
        return int(value or "1")
    except (TypeError, ValueError):
        return 1


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _contained_file(root: Path, candidate: Path, *, max_bytes: int | None = None) -> Path | None:
    """Return a real file only when it resolves inside ``root``.

    Stepfiles are user-supplied content. Asset fields must not be able to use an
    absolute path, ``..`` traversal, or a symlink to make VaporStep open files
    elsewhere on the machine.
    """
    try:
        root_resolved = root.resolve()
        resolved = candidate.resolve()
        resolved.relative_to(root_resolved)
        if not resolved.is_file():
            return None
        if max_bytes is not None and resolved.stat().st_size > max_bytes:
            return None
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


def _resolve_asset(song_dir: Path, value: str | None, *, max_bytes: int | None = None) -> Path | None:
    if not value:
        return None
    relative = Path(value)
    if relative.is_absolute():
        return None
    return _contained_file(song_dir, song_dir / relative, max_bytes=max_bytes)


def _fallback_audio(song_dir: Path) -> Path | None:
    try:
        files = sorted(p for p in song_dir.iterdir() if p.is_file())
    except OSError:
        return None
    for ext in AUDIO_EXTENSIONS:
        for path in files:
            if path.suffix.lower() == ext:
                safe = _contained_file(song_dir, path)
                if safe is not None:
                    return safe
    return None


def _pick_simfile(paths: Sequence[Path]) -> Path | None:
    """Prefer SSC when a song directory contains both SSC and SM."""
    ssc = sorted(p for p in paths if p.suffix.lower() == ".ssc")
    if ssc:
        return ssc[0]
    sm = sorted(p for p in paths if p.suffix.lower() == ".sm")
    return sm[0] if sm else None


def discover_simfiles(root: Path) -> list[Path]:
    """Find one canonical .ssc/.sm file per song directory."""
    root = root.expanduser().resolve()
    if not root.exists():
        return []

    by_dir: dict[Path, list[Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".sm", ".ssc"):
            continue
        safe = _contained_file(root, path, max_bytes=MAX_SIMFILE_BYTES)
        if safe is not None:
            by_dir.setdefault(safe.parent, []).append(safe)

    result: list[Path] = []
    for paths in by_dir.values():
        chosen = _pick_simfile(paths)
        if chosen is not None:
            result.append(chosen)
    return sorted(result)


def scan_song(path: Path) -> SongInfo | None:
    """Read metadata plus lightweight VaporStep stats for compatible charts."""
    try:
        if path.stat().st_size > MAX_SIMFILE_BYTES:
            raise ValueError(f"Stepfile is larger than {MAX_SIMFILE_BYTES // (1024 * 1024)} MiB")
    except OSError as exc:
        raise ValueError(f"Could not read stepfile: {exc}") from exc

    import simfile
    from simfile.notes import NoteData
    from simfile.timing import TimingData
    from simfile.timing.engine import TimingEngine

    sim = simfile.open(str(path), strict=False)
    charts: list[ChartInfo] = []
    for index, chart in enumerate(sim.charts):
        stepstype = (chart.stepstype or "").strip().lower()
        try:
            columns = NoteData(chart).columns
        except (TypeError, ValueError):
            continue
        if (stepstype, columns) not in {
            ("dance-single", 4),
            ("ds3ddx-single", 8),
        }:
            continue

        target_count = foot_count = hand_count = 0
        bpm_min = bpm_max = 0.0
        chain_count = 0
        try:
            timing = TimingData(sim, chart)
            bpms = [float(seg.value) for seg in timing.bpms if float(seg.value) > 0]
            if bpms:
                bpm_min, bpm_max = min(bpms), max(bpms)
            engine = TimingEngine(timing)
            rows = list(_actionable_rows(chart))
            if stepstype == "ds3ddx-single":
                converted, _ = convert_ds3ddx_rows(rows, engine)
            else:
                converted, _ = convert_rows(rows, engine)
            chains = assign_implicit_chains(converted)
            chain_count = len(chains)
            target_count = len(converted)
            foot_count = sum(1 for note in converted if note.kind == NoteKind.FOOT)
            hand_count = sum(1 for note in converted if note.kind == NoteKind.HANDS)
        except Exception:
            # Browser metadata should never make an otherwise playable chart
            # disappear; detailed load errors remain deferred until selection.
            pass

        charts.append(
            ChartInfo(
                index=index,
                difficulty=chart.difficulty or "Unknown",
                meter=_safe_meter(chart.meter),
                description=chart.description or "",
                chart_name=getattr(chart, "chartname", None) or "",
                target_count=target_count,
                foot_count=foot_count,
                hand_count=hand_count,
                bpm_min=bpm_min,
                bpm_max=bpm_max,
                chain_count=chain_count,
            )
        )

    if not charts:
        return None
    charts.sort(key=lambda c: (c.meter, c.difficulty.lower(), c.index))

    song_dir = path.parent
    music_path = _resolve_asset(song_dir, sim.music) or _fallback_audio(song_dir)
    sample_start = _safe_float(
        getattr(sim, "samplestart", None) or getattr(sim, "sample_start", None),
        0.0,
    )
    sample_length = _safe_float(
        getattr(sim, "samplelength", None) or getattr(sim, "sample_length", None),
        15.0,
    )
    if sample_length <= 0:
        sample_length = 15.0

    return SongInfo(
        simfile_path=path,
        song_dir=song_dir,
        title=sim.title or song_dir.name,
        subtitle=sim.subtitle or "",
        artist=sim.artist or "",
        music_path=music_path,
        banner_path=_resolve_asset(song_dir, sim.banner, max_bytes=MAX_IMAGE_ASSET_BYTES),
        background_path=_resolve_asset(song_dir, sim.background, max_bytes=MAX_IMAGE_ASSET_BYTES),
        charts=tuple(charts),
        sample_start=max(0.0, sample_start),
        sample_length=max(3.0, sample_length),
    )


def scan_library(root: Path) -> tuple[list[SongInfo], list[str]]:
    songs: list[SongInfo] = []
    errors: list[str] = []
    for path in discover_simfiles(root):
        try:
            song = scan_song(path)
            if song is not None:
                songs.append(song)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    songs.sort(key=lambda s: (s.display_title.casefold(), s.artist.casefold()))
    return songs, errors


def _actionable_rows(chart) -> Iterable[list[object]]:
    """Yield same-beat rows containing taps/hold/roll heads.

    Existing held notes do not appear on later rows, which preserves our rule
    that only note heads beginning together turn a two-note jump into a hand target.
    """
    from simfile.notes import NoteData, NoteType
    from simfile.notes.group import OrphanedNotes, SameBeatNotes, group_notes

    included = frozenset((NoteType.TAP, NoteType.HOLD_HEAD, NoteType.ROLL_HEAD, NoteType.TAIL))
    return group_notes(
        NoteData(chart),
        include_note_types=included,
        same_beat_notes=SameBeatNotes.JOIN_ALL,
        join_heads_to_tails=True,
        orphaned_head=OrphanedNotes.KEEP_ORPHAN,
        orphaned_tail=OrphanedNotes.DROP_ORPHAN,
    )


def _common_tail_beat(row: Sequence[object]):
    """Return a shared tail beat if every head in a row is a matching hold."""
    tail_beats = []
    for note in row:
        tail = getattr(note, "tail_beat", None)
        if tail is None:
            return None
        tail_beats.append(tail)
    if not tail_beats or any(beat != tail_beats[0] for beat in tail_beats[1:]):
        return None
    return tail_beats[0]


def convert_rows(rows: Iterable[Sequence[object]], engine) -> tuple[list[GameNote], int]:
    """Convert grouped simfile rows into VaporStep notes.

    One note head = lower-body target. Two simultaneous heads = two hand
    targets. Rows with more than two heads are ignored in this first pass.
    """
    notes: list[GameNote] = []
    skipped_rows = 0

    for row in rows:
        if not row:
            continue
        if len(row) not in (1, 2):
            skipped_rows += 1
            continue

        beat = row[0].beat
        if not engine.hittable(beat):
            continue
        lanes = lanes_tuple(int(note.column) + 1 for note in row)
        kind = NoteKind.FOOT if len(row) == 1 else NoteKind.HANDS
        start = float(engine.time_at(beat))

        end_time = None
        tail_beat = _common_tail_beat(row)
        if tail_beat is not None:
            end_time = float(engine.time_at(tail_beat))
            if end_time <= start:
                end_time = None

        notes.append(
            GameNote(
                time=start,
                lanes=lanes,
                kind=kind,
                end_time=end_time,
                beat=float(beat),
                end_beat=float(tail_beat) if tail_beat is not None and end_time is not None else None,
            )
        )

    notes.sort(key=lambda n: (n.time, n.lanes))
    return notes, skipped_rows



# Dance Station 3DDX single charts use eight columns.  The canonical button
# order is HandLeft, FootDownLeft, FootUpLeft, HandUp, HandDown,
# FootUpRight, FootDownRight, HandRight.  VaporStep maps those physical
# controls into its four horizontal hand and foot lanes.
DS3DDX_COLUMN_MAP = {
    0: (NoteKind.HANDS, 1),
    1: (NoteKind.FOOT, 1),
    2: (NoteKind.FOOT, 2),
    3: (NoteKind.HANDS, 2),
    4: (NoteKind.HANDS, 3),
    5: (NoteKind.FOOT, 3),
    6: (NoteKind.FOOT, 4),
    7: (NoteKind.HANDS, 4),
}


def convert_ds3ddx_rows(rows: Iterable[Sequence[object]], engine) -> tuple[list[GameNote], int]:
    """Convert 8-column ds3ddx-single rows into explicit hand/foot targets.

    A single source row may contain both hand and foot actions.  We emit one
    GameNote per body class at the same timestamp, allowing e.g. a foot target
    and a hand target to arrive together.  More than two simultaneous targets
    for one body class cannot be satisfied by one player and are skipped.
    """
    notes: list[GameNote] = []
    skipped_groups = 0

    for row in rows:
        if not row:
            continue
        beat = row[0].beat
        if not engine.hittable(beat):
            continue
        start = float(engine.time_at(beat))

        groups: dict[NoteKind, list[object]] = {NoteKind.FOOT: [], NoteKind.HANDS: []}
        mapped_lanes: dict[NoteKind, list[int]] = {NoteKind.FOOT: [], NoteKind.HANDS: []}
        for note in row:
            mapped = DS3DDX_COLUMN_MAP.get(int(note.column))
            if mapped is None:
                continue
            kind, lane = mapped
            groups[kind].append(note)
            mapped_lanes[kind].append(lane)

        for kind in (NoteKind.FOOT, NoteKind.HANDS):
            group = groups[kind]
            if not group:
                continue
            lanes = lanes_tuple(mapped_lanes[kind])
            if len(lanes) > 2:
                skipped_groups += 1
                continue

            end_time = None
            tail_beat = _common_tail_beat(group)
            if tail_beat is not None:
                end_time = float(engine.time_at(tail_beat))
                if end_time <= start:
                    end_time = None

            notes.append(
                GameNote(
                    time=start,
                    lanes=lanes,
                    kind=kind,
                    end_time=end_time,
                    beat=float(beat),
                    end_beat=float(tail_beat) if tail_beat is not None and end_time is not None else None,
                )
            )

    notes.sort(key=lambda n: (n.time, n.kind.value, n.lanes))
    return notes, skipped_groups

def load_chart(song: SongInfo, chart_info: ChartInfo) -> LoadedChart:
    if song.simfile_path.stat().st_size > MAX_SIMFILE_BYTES:
        raise ValueError(f"Stepfile is larger than {MAX_SIMFILE_BYTES // (1024 * 1024)} MiB")

    import simfile
    from simfile.timing import TimingData
    from simfile.timing.engine import TimingEngine

    sim = simfile.open(str(song.simfile_path), strict=False)
    chart = sim.charts[chart_info.index]
    timing = TimingData(sim, chart)
    engine = TimingEngine(timing)
    rows = list(_actionable_rows(chart))
    stepstype = (chart.stepstype or "").strip().lower()
    if stepstype == "ds3ddx-single":
        notes, skipped_rows = convert_ds3ddx_rows(rows, engine)
    else:
        notes, skipped_rows = convert_rows(rows, engine)
    chains, sustains = assign_sustains(notes)

    initial_bpm = float(timing.bpms[0].value) if timing.bpms else 120.0
    last_note_time = max((n.end_time or n.time for n in notes), default=0.0)

    # Precompute integer beat times using the same timing engine that resolves
    # BPM changes/stops/delays/warps. Renderer pulse effects can therefore stay
    # attached to chart timing without depending on source-format details.
    max_beat = 0.0
    for row in rows:
        for note in row:
            max_beat = max(max_beat, float(note.beat))
            tail = getattr(note, "tail_beat", None)
            if tail is not None:
                max_beat = max(max_beat, float(tail))
    beat_markers: list[BeatMarker] = []
    previous_time: float | None = None
    for beat in range(max(1, int(math.ceil(max_beat)) + 9)):
        try:
            marker_time = float(engine.time_at(Fraction(beat, 1)))
        except Exception:
            continue
        # Warps can collapse multiple beats onto the same timestamp. A single
        # visual pulse at that time is clearer than several stacked pulses.
        if previous_time is not None and marker_time <= previous_time + 1e-6:
            continue
        beat_markers.append(BeatMarker(marker_time, beat))
        previous_time = marker_time

    return LoadedChart(
        song=song,
        chart=chart_info,
        notes=tuple(notes),
        initial_bpm=initial_bpm,
        last_note_time=last_note_time,
        beat_markers=tuple(beat_markers),
        skipped_rows=skipped_rows,
        timing_engine=engine,
        chains=chains,
        sustains=sustains,
    )
