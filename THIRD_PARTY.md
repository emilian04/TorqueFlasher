# Third-party files

TorqueFlasher's own code (`*.py`, `profiles.json`, scripts) is MIT-licensed. The following files are **not**
covered by that license.

## ScooterHacking (ReFlasher)

`binaries/` (bootloaders, firmware, UICR files) and `diagrams/` (three JPG diagrams converted to PNG for
display) come from ScooterHacking's ReFlasher,
the F2 GD32 files `f2_gd32_BOOT.bin` / `f2_gd32_DRV.bin` from ScooterHacking as well.
© ScooterHacking. Included with permission of ScooterHacking (confirmed 2026-11-02); do not reuse them
outside this project without asking them.

## E2 Pro firmware

`binaries/firmware/32kmh.bin` (Ninebot E2 Pro) is community firmware whose author prefers to stay unnamed. It was
shared in the ScooterHacking community and is included with the OK of BastelPichi, who redistributed it.

## Manufacturer firmware

The firmware files are based on Segway-Ninebot and Xiaomi firmware; the copyright of that code stays with the
manufacturers. They are included for repairing and reflashing scooters the user owns.

## OpenOCD (GPL-2.0)

OpenOCD is licensed under the GNU General Public License v2. `oocd/scripts/` contains OpenOCD configuration
scripts; `oocd/scripts/mem_helper.tcl` has a one-line fix (braced `expr`) for OpenOCD ≥ 0.12.

| Binary | Where | Source |
|---|---|---|
| `oocd/bin/openocd.exe` | Windows (repository, Windows installer) | as shipped with ScooterHacking's ReFlasher; upstream source: https://openocd.org, https://github.com/openocd-org/openocd |
| `oocd/bin_at32/openocd.exe` | Windows (repository, Windows installer) | AT32 build as shipped with ReFlasher (`0.11.0+dev-00069-g68e50415a`); AT32 support in the fork https://github.com/encryptize/openocd-at32 |
| `oocd/bin/openocd` | Linux AppImage | built by `installer/linux/build_appimage.sh` from https://github.com/openocd-org/openocd, tag `v0.12.0` |
| `oocd/bin_at32/openocd` | Linux AppImage | built by `installer/linux/build_appimage.sh` from https://github.com/encryptize/openocd-at32, commit `01a6662400525ba7e3a799b26f9335d0d05f1a1f` |

The Linux binaries come with `libusb-1.0` (LGPL-2.1, https://libusb.info). The Linux AppImage and the Windows
installer also contain Python (PSF license) and Tcl/Tk (BSD-style license), packed with PyInstaller.
