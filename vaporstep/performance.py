from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RuntimeProfile:
    samples: int = 0
    update_ms: float = 0.0
    render_ms: float = 0.0
    flip_ms: float = 0.0
    work_ms: float = 0.0
    work_p95_ms: float = 0.0
    missed_60hz: int = 0
    missed_30hz: int = 0


class RuntimeProfiler:
    """Small rolling profiler used by the F3 overlay and benchmark harness."""

    def __init__(self, history: int = 240) -> None:
        size = max(1, int(history))
        self._update_ms: deque[float] = deque(maxlen=size)
        self._render_ms: deque[float] = deque(maxlen=size)
        self._flip_ms: deque[float] = deque(maxlen=size)
        self._work_ms: deque[float] = deque(maxlen=size)

    def clear(self) -> None:
        self._update_ms.clear()
        self._render_ms.clear()
        self._flip_ms.clear()
        self._work_ms.clear()

    def record(
        self,
        *,
        update_ms: float,
        render_ms: float,
        flip_ms: float,
        work_ms: float,
    ) -> None:
        self._update_ms.append(max(0.0, float(update_ms)))
        self._render_ms.append(max(0.0, float(render_ms)))
        self._flip_ms.append(max(0.0, float(flip_ms)))
        self._work_ms.append(max(0.0, float(work_ms)))

    @staticmethod
    def _mean(values: deque[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _percentile(values: deque[float], fraction: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = max(0, math.ceil(len(ordered) * fraction) - 1)
        return ordered[index]

    def snapshot(self) -> RuntimeProfile:
        return RuntimeProfile(
            samples=len(self._work_ms),
            update_ms=self._mean(self._update_ms),
            render_ms=self._mean(self._render_ms),
            flip_ms=self._mean(self._flip_ms),
            work_ms=self._mean(self._work_ms),
            work_p95_ms=self._percentile(self._work_ms, 0.95),
            missed_60hz=sum(value > (1000.0 / 60.0) for value in self._work_ms),
            missed_30hz=sum(value > (1000.0 / 30.0) for value in self._work_ms),
        )


class AdaptiveFrameRate:
    """Select 60 or 30 FPS from sustained main-thread frame pressure."""

    def __init__(
        self,
        *,
        high_fps: int = 60,
        low_fps: int = 30,
        drop_samples: int = 60,
        recover_samples: int = 300,
    ) -> None:
        self.high_fps = max(1, int(high_fps))
        self.low_fps = max(1, min(self.high_fps, int(low_fps)))
        self.drop_samples = max(1, int(drop_samples))
        self.recover_samples = max(self.drop_samples, int(recover_samples))
        self.target_fps = self.high_fps
        self._work_ms: deque[float] = deque(maxlen=self.recover_samples)
        high_budget_ms = 1000.0 / self.high_fps
        # Allow minor scheduler noise at 60 FPS, then require ample headroom
        # before returning from 30 FPS so the target cannot oscillate.
        self._drop_p95_ms = high_budget_ms * 1.08
        self._recover_p95_ms = high_budget_ms * 0.75

    @staticmethod
    def _p95(values) -> float:
        ordered = sorted(values)
        index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return ordered[index]

    def observe(self, work_ms: float) -> bool:
        """Record one frame's work and return whether the target changed."""
        self._work_ms.append(max(0.0, float(work_ms)))
        if self.target_fps == self.high_fps:
            if len(self._work_ms) < self.drop_samples:
                return False
            recent = list(self._work_ms)[-self.drop_samples :]
            if self._p95(recent) <= self._drop_p95_ms:
                return False
            self.target_fps = self.low_fps
            self._work_ms.clear()
            return True

        if len(self._work_ms) < self.recover_samples:
            return False
        if self._p95(self._work_ms) >= self._recover_p95_ms:
            return False
        self.target_fps = self.high_fps
        self._work_ms.clear()
        return True
