from vaporstep.adaptive_sampling import AdaptiveSamplingPolicy, SERVICE_WARMUP_SAMPLES


def _warm(policy: AdaptiveSamplingPolicy, service_ms: float) -> None:
    for _ in range(SERVICE_WARMUP_SAMPLES + 4):
        policy.observe_service(service_ms)


def test_capable_machine_stays_at_full_camera_rate() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 25.0)

    assert policy.full_rate is True
    assert policy.baseline_fps == 30.0
    assert policy.capacity_fps > 30.0


def test_slower_machine_uses_most_capacity_away_from_notes() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)

    assert policy.full_rate is False
    assert 24.0 < policy.capacity_fps < 26.0
    assert 22.0 < policy.baseline_fps < 23.0


def test_timing_window_reserves_explicit_extra_capacity() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)

    assert 24.0 < policy.capacity_fps < 26.0
    assert 14.0 < policy.baseline_fps_for(critical=True) < 16.0


def test_critical_baseline_keeps_ten_fps_floor_on_slower_machine() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 66.6666667)

    assert 14.0 < policy.capacity_fps < 16.0
    assert 13.0 < policy.baseline_fps < 14.0
    assert policy.baseline_fps_for(critical=True) == 10.0


def test_very_slow_machine_cannot_reserve_capacity_it_does_not_have() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 125.0)

    assert policy.full_rate is False
    assert 7.5 < policy.capacity_fps < 8.5
    assert policy.baseline_fps == policy.capacity_fps
    assert policy.baseline_fps_for(critical=True) == policy.capacity_fps


def test_fractional_baseline_does_not_collapse_to_every_other_frame() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)  # 25 Hz capacity -> 22.5 Hz ordinary baseline.

    decisions = []
    timestamp = 1.0
    for _ in range(30):
        decisions.append(policy.decide(timestamp, critical=False))
        timestamp += 1.0 / 30.0

    baseline_count = sum(decision.baseline for decision in decisions)
    assert 21 <= baseline_count <= 24


def test_timing_window_keeps_all_camera_frames_eligible_as_extras() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)  # 25 Hz capacity -> 15 Hz protected baseline.

    decisions = []
    timestamp = 1.0
    for _ in range(30):
        decisions.append(policy.decide(timestamp, critical=True))
        timestamp += 1.0 / 30.0

    baseline_count = sum(decision.keep and decision.baseline for decision in decisions)
    extra_count = sum(decision.keep and not decision.baseline for decision in decisions)

    assert 14 <= baseline_count <= 16
    assert 14 <= extra_count <= 16
    assert all(decision.keep for decision in decisions)


def test_queue_pressure_forces_adaptive_mode_even_when_service_estimate_has_headroom() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 25.0)  # Nominal service capacity is 40 Hz.
    assert policy.full_rate

    policy.observe_queue(queue_depth=2, queue_age_seconds=0.07)

    assert not policy.full_rate
    assert policy.queue_pressured
    assert policy.baseline_fps < 30.0
