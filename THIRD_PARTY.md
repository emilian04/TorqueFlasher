# Third-party files

TorqueFlasher's own code (`*.py`, `profiles.json`, scripts) is MIT-licensed. The following files are **not**
covered by that license.

## ScooterHacking (ReFlasher)

`binaries/` (bootloaders, firmware, UICR files) and `diagrams/` come from ScooterHacking's ReFlasher,
the F2 GD32 files `f2_gd32_BOOT.bin` / `f2_gd32_DRV.bin` from ScooterHacking as well.
© ScooterHacking. Included with permission of ScooterHacking (confirmed 2026-11-02); do not reuse them
outside this project without asking them.

## BastelPichi (E2 Pro firmware)

`binaries/firmware/32kmh.bin` (Ninebot E2 Pro firmware) is by BastelPichi. Included with permission; do not
reuse it outside this project without asking.

## OpenOCD (GPL-2.0)

`oocd/bin/` and `oocd/bin_at32/` contain OpenOCD binaries, and `oocd/scripts/` contains OpenOCD
configuration scripts. OpenOCD is licensed under the GNU General Public License v2.

- Upstream source: https://openocd.org / https://sourceforge.net/p/openocd/code/
- AT32 build: _source location to be added_ (version `0.11.0+dev-00069-g68e50415a`, as shipped with ReFlasher)
- Linux AT32 build script `build_openocd_at32.sh` uses https://github.com/encryptize/openocd-at32

`oocd/scripts/mem_helper.tcl` contains a one-line fix (braced `expr`) for OpenOCD ≥ 0.12.
