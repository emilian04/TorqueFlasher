# Releasing TorqueFlasher

## 1. Version

- `core.py`: `APP_VERSION` (e.g. `0.5.0`) and `APP_STAGE` (`BETA`, or `""` for a normal release).
- `README.md`: add a block under **Changes**; update **Hardware test status**.

The installer file names follow the version automatically:

| File | For |
|---|---|
| `TorqueFlasher-<version>-Windows-Setup.exe` | Windows 10 / 11, 64-bit |
| `TorqueFlasher-<version>-Linux-x86_64.AppImage` | Linux x86_64 (glibc 2.35+, e.g. Ubuntu 22.04, Debian 12, Fedora 36+) |

`<version>` is `0.5.0-beta` for a beta, `0.5.0` for a normal release.

## 2. Build the installers

### Automatically (GitHub Actions)

`.github/workflows/release.yml` builds both files.

- **On a tag:** push a tag like `v0.5.0-beta` (or create the release on GitHub with a new tag). Both files are
  attached to that release; tags containing `beta` become a pre-release.
- **By hand:** *Actions → Build installers → Run workflow*. The files are under *Artifacts* of that run.

### Locally

**Windows** (Python 3.10+ and Inno Setup 6 installed):

```
installer\windows\build.bat
```

Result: `installer\windows\Output\TorqueFlasher-<version>-Windows-Setup.exe`

**Linux** (Ubuntu 22.04 x86_64, internet, about 10 minutes):

```
bash installer/linux/build_appimage.sh
```

Result: `installer/linux/Output/TorqueFlasher-<version>-Linux-x86_64.AppImage`. Building on a newer distribution
works too, but the AppImage then only runs on that distribution and newer ones.

## 3. Publish

1. GitHub → *Releases → Draft a new release*.
2. Tag `v<version>` (e.g. `v0.5.0-beta`), title `TorqueFlasher <version>`.
3. Notes: the **Changes** block of the README, plus the hardware test status.
4. Attach both installer files (if the workflow did not already).
5. Beta: tick *Set as a pre-release*.

## What is where

| Path | Content |
|---|---|
| `gui.py`, `tf_ui.py` | user interface (Tkinter) |
| `core.py`, `e3tool.py`, `countdown.py` | flashing logic, E3 tool, countdown |
| `profiles.json` | scooter models, chips, files, picker groups |
| `binaries/`, `diagrams/` | bootloaders, firmware, UICR, wiring diagrams (see `THIRD_PARTY.md`) |
| `oocd/scripts/` | OpenOCD configuration; `oocd/bin*/` OpenOCD for Windows |
| `assets/` | app icon (`icon.svg`, PNGs, `icon.ico`, `accents/` per accent color) |
| `torqueflasher.spec` | PyInstaller build (Windows and Linux) |
| `installer/windows/` | Inno Setup script, `build.bat` |
| `installer/linux/` | `build_appimage.sh`, AppRun, `.desktop` file |
| `linux/99-stlink.rules` | udev rule for the ST-Link on Linux |
| `start.bat`, `start.sh`, `setup_linux.sh`, `build_openocd_at32.sh` | running from source |
