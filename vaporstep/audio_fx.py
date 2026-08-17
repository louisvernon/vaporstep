from __future__ import annotations

import math

import numpy as np

from .domain import GameplayEvent, GameplayEventType, HitQuality

SFX_SAMPLE_RATE = 44_100
SFX_CHANNELS = 2

# Leave musical headroom so a short percussive input transient can be heard
# clearly without forcing the player to turn the song down dramatically.
GAMEPLAY_MUSIC_VOLUME = 0.82
RECORDING_MUSIC_VOLUME = 0.82
RECORDING_SFX_VOLUME = 1.00


def _tone(
    frequency: float,
    duration: float,
    volume: float,
    *,
    sample_rate: int,
    overtone: float | None = None,
    overtone_mix: float = 0.30,
    attack: float = 0.003,
    decay_scale: float = 9.0,
) -> np.ndarray:
    count = max(1, int(round(sample_rate * duration)))
    t = np.arange(count, dtype=np.float64) / sample_rate
    attack_env = np.minimum(1.0, t / max(attack, 1e-5))
    decay_env = np.exp(-t * (decay_scale / max(duration, 1e-6)))
    wave = np.sin(2.0 * math.pi * frequency * t)
    if overtone is not None:
        wave += overtone_mix * np.sin(2.0 * math.pi * overtone * t)
    return wave * attack_env * decay_env * volume


def _timing_synth_hit(duration: float, volume: float, sample_rate: int) -> np.ndarray:
    """Warm low-frequency confirmation hit for GREAT/PERFECT.

    A short downward pitch glide and quiet harmonic make this read as a synth
    percussion hit rather than a pitched beep. GREAT and PERFECT intentionally
    share the exact same sound; the visuals carry judgement quality.
    """
    count = max(1, int(round(sample_rate * duration)))
    t = np.arange(count, dtype=np.float64) / sample_rate
    # Exponential glide from ~170 Hz toward ~105 Hz.
    freq = 105.0 + 65.0 * np.exp(-t / 0.018)
    phase = 2.0 * math.pi * np.cumsum(freq) / sample_rate
    body = np.sin(phase)
    harmonic = 0.20 * np.sin(2.0 * phase + 0.35)
    attack = np.minimum(1.0, t / 0.0025)
    envelope = attack * np.exp(-t / 0.045)
    return (body + harmonic) * envelope * volume


def _calibration_beat(downbeat: bool, sample_rate: int) -> np.ndarray:
    """Simple unobtrusive 120-BPM calibration metronome pulse."""
    base = 92.0 if downbeat else 108.0
    volume = 0.24 if downbeat else 0.17
    return _tone(
        base,
        0.060,
        volume,
        sample_rate=sample_rate,
        overtone=base * 2.0,
        overtone_mix=0.12,
        attack=0.0015,
        decay_scale=7.5,
    )


def _ui_click(duration: float, volume: float, sample_rate: int, *, seed: int) -> np.ndarray:
    """Short tactile menu click, closer to a wheel/clicker than a cymbal."""
    count = max(1, int(round(sample_rate * duration)))
    t = np.arange(count, dtype=np.float64) / sample_rate
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(count)
    previous = np.concatenate(([0.0], noise[:-1]))
    crisp = noise - 0.93 * previous
    tone = 0.20 * np.sin(2.0 * math.pi * 1450.0 * t)
    env = np.exp(-t / max(duration * 0.16, 1e-5))
    wave = (0.72 * crisp + tone) * env
    peak = float(np.max(np.abs(wave))) if len(wave) else 1.0
    if peak > 1e-9:
        wave /= peak
    return wave * volume

def _pcm(mono: np.ndarray, channels: int) -> np.ndarray:
    pcm = np.clip(mono * 32767.0, -32768, 32767).astype(np.int16)
    if channels > 1:
        pcm = np.repeat(pcm[:, None], channels, axis=1)
    return pcm


