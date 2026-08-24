from __future__ import annotations

"""Fetch the pinned monochrome Noto Emoji font used by packaged builds."""

from hashlib import sha1
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets" / "fonts"

# Pin to the Google Fonts commit that introduced Noto Emoji 3.002. Using an
# immutable commit URL plus the Git blob hash makes release builds reproducible
# without committing the font binary into the VaporStep source repository.
GOOGLE_FONTS_COMMIT = "b979dba422e445492b0eb9951ac52ee0b4d648c3"
BASE_URL = f"https://raw.githubusercontent.com/google/fonts/{GOOGLE_FONTS_COMMIT}/ofl/notoemoji"

FILES = (
    (
        "NotoEmoji[wght].ttf",
        f"{BASE_URL}/NotoEmoji%5Bwght%5D.ttf",
        "c2c26ab612a88a8610ff9cfbb89299bf2aea6c7a",
    ),
    (
        "OFL.txt",
        f"{BASE_URL}/OFL.txt",
        "d09d3d0e09169f6747754e6b25faf5ba5ef6402d",
    ),
)


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return sha1(header + data).hexdigest()


def fetch_file(name: str, url: str, expected_blob_sha: str) -> Path:
    out = ASSET_DIR / name
    if out.is_file():
        data = out.read_bytes()
        if git_blob_sha(data) == expected_blob_sha:
            print(f"Noto Emoji asset already present and verified: {out}")
            return out
        print(f"Existing {name} is not the pinned artifact; replacing it.")

    print(f"Downloading pinned Noto Emoji asset: {name}")
    print(url)
    with urlopen(url, timeout=60) as response:
        data = response.read()

    actual = git_blob_sha(data)
    if actual != expected_blob_sha:
        raise SystemExit(
            f"Downloaded {name} failed verification: expected Git blob "
            f"{expected_blob_sha}, got {actual}"
        )

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(out)
    print(f"Verified Git blob: {actual}")
    print(f"Installed: {out}")
    return out


def main() -> None:
    for name, url, expected_blob_sha in FILES:
        fetch_file(name, url, expected_blob_sha)


if __name__ == "__main__":
    main()
