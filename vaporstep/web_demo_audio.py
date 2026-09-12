from __future__ import annotations

from pathlib import Path


def ensure_web_demo_audio(stepfile: Path) -> Path:
    """Return the bundled OGG click track used by the browser audio probe.

    The fixture is deliberately a real browser-friendly audio asset so the
    playtest exercises the same simfile #MUSIC -> SongInfo -> GameSession ->
    pygame.mixer.music path as an ordinary VaporStep song.
    """
    target = stepfile.with_name("web_demo.ogg").resolve()
    if not target.is_file() or target.stat().st_size <= 0:
        raise RuntimeError(f"Missing VaporTap browser audio fixture: {target}")
    return target
