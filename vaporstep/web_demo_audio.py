from __future__ import annotations

from array import array
import math
from pathlib import Path
import sys


_DEMO_AUDIO_NAME = "web_demo.wav"


def _target_for(stepfile: Path) -> Path:
    return stepfile.with_name(_DEMO_AUDIO_NAME).resolve()


def generate_web_demo_audio(
    stepfile: Path,
    *,
    duration: float = 13.0,
    sample_rate: int = 44_100,
) -> Path:
    """Generate the deterministic PCM WAV click track used by the web probe.

    This intentionally uses only the Python standard library. The build creates
    the fixture before Pygbag packages the app, so the browser only has to load a
    plain PCM WAV through pygame.mixer.music; no NumPy or codec support is needed
    merely to validate the shared song/session/audio path.
    """
    import wave

    target = _target_for(stepfile)
    frame_count = max(1, int(round(duration * sample_rate)))
    pcm = array("h", [0]) * frame_count

    # 120 BPM quarter-note clicks, with a brighter/louder downbeat every four.
    beat_frames = max(1, int(round(sample_rate * 0.5)))
    click_frames = max(1, int(round(sample_rate * 0.060)))
    for beat_start in range(0, frame_count, beat_frames):
        beat_index = beat_start // beat_frames
        frequency = 880.0 if beat_index % 4 == 0 else 620.0
        amplitude = 0.42 if beat_index % 4 == 0 else 0.28
        for offset in range(min(click_frames, frame_count - beat_start)):
            t = offset / sample_rate
            envelope = (1.0 - math.exp(-t / 0.0015)) * math.exp(-t / 0.018)
            value = amplitude * envelope * math.sin(2.0 * math.pi * frequency * t)
            pcm[beat_start + offset] = int(max(-1.0, min(1.0, value)) * 32767.0)

    # WAV PCM is little-endian regardless of the build host.
    if sys.byteorder != "little":
        pcm.byteswap()

    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(pcm.tobytes())
    return target


def ensure_web_demo_audio(stepfile: Path) -> Path:
    """Return the bundled PCM WAV click track used by the browser audio probe."""
    target = _target_for(stepfile)
    if not target.is_file() or target.stat().st_size <= 44:
        raise RuntimeError(f"Missing VaporTap browser audio fixture: {target}")
    with target.open("rb") as stream:
        header = stream.read(12)
    if not (header.startswith(b"RIFF") and header[8:12] == b"WAVE"):
        raise RuntimeError(f"Invalid VaporTap browser WAV fixture: {target}")
    return target
