from types import SimpleNamespace

import pygame

from vaporstep.app import _next_profile_level, _profile_lines, _profile_toggle_requested
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


def test_basic_profile_lines_show_only_requested_live_counters() -> None:
    profiler = RuntimeProfiler()
    profiler.record(update_ms=1.0, render_ms=20.0, flip_ms=1.0, work_ms=22.0)
    pose = SimpleNamespace(
        frames_captured=100,
        frames_dropped=25,
        frames_submitted=75,
        capture_fps=30.0,
        submitted_fps=15.0,
        pose_fps=10.5,
        inference_latency_ms=67.7,
    )

    basic = _profile_lines(
        profiler.snapshot(), pose, target_fps=30, actual_fps=29.8, detailed=False
    )
    detailed = _profile_lines(
        profiler.snapshot(), pose, target_fps=30, actual_fps=29.8, detailed=True
    )

    assert basic == (
        "FRAME RATE  actual=29.8fps  target=30fps",
        "INFERENCE  results=10.5fps  latency=67.7ms  skipped=25 (25%)",
    )
    assert any("MAIN THREAD" in line for line in detailed)
    assert any("CAMERA / INFERENCE" in line for line in detailed)
