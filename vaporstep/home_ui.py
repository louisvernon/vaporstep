from __future__ import annotations

import pygame


BG = (2, 2, 8)
CYAN = (70, 245, 255)
MAGENTA = (255, 55, 210)
WHITE = (235, 245, 255)
DIM = (70, 88, 115)
GRID = (25, 64, 88)


MAIN_OPTIONS = ("PLAY", "STATS", "CALIBRATE", "SONG FOLDER", "ABOUT", "QUIT")


def draw_home(
    renderer,
    selected: int,
    songs_root,
    song_count: int,
    camera_index: int | None,
    horizontal_reach: float,
    camera_status: str,
    profile_name: str,
) -> None:
    screen = renderer.screen
    screen.fill(BG)
    now = pygame.time.get_ticks() / 1000.0
    renderer._draw_background(now, 0.0, False)
    w, h = renderer.size

    title = renderer.huge_font.render("VAPORSTEP", True, MAGENTA)
    screen.blit(title, title.get_rect(center=(w // 2, int(h * 0.17))))
    subtitle = renderer.small_font.render("FULL-BODY RHYTHM", True, CYAN)
    screen.blit(subtitle, subtitle.get_rect(center=(w // 2, int(h * 0.25))))

    profile = renderer.small_font.render(f"PROFILE  {profile_name.upper()}", True, CYAN)
    screen.blit(profile, profile.get_rect(topright=(w - 22, 18)))

    start_y = int(h * 0.34)
    row_h = 52
    for index, label in enumerate(MAIN_OPTIONS):
        y = start_y + index * row_h
        active = index == selected
        color = WHITE if active else DIM
        text = renderer.big_font.render(label, True, color)
        rect = text.get_rect(center=(w // 2, y))
        if active:
            pygame.draw.line(screen, CYAN, (rect.left - 42, y), (rect.left - 14, y), 2)
            pygame.draw.line(screen, MAGENTA, (rect.right + 14, y), (rect.right + 42, y), 2)
        screen.blit(text, rect)

    root_text = str(songs_root) if songs_root is not None else "not configured"
    library = renderer.small_font.render(f"SONGS  {song_count}   •   {root_text}", True, DIM)
    screen.blit(library, library.get_rect(midbottom=(w // 2, h - 66)))
    camera_label = "OFF" if camera_index is None else str(camera_index)
    camera = renderer.small_font.render(
        f"CAMERA {camera_label}   •   REACH {horizontal_reach:.2f}x" +
        (f"   •   {camera_status}" if camera_status else ""),
        True,
        DIM,
    )
    screen.blit(camera, camera.get_rect(midbottom=(w // 2, h - 42)))
    controls = renderer.small_font.render(
        "↑/↓ choose    Enter select    Shift+U profiles    F11 fullscreen", True, GRID
    )
    screen.blit(controls, controls.get_rect(midbottom=(w // 2, h - 16)))
