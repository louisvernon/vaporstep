# Third-party software and assets

VaporStep's own source code is licensed under the MIT License. It depends on
third-party software and one model asset that retain their own licenses.

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
| imageio-ffmpeg | FFmpeg process discovery/wrapping for recording export | BSD-2-Clause; the bundled FFmpeg executable retains its own license |

The opencv-python project documents additional licenses for native components
included in its wheels, including FFmpeg under LGPL-2.1; non-headless Linux
wheels also include Qt under LGPL-3.0. Preserve `LICENSE-3RD-PARTY.txt` from the
installed opencv-python distribution in binary releases.

`imageio-ffmpeg==0.6.0` PyPI wheels include platform-specific FFmpeg executables. VaporStep release builds collect that executable so Record Play works without a separate system installation. FFmpeg remains a separate command-line program and retains the license of the exact supplied build. See `FFMPEG_PROVENANCE.md` for the filenames, version families, upstream source links, and the `imageio-ffmpeg` binary provenance chain.

PyInstaller is a build-time dependency. Its bootloader exception permits frozen
applications to be distributed under the application's own license, subject to
the licenses of bundled dependencies.

PyInstaller bundles a Python runtime. Binary releases should also preserve the
Python license file from the interpreter used to create the build.

## Model asset

The exact MediaPipe model artifact, versioned URL, expected size and SHA-256 are
stored in `assets/models.json`. `MODEL_ASSETS.md` is generated from that
manifest.

## Song/chart content

VaporStep does not ship third-party songs, charts, banners or backgrounds.
StepMania-compatible `.sm`/`.ssc` files and song packs remain subject to their
own licenses and copyrights.

## Compatibility names

References to StepMania, SM/SSC, Dance Super Station, and `ds3ddx-single` are
used only to describe supported file/chart formats and interoperability. Those
projects and names are not part of VaporStep branding and do not imply
endorsement or affiliation.
