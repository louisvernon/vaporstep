from pathlib import Path

from vaporstep.library_index import LibraryIndexer
from vaporstep.song import ChartInfo, SongInfo


def _song(path: Path, title: str = "Song") -> SongInfo:
    return SongInfo(
        simfile_path=path,
        song_dir=path.parent,
        title=title,
        subtitle="",
        artist="Artist",
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=(ChartInfo(index=0, difficulty="Hard", meter=7, target_count=10),),
    )


def test_index_reuses_unchanged_stepfile_and_reparses_edit(tmp_path: Path, monkeypatch):
    root = tmp_path / "Songs"
    song_dir = root / "Pack" / "Song"
    song_dir.mkdir(parents=True)
    stepfile = song_dir / "song.sm"
    stepfile.write_text("first", encoding="utf-8")
    index_path = tmp_path / "song_index.json"

    calls = []

    def fake_scan(path: Path):
        calls.append(path.read_text(encoding="utf-8"))
        return _song(path, title=path.read_text(encoding="utf-8"))

    monkeypatch.setattr("vaporstep.library_index.scan_song", fake_scan)

    first = LibraryIndexer(index_path)
    first._run(root.resolve())
    snap = first.snapshot()
    assert snap.complete
    assert snap.songs_found == 1
    assert snap.parsed_songs == 1
    assert snap.cached_songs == 0
    assert calls == ["first"]

    second = LibraryIndexer(index_path)
    second._run(root.resolve())
    snap = second.snapshot()
    assert snap.cached_songs == 1
    assert snap.parsed_songs == 0
    assert calls == ["first"]

    stepfile.write_text("edited-content", encoding="utf-8")
    third = LibraryIndexer(index_path)
    third._run(root.resolve())
    snap = third.snapshot()
    assert snap.cached_songs == 0
    assert snap.parsed_songs == 1
    assert snap.songs[0].title == "edited-content"
    assert calls == ["first", "edited-content"]


def test_cache_is_scoped_to_selected_root(tmp_path: Path, monkeypatch):
    root_a = tmp_path / "A"
    root_b = tmp_path / "B"
    for root, title in ((root_a, "A"), (root_b, "B")):
        song_dir = root / title
        song_dir.mkdir(parents=True)
        (song_dir / "song.sm").write_text(title, encoding="utf-8")

    monkeypatch.setattr(
        "vaporstep.library_index.scan_song",
        lambda path: _song(path, title=path.read_text(encoding="utf-8")),
    )
    index_path = tmp_path / "song_index.json"
    LibraryIndexer(index_path)._run(root_a.resolve())

    assert [song.title for song in LibraryIndexer(index_path).cached_songs(root_a)] == ["A"]
    assert LibraryIndexer(index_path).cached_songs(root_b) == []
