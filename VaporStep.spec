# PyInstaller build for VaporStep.
from pathlib import Path
from importlib.metadata import PackageNotFoundError, distribution
import os
import re
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files

import imageio_ffmpeg

root = Path(SPECPATH)
assets = root / "assets"

codesign_identity = (
    os.environ.get("VAPORSTEP_CODESIGN_IDENTITY")
    if sys.platform == "darwin"
    else None
)
entitlements_file = (
    str(root / "macos-entitlements.plist")
    if sys.platform == "darwin"
    else None
)

# MediaPipe ships native libraries and task resources that are easy to miss in
# frozen apps. Collecting the package is intentionally conservative for this
# first portable build; we can trim it later if bundle size becomes important.
mp_datas, mp_binaries, mp_hidden = collect_all("mediapipe")
ffmpeg_datas, ffmpeg_binaries, ffmpeg_hidden = collect_all("imageio_ffmpeg")
# imageio-ffmpeg discovers its executable relative to the Python package. Treat
# that file explicitly as a collected binary so its executable permissions and
# package-relative location survive the frozen build on macOS/Linux/Windows.
ffmpeg_exe = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
ffmpeg_datas = [entry for entry in ffmpeg_datas if Path(entry[0]).resolve() != ffmpeg_exe]
ffmpeg_binaries = [entry for entry in ffmpeg_binaries if Path(entry[0]).resolve() != ffmpeg_exe]
sim_datas = collect_data_files("simfile")

datas = mp_datas + ffmpeg_datas + sim_datas + [
    (str(assets / "vaporstep_icon.png"), "assets"),
    (str(assets / "models.json"), "assets"),
    (str(assets / "fonts" / "VaporStepEmojiSymbols.ttf"), "assets/fonts"),
    (str(assets / "fonts" / "NotoEmoji-OFL.txt"), "third_party_licenses/VaporStep-Emoji-Symbols"),
    (str(root / "LICENSE"), "."),
    (str(root / "THIRD_PARTY_NOTICES.md"), "."),
    (str(root / "MODEL_ASSETS.md"), "."),
    (str(root / "FFMPEG_PROVENANCE.md"), "."),
]

# Preserve license/notice files from the exact distributions installed in the
# build environment. This keeps frozen releases aligned with dependency
# versions without maintaining copied license text by hand in this repository.
for dist_name in ("mediapipe", "opencv-python", "pygame", "numpy", "simfile", "setuptools", "imageio-ffmpeg"):
    try:
        dist = distribution(dist_name)
    except PackageNotFoundError:
        continue
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", dist.metadata.get("Name", dist_name))
    for file in dist.files or ():
        basename = Path(str(file)).name.lower()
        if not (basename.startswith("license") or basename.startswith("copying") or basename.startswith("notice")):
            continue
        source = Path(dist.locate_file(file))
        if source.is_file():
            datas.append((str(source), f"third_party_licenses/{safe_name}"))

# PyInstaller includes the Python runtime itself. setup-python and standard
# Python installers normally place the interpreter license at the prefix root.
for candidate in (
    Path(sys.base_prefix) / "LICENSE.txt",
    Path(sys.base_prefix) / "LICENSE",
    Path(sys.executable).resolve().parent / "LICENSE.txt",
):
    if candidate.is_file():
        datas.append((str(candidate), "third_party_licenses/Python"))
        break
for model_name in ("pose_landmarker_lite.task", "pose_landmarker_full.task"):
    model = assets / model_name
    if model.exists():
        datas.append((str(model), "assets"))

hiddenimports = list(mp_hidden) + list(ffmpeg_hidden) + ["pkg_resources"]
binaries = list(mp_binaries) + list(ffmpeg_binaries) + [(str(ffmpeg_exe), "imageio_ffmpeg/binaries")]

icon = None
if sys.platform == "darwin" and (assets / "vaporstep.icns").exists():
    icon = str(assets / "vaporstep.icns")
elif sys.platform.startswith("win") and (assets / "vaporstep.ico").exists():
    icon = str(assets / "vaporstep.ico")

a = Analysis(
    [str(root / "vaporstep_launcher.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VaporStep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
    codesign_identity=codesign_identity,
    entitlements_file=entitlements_file,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VaporStep",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="VaporStep.app",
        icon=icon,
        bundle_identifier="org.vaporstep.game",
        info_plist={
            "CFBundleName": "VaporStep",
            "CFBundleDisplayName": "VaporStep",
            "NSHighResolutionCapable": True,
            "NSCameraUsageDescription": "VaporStep uses the camera to track your movement during gameplay.",
        },
    )