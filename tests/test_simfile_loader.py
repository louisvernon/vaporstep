from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import pytest

from vaporstep.domain import NoteKind
from vaporstep.simfile_loader import convert_rows, discover_simfiles


@dataclass(frozen=True)
class FakeNote:
    beat: Fraction
    column: int
    tail_beat: Fraction | None = None


class FakeEngine:
    def hittable(self, beat):
        return True

    def time_at(self, beat):
        return float(beat) * 0.5


def test_discovery_prefers_ssc_over_sm(tmp_path: Path):
    song = tmp_path / "Pack" / "Song"
    song.mkdir(parents=True)
    (song / "song.sm").write_text("", encoding="utf-8")
    (song / "song.ssc").write_text("", encoding="utf-8")
    other = tmp_path / "Pack" / "Other"
    other.mkdir()
    (other / "other.sm").write_text("", encoding="utf-8")

    found = discover_simfiles(tmp_path)
    assert song / "song.ssc" in found
    assert song / "song.sm" not in found
    assert other / "other.sm" in found


def test_single_row_becomes_foot_and_double_becomes_hands():
    rows = [
        [FakeNote(Fraction(1), 1)],
        [FakeNote(Fraction(4), 0), FakeNote(Fraction(4), 3)],
    ]
    notes, skipped = convert_rows(rows, FakeEngine())
    assert skipped == 0
    assert notes[0].time == 0.5
    assert notes[0].beat == 1.0
    assert notes[0].kind == NoteKind.FOOT
    assert notes[0].lanes == (2,)
    assert notes[1].time == 2.0
    assert notes[1].beat == 4.0
    assert notes[1].kind == NoteKind.HANDS
    assert notes[1].lanes == (1, 4)


def test_simple_single_lane_hold_preserves_end_time():
    rows = [[FakeNote(Fraction(2), 2, tail_beat=Fraction(6))]]
    notes, _ = convert_rows(rows, FakeEngine())
    assert notes[0].kind == NoteKind.FOOT
    assert notes[0].end_time == 3.0
    assert notes[0].end_beat == 6.0


def test_mixed_or_mismatched_double_hold_is_treated_as_hand_tap():
    rows = [[
        FakeNote(Fraction(2), 0, tail_beat=Fraction(6)),
        FakeNote(Fraction(2), 3),
    ]]
    notes, _ = convert_rows(rows, FakeEngine())
    assert notes[0].kind == NoteKind.HANDS
    assert notes[0].end_time is None


def test_more_than_two_new_heads_are_skipped():
    rows = [[
        FakeNote(Fraction(2), 0),
        FakeNote(Fraction(2), 1),
        FakeNote(Fraction(2), 2),
    ]]
    notes, skipped = convert_rows(rows, FakeEngine())
    assert notes == []
    assert skipped == 1


def test_real_simfile_smoke(tmp_path: Path):
    simfile = pytest.importorskip("simfile")
    song = tmp_path / "Test Song"
    song.mkdir()
    (song / "test.ogg").write_bytes(b"")
    sm = song / "test.sm"
    sm.write_text(
        """#TITLE:Test Song;
#ARTIST:Test Artist;
#MUSIC:test.ogg;
#OFFSET:0.000;
#BPMS:0.000=120.000;
#NOTES:
     dance-single:
     :
     Beginner:
     1:
     0,0,0,0,0:
0000
0100
0000
0000
,
1001
0000
0010
0000
;
""",
        encoding="utf-8",
    )

    from vaporstep.simfile_loader import load_chart, scan_song

    info = scan_song(sm)
    assert info is not None
    assert info.title == "Test Song"
    assert len(info.charts) == 1
    assert info.charts[0].target_count == 3
    assert info.charts[0].foot_count == 2
    assert info.charts[0].hand_count == 1
    assert info.charts[0].bpm_label == "120"
    loaded = load_chart(info, info.charts[0])
    assert [(n.kind, n.lanes) for n in loaded.notes] == [
        (NoteKind.FOOT, (2,)),
        (NoteKind.HANDS, (1, 4)),
        (NoteKind.FOOT, (3,)),
    ]


def test_ds3ddx_explicit_hand_and_foot_mapping():
    from vaporstep.simfile_loader import convert_ds3ddx_rows

    # ds3ddx-single source order:
    # 0 HandLeft, 1 FootDownLeft, 2 FootUpLeft, 3 HandUp,
    # 4 HandDown, 5 FootUpRight, 6 FootDownRight, 7 HandRight.
    rows = [
        [FakeNote(Fraction(2), 2)],                       # foot lane 2
        [FakeNote(Fraction(4), 0)],                       # hand lane 1
        [FakeNote(Fraction(6), 1), FakeNote(Fraction(6), 7)],  # foot 1 + hand 4
        [FakeNote(Fraction(8), 3), FakeNote(Fraction(8), 4)],  # hands 2+3
    ]
    notes, skipped = convert_ds3ddx_rows(rows, FakeEngine())

    assert skipped == 0
    assert [(n.time, n.kind, n.lanes) for n in notes] == [
        (1.0, NoteKind.FOOT, (2,)),
        (2.0, NoteKind.HANDS, (1,)),
        (3.0, NoteKind.FOOT, (1,)),
        (3.0, NoteKind.HANDS, (4,)),
        (4.0, NoteKind.HANDS, (2, 3)),
    ]


def test_ds3ddx_all_four_foot_columns_map_left_to_right():
    from vaporstep.simfile_loader import convert_ds3ddx_rows

    source_columns = [1, 2, 5, 6]
    rows = [[FakeNote(Fraction(i + 1), col)] for i, col in enumerate(source_columns)]
    notes, skipped = convert_ds3ddx_rows(rows, FakeEngine())
    assert skipped == 0
    assert [n.lanes for n in notes] == [(1,), (2,), (3,), (4,)]


def test_ds3ddx_keeps_simultaneous_foot_and_hand_pairs_separate():
    from vaporstep.simfile_loader import convert_ds3ddx_rows

    row = [
        FakeNote(Fraction(2), 1),
        FakeNote(Fraction(2), 5),
        FakeNote(Fraction(2), 0),
        FakeNote(Fraction(2), 7),
    ]
    notes, skipped = convert_ds3ddx_rows([row], FakeEngine())

    assert skipped == 0
    assert [(note.kind, note.lanes) for note in notes] == [
        (NoteKind.FOOT, (1, 3)),
        (NoteKind.HANDS, (1, 4)),
    ]


def test_stepfile_asset_paths_cannot_escape_song_directory(tmp_path: Path):
    from vaporstep.simfile_loader import _resolve_asset

    song = tmp_path / "Song"
    song.mkdir()
    inside = song / "banner.png"
    inside.write_bytes(b"png")
    outside = tmp_path / "private.png"
    outside.write_bytes(b"secret")

    assert _resolve_asset(song, "banner.png") == inside.resolve()
    assert _resolve_asset(song, "../private.png") is None
    assert _resolve_asset(song, str(outside.resolve())) is None


def test_stepfile_asset_symlink_cannot_escape_song_directory(tmp_path: Path):
    from vaporstep.simfile_loader import _resolve_asset

    song = tmp_path / "Song"
    song.mkdir()
    outside = tmp_path / "private.png"
    outside.write_bytes(b"secret")
    link = song / "banner.png"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    assert _resolve_asset(song, "banner.png") is None
