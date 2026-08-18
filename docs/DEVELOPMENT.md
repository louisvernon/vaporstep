# Developer guide

This document covers source setup, tests, model assets, packaging and CI. The main README is intentionally focused on players.

## Source setup

Python 3.12 is recommended.

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e .
python -m vaporstep
```

You can select a song library in the UI or override it while developing:

```bash
python -m vaporstep --songs "/path/to/Songs"
```

`VAPORSTEP_SONGS` provides the same override through the environment. Without an override or saved choice, VaporStep uses `~/VaporStep/Songs` and creates that directory if needed.

MediaPipe is currently pinned to `0.10.35` for the tested pose-tracking path. `setuptools<82` is retained because `simfile==2.1.1` imports `pkg_resources`.

## Tests

Install build/development dependencies and run the suite:

```bash
python -m pip install -e ".[build]"
python -m pytest -q
```

## Pose model

The canonical pose-model metadata lives in:

```text
assets/models.json
```

It records the versioned upstream URL, expected file size, SHA-256 and license information.

Fetch and verify the model used by packaged builds:

```bash
python scripts/fetch_pose_model.py
```

Regenerate the human-readable model record after changing the manifest:

```bash
python scripts/generate_model_docs.py
```

Source runs can fetch the same pinned model when it is absent. Packaged builds include the verified model and can run without downloading it.

## Persistent data

VaporStep keeps its user-owned files under one visible home-directory root on all platforms:

```text
~/VaporStep/
├── Songs/
├── Recordings/
└── State/
    ├── settings.json
    ├── highscores.json
    └── Cache/
```

`Songs` is the default song library location, and users can select another song folder from the application. `Recordings` contains saved gameplay videos. `State` contains VaporStep-managed settings, scores and caches; a future song-library index should also live under `State`.

Keeping all default VaporStep-owned data under this root makes backup and removal straightforward: deleting `~/VaporStep` removes the application's default user data. Temporary encoder/runtime files may still use the operating system temporary directory while the application is running.

## PyInstaller

VaporStep uses native PyInstaller builds on each target platform. Windows is packaged as a one-file self-extracting executable; macOS and Linux keep directory-based builds so their native dependencies remain straightforward to package and inspect.

Install build dependencies:

```bash
python -m pip install -e ".[build]"
python scripts/fetch_pose_model.py
```

On macOS, create the `.icns` icon first:

```bash
./scripts/make_macos_icon.sh
```

Build on the target platform:

```bash
pyinstaller --noconfirm --clean VaporStep.spec
```

Typical outputs:

```text
macOS:    dist/VaporStep.app
Windows:  dist/VaporStep.exe
Linux:    dist/VaporStep/
```

The Windows executable contains the Python runtime and bundled native/data dependencies and extracts them to a temporary runtime directory when launched.

PyInstaller is not a cross-compiler; release binaries are built natively for each target platform.

## CI and releases

`.github/workflows/test.yml` runs the test suite on pushes and pull requests.

`.github/workflows/build.yml` builds native packages for:

- Linux x86_64
- Windows x86_64
- macOS Apple Silicon

A manual workflow run builds the packages and stores them as GitHub Actions artifacts. Use this path to test packaged builds on real cameras before publishing a release.

Pushing a tag matching `v*` runs the same native builds, creates a GitHub Release after all builds succeed, generates release notes from GitHub history, and attaches the platform packages to the release.

Example:

```bash
git tag v0.13.0
git push origin v0.13.0
```

The resulting files are:

```text
VaporStep-Linux-x86_64.tar.gz
VaporStep-Windows-x86_64.exe
VaporStep-macOS-AppleSilicon.zip
```

## Repository hygiene

Do not commit generated build outputs:

```text
build/
dist/
```

The model manifest, license files and generated `MODEL_ASSETS.md` should remain in sync. CI verifies the generated model documentation.

## Third-party software

VaporStep itself is MIT licensed. Runtime/build dependencies retain their own licenses. See:

- `THIRD_PARTY_NOTICES.md`
- `MODEL_ASSETS.md`
- `LICENSE`

When changing runtime dependencies, review their redistribution requirements before publishing frozen binaries.


## Gameplay recording

Recording is a normal VaporStep runtime feature. `imageio-ffmpeg==0.6.0` supplies the FFmpeg command-line executable used by source runs and packaged builds. The PyInstaller spec explicitly collects that package and its bundled executable.

The implementation records the rendered 1280×720 surface at 30 fps on a worker thread. Gameplay sound effects are logged as timestamped events and reconstructed after the run; FFmpeg then mixes those effects with the original song and muxes the result into the final MP4. Recording never blocks the gameplay loop if the encoder queue falls behind.

FFmpeg remains a separately licensed executable. Keep `THIRD_PARTY_NOTICES.md` and `FFMPEG_PROVENANCE.md` aligned with the pinned `imageio-ffmpeg` version when changing recording dependencies.
