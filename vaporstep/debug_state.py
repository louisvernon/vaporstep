from __future__ import annotations


_debug_enabled = False
_buffered_scoring_age_ms: float | None = None


def set_debug_enabled(enabled: bool) -> None:
    """Publish whether runtime debug output (F3) is currently enabled."""
    global _debug_enabled
    _debug_enabled = bool(enabled)


def debug_enabled() -> bool:
    return _debug_enabled


def set_scoring_sample_context(buffered_age_ms: float | None) -> None:
    """Mark the camera sample currently driving scoring on the main thread."""
    global _buffered_scoring_age_ms
    _buffered_scoring_age_ms = (
        None if buffered_age_ms is None else max(0.0, float(buffered_age_ms))
    )


def buffered_scoring_age_ms() -> float | None:
    return _buffered_scoring_age_ms


def log_buffered_scoring_hit(quality: object, points: int) -> None:
    """Log when retained older camera evidence directly produces a scored hit."""
    age_ms = _buffered_scoring_age_ms
    if not _debug_enabled or age_ms is None:
        return
    label = getattr(quality, "name", str(quality))
    print(
        "DEBUG buffered scoring contribution: "
        f"{label} hit from pose {age_ms:.1f}ms older than newest completed pose "
        f"(+{int(points)} points)"
    )
