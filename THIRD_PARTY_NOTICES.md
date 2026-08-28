# Third-party software and assets

VaporStep's own source code is licensed under the MIT License. It depends on
third-party software and a small set of build/runtime assets that retain their
own licenses.

The exact dependency versions used for a build are determined by
`pyproject.toml` and the build environment. Frozen release bundles should ship
the license/notice files from the exact installed distributions; `VaporStep.spec`
collects those files where they are provided by the packages.

## Runtime dependencies

| Component | Role | Upstream license |
| --- | --- | --- |
| MediaPipe | Pose inference | Apache-2.0 |
| MediaPipe Pose Landmarker Full model | Pose model | Apache-2.0 |
| OpenCV / opencv-python | Camera capture and image processing | OpenCV: Apache-2.0; opencv-python packaging: MIT; bundled wheel components retain their own licenses |
| Pygame | Rendering, input and audio | LGPL-2.1 |
| NumPy | Numeric arrays | BSD-3-Clause and bundled notices |
| simfile | SM/SSC parsing | MIT |
| setuptools / pkg_resources | Compatibility dependency used by simfile | MIT and bundled notices |
| PyAV | In-process video/audio encoding and muxing for recording export | BSD-3-Clause; bundled FFmpeg shared libraries and codecs retain their own licenses |
| VaporStep Emoji Symbols (modified Noto Emoji subset) | Monochrome hand/foot capability glyphs | SIL Open Font License 1.1 |

The opencv-python project documents additional licenses for native components
included in its wheels, including FFmpeg under LGPL-2.1; non-headless Linux
wheels also include Qt under LGPL-3.0. Preserve `LICENSE-3RD-PARTY.txt` from the
installed opencv-python distribution in binary releases.

PyAV binary wheels include FFmpeg shared libraries and codec dependencies so
Record Play works without a separate system installation. VaporStep calls those
libraries in-process and does not ship or invoke an `ffmpeg` command-line
executable. The exact native components and licenses remain those supplied by
the pinned PyAV wheel; release builds preserve PyAV's packaged license material.

PyInstaller is a build-time dependency. Its bootloader exception permits frozen
applications to be distributed under the application's own license, subject to
the licenses of bundled dependencies.

PyInstaller bundles a Python runtime. Binary releases should also preserve the
Python license file from the interpreter used to create the build.

## Build assets

The MediaPipe pose model is pinned by `assets/models.json` and verified before
release builds.

`assets/fonts/VaporStepEmojiSymbols.ttf` is a renamed, modified subset derived
from Noto Emoji source glyphs for U+1F463 FOOTPRINTS and U+270B RAISED HAND.
Only those presentation glyphs (plus required font bookkeeping glyphs) are kept,
so VaporStep gets deterministic capability icons without shipping the complete
emoji font. The subset is derived from the Noto Emoji source at upstream commit
`8998f5dd683424a73e2314a8c1f1e359c19e8742`, and its upstream SIL OFL 1.1
license is committed beside it as `assets/fonts/NotoEmoji-OFL.txt`.

## Song/chart content

VaporStep does not ship third-party songs, charts, banners or backgrounds.
StepMania-compatible `.sm`/`.ssc` files and song packs remain subject to their
own licenses and copyrights.

## Compatibility names

References to StepMania, SM/SSC, Dance Super Station, and `ds3ddx-single` are
used only to describe supported file/chart formats and interoperability. Those
projects and names are not part of VaporStep branding and do not imply
endorsement or affiliation.
