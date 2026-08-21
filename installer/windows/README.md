# Windows packaging

Windows releases are built as a PyInstaller one-directory application. The
same folder is published as a portable ZIP and installed by Inno Setup. Keeping
the application files outside a self-extracting executable avoids PyInstaller's
temporary extraction behavior at every launch.

## Build locally

From a Windows PowerShell prompt with Python 3.12 and Inno Setup 6 installed.
GitHub release builds install Inno Setup 6.7.1 explicitly rather than relying
on the runner image:

```powershell
python -m pip install -e ".[build]"
python scripts/fetch_pose_model.py
pyinstaller --noconfirm --clean VaporStep.spec

$version = python -c "from vaporstep import __version__; print(__version__.split('+', 1)[0])"
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
  "/DAppVersion=$version" `
  "/DAppNumericVersion=$version.0" `
  "/DSourceDir=$PWD\dist\VaporStep" `
  "/DOutputDir=$PWD" `
  installer\windows\VaporStep.iss
```

The GitHub workflow publishes the installer, portable ZIP, and a checksum file.
Windows code signing will be added separately.
