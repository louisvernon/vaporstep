from vaporstep.simfile_encoding import detect_simfile_encoding_bytes


def test_utf8_metadata_is_detected_directly():
    sample = "#TITLE:테스트 음악;".encode("utf-8")
    assert detect_simfile_encoding_bytes(sample) == "utf-8"


def test_legacy_korean_metadata_prefers_cp949_over_cp1252_and_cp932():
    sample = "#TITLE:테스트 음악;".encode("cp949")
    assert detect_simfile_encoding_bytes(sample) == "cp949"


def test_legacy_japanese_metadata_prefers_cp932():
    sample = "#TITLE:テスト 音楽;".encode("cp932")
    assert detect_simfile_encoding_bytes(sample) == "cp932"


def test_western_legacy_metadata_falls_back_to_cp1252():
    sample = "#TITLE:Café Étude;".encode("cp1252")
    assert detect_simfile_encoding_bytes(sample) == "cp1252"
