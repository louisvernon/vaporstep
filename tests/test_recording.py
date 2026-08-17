from pathlib import Path
import subprocess
import sys
import threading
import types
import wave

import numpy as np
import pytest

from vaporstep.domain import GameplayEvent, GameplayEventType, HitQuality, NoteKind
from vaporstep.recording import RecordingSnapshot, RunRecorder, safe_filename_component, write_sfx_track


def test_safe_filename_component_removes_path_and_shell_characters():
    assert safe_filename_component('../A Song: "Hi" / test') == 'A-Song-Hi-test'


def test_sfx_track_places_event_relative_to_negative_preroll(tmp_path: Path):
    out = tmp_path / "fx.wav"
    event = GameplayEvent(
        time=0.0,
        event_type=GameplayEventType.JUDGEMENT,
        kind=NoteKind.FOOT,
        quality=HitQuality.GREAT,
        hit=True,
    )
    # Recording starts at chart time -1.0, so the beat-zero SFX belongs at 1s.
    write_sfx_track(
        out,
        [event],
        chart_time_at_recording_start=-1.0,
        duration=2.0,
        sample_rate=1000,
        channels=2,
    )
    with wave.open(str(out), "rb") as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).reshape(-1, 2)
    assert np.max(np.abs(pcm[:900])) == 0
    assert np.max(np.abs(pcm[1000:1100])) > 0


def test_sfx_track_mix_clips_safely(tmp_path: Path):
    out = tmp_path / "fx.wav"
    events = [
        GameplayEvent(
            time=0.1,
            event_type=GameplayEventType.JUDGEMENT,
            kind=NoteKind.HANDS,
            quality=HitQuality.PERFECT,
            hit=True,
        )
        for _ in range(20)
    ]
    write_sfx_track(out, events, chart_time_at_recording_start=0.0, duration=0.5)
    with wave.open(str(out), "rb") as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    assert pcm.min() >= -32768
    assert pcm.max() <= 32767


def test_recording_snapshot_surfaces_audio_fallback_error(tmp_path: Path):
    snap = RecordingSnapshot(
        active=False,
        finalizing=False,
        saved_path=tmp_path / "run_silent.mp4",
        error="mux failed",
        dropped_frames=0,
    )
    assert "SAVED SILENT" in snap.message
    assert "AUDIO ERROR" in snap.message


@pytest.mark.parametrize(
    ("suffix", "codec_args"),
    [
        ("ogg", ["-c:a", "libvorbis"]),
        ("mp3", ["-c:a", "libmp3lame"]),
        ("wav", ["-c:a", "pcm_s16le"]),
    ],
)
def test_mux_audio_from_common_song_formats_produces_non_silent_audio(
    tmp_path: Path, suffix: str, codec_args: list[str]
):
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    video = tmp_path / "video.mp4"
    song = tmp_path / f"song.{suffix}"
    sfx = tmp_path / "effects.wav"
    output = tmp_path / "out.mp4"

    subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:r=30:d=0.8",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )
    subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
            *codec_args, str(song),
        ],
        check=True,
    )

    event = GameplayEvent(
        time=0.0,
        event_type=GameplayEventType.JUDGEMENT,
        kind=NoteKind.FOOT,
        quality=HitQuality.GREAT,
        hit=True,
    )
    write_sfx_track(
        sfx, [event], chart_time_at_recording_start=-0.2, duration=0.8
    )

    recorder = RunRecorder.__new__(RunRecorder)
    recorder.music_path = song
    recorder.chart_time_at_start = -0.2
    recorder._temp_video = video
    recorder._sfx_wav = sfx
    recorder._mux_audio(output, duration=0.8, music_stop_time=None)

    raw = tmp_path / "audio.raw"
    subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error", "-i", str(output),
            "-vn", "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", "1", "-ar", "44100", str(raw),
        ],
        check=True,
    )
    pcm = np.fromfile(raw, dtype=np.int16)
    assert len(pcm) > 10_000
    assert np.max(np.abs(pcm.astype(np.int32))) > 1_000


def test_static_tail_adds_three_seconds_without_live_wait(monkeypatch):
    fake_pygame = types.SimpleNamespace(
        transform=types.SimpleNamespace(smoothscale=lambda surface, size: surface),
        image=types.SimpleNamespace(tobytes=lambda surface, fmt: b"frame"),
    )
    monkeypatch.setitem(sys.modules, "pygame", fake_pygame)

    class Surface:
        def get_size(self):
            return (1280, 720)

    recorder = RunRecorder.__new__(RunRecorder)
    recorder._active = True
    recorder._encoder_failed = threading.Event()
    recorder._lock = threading.Lock()
    recorder._error = None
    recorder._tail_frame = None
    recorder._tail_repeats = 0

    recorder.append_static_tail(Surface(), 3.0)

    assert recorder._tail_frame == b"frame"
    assert recorder._tail_repeats == 90


def test_great_and_perfect_share_one_audible_timing_synth():
    from vaporstep.audio_fx import synthesize_gameplay_event

    great = GameplayEvent(0.0, GameplayEventType.JUDGEMENT, NoteKind.FOOT, HitQuality.GREAT, True)
    perfect = GameplayEvent(0.0, GameplayEventType.JUDGEMENT, NoteKind.FOOT, HitQuality.PERFECT, True)
    great_pcm = synthesize_gameplay_event(great)
    perfect_pcm = synthesize_gameplay_event(perfect)
    assert great_pcm.ndim == 2 and great_pcm.shape[1] == 2
    assert np.max(np.abs(great_pcm.astype(np.int32))) > 0
    assert np.array_equal(great_pcm, perfect_pcm)


def test_hit_miss_and_sustain_state_events_are_silent():
    from vaporstep.audio_fx import synthesize_gameplay_event

    events = [
        GameplayEvent(0.0, GameplayEventType.JUDGEMENT, NoteKind.FOOT, HitQuality.HIT, True),
        GameplayEvent(0.0, GameplayEventType.SUSTAIN_COMPLETE, NoteKind.HANDS, HitQuality.GREAT, True),
        GameplayEvent(0.0, GameplayEventType.SUSTAIN_BREAK, NoteKind.FOOT, None, False),
    ]
    for event in events:
        pcm = synthesize_gameplay_event(event)
        assert np.max(np.abs(pcm.astype(np.int32))) == 0


def test_sfx_track_with_timing_hit_and_sustain_break_does_not_broadcast(tmp_path: Path):
    out = tmp_path / "fx.wav"
    events = [
        GameplayEvent(
            time=0.1,
            event_type=GameplayEventType.JUDGEMENT,
            kind=NoteKind.FOOT,
            quality=HitQuality.GREAT,
            hit=True,
        ),
        GameplayEvent(
            time=0.35,
            event_type=GameplayEventType.SUSTAIN_BREAK,
            kind=NoteKind.HANDS,
            quality=None,
            hit=False,
        ),
    ]
    write_sfx_track(out, events, chart_time_at_recording_start=0.0, duration=0.8)

    with wave.open(str(out), "rb") as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    assert len(pcm) > 0
    assert np.max(np.abs(pcm.astype(np.int32))) > 0
