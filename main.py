from __future__ import annotations

import asyncio
import os
import traceback

# Keep package import limited to web-safe modules. The finished desktop app
# continues to use vaporstep.app and its native camera/recording integrations.
os.environ["VAPORSTEP_WEB"] = "1"


def _phase(name: str) -> None:
    print(f"[VaporTap boot] {name}", flush=True)


_phase("PYTHON ENTRY")
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
    _phase("PYGAME INIT")
    pygame.init()
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
        # Delay the heavier shared stack until after a real frame is visible.
        # In particular, simfile and its filesystem dependency should never be
        # able to fail before the browser has something useful to show us.
        _phase("IMPORT SHARED STACK")
        from vaporstep.web_vaportap_session import main as run_vaportap
        _phase("SHARED STACK IMPORTED")

        _phase("START SESSION")
        await run_vaportap()
        _phase("SESSION EXITED")
    except BaseException as exc:
        await _show_startup_error(screen, exc)


asyncio.run(boot())
