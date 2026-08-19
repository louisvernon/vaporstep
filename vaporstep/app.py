from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import math
import os
from pathlib import Path
import sys
import time

import pygame

from . import __version__
from .activity import ActivityStore, RunActivity, counts_as_song, run_progress, target_activity, week_start
from .activity_ui import (
    NamePrompt,
    ProfilePicker,
    draw_activity_dashboard,
    draw_name_prompt,
    draw_profile_badge,
    draw_profile_picker,
)
from .audio_fx import GameplaySounds, MenuSounds
from .config import TARGET_FPS, WINDOW_HEIGHT, WINDOW_WIDTH
from .demo import make_demo_notes
from .directory_browser import DirectoryBrowser
from .domain import BodyState, ChainMode
from .home_ui import MAIN_OPTIONS, draw_home
from .keyboard_input import KeyboardBodyInput
from .library_index import LibraryIndexer, LibraryScanSnapshot
from .menu import HeldMenuRepeater, MenuAction, SongMenu, action_for_event
from .model_asset import ensure_pose_model
from .pose_input import PoseCameraInput, probe_camera
from .preview import SongPreviewPlayer
from .records import ChartRecord, RecordStore, chart_key, song_key
from .recording import RunRecorder, recording_backend_status
from .renderer import Renderer
from .resources import resource_path
from .session import GameSession
from .settings import (
    HORIZONTAL_REACH_STEP,
    PRIVACY_NOTICE_VERSION,
    SettingsStore,
    clamp_horizontal_reach,
)
from .simfile_loader import load_chart
from .tracking_overlay import draw_lower_body_tracking_overlay
from .user_paths import activity_path, profile_highscores_path


APP_VERSION = __version__
RECORD_RESULTS_HOLD_SECONDS = 3.0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VaporStep webcam full-body rhythm game")
    p.add_argument("--camera", type=int, default=None, help="OpenCV camera index")
    p.add_argument("--reach", type=float, default=None, help="Horizontal tracking reach multiplier")
    p.add_argument("--keyboard", action="store_true", help="Start in keyboard input mode")
    p.add_argument("--fullscreen", action="store_true", help="Start fullscreen")
    p.add_argument(
        "--songs",
        type=Path,
        default=None,
        help="Song directory containing supported .sm/.ssc charts; may also be set with VAPORSTEP_SONGS",
    )
    p.add_argument("--demo", action="store_true", help="Skip menus and run the synthetic chart")
    return p


def display_mode(fullscreen: bool) -> pygame.Surface:
    flags = pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE
    size = (0, 0) if fullscreen else (WINDOW_WIDTH, WINDOW_HEIGHT)
    return pygame.display.set_mode(size, flags)


def _songs_root(args, settings_store: SettingsStore) -> Path | None:
    if args.songs is not None:
        return args.songs.expanduser()
    env = os.environ.get("VAPORSTEP_SONGS")
    if env:
        return Path(env).expanduser()
    configured = settings_store.settings.song_path
    if configured is not None:
        return configured
    local = Path("Songs")
    return local if local.exists() else None


def _repeat_action_for_key(key: int) -> MenuAction | None:
    if key in (pygame.K_UP, pygame.K_w):
        return MenuAction.UP
    if key in (pygame.K_DOWN, pygame.K_s):
        return MenuAction.DOWN
    return None


def _readiness_for_session(body: BodyState, session: GameSession) -> str:
    required = []
    labels = []
    if session.has_hand_notes:
        required.extend((body.left_wrist, body.right_wrist))
        labels.append("wrists")
    if session.has_foot_notes:
        required.extend((body.left_knee, body.right_knee))
        labels.append("lower legs")
    if not required:
        return "READY"
    if not all(point.visible for point in required):
        joined = " and ".join(labels)
        return f"Keep both {joined} visible"
    if any(point.lane is None for point in required):
        areas = " / ".join("hand" if label == "wrists" else "foot" for label in labels)
        suffix = "s" if len(labels) > 1 else ""
        return f"Move into the {areas} play area{suffix}"
    return "READY"


def _safe_settings_save(store: SettingsStore) -> None:
    try:
        store.save()
    except OSError as exc:
        print(f"Could not save settings: {exc}", file=sys.stderr)


