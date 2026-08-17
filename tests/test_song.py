from vaporstep.song import ChartInfo


def test_bpm_label_constant_and_range():
    constant = ChartInfo(index=0, difficulty="Easy", meter=3, bpm_min=120.0, bpm_max=120.0)
    variable = ChartInfo(index=1, difficulty="Hard", meter=8, bpm_min=90.0, bpm_max=180.0)
    assert constant.bpm_label == "120"
    assert variable.bpm_label == "90–180"
