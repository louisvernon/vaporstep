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

`VAPORSTEP_SONGS` provides the same override through the environment.

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

High scores and app settings are stored outside the installation directory.

Typical locations:

macOS:

```text
~/Library/Application Support/VaporStep/highscores.json
~/Library/Application Support/VaporStep/settings.json
```

Linux:

```text
~/.local/share/vaporstep/highscores.json
~/.config/vaporstep/settings.json
```

Windows uses the user's Local AppData `VaporStep` directory.

## PyInstaller

VaporStep uses a one-folder PyInstaller build so native dependencies remain easy to inspect and troubleshoot.

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
Windows:  dist/VaporStep/
Linux:    dist/VaporStep/
```

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
VaporStep-Windows-x86_64.zip
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
