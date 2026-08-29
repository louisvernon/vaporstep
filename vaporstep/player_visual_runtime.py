from __future__ import annotations

from typing import Any

from .settings import SettingsStore as BaseSettingsStore, normalize_player_visual as _normalize_player_visual


_ACTIVE_PLAYER_VISUAL = "silhouette"


def current_player_visual() -> str:
    return _ACTIVE_PLAYER_VISUAL


def _set_active_player_visual(value: object) -> str:
    global _ACTIVE_PLAYER_VISUAL
    _ACTIVE_PLAYER_VISUAL = _normalize_player_visual(value)
    return _ACTIVE_PLAYER_VISUAL


class _VisualValue(str):
    """String setting that lets the unchanged app request pose landmarks for Character."""

    def __new__(cls, value: object):
        return super().__new__(cls, _normalize_player_visual(value))

    def __eq__(self, other: object) -> bool:
        # app.py currently forwards PoseFigure only for the skeleton path.
        # Both low-cost character visuals consume that same landmark payload.
        if str(self) == "character" and other == "skeleton":
            return True
        return str.__eq__(self, other)

    __hash__ = str.__hash__


class _ExactVisual(str):
    """Marks an explicit CLI choice so it is not mistaken for a V-key cycle."""


def exact_player_visual(value: object) -> _ExactVisual:
    return _ExactVisual(_normalize_player_visual(value))


class _SettingsProxy:
    def __init__(self, target) -> None:
        object.__setattr__(self, "_target", target)
        _set_active_player_visual(target.player_visual)

    def __getattr__(self, name: str) -> Any:
        value = getattr(object.__getattribute__(self, "_target"), name)
        if name == "player_visual":
            return _VisualValue(value)
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        target = object.__getattribute__(self, "_target")
        if name != "player_visual":
            setattr(target, name, value)
            return

        current = _normalize_player_visual(target.player_visual)
        requested = _normalize_player_visual(value)
        if isinstance(value, _ExactVisual):
            selected = requested
        elif current == "skeleton" and requested == "silhouette":
            # app.py's existing two-state V toggle writes "silhouette" here;
            # reinterpret that transition as the new third state.
            selected = "character"
        elif current == "character" and requested == "silhouette":
            selected = "silhouette"
        else:
            selected = requested
        target.player_visual = selected
        _set_active_player_visual(selected)

    @property
    def _raw(self):
        return object.__getattribute__(self, "_target")

    def _replace(self, target) -> None:
        object.__setattr__(self, "_target", target)
        _set_active_player_visual(target.player_visual)


class SettingsStore:
    """Runtime adapter adding a third player-visual state to the existing app loop."""

    def __init__(self, path=None) -> None:
        self._store = BaseSettingsStore(path)
        self.settings = _SettingsProxy(self._store.settings)

    @property
    def path(self):
        return self._store.path

    def load(self):
        loaded = self._store.load()
        self.settings._replace(loaded)
        return self.settings

    def save(self) -> None:
        self._store.settings = self.settings._raw
        self._store.save()
        self.settings._replace(self._store.settings)

    def __getattr__(self, name: str):
        return getattr(self._store, name)


def main(argv: list[str] | None = None) -> int:
    """Run the app with procedural and hybrid pose-driven player visuals."""
    from . import app
    from .hybrid_character_renderer import Renderer

    app.Renderer = Renderer
    app.SettingsStore = SettingsStore
    app.normalize_player_visual = exact_player_visual
    return app.main(argv)
