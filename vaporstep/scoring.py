from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

from .domain import HitQuality

BASE_POINTS = 1000
QUALITY_MULTIPLIERS = {
    HitQuality.HIT: 1.00,
    HitQuality.GREAT: 1.25,
    HitQuality.PERFECT: 1.50,
}
FAIL_WINDOW_FRACTION = 0.10
MIN_PERFORMANCE_WINDOW = 10
WARNING_WINDOW_FRACTION = 0.40
DANGER_WINDOW_FRACTION = 0.70
WARNING_HIT_RATE = 0.55
DANGER_HIT_RATE = 0.30
FAIL_HIT_RATE = 0.10


def combo_multiplier(combo: int) -> int:
    """Aggressive multiplier ladder; combo is the streak *after* a hit."""
    if combo >= 40:
        return 5
    if combo >= 20:
        return 4
    if combo >= 10:
        return 3
    if combo >= 5:
        return 2
    return 1


def hit_points(combo: int, quality: HitQuality = HitQuality.HIT, score_weight: float = 1.0) -> int:
    base = BASE_POINTS * QUALITY_MULTIPLIERS[quality] * combo_multiplier(combo)
    return int(round(base * max(0.0, float(score_weight))))


def theoretical_max_score(
    note_count: int,
    score_weights: Iterable[float] | None = None,
) -> int:
    """Maximum score for a full PERFECT combo with optional weighted judgements."""
    if score_weights is None:
        weights = (1.0,) * max(0, int(note_count))
    else:
        weights = tuple(float(weight) for weight in score_weights)
    return sum(
        hit_points(combo, HitQuality.PERFECT, weight)
        for combo, weight in enumerate(weights, start=1)
    )


def grade_for_ratio(ratio: float) -> str:
    # Raw score is intentionally combo-heavy, so grading uses deliberately
    # forgiving score-ratio bands. A full combo of plain occupancy HITs scores
    # ~67% of the all-PERFECT theoretical maximum and should still be a solid A.
    if ratio >= 0.85:
        return "S"
    if ratio >= 0.60:
        return "A"
    if ratio >= 0.40:
        return "B"
    if ratio >= 0.20:
        return "C"
    return "D"


def performance_window_size(total_notes: int) -> int:
    if total_notes <= 0:
        return MIN_PERFORMANCE_WINDOW
    return max(MIN_PERFORMANCE_WINDOW, int(math.ceil(total_notes * FAIL_WINDOW_FRACTION)))


def _window_thresholds(total_notes: int) -> tuple[int, int, int]:
    fail_window = performance_window_size(total_notes)
    warning_min = max(5, int(math.ceil(fail_window * WARNING_WINDOW_FRACTION)))
    danger_min = max(warning_min + 1, int(math.ceil(fail_window * DANGER_WINDOW_FRACTION)))
    danger_min = min(danger_min, fail_window)
    return warning_min, danger_min, fail_window


def _recent_window(
    judgements: list[bool] | tuple[bool, ...], total_notes: int
) -> tuple[tuple[bool, ...], float] | None:
    warning_min, _, fail_window = _window_thresholds(total_notes)
    if len(judgements) < warning_min:
        return None
    size = min(fail_window, len(judgements))
    window = tuple(judgements[-size:])
    return window, sum(window) / size


def performance_state(judgements: list[bool] | tuple[bool, ...], total_notes: int) -> str:
    recent = _recent_window(judgements, total_notes)
    if recent is None:
        return "ok"

    window, hit_rate = recent
    warning_min, danger_min, fail_window = _window_thresholds(total_notes)

    if len(judgements) >= fail_window:
        fail_slice = judgements[-fail_window:]
        fail_rate = sum(fail_slice) / fail_window
        if fail_rate <= FAIL_HIT_RATE:
            return "failed"

    if len(judgements) >= danger_min and hit_rate < DANGER_HIT_RATE:
        return "danger"
    if len(judgements) >= warning_min and hit_rate < WARNING_HIT_RATE:
        return "warning"
    return "ok"


@dataclass
class RunStats:
    total_notes: int
    score_weights: tuple[float, ...] = field(default_factory=tuple, repr=False)
    score: int = 0
    hits: int = 0
    misses: int = 0
    combo: int = 0
    max_combo: int = 0
    perfects: int = 0
    greats: int = 0
    basic_hits: int = 0
    judgements: list[bool] = field(default_factory=list, repr=False)

    @property
    def max_score(self) -> int:
        weights = self.score_weights if self.score_weights else None
        return theoretical_max_score(self.total_notes, weights)

    @property
    def multiplier(self) -> int:
        return combo_multiplier(self.combo)

    @property
    def score_ratio(self) -> float:
        if self.max_score <= 0:
            return 0.0
        return self.score / self.max_score

    @property
    def hit_rate(self) -> float:
        judged = self.hits + self.misses
        if judged <= 0:
            return 0.0
        return self.hits / judged

    @property
    def recent_hit_rate(self) -> float | None:
        recent = _recent_window(self.judgements, self.total_notes)
        return None if recent is None else recent[1]

    @property
    def recent_window_size(self) -> int:
        warning_min, _, fail_window = _window_thresholds(self.total_notes)
        if len(self.judgements) < warning_min:
            return 0
        return min(fail_window, len(self.judgements))

    @property
    def performance_window_size(self) -> int:
        return performance_window_size(self.total_notes)

    @property
    def performance_state(self) -> str:
        return performance_state(self.judgements, self.total_notes)

    @property
    def grade(self) -> str:
        return grade_for_ratio(self.score_ratio)

    def register_hit(
        self,
        quality: HitQuality = HitQuality.HIT,
        *,
        score_weight: float = 1.0,
    ) -> int:
        self.hits += 1
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self.judgements.append(True)
        if quality == HitQuality.PERFECT:
            self.perfects += 1
        elif quality == HitQuality.GREAT:
            self.greats += 1
        else:
            self.basic_hits += 1
        points = hit_points(self.combo, quality, score_weight)
        self.score += points
        return points

    def register_miss(self, *, break_combo: bool = True) -> None:
        self.misses += 1
        if break_combo:
            self.combo = 0
        self.judgements.append(False)
