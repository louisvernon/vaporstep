from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys
import time

import pygame

from . import __version__
from .audio_fx import GameplaySounds, MenuSounds
from .config import TARGET_FPS, WINDOW_HEIGHT, WINDOW_WIDTH
from .demo import make_demo_notes
from .directory_browser import DirectoryBrowser
from .domain import BodyState, ChainMode
from .keyboard_input import KeyboardBodyInput
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
    MAX_HORIZONTAL_REACH,
    MIN_HORIZONTAL_REACH,
    SettingsStore,
    clamp_horizontal_reach,
)
from .simfile_loader import load_chart, scan_library
from .tracking_overlay import draw_lower_body_tracking_overlay


APP_VERSION = __version__
MAIN_OPTIONS = ("PLAY", "CALIBRATE", "SONG FOLDER", "ABOUT", "QUIT")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings_store = SettingsStore()
    if args.camera is not None:
        settings_store.settings.camera_index = max(0, args.camera)
    if args.reach is not None:
        settings_store.settings.horizontal_reach = clamp_horizontal_reach(args.reach)

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
    records = RecordStore()
    preview = SongPreviewPlayer()

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

    def song_was_played(song) -> bool:
        key = song_key(song)
        if key in played_keys:
            return True
        return any(records.get(chart_key(song, chart)).played_at for chart in song.charts)

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

    def scan_current_library() -> None:
        nonlocal songs, scan_errors, load_error
        preview.stop(reset_selection=True)
        scan_errors = []
        songs = []
        if songs_root is not None:
            print(f"Scanning stepfile songs: {songs_root}")
            songs, scan_errors = scan_library(songs_root)
            print(f"Found {len(songs)} compatible songs ({len(scan_errors)} parse errors).")
            for err in scan_errors[:8]:
                print(f"  warning: {err}", file=sys.stderr)
        for song in songs:
            if song_was_played(song):
                played_keys.add(song_key(song))
        settings_store.settings.played_song_keys = sorted(played_keys)
        rebuild_song_menu(settings_store.settings.last_song_key)
        load_error = None

    privacy_pending = (
        not args.demo
        and settings_store.settings.privacy_notice_version < PRIVACY_NOTICE_VERSION
    )
    if songs_root is not None and not args.demo and not privacy_pending:
        scan_current_library()

    repeater = HeldMenuRepeater()
    mode = "game" if args.demo else ("privacy" if privacy_pending else "home")
    main_index = 0
    folder_browser: DirectoryBrowser | None = None
    session = GameSession(demo_notes=make_demo_notes()) if args.demo else None
    result_record = ChartRecord()
    result_new_high = False
    result_failed = False

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

    if mode != "privacy":
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

    def handle_song_menu_action(action: MenuAction) -> None:
        nonlocal mode, session, load_error, result_failed, active_recording
        if action == MenuAction.BACK:
            preview.stop(reset_selection=True)
            repeater.clear()
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
        played_keys.add(song_key(song))
        settings_store.settings.played_song_keys = sorted(played_keys)
        settings_store.settings.last_song_key = song_key(song)
        settings_store.settings.preferred_difficulty = menu.preferred_difficulty
        _safe_settings_save(settings_store)
        try:
            loaded = load_chart(song, chart)
            record = records.get(chart_key(song, chart))
            active_recording = None
            session = GameSession(chart=loaded, best_score=record.score, chain_mode=chain_mode)
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

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    toggle_fullscreen()
                    continue

                if mode == "privacy":
                    action = action_for_event(event)
                    if action == MenuAction.BACK:
                        running = False
                    elif action == MenuAction.SELECT:
                        settings_store.settings.privacy_notice_version = PRIVACY_NOTICE_VERSION
                        _safe_settings_save(settings_store)
                        run_camera_probe()
                        if songs_root is not None:
                            scan_current_library()
                        mode = "home"
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
                            preview.stop(reset_selection=True)
                            restart_camera()
                            calibration_session.restart()
                            calibration_last_beat = None
                            renderer.reset_game_effects()
                            mode = "calibration"
                        elif main_index == 2:
                            open_folder_browser()
                        elif main_index == 3:
                            preview.stop(reset_selection=True)
                            mode = "about"
                        else:
                            running = False
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
                            scan_current_library()
                            folder_browser = None
                            mode = "home"
                            menu_sounds.select()
                    continue

                if mode == "calibration":
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
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
                        if event.key == pygame.K_c:
                            chain_mode = chain_mode.shifted(1)
                            menu_sounds.tick()
                            continue
                        if event.key == pygame.K_a:
                            chain_mode = chain_mode.shifted(-1)
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
                    if event.key in (pygame.K_a, pygame.K_c) and session is not None and not session.running:
                        chain_mode = chain_mode.shifted(-1 if event.key == pygame.K_a else 1)
                        session.set_chain_mode(chain_mode)
                        renderer.reset_game_effects()
                        menu_sounds.tick()
                    elif event.key == pygame.K_ESCAPE:
                        if args.demo:
                            running = False
                        else:
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
                        if active_recording is not None:
                            active_recording.abort()
                            active_recording = None
                        session.restart()
                        renderer.reset_game_effects()
                    elif event.key == pygame.K_k:
                        toggle_keyboard_input()

            if mode == "privacy":
                renderer.draw_privacy_notice()
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "about":
                renderer.draw_about()
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "home":
                renderer.draw_main_menu(
                    main_index,
                    songs_root,
                    len(songs),
                    settings_store.settings.camera_index,
                    settings_store.settings.horizontal_reach,
                    camera_status(),
                )
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "folder":
                assert folder_browser is not None
                renderer.draw_directory_browser(folder_browser)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
                continue

            if mode == "song_menu":
                for repeated in repeater.update(now):
                    handle_song_menu_action(repeated)
                menu.animate(frame_dt)
                preview.update(menu.song, now)
                selected_record = ChartRecord()
                if menu.song is not None and menu.chart is not None:
                    selected_record = records.get(chart_key(menu.song, menu.chart))
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
            session.update(body, ready_to_start=(use_keyboard or status == "READY"))

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
                session.stop()
                stop_camera()
                assert session.chart is not None
                key = chart_key(session.chart.song, session.chart.chart)
                result_failed = session.failed
                result_recording = active_recording
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
                    f"{session.chart.chart.label}  •  CHAINS {session.chain_mode.label}"
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
        preview.stop(reset_selection=True)
        settings_store.settings.favorite_song_keys = sorted(favorite_keys)
        settings_store.settings.played_song_keys = sorted(played_keys)
        _safe_settings_save(settings_store)
        if session is not None:
            session.stop()
        if active_recording is not None:
            active_recording.abort()
        stop_camera()
        pygame.quit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
