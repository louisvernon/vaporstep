from __future__ import annotations

from array import array
import math
from pathlib import Path
import sys
import wave


SAMPLE_RATE = 22_050
BPM = 120.0
DURATION_SECONDS = 13.0


def ensure_web_demo_audio(stepfile: Path) -> Path:
    """Create a tiny deterministic click track beside the browser demo chart.

    Keeping this generated avoids carrying a binary fixture in the repository
    while still exercising the normal simfile #MUSIC -> SongInfo -> GameSession
    -> pygame.mixer.music path. The browser filesystem is writable after Pygbag
    mounts the application archive, so the same helper works locally and in
    WASM.
    """
    target = stepfile.with_name("web_demo.wav")
    if target.exists() and target.stat().st_size > 44:
        return target

    frame_count = int(round(DURATION_SECONDS * SAMPLE_RATE))
    samples = array("h", [0]) * frame_count
    beat_seconds = 60.0 / BPM
    beat_count = int(DURATION_SECONDS / beat_seconds) + 1

    for beat in range(beat_count):
        start = int(round(beat * beat_seconds * SAMPLE_RATE))
        if start >= frame_count:
            break
        downbeat = beat % 4 == 0
        frequency = 1_320.0 if downbeat else 880.0
        amplitude = 0.46 if downbeat else 0.28
        click_frames = int(round(0.055 * SAMPLE_RATE))
        for offset in range(click_frames):
            index = start + offset
            if index >= frame_count:
                break
            t = offset / SAMPLE_RATE
            envelope = math.exp(-t * 58.0)
            value = math.sin(2.0 * math.pi * frequency * t) * envelope * amplitude
            samples[index] = max(-32768, min(32767, int(round(value * 32767.0))))

    if sys.byteorder != "little":
        samples.byteswap()

    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())

    return target
