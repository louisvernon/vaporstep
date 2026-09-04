from pathlib import Path
from types import SimpleNamespace

from vaporstep.preview import SongPreviewPlayer


def _song(path: str):
    return SimpleNamespace(simfile_path=Path(path))


def test_playback_elapsed_is_exposed_only_for_the_playing_song() -> None:
    player = SongPreviewPlayer(
        _playing_key="/music/selected.sm",
        _started_at=10.0,
    )

    assert player.playback_elapsed(_song("/music/selected.sm"), 11.25) == 1.25
    assert player.playback_elapsed(_song("/music/other.sm"), 11.25) is None


def test_stopping_preview_resets_scroll_clock() -> None:
    player = SongPreviewPlayer(
        _playing_key="/music/selected.sm",
        _started_at=10.0,
    )

    player.stop()

    assert player.playback_elapsed(_song("/music/selected.sm"), 11.25) is None
