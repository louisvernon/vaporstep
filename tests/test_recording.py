from fractions import Fraction
from pathlib import Path
import sys
import threading
import types
import wave

import av
import numpy as np
import pytest

from vaporstep.domain import GameplayEvent, GameplayEventType, HitQuality, NoteKind
from vaporstep.recording import (
    RECORD_SIZE,
    RecordingBackendProbe,
    RecordingSnapshot,
    RunRecorder,
    recording_backend_status,
    safe_filename_component,
    write_sfx_track,
)


def _write_solid_video(path: Path, *, duration: float = 0.8) -> None:
    frame_count = int(round(duration * 30))
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width = 64
        stream.height = 64
        stream.pix_fmt = "yuv420p"
        for index in range(frame_count):
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, 30)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _write_tone(path: Path, codec: str, *, duration: float = 0.6) -> None:
    sample_rate = 48_000 if codec == "libopus" else 44_100
    sample_count = int(round(duration * sample_rate))
    time = np.arange(sample_count) / sample_rate
    samples = (np.sin(2 * np.pi * 440 * time) * 10_000).astype(np.int16)[None, :]
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream(codec, rate=sample_rate)
        stream.layout = "mono"
        for start in range(0, sample_count, 1024):
            frame = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(samples[:, start : start + 1024]),
                format="s16p",
                layout="mono",
            )
            frame.sample_rate = sample_rate
            frame.pts = start
            frame.time_base = Fraction(1, sample_rate)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _decode_audio(path: Path) -> np.ndarray:
    chunks = []
    resampler = av.AudioResampler(format="s16p", layout="stereo", rate=44_100)
    with av.open(str(path), mode="r") as container:
        for decoded in container.decode(audio=0):
            chunks.extend(frame.to_ndarray() for frame in resampler.resample(decoded))
        chunks.extend(frame.to_ndarray() for frame in resampler.resample(None))
    return np.concatenate(chunks, axis=1)


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


def test_recording_backend_probe_does_not_block_while_pyav_initializes(monkeypatch):
    import vaporstep.recording as recording_module

    entered = threading.Event()
    release = threading.Event()

    def slow_backend_status():
        entered.set()
        release.wait(2)
        return True, ""

    monkeypatch.setattr(recording_module, "recording_backend_status", slow_backend_status)
    probe = RecordingBackendProbe()

    assert entered.wait(1)
    assert probe.result() is None
    release.set()
    assert probe._ready.wait(1)
    assert probe.result() == (True, "")


def test_threaded_pyav_recorder_produces_video_and_audio(tmp_path: Path):
    available, error = recording_backend_status()
    assert available, error

    recorder = RunRecorder(
        song_title="Smoke",
        chart_label="Test",
        music_path=None,
        chart_time_at_start=-0.1,
        output_dir=tmp_path,
    )
    assert recorder._encoder_ready.wait(10)
    recorder._queue.put((bytes(RECORD_SIZE[0] * RECORD_SIZE[1] * 3), 3))
    recorder.finish(grade="A")
    assert recorder._finalizer is not None
    recorder._finalizer.join(20)

    snapshot = recorder.snapshot()
    assert snapshot.error is None
    assert snapshot.saved_path is not None and snapshot.saved_path.exists()
    with av.open(str(snapshot.saved_path), mode="r") as container:
        assert len(container.streams.video) == 1
        assert len(container.streams.audio) == 1
        assert sum(1 for _ in container.decode(video=0)) == 3


@pytest.mark.parametrize(
    ("suffix", "codec"),
    [
        ("ogg", "libopus"),
        ("mp3", "libmp3lame"),
        ("wav", "pcm_s16le"),
    ],
)
def test_mux_audio_from_common_song_formats_produces_non_silent_audio(
    tmp_path: Path, suffix: str, codec: str
):
    video = tmp_path / "video.mp4"
    song = tmp_path / f"song.{suffix}"
    sfx = tmp_path / "effects.wav"
    output = tmp_path / "out.mp4"

    _write_solid_video(video)
    _write_tone(song, codec)

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

    pcm = _decode_audio(output)
    assert pcm.shape[1] > 10_000
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
