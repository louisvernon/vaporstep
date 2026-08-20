import json
from pathlib import Path

from vaporstep.settings import AppSettings, SettingsStore, clamp_horizontal_reach


def test_settings_round_trip(tmp_path: Path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.settings = AppSettings(song_folder="/music/Songs", camera_index=2, horizontal_reach=1.20)
    store.save()

    reloaded = SettingsStore(path)
    assert reloaded.settings.song_folder == "/music/Songs"
    assert reloaded.settings.camera_index == 2
    assert reloaded.settings.horizontal_reach == 1.20


def test_keyboard_only_camera_choice_round_trips(tmp_path: Path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.settings.camera_enabled = False
    store.save()

    assert SettingsStore(path).settings.camera_enabled is False


def test_existing_settings_default_to_camera_enabled(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"camera_index": 1}), encoding="utf-8")

    assert SettingsStore(path).settings.camera_enabled is True


def test_settings_are_clamped_on_load(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"camera_index": -4, "horizontal_reach": 9.0}), encoding="utf-8")
    settings = SettingsStore(path).settings
    assert settings.camera_index == 0
    assert settings.horizontal_reach == 1.35


def test_horizontal_reach_clamps():
    assert clamp_horizontal_reach(0.5) == 1.0
    assert clamp_horizontal_reach(1.17) == 1.17
    assert clamp_horizontal_reach(2.0) == 1.35


def test_library_preferences_round_trip(tmp_path: Path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.settings = AppSettings(
        favorite_song_keys=["fav-b", "fav-a"],
        played_song_keys=["played"],
        last_song_key="last",
        preferred_difficulty="Hard",
    )
    store.save()
    reloaded = SettingsStore(path).settings
    assert reloaded.favorite_song_keys == ["fav-a", "fav-b"]
    assert reloaded.played_song_keys == ["played"]
    assert reloaded.last_song_key == "last"
    assert reloaded.preferred_difficulty == "Hard"


def test_privacy_notice_version_round_trip(tmp_path):
    from vaporstep.settings import SettingsStore

    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.settings.privacy_notice_version = 2
    store.save()

    assert SettingsStore(path).settings.privacy_notice_version == 2


def test_recording_opt_in_is_not_persisted(tmp_path: Path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.save()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert not any("record" in key.lower() for key in raw)
