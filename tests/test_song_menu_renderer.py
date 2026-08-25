from types import SimpleNamespace

from vaporstep.song_menu_renderer import _chart_format_label


def test_native_eight_lane_chart_is_called_out_in_metadata() -> None:
    assert _chart_format_label(SimpleNamespace(native_8_lane=True)) == "NATIVE 8-CHANNEL CHART"


def test_four_lane_chart_has_no_native_channel_callout() -> None:
    assert _chart_format_label(SimpleNamespace(native_8_lane=False)) == ""
