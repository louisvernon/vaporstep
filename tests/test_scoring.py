from vaporstep.domain import HitQuality
from vaporstep.scoring import RunStats, combo_multiplier, grade_for_ratio, theoretical_max_score


def test_multiplier_ramps_aggressively_and_caps_at_five():
    assert combo_multiplier(1) == 1
    assert combo_multiplier(4) == 1
    assert combo_multiplier(5) == 2
    assert combo_multiplier(10) == 3
    assert combo_multiplier(20) == 4
    assert combo_multiplier(40) == 5
    assert combo_multiplier(400) == 5


def test_hit_scoring_uses_post_hit_combo_and_miss_resets():
    stats = RunStats(total_notes=8)
    for _ in range(4):
        stats.register_hit()
    assert stats.score == 4000
    assert stats.multiplier == 1
    assert stats.register_hit() == 2000
    assert stats.combo == 5
    assert stats.multiplier == 2
    stats.register_miss()
    assert stats.combo == 0
    assert stats.multiplier == 1
    assert stats.register_hit() == 1000
    assert stats.max_combo == 5


def test_max_score_is_perfect_combo_simulation():
    # PERFECT is 1.5x quality: first four at combo 1x, fifth at combo 2x.
    assert theoretical_max_score(5) == 9000
    stats = RunStats(total_notes=5)
    for _ in range(5):
        stats.register_hit(HitQuality.PERFECT)
    assert stats.score == stats.max_score
    assert stats.score_ratio == 1.0
    assert stats.grade == "S"


def test_timing_quality_adds_score_without_changing_combo_rules():
    hit = RunStats(total_notes=3)
    assert hit.register_hit(HitQuality.HIT) == 1000
    assert hit.register_hit(HitQuality.GREAT) == 1250
    assert hit.register_hit(HitQuality.PERFECT) == 1500
    assert hit.combo == 3
    assert hit.basic_hits == 1
    assert hit.greats == 1
    assert hit.perfects == 1


def test_grade_is_based_on_percentage_of_maximum_score():
    assert grade_for_ratio(0.85) == "S"
    assert grade_for_ratio(0.60) == "A"
    assert grade_for_ratio(0.40) == "B"
    assert grade_for_ratio(0.20) == "C"
    assert grade_for_ratio(0.19) == "D"


def test_plain_hit_full_combo_is_still_a_solid_grade():
    stats = RunStats(total_notes=100)
    for _ in range(100):
        stats.register_hit(HitQuality.HIT)
    # Timing bonuses still matter for S, but simply clearing accurately should
    # not be punished with a low letter grade.
    assert stats.score_ratio > 0.60
    assert stats.grade == "A"


def test_performance_window_scales_with_chart_size():
    from vaporstep.scoring import performance_window_size

    assert performance_window_size(300) == 30
    assert performance_window_size(500) == 50
    assert performance_window_size(50) == 10


def test_performance_state_uses_ten_percent_of_chart_as_failure_window():
    from vaporstep.scoring import performance_state

    total_notes = 300  # 30-target failure window
    assert performance_state([False] * 11, total_notes) == "ok"
    assert performance_state([True] * 6 + [False] * 6, total_notes) == "warning"  # 50% after 12
    assert performance_state([True] * 6 + [False] * 14, total_notes) == "warning"  # danger waits until 21
    assert performance_state([True] * 6 + [False] * 15, total_notes) == "danger"   # 28.6% after 21
    assert performance_state([True] * 3 + [False] * 26, total_notes) == "danger"  # cannot fail at 29
    assert performance_state([True] * 3 + [False] * 27, total_notes) == "failed"  # 10% over 30
    assert performance_state([True] * 17 + [False] * 13, total_notes) == "ok"      # 56.7%


def test_recent_hit_rate_expands_to_chart_relative_window_then_rolls():
    stats = RunStats(total_notes=200)  # 20-target performance window
    for _ in range(4):
        stats.register_hit()
    for _ in range(4):
        stats.register_miss()
    assert stats.recent_window_size == 8
    assert stats.recent_hit_rate == 0.50
    assert stats.performance_state == "warning"

    for _ in range(12):
        stats.register_hit()
    assert stats.recent_window_size == 20

    for _ in range(10):
        stats.register_miss()
    assert stats.recent_window_size == 20

