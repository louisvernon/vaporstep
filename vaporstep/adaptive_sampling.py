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
SOURCE_FPS_EMA_ALPHA = 0.10
SERVICE_WARMUP_SAMPLES = 12
MAX_QUEUE_AGE_SECONDS = 0.20
QUEUE_PRESSURE_FRAMES = 2
QUEUE_PRESSURE_HOLD_SAMPLES = 18
# Keep a little steady-state headroom for service-time jitter. Timing-critical
# sampling must never reduce this protected stream: intervening camera frames
# become disposable extras on top of the same sustainable baseline.
NORMAL_BASELINE_CAPACITY_RATIO = 0.90


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
    """Choose a sustainable protected stream plus opportunistic extras.

    ``camera_fps`` is the requested/canonical camera ceiling. The policy also
    measures the rate at which frames are actually delivered from capture
    timestamps. Full-rate mode means keeping every *delivered* camera frame,
    not requiring the inference worker to match a camera mode the device did
    not actually provide.

    Inference capacity is measured independently from complete inference
    service time. Machines with genuine headroom over the delivered source rate
    keep every frame. When capacity is lower, gameplay keeps a protected
    baseline close to sustainable throughput.

    Timing-critical windows do not lower that protected baseline. Every
    intervening camera frame remains eligible as an extra, so short dense bursts
    can spend bounded queue latency on additional temporal evidence. The queue
    sheds extras first if protected baseline debt proves the worker is falling
    behind.

    Fractional baseline targets are scheduled with a time-based accumulator. This
    matters at a 30 Hz camera: a naive minimum-interval test turns many targets in
    the 20s into an accidental every-other-frame 15 Hz cadence.
    """

    def __init__(self, camera_fps: float) -> None:
        self.camera_fps = max(1.0, float(camera_fps))
        self._source_fps_ema = 0.0
        self._service_ms_ema = 0.0
        self._service_samples = 0
        self._full_rate = True
        self._last_decision_at = 0.0
        self._baseline_credit = 1.0
        self._queue_pressure_samples = 0

    @property
    def source_fps(self) -> float:
        """Measured delivered camera rate, capped by the requested rate."""
        if self._source_fps_ema <= 0.0:
            return self.camera_fps
        return min(self.camera_fps, self._source_fps_ema)

    @property
    def service_ms(self) -> float:
        return self._service_ms_ema

    @property
    def capacity_fps(self) -> float:
        """Measured serialized inference capacity, independent of camera FPS."""
        if self._service_ms_ema <= 0.0:
            return self.source_fps
        return 1000.0 / self._service_ms_ema

    @property
    def full_rate(self) -> bool:
        return self._full_rate

    @property
    def queue_pressured(self) -> bool:
        return self._queue_pressure_samples > 0

    def _baseline_fps(self, *, critical: bool) -> float:
        source_fps = self.source_fps
        if (
            self._full_rate
            and not self.queue_pressured
            and self._service_samples >= SERVICE_WARMUP_SAMPLES
        ):
            return source_fps
        if self._service_samples < SERVICE_WARMUP_SAMPLES and not self.queue_pressured:
            return source_fps

        capacity = self.capacity_fps
        if capacity < MIN_BASELINE_FPS:
            return max(1.0, capacity)

        # Queue pressure may force us out of optimistic full-rate mode, but it
        # must not reduce the protected stream below the normal sustainable
        # baseline merely because optional extras accumulated. At 90% of measured
        # capacity there is already steady-state headroom to drain baseline debt.
        return min(
            source_fps,
            max(MIN_BASELINE_FPS, capacity * NORMAL_BASELINE_CAPACITY_RATIO),
        )

    @property
    def baseline_fps(self) -> float:
        """Current ordinary (non-critical) protected baseline target."""
        return self._baseline_fps(critical=False)

    def baseline_fps_for(self, *, critical: bool) -> float:
        return self._baseline_fps(critical=bool(critical))

    def observe_queue(self, *, queue_depth: int, queue_age_seconds: float) -> None:
        """React to sustained source/inference mismatch before latency can grow."""
        frame_interval = 1.0 / self.source_fps
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

        ratio = self.capacity_fps / self.source_fps
        if self._full_rate:
            if ratio < FULL_RATE_EXIT_RATIO:
                self._full_rate = False
        elif not self.queue_pressured and ratio >= FULL_RATE_ENTER_RATIO:
            self._full_rate = True

    def _observe_source_interval(self, elapsed: float) -> None:
        if elapsed <= 0.0:
            return
        # Do not let timestamp jitter imply a source rate above the canonical
        # requested camera rate. A slower delivered rate, however, is real input
        # availability and should redefine what "full rate" means.
        sample = min(self.camera_fps, 1.0 / max(elapsed, 1e-6))
        self._source_fps_ema = (
            sample
            if self._source_fps_ema <= 0.0
            else (1.0 - SOURCE_FPS_EMA_ALPHA) * self._source_fps_ema
            + SOURCE_FPS_EMA_ALPHA * sample
        )

    def decide(self, captured_at: float, *, critical: bool) -> SamplingDecision:
        captured_at = float(captured_at)
        critical = bool(critical)

        if self._last_decision_at <= 0.0:
            self._last_decision_at = captured_at
            self._baseline_credit = 0.0
            return SamplingDecision(True, True, critical)

        elapsed = max(0.0, captured_at - self._last_decision_at)
        self._last_decision_at = captured_at
        self._observe_source_interval(elapsed)
        baseline_fps = self.baseline_fps_for(critical=critical)

        if self._full_rate and not self.queue_pressured:
            self._baseline_credit = 0.0
            return SamplingDecision(True, True, critical)

        # Accumulate the desired baseline rate in real elapsed time, capped so a
        # long camera pause cannot create a burst of artificial catch-up samples.
        self._baseline_credit = min(
            1.5,
            self._baseline_credit + elapsed * max(baseline_fps, 1e-6),
        )
        if self._baseline_credit >= 1.0:
            self._baseline_credit -= 1.0
            return SamplingDecision(True, True, critical)
        if critical:
            return SamplingDecision(True, False, True)
        return SamplingDecision(False, False, False)
