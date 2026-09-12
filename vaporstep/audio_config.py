from __future__ import annotations

# Platform-neutral audio levels shared by gameplay/session code and the
# desktop synthesis/mixer implementation. Keep these constants free of NumPy,
# pygame, or browser/native audio dependencies so WASM frontends can import
# session logic without pulling in desktop audio synthesis.
GAMEPLAY_MUSIC_VOLUME = 0.82
RECORDING_MUSIC_VOLUME = 0.82
RECORDING_SFX_VOLUME = 1.00
MENU_AMBIENCE_VOLUME = 0.055
MENU_AMBIENCE_SECONDS = 4.0
