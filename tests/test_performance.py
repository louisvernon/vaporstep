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