def _draw_library_scan(renderer: Renderer, snapshot: LibraryScanSnapshot) -> None:
    """Draw a lightweight responsive progress screen while a new library is indexed."""
    screen = renderer.screen
    screen.fill((2, 2, 8))
    width, height = screen.get_size()
    cyan = (70, 245, 255)
    magenta = (255, 55, 210)
    white = (235, 245, 255)
    dim = (70, 88, 115)
    grid = (25, 64, 88)

    title = renderer.big_font.render("BUILDING SONG LIBRARY", True, magenta)
    screen.blit(title, title.get_rect(center=(width // 2, int(height * 0.18))))

    phase = "Scanning folders…" if snapshot.phase == "discovering" else "Indexing stepfiles…"
    if snapshot.complete:
        phase = "Library ready"
    phase_surface = renderer.font.render(phase, True, cyan)
    screen.blit(phase_surface, phase_surface.get_rect(center=(width // 2, int(height * 0.28))))

    rows = (
        ("Folders scanned", snapshot.folders_scanned),
        ("Stepfiles found", snapshot.stepfiles_found),
        ("Songs indexed", snapshot.songs_found),
        ("Charts found", snapshot.charts_found),
        ("Loaded from cache", snapshot.cached_songs),
        ("Re-parsed", snapshot.parsed_songs),
        ("Skipped / errors", len(snapshot.errors)),
    )
    y = int(height * 0.36)
    for label, value in rows:
        label_surface = renderer.small_font.render(label.upper(), True, dim)
        value_surface = renderer.font.render(f"{value:,}", True, white)
        screen.blit(label_surface, label_surface.get_rect(midright=(width // 2 - 18, y)))
        screen.blit(value_surface, value_surface.get_rect(midleft=(width // 2 + 18, y)))
        y += 34

    ratio = snapshot.progress_ratio
    bar_width = min(520, max(220, width - 160))
    bar_height = 14
    bar_x = (width - bar_width) // 2
    bar_y = min(height - 105, y + 14)
    pygame.draw.rect(screen, grid, (bar_x, bar_y, bar_width, bar_height), 1)
    if ratio is None:
        sweep_width = max(30, bar_width // 5)
        phase_px = int((time.monotonic() * 180) % (bar_width + sweep_width)) - sweep_width
        left = max(0, phase_px)
        right = min(bar_width, phase_px + sweep_width)
        if right > left:
            pygame.draw.rect(screen, cyan, (bar_x + left, bar_y + 2, right - left, bar_height - 4))
    else:
        fill = int((bar_width - 4) * ratio)
        if fill > 0:
            pygame.draw.rect(screen, cyan, (bar_x + 2, bar_y + 2, fill, bar_height - 4))
        progress = renderer.small_font.render(
            f"{snapshot.files_processed:,} / {snapshot.stepfiles_found:,}", True, dim
        )
        screen.blit(progress, progress.get_rect(center=(width // 2, bar_y + 32)))

    hint = renderer.small_font.render("Esc returns to the main menu; indexing continues in the background", True, dim)
    screen.blit(hint, hint.get_rect(midbottom=(width // 2, height - 24)))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings_store = SettingsStore()
    if args.camera is not None:
        settings_store.settings.camera_index = max(0, args.camera)
    if args.reach is not None:
        settings_store.settings.horizontal_reach = clamp_horizontal_reach(args.reach)

    activity_store = ActivityStore(activity_path())
    active_profile = activity_store.active_profile()
    if active_profile is not None:
        prefs = active_profile.settings
        settings_store.settings.horizontal_reach = clamp_horizontal_reach(
            float(prefs.get("horizontal_reach", settings_store.settings.horizontal_reach))
        )
        settings_store.settings.favorite_song_keys = list(prefs.get("favorite_song_keys", []))
        settings_store.settings.played_song_keys = list(prefs.get("played_song_keys", []))
        settings_store.settings.last_song_key = str(prefs.get("last_song_key", ""))
        settings_store.settings.preferred_difficulty = str(
            prefs.get("preferred_difficulty", settings_store.settings.preferred_difficulty)
        )

    pygame.init()
    pygame.display.set_caption(f"VaporStep V{APP_VERSION}")
    try:
        icon_path = resource_path("assets/vaporstep_icon.png")
        if icon_path.exists():
            pygame.display.set_icon(pygame.image.load(str(icon_path)))
    except Exception:
        pass

    fullscreen = bool(args.fullscreen)
    screen = display_mode(fullscreen)
    clock = pygame.time.Clock()
    renderer = Renderer(screen)
    renderer.set_player_horizontal_zoom(settings_store.settings.horizontal_reach)
    keyboard = KeyboardBodyInput()
    menu_sounds = MenuSounds()
    gameplay_sounds = GameplaySounds()
    records: RecordStore | None = (
        RecordStore(profile_highscores_path(active_profile.id)) if active_profile is not None else None
    )
    preview = SongPreviewPlayer()
    library_indexer = LibraryIndexer()

    songs_root = _songs_root(args, settings_store)
    scan_errors: list[str] = []
    songs = []
    menu = SongMenu([])
    load_error: str | None = None
    favorite_keys = set(settings_store.settings.favorite_song_keys)
    played_keys = set(settings_store.settings.played_song_keys)
    favorites_only = False
    played_only = False
    chain_mode = ChainMode.BLOCKS
    record_play_enabled = False
    active_recording: RunRecorder | None = None
    result_recording: RunRecorder | None = None
    applied_scan_complete = False
    stats_week = week_start(date.today())
    profile_picker = ProfilePicker()
    profile_return_mode = "home"
    name_return_mode = "home"
    name_prompt: NamePrompt | None = None
    activity_started_at: datetime | None = None
    activity_run_recorded = False

    def chains_enabled(mode: ChainMode) -> bool:
        return mode != ChainMode.OFF

    def record_key(song, chart, mode: ChainMode) -> str:
        return chart_key(song, chart, chains_enabled=chains_enabled(mode))

    def save_profile_preferences() -> None:
        nonlocal active_profile
        if active_profile is None:
            return
        activity_store.update_profile_settings(
            active_profile.id,
            {
                "horizontal_reach": settings_store.settings.horizontal_reach,
                "favorite_song_keys": sorted(favorite_keys),
                "played_song_keys": sorted(played_keys),
                "last_song_key": settings_store.settings.last_song_key,
                "preferred_difficulty": settings_store.settings.preferred_difficulty,
            },
        )
        active_profile = activity_store.get_profile(active_profile.id)

    def song_was_played(song) -> bool:
        key = song_key(song)
        if key in played_keys:
            return True
        if records is None:
            return False
        return any(
            records.get(chart_key(song, chart, chains_enabled=enabled)).played_at
            for chart in song.charts
            for enabled in (True, False)
        )

    def rebuild_song_menu(preserve_key: str | None = None, fallback_index: int = 0) -> None:
        nonlocal menu
        visible = [
            song
            for song in songs
            if (not favorites_only or song_key(song) in favorite_keys)
            and (not played_only or song_was_played(song))
        ]
        menu = SongMenu(visible, preferred_difficulty=settings_store.settings.preferred_difficulty)
        target = preserve_key or settings_store.settings.last_song_key
        if target and visible:
            for index, song in enumerate(visible):
                if song_key(song) == target:
                    menu.select_song_index(index)
                    break
            else:
                menu.select_song_index(min(max(0, fallback_index), len(visible) - 1))
        elif visible:
            menu.select_song_index(min(max(0, fallback_index), len(visible) - 1))

    def apply_profile(profile) -> None:
        nonlocal active_profile, records, favorite_keys, played_keys
        active_profile = profile
        activity_store.set_active_profile(profile.id)
        records = RecordStore(profile_highscores_path(profile.id))
        prefs = profile.settings
        favorite_keys = set(prefs.get("favorite_song_keys", []))
        played_keys = set(prefs.get("played_song_keys", []))
        settings_store.settings.favorite_song_keys = sorted(favorite_keys)
        settings_store.settings.played_song_keys = sorted(played_keys)
        settings_store.settings.last_song_key = str(prefs.get("last_song_key", ""))
        settings_store.settings.preferred_difficulty = str(prefs.get("preferred_difficulty", "Medium"))
        settings_store.settings.horizontal_reach = clamp_horizontal_reach(
            float(prefs.get("horizontal_reach", settings_store.settings.horizontal_reach))
        )
        renderer.set_player_horizontal_zoom(settings_store.settings.horizontal_reach)
        rebuild_song_menu()
        _safe_settings_save(settings_store)

    def _adopt_song_list(new_songs, new_errors) -> None:
        nonlocal songs, scan_errors, load_error
        preserve_key = song_key(menu.song) if menu.song is not None else settings_store.settings.last_song_key
        songs = list(new_songs)
        scan_errors = list(new_errors)
        for song in songs:
            if song_was_played(song):
                played_keys.add(song_key(song))
        settings_store.settings.played_song_keys = sorted(played_keys)
        rebuild_song_menu(preserve_key)
        load_error = None

    def start_library_scan(*, show_progress: bool) -> None:
        nonlocal applied_scan_complete, mode
        preview.stop(reset_selection=True)
        if songs_root is None:
            _adopt_song_list([], [])
            return
        try:
            cached = library_indexer.cached_songs(songs_root)
        except Exception:
            cached = []
        if cached:
            _adopt_song_list(cached, [])
        library_indexer.start(songs_root)
        applied_scan_complete = False
        if show_progress:
            mode = "library_scan"

    def reset_activity_run() -> None:
        nonlocal activity_started_at, activity_run_recorded
        activity_started_at = None
        activity_run_recorded = False

    def finalize_activity_run(outcome: str) -> None:
        nonlocal activity_run_recorded
        if activity_run_recorded or active_profile is None or session is None or session.chart is None:
            return
        song_time = session.failed_song_time if session.failed_song_time is not None else session.time
        if activity_started_at is None or song_time <= 0.0:
            return
        progress = run_progress(song_time, session.chart.last_note_time)
        stomps, punches = target_activity(session.notes)
        qualifies = counts_as_song(progress)
        if qualifies:
            played_keys.add(song_key(session.chart.song))
            settings_store.settings.played_song_keys = sorted(played_keys)
        local_now = datetime.now().astimezone()
        activity_store.record_run(
            RunActivity(
                profile_id=active_profile.id,
                started_at_utc=activity_started_at.astimezone(timezone.utc).isoformat(),
                local_date=local_now.date().isoformat(),
                duration_seconds=max(0.0, min(song_time, session.chart.last_note_time)),
                song_key=song_key(session.chart.song),
                chart_key=record_key(session.chart.song, session.chart.chart, session.chain_mode),
                outcome=outcome,
                progress=progress,
                counts_as_song=qualifies,
                stomps=stomps,
                punches=punches,
                score=session.stats.score,
            )
        )
        activity_run_recorded = True
        save_profile_preferences()

    privacy_pending = (
        not args.demo
        and settings_store.settings.privacy_notice_version < PRIVACY_NOTICE_VERSION
    )

    repeater = HeldMenuRepeater()
    if args.demo:
        mode = "game"
    elif privacy_pending:
        mode = "privacy"
    elif active_profile is None:
        name_prompt = NamePrompt("CREATE PROFILE")
        mode = "profile_name"
    else:
        mode = "home"
    main_index = 0
    folder_browser: DirectoryBrowser | None = None
    session = GameSession(demo_notes=make_demo_notes()) if args.demo else None
    result_record = ChartRecord()
    result_new_high = False
    result_failed = False

    if songs_root is not None and not args.demo and not privacy_pending and active_profile is not None:
        start_library_scan(show_progress=False)

    camera: PoseCameraInput | None = None
    camera_error = ""
    camera_probe_ok: bool | None = None
    force_keyboard = bool(args.keyboard)
    use_keyboard = force_keyboard

    def stop_camera() -> None:
        nonlocal camera
        if camera is not None:
            camera.stop()
            camera = None

    def restart_camera(index: int | None = None) -> None:
        nonlocal camera, camera_error, use_keyboard
        if index is not None:
            settings_store.settings.camera_index = max(0, int(index))
        stop_camera()
        if force_keyboard:
            use_keyboard = True
            camera_error = "Keyboard mode"
            return
        try:
            model_path = ensure_pose_model()
            camera = PoseCameraInput(
                str(model_path),
                camera_index=settings_store.settings.camera_index,
                horizontal_zoom=settings_store.settings.horizontal_reach,
            )
            camera.start()
            use_keyboard = False
            camera_error = ""
        except Exception as exc:
            camera_error = str(exc)
            print(f"Camera/MediaPipe startup failed: {exc}", file=sys.stderr)
            use_keyboard = False

    def camera_status() -> str:
        if force_keyboard or (use_keyboard and camera is None):
            return camera_error or "Keyboard mode"
        if camera is None:
            if camera_error:
                return camera_error
            if camera_probe_ok is True:
                return "Camera ready — idle until calibration/gameplay"
            if camera_probe_ok is False:
                return "Camera idle — will retry when needed"
            return "Camera idle"
        snap = camera.snapshot()
        return snap.message

    def toggle_keyboard_input() -> None:
        nonlocal use_keyboard, camera_error
        if force_keyboard:
            use_keyboard = True
            camera_error = "Keyboard mode"
            stop_camera()
            return
        if use_keyboard:
            restart_camera()
        else:
            stop_camera()
            use_keyboard = True
            camera_error = "Keyboard mode"

    def run_camera_probe() -> None:
        nonlocal camera_probe_ok, camera_error
        if force_keyboard:
            camera_error = "Keyboard mode"
            return
        camera_probe_ok = probe_camera(settings_store.settings.camera_index)
        camera_error = ""

    if mode not in ("privacy", "profile_name"):
        run_camera_probe()

    if args.demo:
        restart_camera()

    debug = False
    running = True
    calibration_session = GameSession(demo_notes=make_demo_notes())
    calibration_last_beat: int | None = None

    def toggle_fullscreen() -> None:
        nonlocal fullscreen, screen
        fullscreen = not fullscreen
        screen = display_mode(fullscreen)
        renderer.replace_screen(screen)
        renderer.set_player_horizontal_zoom(settings_store.settings.horizontal_reach)

    def open_folder_browser() -> None:
        nonlocal mode, folder_browser
        start = songs_root if songs_root is not None and songs_root.exists() else (Path.home() / "Music")
        if not start.exists():
            start = Path.home()
        folder_browser = DirectoryBrowser(start)
        preview.stop(reset_selection=True)
        repeater.clear()
        mode = "folder"

    def open_profile_picker(return_mode: str) -> None:
        nonlocal mode, profile_return_mode
        profiles = activity_store.profiles()
        if not profiles:
            return
        save_profile_preferences()
        profile_return_mode = return_mode
        profile_picker.index = next(
            (index for index, profile in enumerate(profiles) if active_profile and profile.id == active_profile.id),
            0,
        )
        mode = "profiles"

    def handle_song_menu_action(action: MenuAction) -> None:
        nonlocal mode, session, load_error, result_failed, active_recording
        if action == MenuAction.BACK:
            preview.stop(reset_selection=True)
            repeater.clear()
            save_profile_preferences()
            _safe_settings_save(settings_store)
            mode = "home"
            return
        before_song = menu.song_index
        before_chart = menu.chart_index
        choice = menu.handle(action)
        moved = before_song != menu.song_index or before_chart != menu.chart_index
        if moved:
            menu_sounds.tick()
        if menu.song is not None:
            settings_store.settings.last_song_key = song_key(menu.song)
        settings_store.settings.preferred_difficulty = menu.preferred_difficulty
        if choice is None:
            return

        song, chart = choice
        preview.stop(reset_selection=True)
        menu_sounds.select()
        settings_store.settings.last_song_key = song_key(song)
        settings_store.settings.preferred_difficulty = menu.preferred_difficulty
        save_profile_preferences()
        _safe_settings_save(settings_store)
        try:
            loaded = load_chart(song, chart)
            assert records is not None
            record = records.get(record_key(song, chart, chain_mode))
            active_recording = None
            session = GameSession(chart=loaded, best_score=record.score, chain_mode=chain_mode)
            reset_activity_run()
            restart_camera()
            renderer.reset_game_effects()
            repeater.clear()
            load_error = None
            result_failed = False
            mode = "game"
            print(
                f"Loaded {song.display_title} / {chart.label}: "
                f"{len(loaded.notes)} VaporStep notes, "
                f"{loaded.skipped_rows} unsupported groups"
            )
        except Exception as exc:
            load_error = str(exc)

    try:
        while running:
            frame_dt = min(clock.get_time() / 1000.0, 0.10)
            now = time.monotonic()
            scan_snapshot = library_indexer.snapshot()
            if scan_snapshot.complete and not applied_scan_complete:
                expected_root = songs_root.expanduser().resolve() if songs_root is not None else None
                if scan_snapshot.root == expected_root:
                    _adopt_song_list(scan_snapshot.songs, scan_snapshot.errors)
                    for err in scan_snapshot.errors[:8]:
                        print(f"  warning: {err}", file=sys.stderr)
                    print(
                        f"Indexed {scan_snapshot.songs_found} songs / {scan_snapshot.charts_found} charts "
                        f"({scan_snapshot.cached_songs} cached, {scan_snapshot.parsed_songs} parsed)."
                    )
                    applied_scan_complete = True
                    if mode == "library_scan":
                        mode = "home"

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if mode == "game":
                        finalize_activity_run("escaped")
                    running = False
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    toggle_fullscreen()
                    continue

                if mode in ("home", "song_menu", "results", "stats", "about"):
                    if (
                        event.type == pygame.KEYDOWN
                        and event.key == pygame.K_u
                        and bool(getattr(event, "mod", 0) & pygame.KMOD_SHIFT)
                    ):
                        open_profile_picker(mode)
                        menu_sounds.select()
                        continue

                if mode == "profile_name":
                    assert name_prompt is not None
                    result = name_prompt.handle(event)
                    if result == "cancel":
                        if active_profile is None:
                            running = False
                        else:
                            mode = name_return_mode
                        continue
                    if result == "submit":
                        if name_prompt.profile_id is None:
                            profile = activity_store.create_profile(name_prompt.value)
                        else:
                            profile = activity_store.rename_profile(name_prompt.profile_id, name_prompt.value)
                        apply_profile(profile)
                        name_prompt = None
                        if active_profile is not None and songs_root is not None and not library_indexer.snapshot().running:
                            start_library_scan(show_progress=False)
                        run_camera_probe()
                        mode = name_return_mode
                        menu_sounds.select()
                    continue

                if mode == "profiles":
                    profiles = activity_store.profiles()
                    profile_picker.clamp(profiles)
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            mode = profile_return_mode
                        elif event.key in (pygame.K_UP, pygame.K_w):
                            profile_picker.index = (profile_picker.index - 1) % len(profiles)
                            menu_sounds.tick()
                        elif event.key in (pygame.K_DOWN, pygame.K_s):
                            profile_picker.index = (profile_picker.index + 1) % len(profiles)
                            menu_sounds.tick()
                        elif event.key == pygame.K_n:
                            name_prompt = NamePrompt("CREATE PROFILE")
                            name_return_mode = "profiles"
                            mode = "profile_name"
                        elif event.key == pygame.K_r and profiles:
                            selected = profiles[profile_picker.index]
                            name_prompt = NamePrompt("RENAME PROFILE", selected.name, selected.id)
                            name_return_mode = "profiles"
                            mode = "profile_name"
                        elif event.key == pygame.K_RETURN and profiles:
                            save_profile_preferences()
                            apply_profile(profiles[profile_picker.index])
                            mode = profile_return_mode
                            menu_sounds.select()
                    continue

                if mode == "library_scan":
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        mode = "home"
                    continue

                if mode == "privacy":
                    action = action_for_event(event)
                    if action == MenuAction.BACK:
                        running = False
                    elif action == MenuAction.SELECT:
                        settings_store.settings.privacy_notice_version = PRIVACY_NOTICE_VERSION
                        _safe_settings_save(settings_store)
                        if active_profile is None:
                            name_prompt = NamePrompt("CREATE PROFILE")
                            name_return_mode = "home"
                            mode = "profile_name"
                        else:
                            run_camera_probe()
                            mode = "home"
                            if songs_root is not None:
                                start_library_scan(show_progress=False)
                        menu_sounds.select()
                    continue

                if mode == "home":
                    action = action_for_event(event)
                    if action == MenuAction.UP:
                        main_index = (main_index - 1) % len(MAIN_OPTIONS)
                        menu_sounds.tick()
                    elif action == MenuAction.DOWN:
                        main_index = (main_index + 1) % len(MAIN_OPTIONS)
                        menu_sounds.tick()
                    elif action == MenuAction.BACK:
                        running = False
                    elif action == MenuAction.SELECT:
                        menu_sounds.select()
                        if main_index == 0:
                            if songs_root is None:
                                open_folder_browser()
                            else:
                                mode = "song_menu"
                        elif main_index == 1:
                            stats_week = week_start(date.today())
                            preview.stop(reset_selection=True)
                            mode = "stats"
                        elif main_index == 2:
                            preview.stop(reset_selection=True)
                            restart_camera()
                            calibration_session.restart()
                            calibration_last_beat = None
                            renderer.reset_game_effects()
                            mode = "calibration"
                        elif main_index == 3:
                            open_folder_browser()
                        elif main_index == 4:
                            preview.stop(reset_selection=True)
                            mode = "about"
                        else:
                            running = False
                    continue

                if mode == "stats":
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            mode = "home"
                        elif event.key in (pygame.K_LEFT, pygame.K_a):
                            stats_week -= timedelta(days=7)
                            menu_sounds.tick()
                        elif event.key in (pygame.K_RIGHT, pygame.K_d):
                            next_week = stats_week + timedelta(days=7)
                            if next_week <= week_start(date.today()):
                                stats_week = next_week
                                menu_sounds.tick()
                    continue

                if mode == "about":
                    action = action_for_event(event)
                    if action in (MenuAction.BACK, MenuAction.SELECT):
                        mode = "home"
                        menu_sounds.select()
                    continue

                if mode == "folder":
                    action = action_for_event(event)
                    if action == MenuAction.BACK:
                        mode = "home"
                        folder_browser = None
                        continue
                    if action is not None and folder_browser is not None:
                        before = folder_browser.index
                        chosen = folder_browser.handle(action)
                        if folder_browser.index != before or action == MenuAction.SELECT:
                            menu_sounds.tick()
                        if chosen is not None:
                            songs_root = chosen
                            settings_store.settings.song_folder = str(chosen)
                            _safe_settings_save(settings_store)
                            folder_browser = None
                            start_library_scan(show_progress=True)
                            menu_sounds.select()
                    continue

                if mode == "calibration":
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            save_profile_preferences()
                            _safe_settings_save(settings_store)
                            calibration_session.stop()
                            stop_camera()
                            renderer.reset_game_effects()
                            mode = "home"
                        elif event.key in (pygame.K_LEFT, pygame.K_a):
                            settings_store.settings.horizontal_reach = clamp_horizontal_reach(
                                settings_store.settings.horizontal_reach - HORIZONTAL_REACH_STEP
                            )
                            renderer.set_player_horizontal_zoom(settings_store.settings.horizontal_reach)
                            if camera is not None:
                                camera.set_horizontal_zoom(settings_store.settings.horizontal_reach)
                            menu_sounds.tick()
                        elif event.key in (pygame.K_RIGHT, pygame.K_d):
                            settings_store.settings.horizontal_reach = clamp_horizontal_reach(
                                settings_store.settings.horizontal_reach + HORIZONTAL_REACH_STEP
                            )
                            renderer.set_player_horizontal_zoom(settings_store.settings.horizontal_reach)
                            if camera is not None:
                                camera.set_horizontal_zoom(settings_store.settings.horizontal_reach)
                            menu_sounds.tick()
                        elif event.key in (pygame.K_UP, pygame.K_w):
                            restart_camera(settings_store.settings.camera_index + 1)
                            calibration_session.restart()
                            renderer.reset_game_effects()
                            menu_sounds.tick()
                        elif event.key in (pygame.K_DOWN, pygame.K_s):
                            restart_camera(max(0, settings_store.settings.camera_index - 1))
                            calibration_session.restart()
                            renderer.reset_game_effects()
                            menu_sounds.tick()
                        elif event.key == pygame.K_k:
                            toggle_keyboard_input()
                    continue

                if mode == "song_menu":
                    if event.type == pygame.KEYUP:
                        repeat_action = _repeat_action_for_key(event.key)
                        if repeat_action is not None:
                            repeater.release(repeat_action)
                        continue
                    if event.type == pygame.KEYDOWN:
                        shifted = bool(getattr(event, "mod", 0) & pygame.KMOD_SHIFT)
                        if event.key == pygame.K_f:
                            current_key = song_key(menu.song) if menu.song is not None else None
                            old_index = menu.song_index
                            if shifted:
                                favorites_only = not favorites_only
                                preview.stop(reset_selection=True)
                                rebuild_song_menu(current_key, old_index)
                            elif current_key is not None:
                                if current_key in favorite_keys:
                                    favorite_keys.remove(current_key)
                                else:
                                    favorite_keys.add(current_key)
                                settings_store.settings.favorite_song_keys = sorted(favorite_keys)
                                save_profile_preferences()
                                _safe_settings_save(settings_store)
                                if favorites_only:
                                    preview.stop(reset_selection=True)
                                    rebuild_song_menu(current_key, old_index)
                            menu_sounds.tick()
                            continue
                        if shifted and event.key == pygame.K_p:
                            current_key = song_key(menu.song) if menu.song is not None else None
                            old_index = menu.song_index
                            played_only = not played_only
                            preview.stop(reset_selection=True)
                            rebuild_song_menu(current_key, old_index)
                            menu_sounds.tick()
                            continue
                        if shifted and event.key == pygame.K_r:
                            if record_play_enabled:
                                record_play_enabled = False
                                load_error = None
                            else:
                                backend_ok, backend_error = recording_backend_status()
                                if backend_ok:
                                    record_play_enabled = True
                                    load_error = None
                                else:
                                    load_error = (
                                        "Recording unavailable in this build. "
                                        f"{backend_error}"
                                    )
                            menu_sounds.tick()
                            continue
                        if event.key == pygame.K_v:
                            chain_mode = chain_mode.shifted()
                            menu_sounds.tick()
                            continue
                    action = action_for_event(event)
                    if action is not None:
                        if getattr(event, "repeat", False) and action in (MenuAction.UP, MenuAction.DOWN):
                            continue
                        repeat_action = _repeat_action_for_key(getattr(event, "key", -1))
                        if repeat_action is not None:
                            repeater.press(repeat_action, now)
                        handle_song_menu_action(action)
                    continue

                if mode == "results":
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_r and session is not None:
                        session.set_best_score(result_record.score)
                        restart_camera()
                        session.restart()
                        reset_activity_run()
                        renderer.reset_game_effects()
                        result_failed = False
                        mode = "game"
                        menu_sounds.select()
                        continue
                    action = action_for_event(event)
                    if action in (MenuAction.BACK, MenuAction.SELECT):
                        repeater.clear()
                        renderer.reset_game_effects()
                        preview.stop(reset_selection=True)
                        mode = "song_menu"
                        if action == MenuAction.SELECT:
                            menu_sounds.select()
                    continue

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_v and session is not None and not session.running:
                        chain_mode = chain_mode.shifted()
                        session.set_chain_mode(chain_mode)
                        if session.chart is not None and records is not None:
                            current_record = records.get(
                                record_key(session.chart.song, session.chart.chart, chain_mode)
                            )
                            session.set_best_score(current_record.score)
                        renderer.reset_game_effects()
                        menu_sounds.tick()
                    elif event.key == pygame.K_ESCAPE:
                        if args.demo:
                            running = False
                        else:
                            finalize_activity_run("escaped")
                            if session is not None:
                                session.stop()
                            if active_recording is not None:
                                active_recording.abort()
                                active_recording = None
                            stop_camera()
                            repeater.clear()
                            mode = "song_menu"
                    elif event.key == pygame.K_d:
                        debug = not debug
                    elif event.key == pygame.K_r and session is not None:
                        finalize_activity_run("escaped")
                        if active_recording is not None:
                            active_recording.abort()
                            active_recording = None
                        session.restart()
                        reset_activity_run()
                        renderer.reset_game_effects()
                    elif event.key == pygame.K_k:
                        toggle_keyboard_input()

            if mode == "privacy":
                renderer.draw_privacy_notice()
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "profile_name":
                renderer.screen.fill((2, 2, 8))
                renderer._draw_background(time.monotonic(), 0.0, False)
                assert name_prompt is not None
                draw_name_prompt(renderer, name_prompt)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "profiles":
                if profile_return_mode == "home" and active_profile is not None:
                    draw_home(
                        renderer,
                        main_index,
                        songs_root,
                        len(songs),
                        settings_store.settings.camera_index,
                        settings_store.settings.horizontal_reach,
                        camera_status(),
                        active_profile.name,
                    )
                else:
                    renderer.screen.fill((2, 2, 8))
                    renderer._draw_background(time.monotonic(), 0.0, False)
                draw_profile_picker(renderer, activity_store.profiles(), profile_picker)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "about":
                renderer.draw_about()
                draw_profile_badge(renderer, active_profile)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "stats":
                assert active_profile is not None
                draw_activity_dashboard(renderer, activity_store, active_profile, stats_week)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "library_scan":
                _draw_library_scan(renderer, scan_snapshot)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "home":
                assert active_profile is not None
                status_text = camera_status()
                if scan_snapshot.running:
                    if scan_snapshot.phase == "discovering":
                        status_text += f"  ·  library scan {scan_snapshot.folders_scanned:,} folders"
                    else:
                        status_text += (
                            f"  ·  library {scan_snapshot.files_processed:,}/{scan_snapshot.stepfiles_found:,}"
                        )
                draw_home(
                    renderer,
                    main_index,
                    songs_root,
                    len(songs),
                    settings_store.settings.camera_index,
                    settings_store.settings.horizontal_reach,
                    status_text,
                    active_profile.name,
                )
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "folder":
                assert folder_browser is not None
                renderer.draw_directory_browser(folder_browser)
                draw_profile_badge(renderer, active_profile)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "song_menu":
                for repeated in repeater.update(now):
                    handle_song_menu_action(repeated)
                menu.animate(frame_dt)
                preview.update(menu.song, now)
                selected_record = ChartRecord()
                if menu.song is not None and menu.chart is not None and records is not None:
                    selected_record = records.get(record_key(menu.song, menu.chart, chain_mode))
                renderer.draw_song_menu(
                    menu,
                    songs_root,
                    load_error,
                    len(scan_errors),
                    selected_record,
                    library_count=len(songs),
                    favorite_keys=favorite_keys,
                    favorites_only=favorites_only,
                    played_only=played_only,
                    chain_mode=chain_mode,
                    recording_enabled=record_play_enabled,
                )
                draw_profile_badge(renderer, active_profile)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "results":
                assert session is not None
                title = session.chart.song.display_title if session.chart else "VaporStep Demo"
                chart_label = session.chart.chart.label if session.chart else "Synthetic chart"
                renderer.draw_results(
                    title,
                    chart_label,
                    session.stats,
                    result_record.score,
                    result_new_high,
                    failed=result_failed,
                    recording_status=(result_recording.snapshot().message if result_recording is not None else ""),
                )
                draw_profile_badge(renderer, active_profile)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if use_keyboard:
                body = keyboard.body_state()
                mask = None
                status = "READY"
                pose_fps = 0.0
                input_name = "keyboard"
            elif camera is None:
                body = BodyState()
                mask = None
                status = camera_error or "Camera unavailable — press K for keyboard mode"
                pose_fps = 0.0
                input_name = "camera unavailable"
            else:
                snap = camera.snapshot()
                body = snap.body
                mask = snap.mask
                status = snap.message
                pose_fps = snap.pose_fps
                input_name = "webcam"

            if mode == "calibration":
                calibration_ready = use_keyboard or status == "READY"
                calibration_session.update(body, ready_to_start=calibration_ready)
                gameplay_sounds.play(calibration_session.drain_gameplay_events())
                if calibration_session.finished or calibration_session.failed:
                    calibration_session.restart()
                    calibration_last_beat = None
                    renderer.reset_game_effects()

                beat_pulse, downbeat = (
                    calibration_session.beat_pulse() if calibration_session.running else (0.0, False)
                )
                if calibration_session.running:
                    beat_index = int(math.floor(calibration_session.beat_position))
                    if beat_index != calibration_last_beat:
                        gameplay_sounds.play_calibration_beat(downbeat=(beat_index % 4 == 0))
                        calibration_last_beat = beat_index
                else:
                    calibration_last_beat = None
                renderer.draw(
                    body=body,
                    mask=mask,
                    notes=calibration_session.notes,
                    song_time=calibration_session.time,
                    song_beat=calibration_session.beat_position,
                    status=status,
                    debug=debug,
                    pose_fps=pose_fps,
                    input_name=input_name,
                    song_title="CALIBRATION",
                    chart_label="Hit the demo targets; hands strike upward, feet step downward",
                    stats=None,
                    best_score=0,
                    running=calibration_session.running,
                    beat_pulse=beat_pulse,
                    downbeat=downbeat,
                    hand_enabled=True,
                    foot_enabled=True,
                    performance_state="ok",
                    strike_events=tuple(calibration_session.recent_motion_events),
                    show_lower_body_sources=True,
                )
                renderer.draw_calibration_overlay(
                    settings_store.settings.camera_index,
                    settings_store.settings.horizontal_reach,
                    camera_status(),
                )
                draw_lower_body_tracking_overlay(renderer, body)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            assert session is not None
            if not use_keyboard and camera is not None:
                status = _readiness_for_session(body, session)
            was_running = session.running
            session.update(body, ready_to_start=(use_keyboard or status == "READY"))
            if not was_running and session.running and activity_started_at is None and session.chart is not None:
                activity_started_at = datetime.now(timezone.utc)

            if (
                record_play_enabled
                and not args.demo
                and session.running
                and active_recording is None
                and session.chart is not None
            ):
                active_recording = RunRecorder(
                    song_title=session.chart.song.display_title,
                    chart_label=session.chart.chart.label,
                    music_path=session.chart.song.music_path,
                    chart_time_at_start=session.time,
                )

            gameplay_events = session.drain_gameplay_events()
            gameplay_sounds.play(gameplay_events)
            if active_recording is not None:
                active_recording.add_events(gameplay_events)

            if session.finished and not args.demo:
                outcome = "failed" if session.failed else "completed"
                finalize_activity_run(outcome)
                session.stop()
                stop_camera()
                assert session.chart is not None
                key = record_key(session.chart.song, session.chart.chart, session.chain_mode)
                result_failed = session.failed
                result_recording = active_recording
                assert records is not None
                if result_failed:
                    result_record = records.get(key)
                    result_new_high = False
                else:
                    result_record, result_new_high = records.submit(key, session.stats)
                    session.set_best_score(result_record.score)
                mode = "results"

                renderer.draw_results(
                    session.chart.song.display_title,
                    session.chart.chart.label,
                    session.stats,
                    result_record.score,
                    result_new_high,
                    failed=result_failed,
                    recording_status="",
                )
                if active_recording is not None:
                    active_recording.append_static_tail(renderer.screen, RECORD_RESULTS_HOLD_SECONDS)
                    active_recording.finish(
                        grade=session.stats.grade,
                        failed=result_failed,
                        music_stop_time=(session.failed_song_time if result_failed else None),
                    )
                    active_recording = None
                    renderer.draw_results(
                        session.chart.song.display_title,
                        session.chart.chart.label,
                        session.stats,
                        result_record.score,
                        result_new_high,
                        failed=result_failed,
                        recording_status=result_recording.snapshot().message,
                    )
                draw_profile_badge(renderer, active_profile)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            beat_pulse, downbeat = session.beat_pulse() if session.running else (0.0, False)
            renderer.draw(
                body=body,
                mask=mask,
                notes=session.notes,
                song_time=session.time,
                song_beat=session.beat_position,
                status=status,
                debug=debug,
                pose_fps=pose_fps,
                input_name=input_name,
                song_title=(session.chart.song.display_title if session.chart else "VaporStep Demo"),
                chart_label=(
                    f"{session.chart.chart.label}  •  VIRTUAL HOLDS {session.chain_mode.label}"
                    if session.chart
                    else "Synthetic chart"
                ),
                audio_error=session.audio_error,
                stats=session.stats,
                best_score=session.best_score,
                running=session.running,
                beat_pulse=beat_pulse,
                downbeat=downbeat,
                hand_enabled=session.has_hand_notes,
                foot_enabled=session.has_foot_notes,
                performance_state=session.performance_state,
                strike_events=tuple(session.recent_motion_events),
                chains=tuple(session.chains),
                chain_mode=session.chain_mode,
            )
            if active_recording is not None:
                active_recording.capture(renderer.screen, time.monotonic())
            if record_play_enabled:
                renderer.draw_recording_indicator()
            pygame.display.flip()
            clock.tick(TARGET_FPS)
    finally:
        if mode == "game":
            finalize_activity_run("escaped")
        preview.stop(reset_selection=True)
        settings_store.settings.favorite_song_keys = sorted(favorite_keys)
        settings_store.settings.played_song_keys = sorted(played_keys)
        save_profile_preferences()
        _safe_settings_save(settings_store)
        if session is not None:
            session.stop()
        if active_recording is not None:
            active_recording.abort()
        stop_camera()
        activity_store.close()
        pygame.quit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
