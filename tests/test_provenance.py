from pathlib import Path

from vaporstep.domain import GameNote, NoteKind
from vaporstep.provenance import display_fingerprint, play_fingerprint, song_chart_fingerprint
from vaporstep.scoring import RunStats
from vaporstep.song import ChartInfo, LoadedChart, SongInfo


def _chart(tmp_path: Path, *, audio: bytes = b"audio", note_time: float = 1.0) -> LoadedChart:
    music = tmp_path / "song.ogg"
    music.write_bytes(audio)
    chart_info = ChartInfo(index=0, difficulty="Hard", meter=9)
    song = SongInfo(
        simfile_path=tmp_path / "song.sm",
        song_dir=tmp_path,
        title="Test Song",
        subtitle="",
        artist="Test Artist",
        music_path=music,
        banner_path=None,
        background_path=None,
        charts=(chart_info,),
    )
    return LoadedChart(
        song=song,
        chart=chart_info,
        notes=(GameNote(note_time, (2,), NoteKind.FOOT, beat=4.0),),
        initial_bpm=120.0,
        last_note_time=note_time,
    )


def test_song_chart_fingerprint_binds_audio_and_effective_chart(tmp_path):
    first = song_chart_fingerprint(_chart(tmp_path, audio=b"first", note_time=1.0))
    same = song_chart_fingerprint(_chart(tmp_path, audio=b"first", note_time=1.0))
    changed_audio = song_chart_fingerprint(_chart(tmp_path, audio=b"second", note_time=1.0))
    changed_chart = song_chart_fingerprint(_chart(tmp_path, audio=b"first", note_time=1.25))

    assert first == same
    assert first != changed_audio
    assert first != changed_chart


def test_play_fingerprint_uses_visible_result_fields_and_chart():
    stats = RunStats(total_notes=10)
    stats.score = 123_456
    stats.perfects = 4
    stats.greats = 3
    stats.basic_hits = 2
    stats.misses = 1
    stats.dropped_holds = 1
    stats.max_combo = 7

    first = play_fingerprint("a" * 64, stats)
    assert first == play_fingerprint("a" * 64, stats)
    assert first != play_fingerprint("b" * 64, stats)

    stats.max_combo += 1
    assert first != play_fingerprint("a" * 64, stats)


def test_display_fingerprint_is_short_grouped_uppercase():
    assert display_fingerprint("abcdef0123456789") == "ABCD EF01 2345"
