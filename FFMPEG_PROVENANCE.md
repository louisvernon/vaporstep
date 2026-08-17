# FFmpeg binary provenance

VaporStep uses FFmpeg as a separate command-line program to encode and mux local gameplay recordings. VaporStep does not modify or link against FFmpeg.

Release builds use the FFmpeg executable supplied by `imageio-ffmpeg==0.6.0`. The `imageio-ffmpeg` project publishes platform-specific wheels that include these executables, and its release tooling copies those executables from the `imageio/imageio-binaries` repository into the wheels.

For the 64-bit platforms currently built by VaporStep, `imageio-ffmpeg 0.6.0` identifies the bundled files as:

| Platform | Bundled executable | FFmpeg version family |
| --- | --- | --- |
| macOS Apple Silicon | `ffmpeg-macos-aarch64-v7.1` | 7.1 |
| macOS Intel | `ffmpeg-macos-x86_64-v7.1` | 7.1 |
| Windows x86-64 | `ffmpeg-win-x86_64-v7.1.exe` | 7.1 |
| Linux x86-64 | `ffmpeg-linux-x86_64-v7.0.2` | 7.0.2 |

Upstream source releases for those FFmpeg versions are available from:

- FFmpeg 7.1: https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz
- FFmpeg 7.0.2: https://ffmpeg.org/releases/ffmpeg-7.0.2.tar.xz
- FFmpeg source/release index: https://ffmpeg.org/download.html
- FFmpeg licensing overview: https://ffmpeg.org/legal.html
- GPLv3 text used by GPLv3 FFmpeg builds: https://www.gnu.org/licenses/gpl-3.0.html

Binary provenance:

- `imageio-ffmpeg`: https://github.com/imageio/imageio-ffmpeg
- binary repository used by its release tooling: https://github.com/imageio/imageio-binaries/tree/master/ffmpeg

FFmpeg licensing depends on the options and third-party libraries used to build a particular executable. The executable itself reports its version, license-relevant configuration, and build provenance via `ffmpeg -version`. VaporStep release builds redistribute that executable unmodified and preserve the applicable FFmpeg/license notices alongside VaporStep's own MIT license.

This file records provenance for reproducibility and attribution; it is not a substitute for the license terms that apply to the exact bundled executable.