def synthesize_gameplay_event(
    event: GameplayEvent,
    *,
    sample_rate: int = SFX_SAMPLE_RATE,
    channels: int = SFX_CHANNELS,
) -> np.ndarray:
    """Return signed 16-bit PCM for one VaporStep gameplay event.

    Only GREAT/PERFECT note confirmations are audible. Both intentionally share
    one warm synth hit so dense charts reinforce the beat without becoming a
    collection of judgement beeps. Misses, raw motion, and sustain state changes
    remain silent and are communicated visually.
    """
    if (
        event.event_type == GameplayEventType.JUDGEMENT
        and event.hit
        and event.quality in (HitQuality.GREAT, HitQuality.PERFECT)
    ):
        mono = _timing_synth_hit(0.095, 0.52, sample_rate)
    else:
        mono = np.zeros(max(1, int(round(sample_rate * 0.01))), dtype=np.float64)

    return _pcm(mono, channels)


class MenuSounds:
    """Short UI clicks from the same sonic family as gameplay input feedback."""

    def __init__(self) -> None:
        self._tick = None
        self._select = None
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            init = pygame.mixer.get_init()
            sample_rate = int(init[0]) if init else SFX_SAMPLE_RATE
            channels = int(init[2]) if init else SFX_CHANNELS
            self._tick = pygame.sndarray.make_sound(
                _pcm(_ui_click(0.026, 0.20, sample_rate, seed=0x5655), channels)
            )
            self._select = pygame.sndarray.make_sound(
                _pcm(_ui_click(0.038, 0.28, sample_rate, seed=0x5656), channels)
            )
        except Exception:
            # Menus remain fully usable if audio initialization is unavailable.
            self._tick = None
            self._select = None

    def tick(self) -> None:
        if self._tick is not None:
            self._tick.play()

    def select(self) -> None:
        if self._select is not None:
            self._select.play()


class GameplaySounds:
    """Live gameplay SFX synthesized from the same events used by recordings."""

    def __init__(self) -> None:
        self._pygame = None
        self._sample_rate = SFX_SAMPLE_RATE
        self._channels = SFX_CHANNELS
        self._cache: dict[tuple[str, str, str, bool], object] = {}
        self._beat_cache: dict[bool, object] = {}
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            init = pygame.mixer.get_init()
            if init:
                self._sample_rate = int(init[0])
                self._channels = int(init[2])
            self._pygame = pygame
        except Exception:
            self._pygame = None

    @staticmethod
    def _event_key(event: GameplayEvent) -> tuple[str, str, str, bool]:
        return (
            event.event_type.value,
            event.kind.value,
            (event.quality.value if event.quality is not None else "none"),
            bool(event.hit),
        )

    def play(self, events: tuple[GameplayEvent, ...] | list[GameplayEvent]) -> None:
        if self._pygame is None:
            return
        for event in events:
            if not (
                event.event_type == GameplayEventType.JUDGEMENT
                and event.hit
                and event.quality in (HitQuality.GREAT, HitQuality.PERFECT)
            ):
                continue
            key = self._event_key(event)
            sound = self._cache.get(key)
            if sound is None:
                try:
                    pcm = synthesize_gameplay_event(
                        event,
                        sample_rate=self._sample_rate,
                        channels=self._channels,
                    )
                    sound = self._pygame.sndarray.make_sound(pcm)
                    self._cache[key] = sound
                except Exception:
                    continue
            try:
                sound.play()
            except Exception:
                pass

    def play_calibration_beat(self, *, downbeat: bool = False) -> None:
        """Play one quiet metronome pulse for the calibration demo."""
        if self._pygame is None:
            return
        sound = self._beat_cache.get(bool(downbeat))
        if sound is None:
            try:
                pcm = _pcm(
                    _calibration_beat(bool(downbeat), self._sample_rate),
                    self._channels,
                )
                sound = self._pygame.sndarray.make_sound(pcm)
                self._beat_cache[bool(downbeat)] = sound
            except Exception:
                return
        try:
            sound.play()
        except Exception:
            pass

