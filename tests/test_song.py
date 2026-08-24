from pathlib import Path

from vaporstep.song import ChartInfo, SongInfo, chart_sort_key, difficulty_rank


def test_bpm_label_constant_and_range():
    constant = ChartInfo(index=0, difficulty="Easy", meter=3, bpm_min=120.0, bpm_max=120.0)
    variable = ChartInfo(index=1, difficulty="Hard", meter=8, bpm_min=90.0, bpm_max=180.0)
    assert constant.bpm_label == "120"
    assert variable.bpm_label == "90–180"


def test_difficulty_aliases_share_semantic_tiers():
    assert difficulty_rank("Beginner") == difficulty_rank("Novice") == 0
    assert difficulty_rank("Easy") == difficulty_rank("Basic") == 1
    assert difficulty_rank("Medium") == difficulty_rank("Normal") == difficulty_rank("Standard") == 2
    assert difficulty_rank("Hard") == difficulty_rank("Difficult") == 3
    assert difficulty_rank("Challenge") == difficulty_rank("Expert") == 4
    assert difficulty_rank("Edit") == 5


def test_chart_sort_prefers_named_difficulty_over_meter():
    charts = [
        ChartInfo(index=0, difficulty="Medium", meter=2),
        ChartInfo(index=1, difficulty="Easy", meter=7),
        ChartInfo(index=2, difficulty="Beginner", meter=9),
        ChartInfo(index=3, difficulty="Hard", meter=3),
        ChartInfo(index=4, difficulty="Challenge", meter=1),
        ChartInfo(index=5, difficulty="Edit", meter=1),
        ChartInfo(index=6, difficulty="Mystery", meter=2),
    ]

    ordered = sorted(charts, key=chart_sort_key)
    assert [chart.difficulty for chart in ordered] == [
        "Beginner",
        "Easy",
        "Medium",
        "Hard",
        "Challenge",
        "Edit",
        "Mystery",
    ]


def test_song_capabilities_are_derived_across_charts():
    song = SongInfo(
        simfile_path=Path("/Pack/Song/song.sm"),
        song_dir=Path("/Pack/Song"),
        title="Song",
        subtitle="",
        artist="Artist",
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=(
            ChartInfo(index=0, difficulty="Easy", meter=3, foot_count=10),
            ChartInfo(index=1, difficulty="Hard", meter=7, hand_count=5),
            ChartInfo(index=2, difficulty="Challenge", meter=9, foot_count=8, hand_count=8, native_8_lane=True),
        ),
    )

    assert song.has_foot_targets
    assert song.has_hand_targets
    assert song.has_native_8_lane
