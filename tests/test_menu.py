from vaporstep.menu import MenuAction, NoteSpeedTapDetector, SongMenu
from vaporstep.song import ChartInfo, SongInfo
from pathlib import Path


def _song(name: str, meters=(2, 5), pack: str | None = None) -> SongInfo:
    charts = tuple(
        ChartInfo(index=i, difficulty=f"D{i}", meter=meter)
        for i, meter in enumerate(meters)
    )
    song_dir = Path(f"/{pack}/{name}") if pack else Path(f"/{name}")
    return SongInfo(
        simfile_path=song_dir / f"{name}.sm",
        song_dir=song_dir,
        title=name,
        subtitle="",
        artist="Artist",
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=charts,
    )


def test_song_menu_uses_abstract_actions():
    menu = SongMenu([_song("A"), _song("B")])
    assert menu.song.display_title == "A"
    menu.handle(MenuAction.DOWN)
    assert menu.song.display_title == "B"
    menu.handle(MenuAction.RIGHT)
    assert menu.chart.meter == 5
    selected = menu.handle(MenuAction.SELECT)
    assert selected == (menu.song, menu.chart)


def test_song_menu_scroll_position_eases_toward_target():
    menu = SongMenu([_song("A"), _song("B"), _song("C")])
    menu.handle(MenuAction.DOWN)
    assert menu.scroll_target == 1
    assert menu.visual_position == 0.0
    menu.animate(0.05)
    assert 0.0 < menu.visual_position < 1.0
    menu.animate(1.0)
    assert abs(menu.visual_position - 1.0) < 0.01


def test_held_repeater_has_delay_then_repeats_and_accelerates():
    from vaporstep.menu import HeldMenuRepeater

    r = HeldMenuRepeater()
    r.press(MenuAction.DOWN, 10.0)
    assert r.update(10.20) == []
    assert r.update(10.29) == [MenuAction.DOWN]
    # Much later, catch-up is capped rather than emitting an unbounded burst.
    emitted = r.update(13.0)
    assert 1 <= len(emitted) <= 5
    r.release(MenuAction.DOWN)
    assert r.update(14.0) == []


def test_double_tap_note_speed_gesture_does_not_release_navigation():
    detector = NoteSpeedTapDetector()

    assert detector.register(MenuAction.DOWN, 10.0) == (None, None)
    assert detector.pop_expired(10.04) is None
    assert detector.register(MenuAction.DOWN, 10.049) == (2.0, None)
    assert detector.register(MenuAction.UP, 11.0) == (None, None)
    assert detector.register(MenuAction.UP, 11.04) == (1.0, None)


def test_slow_song_navigation_does_not_trigger_note_speed_gesture():
    detector = NoteSpeedTapDetector()

    assert detector.register(MenuAction.DOWN, 10.0) == (None, None)
    assert detector.pop_expired(10.049) is None
    assert detector.pop_expired(10.05) == MenuAction.DOWN
    assert detector.register(MenuAction.DOWN, 10.5) == (None, None)


def test_opposite_direction_releases_pending_navigation_before_new_gesture():
    detector = NoteSpeedTapDetector()

    assert detector.register(MenuAction.DOWN, 10.0) == (None, None)
    assert detector.register(MenuAction.UP, 10.02) == (None, MenuAction.DOWN)
    assert detector.pop_expired(10.07) == MenuAction.UP


def _difficulty_song(name: str, difficulties):
    charts = tuple(
        ChartInfo(index=i, difficulty=difficulty, meter=i + 3)
        for i, difficulty in enumerate(difficulties)
    )
    return SongInfo(
        simfile_path=Path(f"/{name}/{name}.sm"),
        song_dir=Path(f"/{name}"),
        title=name,
        subtitle="",
        artist="Artist",
        music_path=None,
        banner_path=None,
        background_path=None,
        charts=charts,
    )


def test_song_menu_preserves_preferred_difficulty_across_fallbacks():
    songs = [
        _difficulty_song("A", ("Easy", "Medium", "Hard")),
        _difficulty_song("B", ("Easy", "Hard")),
        _difficulty_song("C", ("Easy", "Medium", "Hard")),
    ]
    menu = SongMenu(songs, preferred_difficulty="Medium")
    assert menu.chart.difficulty == "Medium"
    menu.handle(MenuAction.DOWN)
    assert menu.chart.difficulty in ("Easy", "Hard")
    assert menu.preferred_difficulty == "Medium"
    menu.handle(MenuAction.DOWN)
    assert menu.chart.difficulty == "Medium"


def test_explicit_difficulty_change_updates_preference():
    songs = [
        _difficulty_song("A", ("Easy", "Medium", "Hard")),
        _difficulty_song("B", ("Easy", "Medium", "Hard")),
    ]
    menu = SongMenu(songs, preferred_difficulty="Medium")
    menu.handle(MenuAction.RIGHT)
    assert menu.chart.difficulty == "Hard"
    assert menu.preferred_difficulty == "Hard"
    menu.handle(MenuAction.DOWN)
    assert menu.chart.difficulty == "Hard"


def test_song_menu_cycles_pack_scope_after_external_filters():
    songs = [
        _song("A", pack="Pack One"),
        _song("B", pack="Pack One"),
        _song("C", pack="Pack Two"),
    ]
    menu = SongMenu(songs)

    assert menu.active_pack == "ALL"
    assert [song.title for song in menu.songs] == ["A", "B", "C"]

    menu.handle(MenuAction.NEXT_PACK)
    assert menu.active_pack == "Pack One"
    assert [song.title for song in menu.songs] == ["A", "B"]

    menu.handle(MenuAction.NEXT_PACK)
    assert menu.active_pack == "Pack Two"
    assert [song.title for song in menu.songs] == ["C"]

    menu.handle(MenuAction.NEXT_PACK)
    assert menu.active_pack == "ALL"
    assert [song.title for song in menu.songs] == ["A", "B", "C"]


def test_song_menu_pack_scope_uses_only_songs_supplied_to_menu():
    # App-level Favorites/Played filtering happens before SongMenu construction.
    filtered = [_song("Favorite", pack="Pack Two")]
    menu = SongMenu(filtered)
    assert menu.packs == ("ALL", "Pack Two")
    menu.handle(MenuAction.NEXT_PACK)
    assert [song.title for song in menu.songs] == ["Favorite"]
