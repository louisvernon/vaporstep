from types import SimpleNamespace

from vaporstep.song_menu_renderer import _chart_format_label, _metadata_scroll_offset


def test_native_eight_lane_chart_is_called_out_in_metadata() -> None:
    assert _chart_format_label(SimpleNamespace(native_8_lane=True)) == "NATIVE 8-CHANNEL CHART"


def test_four_lane_chart_has_no_native_channel_callout() -> None:
    assert _chart_format_label(SimpleNamespace(native_8_lane=False)) == ""


def test_metadata_that_fits_does_not_scroll() -> None:
    assert _metadata_scroll_offset(180, 240, 10.0) == 0


def test_overflow_waits_for_preview_then_scrolls_once() -> None:
    assert _metadata_scroll_offset(300, 200, None) == 0
    assert _metadata_scroll_offset(300, 200, 1.0) == 42
    assert _metadata_scroll_offset(300, 200, 20.0) == 100
