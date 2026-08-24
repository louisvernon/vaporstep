from vaporstep.font_support import _candidate_names_for_text, _contains_hangul


def test_synthetic_hangul_routes_to_korean_font_candidates():
    sample = "테스트 음악"
    assert _contains_hangul(sample)
    candidates = _candidate_names_for_text(sample)
    assert candidates[0] == "Apple SD Gothic Neo"
    assert "Noto Sans CJK KR" in candidates
    assert "Malgun Gothic" in candidates


def test_plain_latin_metadata_uses_general_font_candidates():
    candidates = _candidate_names_for_text("Synthetic Track")
    assert "Apple SD Gothic Neo" not in candidates
    assert "Noto Sans" in candidates
