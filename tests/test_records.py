from pathlib import Path

from vaporstep.records import RecordStore, chart_key
from vaporstep.scoring import RunStats
from vaporstep.song import ChartInfo, SongInfo


def _song_chart(tmp_path: Path):
    chart = ChartInfo(index=1, difficulty="Hard", meter=7, description="Test")
    song = SongInfo(
        simfile_path=tmp_path / "Pack" / "Song" / "song.sm",
        song_dir=tmp_path / "Pack" / "Song",
        title="Song",
        subtitle="",
        artist="Artist",
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=(chart,),
    )
    return song, chart


def test_chart_key_does_not_depend_on_absolute_song_directory(tmp_path: Path):
    song, chart = _song_chart(tmp_path)
    other = SongInfo(
        simfile_path=Path("/somewhere/else/song.sm"),
        song_dir=Path("/somewhere/else"),
        title=song.title,
        subtitle=song.subtitle,
        artist=song.artist,
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=song.charts,
    )
    assert chart_key(song, chart) == chart_key(other, chart)


def test_record_store_only_replaces_high_score(tmp_path: Path):
    path = tmp_path / "scores.json"
    store = RecordStore(path)
    stats = RunStats(total_notes=5)
    for _ in range(5):
        stats.register_hit()
    record, new = store.submit("abc", stats)
    assert new is True
    assert record.score == 6000

    worse = RunStats(total_notes=5)
    worse.register_hit()
    record2, new2 = store.submit("abc", worse)
    assert new2 is False
    assert record2.score == 6000

    reloaded = RecordStore(path)
    assert reloaded.get("abc").score == 6000
