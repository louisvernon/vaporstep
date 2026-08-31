#!/usr/bin/env python3
"""Deterministic gameplay benchmark with renderer phase timings.

This deliberately avoids a webcam and song files. It is intended for A/B runs
on the same machine; absolute numbers from unrelated machines are not directly
comparable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np
import pygame

from vaporstep.domain import BodyPoint, BodyState, ChainMode, GameNote, HitQuality, NoteKind
from vaporstep.renderer import Renderer
from vaporstep.scoring import RunStats
from vaporstep.session import GameSession


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values) if values else 0.0,
        "median": statistics.median(values) if values else 0.0,
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": max(values, default=0.0),
    }


def _notes(count: int = 6000, spacing: float = 0.05) -> list[GameNote]:
    notes = []
    hand_ordinal = 0
    for index in range(count):
        kind = NoteKind.HANDS if index % 3 == 0 else NoteKind.FOOT
        lane = index % 4 + 1
        lanes = (lane, ((lane + 1) % 4) + 1) if index % 17 == 0 else (lane,)
        note = GameNote(
            time=index * spacing,
            beat=index * spacing * 2.0,
            lanes=lanes,
            kind=kind,
        )
        if kind == NoteKind.HANDS:
            note.visual_ordinal = hand_ordinal
            hand_ordinal += 1
        notes.append(note)
    return notes


def _body(timestamp: float) -> BodyState:
    def point(x: float, y: float, lane: int) -> BodyPoint:
        return BodyPoint(x=x, y=y, lane=lane, visible=True, source_weight=0.65)

    return BodyState(
        left_wrist=point(0.28, 0.28, 1),
        right_wrist=point(0.72, 0.28, 4),
        left_hand_control=point(0.28, 0.28, 1),
        right_hand_control=point(0.72, 0.28, 4),
        left_knee=point(0.38, 0.68, 2),
        right_knee=point(0.62, 0.68, 3),
        left_ankle=point(0.36, 0.90, 2),
        right_ankle=point(0.64, 0.90, 3),
        left_foot_control=point(0.37, 0.82, 2),
        right_foot_control=point(0.63, 0.82, 3),
        pose_visible=True,
        timestamp=timestamp,
    )


def _masks() -> tuple[np.ndarray, ...]:
    yy, xx = np.mgrid[0:480, 0:640]
    masks = []
    for offset in range(8):
        center_x = 320 + offset * 3
        body = ((xx - center_x) / 105.0) ** 2 + ((yy - 265) / 210.0) ** 2
        masks.append(np.clip(1.0 - body, 0.0, 1.0).astype(np.float32))
    return tuple(masks)


def _renderer_benchmark(frames: int, warmup: int) -> dict[str, object]:
    pygame.font.init()
    screen = pygame.Surface((1280, 720))
    renderer = Renderer(screen)
    renderer.set_profiling_enabled(True)
    notes = _notes()
    note_times = tuple(note.time for note in notes)
    session = GameSession(demo_notes=notes, chain_mode=ChainMode.OFF)
    stats = RunStats(total_notes=len(notes))
    for _ in range(45):
        stats.register_hit(HitQuality.PERFECT)
    masks = _masks()
    frame_times: list[float] = []
    window_times: list[float] = []
    visible_counts: list[int] = []
    phase_times: dict[str, list[float]] = {}

    total_frames = warmup + frames
    start_cpu = time.process_time()
    start_wall = time.perf_counter()
    for frame in range(total_frames):
        song_time = 10.0 + frame / 60.0
        song_beat = song_time * 2.0
        judged_index = min(len(notes) - 1, int(song_time / 0.05))
        judged = session.notes[judged_index]
        if not judged.judged:
            judged.judged = True
            judged.hit = True
            judged.judged_at = song_time
            judged.judgement = (HitQuality.PERFECT, HitQuality.GREAT, HitQuality.HIT)[frame % 3]

        window_started = time.perf_counter()
        visible = session.render_notes(song_time, song_beat)
        window_ms = (time.perf_counter() - window_started) * 1000.0
        started = time.perf_counter()
        renderer.draw(
            body=_body(song_time),
            mask=masks[(frame // 2) % len(masks)],
            notes=visible,
            song_time=song_time,
            song_beat=song_beat,
            status="READY",
            debug=False,
            pose_fps=30.0,
            input_name="benchmark",
            song_title="DENSE BENCHMARK",
            chart_label="SYNTHETIC",
            stats=stats,
            running=True,
            beat_pulse=(frame % 30) / 29.0,
            downbeat=frame % 120 == 0,
            hand_enabled=True,
            foot_enabled=True,
            chain_mode=ChainMode.OFF,
            show_body_markers=True,
        )
        frame_ms = (time.perf_counter() - started) * 1000.0

        if frame >= warmup:
            frame_times.append(frame_ms)
            window_times.append(window_ms)
            visible_counts.append(len(visible))
            for name, value in renderer.phase_times_ms.items():
                phase_times.setdefault(name, []).append(value)

    wall = time.perf_counter() - start_wall
    cpu = time.process_time() - start_cpu
    return {
        "total_notes": len(note_times),
        "visible_notes_mean": statistics.fmean(visible_counts),
        "note_window_ms": _summary(window_times),
        "render_ms": _summary(frame_times),
        "phase_mean_ms": {
            name: statistics.fmean(values) for name, values in sorted(phase_times.items())
        },
        "cpu_seconds": cpu,
        "wall_seconds": wall,
        "cpu_core_equivalents": cpu / max(wall, 1e-9),
    }


def _session_benchmark(frames: int, warmup: int) -> dict[str, object]:
    session = GameSession(demo_notes=_notes(), chain_mode=ChainMode.OFF)
    session.running = True
    session.audio_started = True
    session.audio_loaded = False
    samples: list[float] = []
    total_frames = warmup + frames

    for frame in range(total_frames):
        song_time = frame / 60.0
        session.started = time.monotonic() - song_time
        started = time.perf_counter()
        session.update(BodyState(timestamp=song_time + 1.0), ready_to_start=True)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if frame >= warmup:
            samples.append(elapsed_ms)

    semantic = {
        "hits": session.stats.hits,
        "misses": session.stats.misses,
        "score": session.stats.score,
        "pending_cursor": session._pending_note_cursor,
    }
    checksum = hashlib.sha256(json.dumps(semantic, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "update_ms": _summary(samples),
        "semantic": semantic,
        "semantic_sha256": checksum,
    }


def _comparison(current: dict, baseline: dict) -> dict[str, object]:
    paths = {
        "render_median": ("renderer", "render_ms", "median"),
        "render_p95": ("renderer", "render_ms", "p95"),
        "note_window_median": ("renderer", "note_window_ms", "median"),
        "session_median": ("session", "update_ms", "median"),
    }
    comparison: dict[str, object] = {}
    for name, path in paths.items():
        before = baseline
        after = current
        for key in path:
            before = before[key]
            after = after[key]
        comparison[name] = 100.0 * (float(after) - float(before)) / max(float(before), 1e-9)

    current_phases = current["renderer"]["phase_mean_ms"]
    baseline_phases = baseline["renderer"]["phase_mean_ms"]
    phase_comparison = {}
    for name in sorted(current_phases.keys() & baseline_phases.keys()):
        before = float(baseline_phases[name])
        after = float(current_phases[name])
        phase_comparison[name] = 100.0 * (after - before) / max(before, 1e-9)
    comparison["renderer_phases"] = phase_comparison
    comparison["semantic_checksum_match"] = (
        current["session"]["semantic_sha256"] == baseline["session"]["semantic_sha256"]
    )
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()

    result = {
        "metadata": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "resolution": "1280x720",
            "frames": max(1, args.frames),
            "warmup": max(0, args.warmup),
        },
        "renderer": _renderer_benchmark(max(1, args.frames), max(0, args.warmup)),
        "session": _session_benchmark(max(1, args.frames), max(0, args.warmup)),
    }
    if args.compare:
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        result["comparison_percent"] = _comparison(result, baseline)

    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.json:
        args.json.write_text(rendered + "\n", encoding="utf-8")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
