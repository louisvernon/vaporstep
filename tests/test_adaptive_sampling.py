from vaporstep.adaptive_sampling import AdaptiveSamplingPolicy, SERVICE_WARMUP_SAMPLES


def _warm(policy: AdaptiveSamplingPolicy, service_ms: float) -> None:
    for _ in range(SERVICE_WARMUP_SAMPLES + 4):
        policy.observe_service(service_ms)


def test_capable_machine_stays_at_full_camera_rate() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 30.0)

    assert policy.full_rate is True
    assert policy.baseline_fps == 30.0
    assert policy.capacity_fps == 30.0


def test_slower_machine_uses_half_capacity_with_ten_fps_floor() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)

    assert policy.full_rate is False
    assert 24.0 < policy.capacity_fps < 26.0
    assert 12.0 < policy.baseline_fps < 13.0


def test_very_slow_machine_cannot_reserve_capacity_it_does_not_have() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 125.0)

    assert policy.full_rate is False
    assert 7.5 < policy.capacity_fps < 8.5
    assert policy.baseline_fps == policy.capacity_fps


def test_timing_window_keeps_frames_between_baselines() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 50.0)  # 20 Hz capacity -> 10 Hz protected baseline.

    first = policy.decide(1.000, critical=False)
    ordinary = policy.decide(1.033, critical=False)
    extra = policy.decide(1.066, critical=True)
    next_baseline = policy.decide(1.100, critical=True)

    assert first.keep and first.baseline
    assert not ordinary.keep
    assert extra.keep and not extra.baseline and extra.critical
    assert next_baseline.keep and next_baseline.baseline
