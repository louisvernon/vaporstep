from __future__ import annotations

import threading
from dataclasses import dataclass


MIN_BASELINE_FPS = 10.0
# Full-rate mode should have real service headroom. Queue pressure can still
# force adaptive mode immediately if non-inference overhead makes this estimate
# optimistic.
FULL_RATE_ENTER_RATIO = 1.08
FULL_RATE_EXIT_RATIO = 1.00
SERVICE_EMA_ALPHA = 0.10
SERVICE_WARMUP_SAMPLES = 12
MAX_QUEUE_AGE_SECONDS = 0.20
QUEUE_PRESSURE_FRAMES = 2
QUEUE_PRESSURE_HOLD_SAMPLES = 18
# Away from scoring windows, use most of sustainable inference throughput so
# motion remains naturally smooth. In timing-critical windows, reserve up to ten
# inference slots per second for disposable higher-resolution samples, but never
# request more total work than measured capacity can sustain.
NORMAL_BASELINE_CAPACITY_RATIO = 0.90
PRESSURED_BASELINE_CAPACITY_RATIO = 0.85
PRESSURED_CAMERA_RATE_RATIO = 0.90
CRITICAL_EXTRA_RESERVE_FPS = 10.0
CRITICAL_TOTAL_CAPACITY_RATIO = 0.98
PRESSURED_TOTAL_CAPACITY_RATIO = 0.90


_timing_critical = threading.Event()


def set_timing_critical(active: bool) -> None:
    """Publish whether the active chart is inside a camera timing window."""
    if active:
        _timing_critical.set()
    else:
        _timing_critical.clear()


def timing_critical() -> bool:
    return _timing_critical.is_set()


@dataclass(frozen=True)
class SamplingDecision:
    keep: bool
    baseline: bool
    critical: bool


