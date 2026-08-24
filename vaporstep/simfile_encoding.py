from __future__ import annotations

"""Encoding selection for legacy StepMania simfiles.

``simfile`` 2.1.1 tries UTF-8, then CP1252, CP932 and CP949. CP1252 can decode
most byte sequences without error, so Korean/Japanese files may be accepted as
the wrong encoding before their real code page is attempted. VaporStep keeps
using ``simfile`` for parsing, but chooses the encoding first.
"""

from pathlib import Path


_installed = False
_original_open = None


def _count_in_ranges(text: str, ranges: tuple[tuple[int, int], ...]) -> int:
    return sum(any(lo <= ord(char) <= hi for lo, hi in ranges) for char in text)


def _legacy_script_score(text: str, encoding: str) -> int:
    """Score how plausible a decoded legacy East-Asian string is."""
    hangul = _count_in_ranges(
        text,
        (
            (0x1100, 0x11FF),
            (0x3130, 0x318F),
            (0xA960, 0xA97F),
            (0xAC00, 0xD7AF),
            (0xD7B0, 0xD7FF),
        ),
    )
    kana = _count_in_ranges(text, ((0x3040, 0x30FF), (0x31F0, 0x31FF)))
    halfwidth_kana = _count_in_ranges(text, ((0xFF61, 0xFF9F),))
    cjk = _count_in_ranges(text, ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF)))

    if encoding == "cp932":
        # Correct Shift-JIS commonly yields kana/kanji. Korean CP949 bytes often
        # turn into suspicious half-width katakana under CP932, so weight those
        # much less heavily.
        return 3 * (kana + cjk) + halfwidth_kana
    if encoding == "cp949":
        # Correct Korean text overwhelmingly yields Hangul. Hanja is possible,
        # but it is a weaker signal because Japanese Shift-JIS can also become
        # CJK-looking text under another legacy decoder.
        return 3 * hangul + cjk
    return 0


def detect_simfile_encoding_bytes(data: bytes) -> str:
    """Choose UTF-8, CP932, CP949 or CP1252 for one simfile byte stream."""
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    decoded: dict[str, str] = {}
    for encoding in ("cp932", "cp949", "cp1252"):
        try:
            decoded[encoding] = data.decode(encoding)
        except UnicodeDecodeError:
            continue

    scored: list[tuple[int, int, str]] = []
    # Prefer CP932 on a genuine tie: Japanese Kanji-only metadata and its CP949
    # mojibake can otherwise have identical script counts. Korean CP949 text
    # normally beats its CP932 half-width-katakana mojibake by a wide margin.
    priorities = {"cp932": 2, "cp949": 1}
    for encoding in ("cp932", "cp949"):
        text = decoded.get(encoding)
        if text is not None:
            scored.append((_legacy_script_score(text, encoding), priorities[encoding], encoding))

    if scored:
        score, _, encoding = max(scored)
        if score > 0:
            return encoding

    if "cp1252" in decoded:
        return "cp1252"
    if decoded:
        return next(iter(decoded))
    raise UnicodeDecodeError("utf-8", data, 0, min(1, len(data)), "unsupported simfile encoding")


def detect_simfile_encoding(path: Path) -> str:
    return detect_simfile_encoding_bytes(path.read_bytes())


def install_simfile_encoding_detection() -> None:
    """Make ``simfile.open`` use VaporStep's encoding choice for local files."""
    global _installed, _original_open
    if _installed:
        return

    import simfile

    _original_open = simfile.open

    def open_with_vaporstep_encoding(filename, *args, **kwargs):
        if "encoding" not in kwargs:
            try:
                path = Path(filename)
                if path.is_file():
                    kwargs["encoding"] = detect_simfile_encoding(path)
            except (OSError, TypeError, ValueError, UnicodeError):
                # Preserve simfile's normal error handling if the path cannot be
                # inspected. VaporStep only passes ordinary local paths here.
                pass
        return _original_open(filename, *args, **kwargs)

    simfile.open = open_with_vaporstep_encoding
    _installed = True
