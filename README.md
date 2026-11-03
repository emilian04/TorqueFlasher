# TorqueFlasher

Flash the **ESC (DRV)** and **BLE module** of Ninebot and Xiaomi scooters over an **ST-Link**, on
**Windows and Linux**, without .NET. Includes backup, restore and serial-number (region) change for the
**Ninebot E3 / E3 Pro**.

TorqueFlasher uses the same OpenOCD command sequences as ScooterHacking's ReFlasher and its bootloader /
firmware files, and adds a read-back check after every write.

![Flash ESC](docs/screenshot-flash.png)

**Download:** [Releases](https://github.com/emilian04/TorqueFlasher/releases): `…-Windows-Setup.exe` for Windows,
`…-Linux-x86_64.AppImage` for Linux. See [Install](#install).

> **Beta. Use at your own risk.** Flashing erases the controller and can brick it. Not affiliated with
> Segway-Ninebot, Xiaomi or ScooterHacking.

## Scooters

| Brand | Models | Chip |
|---|---|---|
| Ninebot | ES1/ES2/ES4 (ESx), E22/E25/E45 (E) | STM32 |
| Ninebot | F20, F30, F40, D18, D28, D38, Max G30, Max G2 | STM32 / AT32, detected automatically |
| Ninebot | F2 / Plus / Pro | STM32 / AT32, detected; or GD32 with special files (own entry) |
| Ninebot | E2 Pro (community firmware `32kmh.bin` included, other firmware selectable) | STM32 / AT32, detected |
| Ninebot | E3 / E3 Pro: backup, restore, serial-number change (no flashing) | AT32 |
| Xiaomi | M365, Mi Pro | STM32 |
| Xiaomi | Mi Lite / Essential, 1S, Pro 2, Mi 3 | STM32 or GD32, chosen by you |

BLE flashing is available where ReFlasher has a BLE file (not for G2, F2, D18/D28/D38, E2 Pro).

**Chip:** for models that come with STM32 or AT32, *Check connection* detects the chip and TorqueFlasher keeps
using it (shown as `AUTO ✓ detected`). Flash ESC detects it again and stops if the controller changed since the
check. If detection fails, set the chip by hand with *override*. Xiaomi models that also exist with a GD32 chip
show an STM32 / GD32 switch instead; the check warns when the chip looks different from your choice.

## Actions

| Action | What it does |
|---|---|
| **Check connection** | Detects the chip, probes ST-Link and controller (device id, flash size, read protection). On an unlocked chip it also reads **serial number, mileage and UID** and saves them to `dumps/`. Writes nothing. |
| **Flash ESC** | Removes read protection, mass erase, reads the chip UID, writes bootloader @ `0x0`, firmware @ `0x1000` and a new user-data page (serial number, mileage, UID), then **reads everything back and compares it**. Values read by the last check can be taken over with one click. |
| **BLE check / BLE flash** | nRF51822: probe; or mass erase, bootloader, firmware, Bluetooth name, UICR, each with OpenOCD verify. |
| **E3 / E3 Pro** | Check, read serial number, full 128 KB backup with SHA-256, change serial number (backup first, then 2 KB written and verified), restore backup, make a patched dump offline. |

At every start a short **warning** comes first (bricking risk, battery, warranty and road approval, beta);
TorqueFlasher opens after *I understand*.

The **countdown** before each start is set with − / + in the header (0 = off). Actions that write ask for one
confirmation. **Dry run** (top bar or Settings) shows all OpenOCD commands in the console without touching the chip.

**Scooter picker:** models grouped by series, a search field over both brands (↑ ↓ Enter), and the last three
scooters for one-click switching.
**Settings:** accent color (also used for the app icon), dry run, program folder check, E3 backup folder, dumps and logs.
**Info:** version, hardware test status, *Report a test result*, credits and licenses.

## Wiring

The controller is **powered by the ST-Link only. Disconnect the scooter battery first.** Connect GND, SWDIO,
SWCLK and the supply as shown in the wiring diagram: *wiring ›* on the scooter card shows ReFlasher's diagram for
the selected scooter. Never put 5 V on the 3.3 V pad.

## Install

Download the file for your system from [Releases](https://github.com/emilian04/TorqueFlasher/releases).
Python is not needed.

### Windows 10 / 11

1. Run `TorqueFlasher-<version>-Windows-Setup.exe`. The wizard asks for the install folder, the **data folder**
   (backups, dumps, logs; default `Documents\TorqueFlasher`) and a desktop shortcut. No admin rights needed.
2. Windows may show *"Windows protected your PC"* because the installer is not signed: *More info → Run anyway*.
3. ST-Link driver: if ReFlasher works on this PC, TorqueFlasher works too. Otherwise install ST's ST-Link driver
   (STSW-LINK009). Close ReFlasher before using TorqueFlasher.

Uninstall via *Settings → Apps*. The data folder is kept.

### Linux (x86_64)

1. Download `TorqueFlasher-<version>-Linux-x86_64.AppImage`, make it executable
   (file properties → *Allow executing*, or `chmod +x TorqueFlasher-*.AppImage`) and start it.
2. On the first connection Linux may report *no permission* for the ST-Link: press **Set up ST-Link access** in
   TorqueFlasher (asks once for your password), then unplug and re-plug the ST-Link.
3. If the AppImage does not start because FUSE is missing, start it with `--appimage-extract-and-run`.

Data folder: `~/TorqueFlasher` (changeable in Settings).

## Files it writes

All in the **data folder** (installer default `Documents\TorqueFlasher` / `~/TorqueFlasher`; when run from
source: the program folder). Settings → *Data folder* shows and changes it.

| Path | Content |
|---|---|
| `dumps/` | user-data page + UID from *Check connection* (unlocked chips) |
| `e3_backups/` (folder changeable) | E3 full backups + `.sha256` |
| `logs/` | full OpenOCD output, one file per day |
| `temp/` | generated user-data / name pages, read-back files |
| settings | `%APPDATA%\torqueflasher\settings.json` or `~/.config/torqueflasher/settings.json` |

Dumps and backups contain serial numbers, chip UIDs and mileage. Keep them private.

## Troubleshooting

| Message | Meaning |
|---|---|
| *No ST-Link found* | USB cable or driver; ReFlasher or another tool still holds the ST-Link. |
| *no permission to use it* (Linux) | Press *Set up ST-Link access* (or run `setup_linux.sh`), then re-plug. |
| *… does not respond* | Wiring, or the board has no power: ST-Link supply connected, battery disconnected? |
| *Read protection: on* | Normal for a stock ESC; flashing removes it. For the E3 tool it means the backup is not possible. |
| *Chip not detected reliably* | Set the chip with *override* on the chip card, and please report the console log. |
| *The chip is now detected as …* | The controller changed since *Check connection*. Run the check again. |
| *Verify failed* | What was read back differs from what was written. Flash again; for the E3 restore the backup. |
| `mem_helper.tcl:37: wrong # args` | Harmless with OpenOCD ≥ 0.12 and old scripts; fixed in the `mem_helper.tcl` shipped here. |

## Hardware test status

| Scooter / chip | Action | Status |
|---|---|---|
| Max G2 · AT32 | Flash ESC | worked |
| F2 Pro, F2 Pro II · AT32 | Flash ESC | worked |
| E3 · AT32 | backup, read SN, change SN | worked |
| any | read-back verify after Flash ESC, SN/mileage read in Check connection | new, not yet tested on hardware |
| any | chip auto-detection | new, not yet tested on hardware |
| any | Flash BLE | not yet tested on hardware |
| Xiaomi, GD32 | all | not yet tested on hardware |
| Windows | all | not yet tested (startup, dark title bar: OK) |

Tried a scooter? Please [report the result](https://github.com/emilian04/TorqueFlasher/issues/new?template=test-report.yml),
worked or not, with the console log (Info page → *Report a test result*).

All actions are covered by an automated test that drives the real GUI against a simulated OpenOCD (89 checks).

## Run from source (developers)

The repository contains everything the program needs (`binaries/`, `diagrams/`, `oocd/`, `assets/`).
If a file is missing, the app shows **Setup needed** with the list (also under Settings → Program files).

**Windows:** install Python 3 from [python.org](https://www.python.org) (tick *Add python.exe to PATH*), then
double-click `start.bat`. If no window appears, run `py -3 gui.py` in that folder to see the error.

**Linux:**

```
bash setup_linux.sh          # OpenOCD, python3-tk, ST-Link udev rule
bash build_openocd_at32.sh   # AT32-capable OpenOCD into oocd/bin_at32 (needed for AT32 and E3)
bash start.sh
```

Existing OpenOCD binaries can be used with `TORQUEFLASHER_OPENOCD` and `TORQUEFLASHER_OPENOCD_AT32`
(or `openocd-at32` on the `PATH`).

**Installers:** see [RELEASING.md](RELEASING.md).

## Changes

**0.5.1 beta**
- Wiring diagrams for G2, F2, E2 Pro, G30D and the Xiaomi Pro BLE are shown in the app on Linux too (converted
  from JPG to PNG, pixel-identical). The E3 / E3 Pro shows the G2/F2 diagram (same wiring).
- Windows: app icon in the title bar and the taskbar (it was lost while the startup warning was open).
- AppImage: opening folders and the ST-Link password prompt use the system libraries.

**0.5.0 beta**
- Installers: Windows setup wizard (install folder, data folder, shortcuts) and a Linux AppImage with Python,
  Tk and both OpenOCD builds inside.
- Data folder for dumps, backups, logs and temporary files (Settings → *Data folder*).
- Linux: *Set up ST-Link access* button when the ST-Link cannot be opened.

**0.4.3 beta**
- Windows: app icon in the title bar and the taskbar (own taskbar entry instead of Python's).
- Startup warning and BLE hints reworded.

**0.4.2 beta**
- Warning at every start; TorqueFlasher opens after *I understand* (unlocks after 3 s), *Quit* ends it.
- The app icon follows the accent color (window, taskbar, top bar). The icon of the .exe file itself stays lime.

**0.4.1 beta**
- New scooter picker: series groups, search over both brands (↑ ↓ Enter, Esc clears), last three scooters.
- Rounder corners everywhere, app icon (lightning bolt), dark title bar (Windows 11 in the app color,
  Windows 10 dark, GNOME via `xprop`, KDE follows the system theme).
- No supply-voltage tables any more: wire as in the diagram, never 5 V on the 3.3 V pad.

**0.4.0 beta**
- New design with accent colors; header cards for scooter, chip and countdown (− / +); dry run in the top bar.
- Chip auto-detection for STM32/AT32 models: *Check connection* adopts the chip, *Flash ESC* detects it again and
  stops if the controller changed; *override* for manual choice. Xiaomi models with GD32 variant: STM32 / GD32
  switch.
- *Check connection* reads serial number, mileage and UID on unlocked chips; *use check values* in Flash ESC.
- Info page with hardware test status and *Report a test result*.

## Credits

- Flash sequences, bootloader/firmware files, F2 GD32 files and wiring diagrams:
  [ScooterHacking](https://cfw.sh) (ReFlasher), used with permission.
- E2 Pro firmware `32kmh.bin`: community firmware (author unnamed), included with BastelPichi's OK.
- See [THIRD_PARTY.md](THIRD_PARTY.md).

## License

MIT for TorqueFlasher's own code (see `LICENSE`). Third-party files keep their own terms.