class AdaptiveSamplingPolicy:
    """Choose protected baseline samples and disposable timing-window extras.

    The policy begins at full camera rate while it measures complete inference
    service time. Machines with genuine headroom keep every frame. When capacity
    is lower, ordinary gameplay keeps a high protected baseline near sustainable
    throughput. During timing-critical chart windows, the protected baseline is
    reduced aggressively and the remaining measured capacity is spent on extra
    samples, up to a 10 Hz reserve.

    Critically, extras are themselves rate-limited. Reducing a 25 Hz machine to
    a 15 Hz protected baseline does *not* mean accepting every remaining 30 Hz
    camera frame; it means accepting about 10 Hz of extras for roughly 25 Hz of
    total inference. Queue growth remains a direct signal that the estimate is
    optimistic and temporarily increases headroom further.
    """

    def __init__(self, camera_fps: float) -> None:
        self.camera_fps = max(1.0, float(camera_fps))
        self._service_ms_ema = 0.0
        self._service_samples = 0
        self._full_rate = True
        self._last_decision_at = 0.0
        self._baseline_credit = 1.0
        self._extra_credit = 0.0
        self._queue_pressure_samples = 0

    @property
    def service_ms(self) -> float:
        return self._service_ms_ema

    @property
    def capacity_fps(self) -> float:
        if self._service_ms_ema <= 0.0:
            return self.camera_fps
        return 1000.0 / self._service_ms_ema

    @property
    def full_rate(self) -> bool:
        return self._full_rate

    @property
    def queue_pressured(self) -> bool:
        return self._queue_pressure_samples > 0

    def _baseline_fps(self, *, critical: bool) -> float:
        if (
            self._full_rate
            and not self.queue_pressured
            and self._service_samples >= SERVICE_WARMUP_SAMPLES
        ):
            return self.camera_fps
        if self._service_samples < SERVICE_WARMUP_SAMPLES and not self.queue_pressured:
            return self.camera_fps

        capacity = self.capacity_fps
        if capacity < MIN_BASELINE_FPS:
            return max(1.0, capacity)

        ratio = (
            PRESSURED_BASELINE_CAPACITY_RATIO
            if self.queue_pressured
            else NORMAL_BASELINE_CAPACITY_RATIO
        )
        camera_cap = (
            self.camera_fps * PRESSURED_CAMERA_RATE_RATIO
            if self.queue_pressured
            else self.camera_fps
        )
        ordinary = min(
            camera_cap,
            max(MIN_BASELINE_FPS, capacity * ratio),
        )
        if not critical:
            return ordinary

        # Preserve a useful motion floor, then devote up to 10 inferences/sec to
        # timing-window extras. If the machine has less spare capacity than that,
        # the reserve naturally shrinks rather than starving the protected stream.
        critical_baseline = max(MIN_BASELINE_FPS, capacity - CRITICAL_EXTRA_RESERVE_FPS)
        return min(ordinary, critical_baseline)

    def _total_fps(self, *, critical: bool) -> float:
        baseline = self._baseline_fps(critical=critical)
        if not critical or self._full_rate and not self.queue_pressured:
            return baseline

        capacity = self.capacity_fps
        ratio = (
            PRESSURED_TOTAL_CAPACITY_RATIO
            if self.queue_pressured
            else CRITICAL_TOTAL_CAPACITY_RATIO
        )
        camera_cap = (
            self.camera_fps * PRESSURED_CAMERA_RATE_RATIO
            if self.queue_pressured
            else self.camera_fps
        )
        sustainable = min(camera_cap, capacity * ratio)
        return max(baseline, sustainable)

    @property
    def baseline_fps(self) -> float:
        """Current ordinary (non-critical) protected baseline target."""
        return self._baseline_fps(critical=False)

    def baseline_fps_for(self, *, critical: bool) -> float:
        return self._baseline_fps(critical=bool(critical))

    def total_fps_for(self, *, critical: bool) -> float:
        """Return total requested inference rate, including critical extras."""
        return self._total_fps(critical=bool(critical))

    def observe_queue(self, *, queue_depth: int, queue_age_seconds: float) -> None:
        """React to sustained source/inference mismatch before latency can grow."""
        frame_interval = 1.0 / self.camera_fps
        pressured = (
            int(queue_depth) >= QUEUE_PRESSURE_FRAMES
            or float(queue_age_seconds) >= frame_interval * 1.5
        )
        if pressured:
            self._full_rate = False
            self._queue_pressure_samples = QUEUE_PRESSURE_HOLD_SAMPLES

    def observe_service(self, service_ms: float) -> None:
        sample = max(0.1, float(service_ms))
        self._service_ms_ema = (
            sample
            if self._service_ms_ema <= 0.0
            else (1.0 - SERVICE_EMA_ALPHA) * self._service_ms_ema + SERVICE_EMA_ALPHA * sample
        )
        self._service_samples += 1
        if self._queue_pressure_samples > 0:
            self._queue_pressure_samples -= 1
        if self._service_samples < SERVICE_WARMUP_SAMPLES:
            return

        ratio = self.capacity_fps / self.camera_fps
        if self._full_rate:
            if ratio < FULL_RATE_EXIT_RATIO:
                self._full_rate = False
        elif not self.queue_pressured and ratio >= FULL_RATE_ENTER_RATIO:
            self._full_rate = True

    def decide(self, captured_at: float, *, critical: bool) -> SamplingDecision:
        captured_at = float(captured_at)
        critical = bool(critical)
        baseline_fps = self.baseline_fps_for(critical=critical)
        total_fps = self.total_fps_for(critical=critical)
        extra_fps = max(0.0, total_fps - baseline_fps)

        if self._last_decision_at <= 0.0:
            self._last_decision_at = captured_at
            self._baseline_credit = 0.0
            self._extra_credit = 0.0
            return SamplingDecision(True, True, critical)

        elapsed = max(0.0, captured_at - self._last_decision_at)
        self._last_decision_at = captured_at

        if self._full_rate and not self.queue_pressured:
            self._baseline_credit = 0.0
            self._extra_credit = 0.0
            return SamplingDecision(True, True, critical)

        # Baselines and extras have independent credits so lowering the baseline
        # genuinely reserves only the intended amount of extra work. Each credit
        # is capped to prevent pauses or mode transitions from causing bursts.
        self._baseline_credit = min(
            1.5,
            self._baseline_credit + elapsed * max(baseline_fps, 1e-6),
        )
        if critical:
            self._extra_credit = min(
                1.5,
                self._extra_credit + elapsed * extra_fps,
            )
        else:
            self._extra_credit = 0.0

        if self._baseline_credit >= 1.0:
            self._baseline_credit -= 1.0
            return SamplingDecision(True, True, critical)
        if critical and self._extra_credit >= 1.0:
            self._extra_credit -= 1.0
            return SamplingDecision(True, False, True)
        return SamplingDecision(False, False, False)
