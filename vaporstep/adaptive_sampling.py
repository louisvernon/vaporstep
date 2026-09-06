from __future__ import annotations

import threading
from dataclasses import dataclass


MIN_BASELINE_FPS = 10.0
FULL_RATE_ENTER_RATIO = 0.98
FULL_RATE_EXIT_RATIO = 0.90
SERVICE_EMA_ALPHA = 0.10
SERVICE_WARMUP_SAMPLES = 12
EXTRA_MAX_AGE_SECONDS = 0.20
# Outside scoring windows, keep the protected baseline close to measured
# sustainable capacity so presentation remains smooth. Inside a scoring window,
# deliberately lower only the protected baseline so disposable 30 Hz samples can
# consume the remaining service capacity without risking baseline starvation.
NORMAL_BASELINE_CAPACITY_RATIO = 0.90
CRITICAL_BASELINE_CAPACITY_RATIO = 0.60


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
    service time. Machines that can sustain essentially the full camera rate keep
    every frame. When capacity is lower, ordinary gameplay keeps a high protected
    baseline near sustainable throughput. During timing-critical chart windows,
    only the *protected* baseline is reduced aggressively so spare service slots
    can be filled by disposable 30 Hz samples. This preserves smooth motion away
    from notes while reserving priority headroom for denser timing evidence.
    """

    def __init__(self, camera_fps: float) -> None:
        self.camera_fps = max(1.0, float(camera_fps))
        self._service_ms_ema = 0.0
        self._service_samples = 0
        self._full_rate = True
        self._last_baseline_at = 0.0

    @property
    def service_ms(self) -> float:
        return self._service_ms_ema

    @property
    def capacity_fps(self) -> float:
        if self._service_ms_ema <= 0.0:
            return self.camera_fps
        return min(self.camera_fps, 1000.0 / self._service_ms_ema)

    @property
    def full_rate(self) -> bool:
        return self._full_rate

    def _baseline_fps(self, *, critical: bool) -> float:
        if self._full_rate or self._service_samples < SERVICE_WARMUP_SAMPLES:
            return self.camera_fps
        capacity = self.capacity_fps
        if capacity < MIN_BASELINE_FPS:
            return max(1.0, capacity)
        ratio = (
            CRITICAL_BASELINE_CAPACITY_RATIO
            if critical
            else NORMAL_BASELINE_CAPACITY_RATIO
        )
        return min(self.camera_fps, max(MIN_BASELINE_FPS, capacity * ratio))

    @property
    def baseline_fps(self) -> float:
        """Current ordinary (non-critical) protected baseline target."""
        return self._baseline_fps(critical=False)

    def baseline_fps_for(self, *, critical: bool) -> float:
        return self._baseline_fps(critical=bool(critical))

    def observe_service(self, service_ms: float) -> None:
        sample = max(0.1, float(service_ms))
        self._service_ms_ema = (
            sample
            if self._service_ms_ema <= 0.0
            else (1.0 - SERVICE_EMA_ALPHA) * self._service_ms_ema + SERVICE_EMA_ALPHA * sample
        )
        self._service_samples += 1
        if self._service_samples < SERVICE_WARMUP_SAMPLES:
            return

        ratio = self.capacity_fps / self.camera_fps
        if self._full_rate:
            if ratio < FULL_RATE_EXIT_RATIO:
                self._full_rate = False
        elif ratio >= FULL_RATE_ENTER_RATIO:
            self._full_rate = True

    def decide(self, captured_at: float, *, critical: bool) -> SamplingDecision:
        captured_at = float(captured_at)
        baseline_fps = self.baseline_fps_for(critical=critical)
        interval = 1.0 / max(baseline_fps, 1e-6)
        baseline_due = (
            self._full_rate
            or self._last_baseline_at <= 0.0
            or captured_at - self._last_baseline_at >= interval * 0.92
        )
        if baseline_due:
            self._last_baseline_at = captured_at
            return SamplingDecision(True, True, bool(critical))
        if critical:
            return SamplingDecision(True, False, True)
        return SamplingDecision(False, False, False)
