# GremlinEx GitHub Releases installer (prototype)

This folder contains an Inno Setup 6 online bootstrapper. Build `GremlinEx.iss` with ISCC.exe on Windows. Output is `dist/installer/GremlinEx-Setup.exe`.

## Behavior
- Queries public GitHub Releases, including prereleases, and lists assets matching `gremlinEx_<major>_<minor>_m<milestone>[T|RC<build>[revision]].zip`.
- Sorts by numeric major, minor, milestone, channel (production > RC > test), build, and optional revision.
- Downloads the selected ZIP and extracts its contents to the managed installation directory.
- Offers **Extract portable copy** to a user-selected **empty** directory without creating an Inno Setup installation.
- Writes `.gremlinex-installed-version` in the destination.
- Offers an **optional, unchecked FFmpeg download** for both managed installation and portable extraction. It downloads a Windows essentials ZIP from gyan.dev and extracts `ffmpeg.exe` and `ffprobe.exe` under `<destination>\\tools\\ffmpeg\\bin`. It does not modify the system PATH. Existing copies in that destination are left unchanged. FFmpeg is independently licensed; see the license files in the downloaded distribution.

## Important limitations before production release
- This is **not yet tested on Windows** and must not be advertised as production-ready.
- Inno Setup's static `AppVersion` is not the selected asset's version. Previous selections are recorded as wizard data; future work should read the marker from the existing installation and show a comparison/confirmation for downgrades.
- Existing managed installations are backed up only in a temporary directory; rollback is best-effort and the backup is deleted when the script exits.
- No cryptographic SHA-256 verification is available because current GitHub release assets do not expose a separately trusted checksum manifest. The optional FFmpeg ZIP also lacks a pinned checksum in this prototype; pin and verify a known build before production distribution.
- Portable extraction bypasses Inno's uninstaller by exiting the wizard after extraction.
- Managed updates currently overlay files and do **not** remove obsolete files. A release manifest is recommended.
- No assumptions are made about where GremlinEx stores user profiles or plugins; this requires an application-specific preservation policy.
- Confirm the packaged executable's actual filename before enabling the Start Menu shortcut.
- PowerShell execution requires internet connectivity and a working TLS configuration.

Do not use the installer for unattended upgrades or broad distribution until Windows build, install, upgrade, downgrade, rollback, and uninstall tests pass.
