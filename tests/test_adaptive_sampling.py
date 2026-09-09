from vaporstep.adaptive_sampling import (
    AdaptiveSamplingPolicy,
    QUEUE_PRESSURE_HOLD_SAMPLES,
    SERVICE_WARMUP_SAMPLES,
)


def _warm(policy: AdaptiveSamplingPolicy, service_ms: float) -> None:
    for _ in range(SERVICE_WARMUP_SAMPLES + 4):
        policy.observe_service(service_ms)


def _deliver(policy: AdaptiveSamplingPolicy, fps: float, frames: int = 24) -> None:
    timestamp = 1.0
    policy.decide(timestamp, critical=False)
    for _ in range(frames - 1):
        timestamp += 1.0 / fps
        policy.decide(timestamp, critical=False)


def test_capable_machine_stays_at_full_camera_rate() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 25.0)

    assert policy.full_rate is True
    assert policy.baseline_fps == 30.0
    assert policy.capacity_fps > 30.0


def test_measured_source_rate_does_not_cap_inference_capacity() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _deliver(policy, 15.0)
    _warm(policy, 50.0)  # 20 Hz inference capacity on a 15 Hz delivered camera.

    assert 14.5 < policy.source_fps < 15.5
    assert 19.5 < policy.capacity_fps < 20.5
    assert policy.full_rate is True
    assert 14.5 < policy.baseline_fps < 15.5


def test_slow_delivered_camera_keeps_every_frame_when_inference_can_keep_up() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _deliver(policy, 15.0)
    _warm(policy, 50.0)

    decisions = []
    timestamp = 5.0
    for _ in range(30):
        decisions.append(policy.decide(timestamp, critical=False))
        timestamp += 1.0 / 15.0

    assert all(decision.keep and decision.baseline for decision in decisions)


def test_slower_machine_uses_most_capacity_away_from_notes() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)

    assert policy.full_rate is False
    assert 24.0 < policy.capacity_fps < 26.0
    assert 22.0 < policy.baseline_fps < 23.0


def test_timing_window_never_reduces_protected_baseline() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)

    assert 24.0 < policy.capacity_fps < 26.0
    assert 22.0 < policy.baseline_fps < 23.0
    assert policy.baseline_fps_for(critical=True) == policy.baseline_fps


def test_critical_baseline_stays_at_normal_rate_on_slower_machine() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 66.6666667)

    assert 14.0 < policy.capacity_fps < 16.0
    assert 13.0 < policy.baseline_fps < 14.0
    assert policy.baseline_fps_for(critical=True) == policy.baseline_fps


def test_very_slow_machine_uses_all_capacity_as_protected_baseline() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 125.0)

    assert policy.full_rate is False
    assert 7.5 < policy.capacity_fps < 8.5
    assert policy.baseline_fps == policy.capacity_fps
    assert policy.baseline_fps_for(critical=True) == policy.capacity_fps


def test_fractional_baseline_does_not_collapse_to_every_other_frame() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)  # 25 Hz capacity -> 22.5 Hz protected baseline.

    decisions = []
    timestamp = 1.0
    for _ in range(30):
        decisions.append(policy.decide(timestamp, critical=False))
        timestamp += 1.0 / 30.0

    baseline_count = sum(decision.baseline for decision in decisions)
    assert 21 <= baseline_count <= 24


def test_timing_window_keeps_remaining_camera_frames_eligible_as_extras() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)  # 25 Hz capacity -> 22.5 Hz protected baseline.

    decisions = []
    timestamp = 1.0
    for _ in range(30):
        decisions.append(policy.decide(timestamp, critical=True))
        timestamp += 1.0 / 30.0

    baseline_count = sum(decision.keep and decision.baseline for decision in decisions)
    extra_count = sum(decision.keep and not decision.baseline for decision in decisions)

    # Dense sections preserve the same sustainable protected stream. Every
    # intervening camera frame is requested as an optional refinement, and the
    # queue decides which extras survive.
    assert 21 <= baseline_count <= 24
    assert 6 <= extra_count <= 9
    assert baseline_count + extra_count == 30
    assert all(decision.keep for decision in decisions)


def test_queue_pressure_forces_adaptive_mode_without_throttling_headroom() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 25.0)  # Nominal service capacity is 40 Hz.
    assert policy.full_rate

    policy.observe_queue(queue_depth=2, queue_age_seconds=0.07)

    assert not policy.full_rate
    assert policy.queue_pressured
    # Even the recovery target is 30 Hz here (75% of 40 Hz), so a machine with
    # enough headroom to process every source frame should still keep them all.
    assert policy.baseline_fps == 30.0


def test_queue_pressure_uses_lower_recovery_rate_only_outside_timing_window() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)  # 25 Hz capacity -> 22.5 Hz normal protected baseline.
    normal = policy.baseline_fps

    policy.observe_queue(queue_depth=2, queue_age_seconds=0.07)

    assert policy.queue_pressured
    assert 18.0 < policy.baseline_fps < 19.5  # 75% of ~25 Hz capacity.
    assert policy.baseline_fps_for(critical=True) == normal


def test_recovery_rate_returns_to_normal_after_pressure_hold_expires() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _warm(policy, 40.0)
    normal = policy.baseline_fps
    policy.observe_queue(queue_depth=2, queue_age_seconds=0.07)
    assert policy.baseline_fps < normal

    for _ in range(QUEUE_PRESSURE_HOLD_SAMPLES):
        policy.observe_service(40.0)

    assert not policy.queue_pressured
    assert policy.baseline_fps == normal


def test_queue_pressure_does_not_thin_slow_source_that_fits_recovery_capacity() -> None:
    policy = AdaptiveSamplingPolicy(30.0)
    _deliver(policy, 15.0)
    _warm(policy, 50.0)  # 20 Hz inference capacity, 15 Hz source.

    policy.observe_queue(queue_depth=2, queue_age_seconds=0.11)

    assert policy.queue_pressured
    # 75% of 20 Hz is still the full 15 Hz delivered source rate.
    assert 14.5 < policy.baseline_fps < 15.5
