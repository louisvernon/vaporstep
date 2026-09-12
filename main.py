from __future__ import annotations

import asyncio
import os
from pathlib import Path
import traceback

# Keep package import limited to web-safe modules. The finished desktop app
# continues to use vaporstep.app and its native camera/recording integrations.
os.environ["VAPORSTEP_WEB"] = "1"


def _phase(name: str) -> None:
    print(f"[VaporTap boot] {name}", flush=True)


def _build_id() -> str:
    try:
        return Path(__file__).with_name("build-version.txt").read_text(encoding="utf-8").strip()
    except (NameError, OSError):
        return "local"


_phase("PYTHON ENTRY")
_phase(f"BUILD {_build_id()}")
import pygame
_phase("PYGAME IMPORTED")


BG = (2, 2, 8)
CYAN = (70, 245, 255)
WHITE = (235, 245, 255)
RED = (255, 75, 110)


def _draw_status(
    screen: pygame.Surface,
    title: str,
    lines: list[str],
    *,
    error: bool = False,
) -> None:
    screen.fill(BG)
    title_font = pygame.font.Font(None, 42)
    body_font = pygame.font.Font(None, 25)
    color = RED if error else CYAN
    screen.blit(title_font.render(title, True, color), (42, 38))

    y = 96
    for raw in lines:
        text = str(raw)
        while len(text) > 96:
            split = text.rfind(" ", 0, 96)
            if split < 24:
                split = 96
            screen.blit(body_font.render(text[:split], True, WHITE), (44, y))
            text = text[split:].lstrip()
            y += 27
        screen.blit(body_font.render(text, True, WHITE), (44, y))
        y += 27
    pygame.display.flip()


async def _wait_for_user_start(screen: pygame.Surface) -> bool:
    _draw_status(
        screen,
        "VaporTap audio playtest",
        [
            "Click, tap, or press any key to start.",
            "This gesture unlocks browser audio before the shared GameSession starts.",
            "You should hear a 120 BPM click track when chart time reaches zero.",
        ],
    )
    _phase("WAIT USER START")
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                _phase("USER START (keyboard)")
                return True
            if event.type == pygame.MOUSEBUTTONDOWN:
                _phase("USER START (mouse)")
                return True
            if event.type == pygame.FINGERDOWN:
                _phase("USER START (touch)")
                return True
        await asyncio.sleep(0)


async def _show_startup_error(screen: pygame.Surface, exc: BaseException) -> None:
    _phase(f"FAILED: {type(exc).__name__}: {exc}")
    traceback.print_exc()
    details = traceback.format_exception(type(exc), exc, exc.__traceback__)
    lines = [line.rstrip() for chunk in details for line in chunk.splitlines()]
    _draw_status(
        screen,
        "VaporTap startup failed",
        [*lines[-18:], "", "Reload the page after the next build to retry."],
        error=True,
    )

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return
        await asyncio.sleep(0)


async def boot() -> None:
    # Avoid initializing the mixer until after a browser user gesture. Display
    # and font are enough to show diagnostics and the explicit start gate.
    _phase("PYGAME VIDEO INIT")
    pygame.display.init()
    pygame.font.init()
    _phase("CREATE DISPLAY")
    screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
    pygame.display.set_caption("VaporTap WASM Shared-Session Playtest")
    _phase("DISPLAY READY")
    _draw_status(
        screen,
        "VaporTap",
        ["Loading shared VaporStep chart/session stack…"],
    )
    await asyncio.sleep(0)

    try:
        _phase("CHECK WEB RUNTIME")
        from vaporstep.web_compat import ensure_decimal_runtime, install_pkg_resources_shim

        pkg_resources_backend = install_pkg_resources_shim()
        _phase(f"PKG_RESOURCES READY ({pkg_resources_backend})")
        decimal_backend = ensure_decimal_runtime()
        _phase(f"DECIMAL READY ({decimal_backend})")

        # Delay the heavier shared stack until after a real frame is visible.
        # In particular, simfile and its filesystem dependency should never be
        # able to fail before the browser has something useful to show us.
        _phase("IMPORT SHARED STACK")
        from vaporstep.web_vaportap_session import main as run_vaportap
        _phase("SHARED STACK IMPORTED")

        if not await _wait_for_user_start(screen):
            return

        _phase("INIT MIXER")
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        _phase(f"MIXER READY {pygame.mixer.get_init()}")

        _phase("START SESSION")
        await run_vaportap()
        _phase("SESSION EXITED")
    except BaseException as exc:
        await _show_startup_error(screen, exc)


asyncio.run(boot())
