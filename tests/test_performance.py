from types import SimpleNamespace

import pygame

from vaporstep.app import (
    _inference_completion_percent,
    _next_profile_level,
    _profile_lines,
    _profile_toggle_requested,
)
from vaporstep.performance import AdaptiveFrameRate, RuntimeProfiler


def test_runtime_profiler_reports_rolling_latency_and_deadlines() -> None:
    profiler = RuntimeProfiler(history=3)
    for work_ms in (10.0, 20.0, 40.0, 5.0):
        profiler.record(
            update_ms=1.0,
            render_ms=work_ms - 2.0,
            flip_ms=1.0,
            work_ms=work_ms,
        )

    snapshot = profiler.snapshot()
    assert snapshot.samples == 3
    assert snapshot.work_ms == (20.0 + 40.0 + 5.0) / 3.0
    assert snapshot.work_p95_ms == 40.0
    assert snapshot.missed_60hz == 2
    assert snapshot.missed_30hz == 1


def test_runtime_profiler_clear_removes_history() -> None:
    profiler = RuntimeProfiler()
    profiler.record(update_ms=1, render_ms=2, flip_ms=3, work_ms=6)
    profiler.clear()
    assert profiler.snapshot().samples == 0


def test_adaptive_frame_rate_drops_and_recovers_with_hysteresis() -> None:
    controller = AdaptiveFrameRate(drop_samples=10, recover_samples=20)

    for _ in range(10):
        controller.observe(24.0)
    assert controller.target_fps == 30

    # Work that is merely below 16.7 ms is not enough to bounce immediately
    # back to 60; recovery requires sustained, generous headroom.
    for _ in range(20):
        controller.observe(15.0)
    assert controller.target_fps == 30

    for _ in range(20):
        controller.observe(10.0)
    assert controller.target_fps == 60


def test_adaptive_frame_rate_ignores_occasional_60_fps_spike() -> None:
    controller = AdaptiveFrameRate(drop_samples=20, recover_samples=40)
    for index in range(20):
        controller.observe(22.0 if index == 0 else 10.0)

    assert controller.target_fps == 60


def test_f3_cycles_off_basic_detailed_and_applies_in_calibration() -> None:
    assert [_next_profile_level(level) for level in (0, 1, 2)] == [1, 2, 0]
    event = SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_F3)
    assert _profile_toggle_requested("game", event)
    assert _profile_toggle_requested("calibration", event)
    assert not _profile_toggle_requested("home", event)


def test_basic_profile_lines_distinguish_omitted_and_flushed_frames() -> None:
    profiler = RuntimeProfiler()
    profiler.record(update_ms=1.0, render_ms=20.0, flip_ms=1.0, work_ms=22.0)
    pose = SimpleNamespace(
        frames_captured=100,
        frames_intentionally_skipped=20,
        frames_dropped=5,
        frames_submitted=75,
        extra_frames_submitted=12,
        extra_frames_flushed=4,
        baseline_frames_flushed=1,
        capture_fps=30.0,
        submitted_fps=20.0,
        pose_fps=19.5,
        inference_latency_ms=67.7,
        inference_service_ms=45.0,
        baseline_fps=15.0,
        inference_capacity_fps=22.2,
        inference_queue_depth=1,
        inference_queue_age_ms=32.0,
        pose_age_ms=84.0,
    )

    basic = _profile_lines(
        profiler.snapshot(), pose, target_fps=30, actual_fps=29.8, detailed=False
    )
    detailed = _profile_lines(
        profiler.snapshot(), pose, target_fps=30, actual_fps=29.8, detailed=True
    )

    assert basic == (
        "FRAME RATE  actual=29.8fps  target=30fps",
        "INFERENCE  results=19.5fps  latency=67.7ms  omitted=20%  flushed=5%",
    )
    assert any("MAIN THREAD" in line for line in detailed)
    assert any("CAMERA / INFERENCE" in line for line in detailed)
    assert any("SAMPLER" in line and "queue age=32ms" in line for line in detailed)
    assert any("omitted=20" in line and "flushed=5" in line for line in detailed)


def test_inference_completion_percent_waits_for_warmup_and_uses_submissions() -> None:
    warming = SimpleNamespace(frames_captured=29, frames_submitted=10)
    snapshot = SimpleNamespace(frames_captured=100, frames_submitted=74)

    assert _inference_completion_percent(warming) is None
    assert _inference_completion_percent(snapshot) == 74
