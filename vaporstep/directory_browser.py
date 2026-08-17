from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .menu import MenuAction


@dataclass
class DirectoryBrowser:
    current: Path
    index: int = 0
    directories: list[Path] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        self.current = self.current.expanduser().resolve()
        self.refresh()

    @property
    def entries(self) -> list[tuple[str, Path | None]]:
        result: list[tuple[str, Path | None]] = [("USE THIS FOLDER", None)]
        parent = self.current.parent
        if parent != self.current:
            result.append(("..", parent))
        result.extend((p.name, p) for p in self.directories)
        return result

    @property
    def selected_label(self) -> str:
        entries = self.entries
        if not entries:
            return ""
        return entries[self.index % len(entries)][0]

    def refresh(self) -> None:
        self.error = None
        try:
            dirs = [p for p in self.current.iterdir() if p.is_dir() and not p.name.startswith(".")]
            self.directories = sorted(dirs, key=lambda p: p.name.casefold())
        except OSError as exc:
            self.directories = []
            self.error = str(exc)
        self.index = max(0, min(self.index, max(0, len(self.entries) - 1)))

    def handle(self, action: MenuAction) -> Path | None:
        entries = self.entries
        if not entries:
            return None
        if action == MenuAction.UP:
            self.index = (self.index - 1) % len(entries)
            return None
        if action == MenuAction.DOWN:
            self.index = (self.index + 1) % len(entries)
            return None
        if action == MenuAction.SELECT:
            label, target = entries[self.index]
            if target is None and label == "USE THIS FOLDER":
                return self.current
            if target is not None:
                self.current = target.resolve()
                self.index = 0
                self.refresh()
        return None
