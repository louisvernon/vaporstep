import numpy as np

from vaporstep.audio_fx import MENU_AMBIENCE_SECONDS, synthesize_menu_ambience


def test_menu_ambience_is_quiet_stereo_and_seamless():
    sample_rate = 8_000
    pcm = synthesize_menu_ambience(sample_rate=sample_rate, channels=2)

    assert pcm.shape == (int(sample_rate * MENU_AMBIENCE_SECONDS), 2)
    assert pcm.dtype == np.int16
    peak = int(np.max(np.abs(pcm.astype(np.int32))))
    assert 500 < peak < 2_500
    mono = pcm[:, 0].astype(np.int32)
    ordinary_steps = np.abs(np.diff(mono))
    seam_step = abs(int(mono[0]) - int(mono[-1]))
    assert seam_step <= int(np.max(ordinary_steps))
