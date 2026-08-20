from vaporstep.activity_ui import _axis_scale, _record_badge


def test_record_badge_is_positive_only_and_requires_history():
    assert _record_badge(101, 100, has_history=True) == "NEW RECORD"
    assert _record_badge(100, 100, has_history=True) == ""
    assert _record_badge(50, 100, has_history=True) == ""
    assert _record_badge(100, 0, has_history=False) == ""


def test_axis_scale_uses_readable_rounded_units():
    assert _axis_scale("time", 70) == (120, "2m")
    assert _axis_scale("time", 3900) == (7200, "2h")
    assert _axis_scale("activity", 2329) == (5000, "5,000")
    assert _axis_scale("songs", 3) == (5, "5")
