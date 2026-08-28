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
