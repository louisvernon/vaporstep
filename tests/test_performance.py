from vaporstep.performance import RuntimeProfiler


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
