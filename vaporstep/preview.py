from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .song import SongInfo


PREVIEW_SETTLE_SECONDS = 0.65
PREVIEW_VOLUME = 0.48


@dataclass
class SongPreviewPlayer:
    """Delayed menu preview using pygame's streamed music channel.

    Navigation can move rapidly through a library; previews are only loaded after
    the current selection remains stable for a short moment.
    """

    _desired_key: str | None = None
    _desired_song: SongInfo | None = None
    _changed_at: float = 0.0
    _playing_key: str | None = None
    _stop_at: float | None = None
    _started_at: float | None = None

    @staticmethod
    def _key(song: SongInfo | None) -> str | None:
        return str(song.simfile_path) if song is not None else None

    def stop(self, reset_selection: bool = False) -> None:
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.music.set_volume(1.0)
        except Exception:
            pass
        self._playing_key = None
        self._stop_at = None
        self._started_at = None
        if reset_selection:
            self._desired_key = None
            self._desired_song = None

    def update(self, song: SongInfo | None, now: float) -> None:
        key = self._key(song)
        if key != self._desired_key:
            self.stop(reset_selection=False)
            self._desired_key = key
            self._desired_song = song
            self._changed_at = now

        if song is None or song.music_path is None:
            return
        if self._playing_key == key:
            if self._stop_at is not None and now >= self._stop_at:
                self.stop(reset_selection=False)
            return
        if now - self._changed_at < PREVIEW_SETTLE_SECONDS:
            return

        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(Path(song.music_path)))
            pygame.mixer.music.set_volume(PREVIEW_VOLUME)
            try:
                pygame.mixer.music.play(start=max(0.0, song.sample_start))
            except pygame.error:
                # Some codecs/backends do not support seek-at-start. A preview
                # from the beginning is still preferable to no preview.
                pygame.mixer.music.play()
            self._playing_key = key
            self._started_at = now
            self._stop_at = now + max(3.0, song.sample_length)
        except Exception:
            self._playing_key = None
            self._started_at = None
            self._stop_at = None

    def playback_elapsed(self, song: SongInfo | None, now: float) -> float | None:
        """Return elapsed preview time only while this song is actually playing."""
        if self._playing_key != self._key(song) or self._started_at is None:
            return None
        return max(0.0, float(now) - self._started_at)
