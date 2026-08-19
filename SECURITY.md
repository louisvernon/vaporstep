# Security

## Supported version

Security fixes are applied to the current `main` branch and the latest release.

## Reporting a vulnerability

Please avoid publishing sensitive exploit details in a public issue. If GitHub
Private Vulnerability Reporting is enabled for the repository, use that channel.
Otherwise, open a minimal issue asking the maintainers for a private contact
channel without including exploit details.

## Local data and camera

VaporStep is a local desktop application. It does not intentionally upload song
libraries or camera frames. Raw camera frames are not persisted; the optional
Record Play feature stores only the rendered gameplay surface and reconstructed
game audio in a user-local video file. See the Privacy and security section of `README.md`
for camera lifetime, model downloads, and handling of local stepfile content.
