"""TorqueFlasher core: ESC (DRV) and BLE flashing for Ninebot / Xiaomi scooters via ST-Link + OpenOCD.

The OpenOCD command sequences follow ScooterHacking's ReFlasher (read from its code); the user-data page layout
was verified byte for byte against real dumps. No user I/O in here: every operation takes
    log(text)                       short status lines for the user
    progress(step, total, label)    optional, for step indicators
Raw OpenOCD output goes to RAW_SINK(line) when a front end sets it (the GUI console), otherwise to log.

Folders next to this file: binaries/ (bootloader/, firmware/, UICR files), diagrams/, oocd/scripts/,
OpenOCD in oocd/bin and oocd/bin_at32 (Windows), or a system OpenOCD on Linux/macOS.
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Callable

APP_NAME = "TorqueFlasher"
APP_VERSION = "0.4.0"
APP_STAGE = "BETA"
REPO_URL = "https://github.com/emilian04/TorqueFlasher"
TEST_REPORT_URL = REPO_URL + "/issues/new?template=test-report.yml"


def _app_dir() -> Path:
    """Folder with profiles.json, binaries, oocd... For a PyInstaller build: the folder of the EXE."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _app_dir()
PROFILES = json.loads((ROOT / "profiles.json").read_text(encoding="utf-8"))
LOGS = ROOT / "logs"
TEMP = ROOT / "binaries" / "temp"

RAW_SINK: Callable[[str], None] | None = None


def _noprogress(step, total, label):
    pass


def tcl_path(p) -> str:
    """Path for an OpenOCD (Tcl) command: braced, so spaces in the path do not split it."""
    return "{" + Path(p).resolve().as_posix() + "}"


def blank(data: bytes) -> bool:
    return not data or all(b == 0 for b in data) or all(b == 0xFF for b in data)


# ----------------------------------------------------------------------------------------------- OpenOCD
def _env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def find_openocd(variant_dir: str) -> str:
    """Windows: bundled oocd/<dir>/openocd.exe. Linux/macOS: bundled binary or system OpenOCD.
    AT32 needs a patched build (oocd/bin_at32/openocd, or TORQUEFLASHER_OPENOCD_AT32 / openocd-at32 on PATH)."""
    env = _env("TORQUEFLASHER_OPENOCD", "REFLASHER_OPENOCD")
    if env and variant_dir != "bin_at32":
        return env
    exe = "openocd.exe" if platform.system() == "Windows" else "openocd"
    bundled = ROOT / "oocd" / variant_dir / exe
    if bundled.exists():
        return str(bundled)
    if variant_dir == "bin_at32":
        alt = _env("TORQUEFLASHER_OPENOCD_AT32", "REFLASHER_OPENOCD_AT32") or shutil.which("openocd-at32")
        if alt:
            return alt
        raise FileNotFoundError("AT32 build of OpenOCD missing (oocd/bin_at32/openocd). "
                                "Linux: run ./build_openocd_at32.sh")
    found = shutil.which("openocd")
    if not found:
        if platform.system() == "Windows":
            raise FileNotFoundError("OpenOCD not found: copy 'oocd\\bin' (and 'oocd\\bin_at32') from the "
                                    "ReFlasher folder into the TorqueFlasher folder")
        raise FileNotFoundError("openocd not found (Linux: sudo apt install openocd, or run setup_linux.sh)")
    return found


def openocd_version(exe: str) -> str:
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=8,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        m = re.search(r"Open On-Chip Debugger\s+(\S+)", (r.stdout or "") + (r.stderr or ""))
        return re.sub(r"-g[0-9a-f]{6,}", "", m.group(1)) if m else ""
    except Exception:  # noqa
        return ""


def _raw(line: str, log):
    if RAW_SINK:
        try:
            RAW_SINK(line)
        except Exception:  # noqa
            pass
    else:
        log(line)


def run_openocd(exe: str, target_cfg: str, commands: list[str], dry_run=False,
                log: Callable[[str], None] = print) -> tuple[int, list[str]]:
    """Runs OpenOCD and streams its output line by line. No shell -> no quoting problems.
    Every run is also appended to logs/torqueflasher_<date>.log."""
    args = [exe, "-s", str(ROOT / "oocd" / "scripts"), "-f", "interface/stlink.cfg", "-f", target_cfg]
    for c in commands:
        args += ["-c", c]
    args += ["-c", "exit"]
    shown = "$ openocd " + " ".join(f'"{a}"' if " " in a else a for a in args[1:])
    _raw(shown, log)
    if dry_run:
        return 0, []
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        logfile = (LOGS / f"torqueflasher_{datetime.date.today()}.log").open("a", encoding="utf-8")
        logfile.write("\n" + shown + "\n")
    except OSError:
        logfile = None
    out: list[str] = []
    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", cwd=ROOT,
                             creationflags=0x08000000 if os.name == "nt" else 0)  # CREATE_NO_WINDOW
    except OSError as e:
        if logfile:
            logfile.close()
        raise RuntimeError(f"Could not start OpenOCD ({exe}): {e}") from e
    for line in p.stdout:  # OpenOCD writes almost everything to stderr -> merged
        line = line.rstrip()
        out.append(line)
        _raw(line, log)
        if logfile:
            logfile.write(line + "\n")
    rc = p.wait()
    if logfile:
        logfile.close()
    return rc, out


POWER_HINT = "Power the board from the ST-Link only, with the scooter battery disconnected"


def connection_error(text: str, what="the chip") -> str | None:
    """Common OpenOCD failure texts -> a readable message, or None."""
    if "LIBUSB_ERROR_ACCESS" in text:
        return ("ST-Link found, but no permission to use it (Linux: run setup_linux.sh for the udev rules, "
                "then re-plug the ST-Link)")
    if "open failed" in text:
        return "No ST-Link found (check the USB cable and driver; close ReFlasher or other tools)"
    if "init mode failed" in text or "unable to connect" in text:
        return (f"ST-Link found, but {what} does not respond. Check SWDIO/SWCLK/GND and the supply: "
                f"{POWER_HINT.lower()}. (\"Target voltage\" alone does not prove the chip has power.)")
    return None


def check_connection(exe, target, gd32e=False, **kw) -> str | None:
    """None = OK, otherwise an error text."""
    rc, out = run_openocd(exe, target, ["init"] if gd32e else ["init", "reset halt"], **kw)
    err = connection_error("\n".join(out))
    if err:
        return err
    if rc != 0:
        return f"OpenOCD exit code {rc} (see the console)"
    return None


def parse_probe(text: str) -> dict:
    info = {}
    for key, pattern in (("stlink", r"Info : (STLINK \S+)"),
                         ("voltage", r"Target voltage: ([\d.]+)"),
                         ("cpu", r"\] (Cortex-\S+ \S+) processor detected"),
                         ("device_id", r"device id = (0x[0-9a-fA-F]+)"),
                         ("flash_kb", r"flash size = (\d+)\s*Ki?B"),
                         ("rdp", r"read protection: (\w+)")):
        m = re.search(pattern, text)
        if m:
            info[key] = m.group(1)
    return info


# ----------------------------------------------------------------------------------------------- serial number
DEFAULT_SN = PROFILES["serial_number"].get("default", "00000/000000000")


def validate_sn(sn: str, brand: str | None = None) -> None:
    """Like ReFlasher: 14 characters. Ninebot A-Z/0-9 only, Xiaomi 5 digits, '/', 8 digits."""
    sc = PROFILES["serial_number"]
    if len(sn) != sc["length"]:
        raise ValueError("The serial number must be 14 characters long")
    if brand == "xiaomi":
        if not re.fullmatch(sc["mi_regex"], sn):
            raise ValueError("Invalid serial number (Xiaomi format: 5 digits, /, 8 digits, e.g. 26354/00012345)")
    elif not re.fullmatch(sc["nb_regex"], sn):
        raise ValueError("Invalid serial number (A-Z and 0-9 only)")


def sn_valid(sn: str, brand: str | None = None) -> bool:
    try:
        validate_sn(sn, brand)
        return True
    except ValueError:
        return False


def build_userdata_page(brand: str, model: str, sn: str, mileage_km: float, uid: bytes | None = None,
                        activate: bool = True) -> bytes:
    """Builds the 1024-byte user-data page exactly like ReFlasher (layout read from its code, verified against
    a real F40 dump). uid=None -> 'Copy CPUID' off; activate=False -> 'Activate ESC' off."""
    lay = PROFILES["userdata"]
    page = bytearray(lay["size"])
    for off, val in lay["fixed"].items():
        page[int(off, 16)] = val
    if activate:
        page[int(lay["activation"]["offset"], 16)] = lay["activation"]["value"]
    if sn != DEFAULT_SN:
        validate_sn(sn, brand)
    snb = sn.encode("ascii")
    o = int(lay["sn"]["offset"], 16)
    page[o:o + len(snb)] = snb
    if uid is not None:
        if len(uid) != lay["uid"]["length"]:
            raise ValueError("UID has the wrong length")
        o = int(lay["uid"]["offset"], 16)
        page[o:o + len(uid)] = uid
    meters = int(round(mileage_km * 1000))
    if not 0 <= meters < 2 ** 31:
        raise ValueError("Mileage out of range")
    o = int(lay["mileage"]["offset"], 16)
    page[o:o + 4] = meters.to_bytes(4, "little")
    return bytes(page)


def parse_userdata_page(page: bytes) -> dict:
    """SN and mileage from a dumped user-data page (same layout for Ninebot and Xiaomi)."""
    lay = PROFILES["userdata"]
    o = int(lay["sn"]["offset"], 16)
    raw = page[o:o + lay["sn"]["length"]]
    sn = raw.decode("ascii", "replace") if all(32 <= b < 127 for b in raw) else None
    o = int(lay["mileage"]["offset"], 16)
    meters = int.from_bytes(page[o:o + 4], "little") if len(page) >= o + 4 else 0
    return {"sn": sn, "km": meters / 1000 if meters < 2 ** 31 else None}


# ----------------------------------------------------------------------------------------------- chip
def detect_chip(dry_run=False, log=print) -> dict:
    """Reads DBGMCU_IDCODE and CPUID and suggests stm32 / gd32 / at32 (heuristic)."""
    d = PROFILES["drv"]
    cfg = d["detect"]
    exe = find_openocd("bin")
    rc, out = run_openocd(exe, d["openocd_target"],
                          ["init", "reset halt", f"mdw {cfg['idcode_addr']}", f"mdw {cfg['cpuid_addr']}"],
                          dry_run=dry_run, log=log)
    txt = "\n".join(out)
    err = connection_error(txt)
    if err:
        raise RuntimeError(err)
    vals = {int(a, 16): int(v, 16) for a, v in re.findall(r"0x([0-9a-fA-F]{8}):\s+([0-9a-fA-F]{8})", txt)}
    idc = vals.get(int(cfg["idcode_addr"], 16))
    cpu = vals.get(int(cfg["cpuid_addr"], 16))
    info = {"idcode": idc, "cpuid": cpu, "family": "unknown"}
    if idc is None or cpu is None:
        return info
    partno = (cpu >> 4) & 0xFFF
    if (idc & 0xFFF) in [int(x, 16) for x in cfg["st_f1_devids"]] and partno == 0xC23:
        info["family"] = "gd32" if cpu == int(cfg["cpuid_gd32"], 16) else \
                         "stm32" if cpu == int(cfg["cpuid_stm32"], 16) else "unknown"
    elif partno == 0xC24 and (idc & 0xFFF) not in [int(x, 16) for x in cfg["st_f1_devids"]]:
        info["family"] = "at32"
    known = cfg.get("known_ids", {}).get(f"0x{idc:08X}")
    if known:
        info["known"] = known
    log(f"Detection: IDCODE=0x{idc:08X} CPUID=0x{cpu:08X} -> {info['family']}")
    return info


def resolve_variant(variant: str, dry_run=False, log=print) -> str:
    """'auto' -> stm32/gd32/at32 via chip detection; otherwise unchanged."""
    if variant != "auto":
        return variant
    if dry_run:
        log("(Dry run: chip detection skipped, using stm32)")
        return "stm32"
    fam = detect_chip(log=log)["family"]
    if fam == "unknown":
        raise RuntimeError("Chip not detected reliably. Choose STM32/GD32/AT32 manually and send the console log.")
    log(f"Detected chip: {fam.upper()}")
    return fam


def _item(brand, model):
    prof = PROFILES["models"][brand]
    return prof, prof["items"][model]


def _variant_for(item, variant, dry_run, log):
    if item.get("variant"):
        log(f"Chip: {item['variant'].upper()} (fixed for this model)")
        return item["variant"]
    return resolve_variant(variant, dry_run, log)


def _gd32e(brand, item, variant) -> bool:
    return bool(item.get("gd32e")) or (brand == "xiaomi" and variant == "gd32")


def _target_for(variant):
    drv = PROFILES["drv"]
    var = drv["variants"][variant]
    return find_openocd(var["openocd_dir"]), var.get("openocd_target", drv["openocd_target"])


def check_drv(brand: str, model: str, variant: str, *, read_userdata=True, dry_run=False, log=print,
              progress=_noprogress) -> dict:
    """Read-only check in three steps:
    1. detect the chip (skipped for models with a fixed chip and for Xiaomi GD32, whose sessions start without
       'reset halt'); with variant 'auto' the detected chip is used,
    2. probe ST-Link and target: CPU, device id, flash size, read protection,
    3. if the chip is not read-protected: read the user-data page (serial number, mileage) and the UID into dumps/.
    Returns the probe info plus 'variant', optionally 'detected' / 'known' / 'idcode' and 'userdata'."""
    _, item = _item(brand, model)
    info = {}
    progress(1, 3, "Detecting the chip")
    if item.get("variant"):
        variant = item["variant"]
        log(f"Chip: {variant.upper()} (fixed for this model)")
    elif dry_run:
        log("(Dry run: chip detection skipped)")
        if variant == "auto":
            variant = "stm32"
    elif variant == "auto" or not _gd32e(brand, item, variant):
        det = detect_chip(log=log)
        info["detected"] = det["family"]
        if det.get("idcode") is not None:
            info["idcode"] = f"0x{det['idcode']:08X}"
        if det.get("known"):
            info["known"] = det["known"]
        if variant == "auto":
            if det["family"] == "unknown":
                raise RuntimeError("Chip not detected reliably. Choose the chip manually (Chip → override) and "
                                   "send the console log.")
            variant = det["family"]
            log(f"Detected chip: {variant.upper()}")
        elif det["family"] not in ("unknown", variant):
            log(f"Warning: the chip looks like {det['family'].upper()}, but {variant.upper()} is selected.")

    progress(2, 3, "Probing flash and read protection")
    exe, target = _target_for(variant)
    gd32e = _gd32e(brand, item, variant)
    cmds = ["init"] if gd32e else ["init", "reset halt", "flash probe 0", "stm32f1x options_read 0"]
    rc, out = run_openocd(exe, target, cmds, dry_run=dry_run, log=log)
    info["variant"] = variant
    if dry_run:
        progress(3, 3, "Reading serial number and mileage")
        log("(Dry run: user data is read only on a real, unlocked chip)")
        return info
    text = "\n".join(out)
    err = connection_error(text)
    if err:
        raise RuntimeError(err)
    info.update(parse_probe(text))
    if "cpu" not in info and "device_id" not in info and rc != 0:
        raise RuntimeError(f"OpenOCD exit code {rc}, no target information (see the console)")
    if info.get("rdp") == "on":
        log("Read protection is ON (normal for a stock ESC; flashing removes it with a full erase).")
    log("Connection OK")

    progress(3, 3, "Reading serial number and mileage")
    if not read_userdata:
        pass
    elif info.get("rdp") == "off":
        out_path = ROOT / "dumps" / f"userdata_{model}_{datetime.datetime.now():%Y%m%d-%H%M%S}.bin"
        try:
            info["userdata"] = dump_userdata(brand, variant, str(out_path), log=log, model=model)
        except RuntimeError as e:  # the check itself succeeded; reading the page is a bonus
            log(f"Note: serial number and mileage could not be read ({e})")
    elif info.get("rdp") == "on":
        log("Serial number and mileage cannot be read while read protection is on.")
    else:
        log("Serial number and mileage: read protection state unknown for this chip, not read.")
    return info


# ----------------------------------------------------------------------------------------------- DRV flashing
def check_firmware(path: Path, start: int, end: int) -> None:
    """Sanity check: does the image fit between firmware start and user-data page, and does it look like a
    Cortex-M image for base 0x08000000+start? (prevents e.g. flashing a full dump by accident)"""
    data = Path(path).read_bytes()
    if len(data) > end - start:
        raise ValueError(f"Firmware too large ({len(data)} bytes, max. {end - start}). A full dump instead of an app image?")
    if len(data) < 1024:
        raise ValueError("Firmware file is suspiciously small")
    sp, reset = struct.unpack_from("<II", data)
    base = 0x08000000 + start
    if not (0x20000000 <= sp <= 0x20100000) or not (base <= (reset & ~1) < base + len(data)):
        raise ValueError(f"Vector table does not match an image for 0x{base:08X} "
                         f"(SP=0x{sp:08X}, Reset=0x{reset:08X}). Wrong file?")


def _read_uid(path: Path, dry_run: bool, log) -> bytes:
    if dry_run and not Path(path).exists():
        log("(Dry run: UID placeholder, the real UID is read when flashing)")
        return bytes(12)
    data = Path(path).read_bytes() if Path(path).exists() else b""
    if len(data) != 12:
        raise RuntimeError("Could not read the UID (file empty or incomplete)")
    return data


def drv_files(brand: str, model: str, variant: str, firmware_file=None):
    """(bootloader, firmware, note) for a model/chip, without touching the device."""
    prof, item = _item(brand, model)
    var = PROFILES["drv"]["variants"][variant]
    bdir = ROOT / "binaries/bootloader"
    pre = prof["bootloader_prefix"]
    note = None
    boot = bdir / (item.get("bootloader") or f"{pre}_DRV{var['bootloader_suffix']}.bin")
    if not item.get("bootloader") and not boot.exists() and variant == "gd32":
        boot = bdir / f"{pre}_DRV.bin"  # Ninebot has no GD32 bootloader -> standard one (assumption)
        note = f"No {pre}_DRV_GD32.bin available, using {boot.name} (assumption, please check)"
    if firmware_file:
        fw = Path(firmware_file)
    elif item.get("drv"):
        fw = ROOT / "binaries/firmware" / item["drv"]
    elif item.get("default_fw") and (ROOT / "binaries/firmware" / item["default_fw"]).exists():
        fw = ROOT / "binaries/firmware" / item["default_fw"]
    else:
        hint = f" (or put {item['default_fw']} into binaries/firmware)" if item.get("default_fw") else ""
        raise ValueError("Choose a firmware file for this model" + hint)
    return boot, fw, note


def flash_drv(model: str, brand: str, variant: str, *, sn=None, mileage_km=None, userdata_file=None,
              firmware_file=None, copy_uid=True, activate=True, verify=True, expect=None, dry_run=False, log=print,
              progress=_noprogress) -> dict:
    """Full ESC flash like ReFlasher: remove read protection, mass erase, read UID, erase again, write
    bootloader @0x0, firmware @0x1000 and the user-data page, then read everything back and compare.
    expect: chip found by an earlier check. With variant 'auto' the chip is detected again and must match it
    (protects against a controller swapped since the check)."""
    prof, item = _item(brand, model)
    ud_off = item.get("userdata_offset", prof["userdata_offset_drv"])
    if expect and variant == "auto" and dry_run:
        variant = expect
    variant = _variant_for(item, variant, dry_run, log)
    if expect and not item.get("variant") and variant != expect:
        raise RuntimeError(f"The chip is now detected as {variant.upper()}, but Check connection found "
                           f"{expect.upper()}. Run Check connection again.")
    chips = item.get("chips")
    if chips and variant not in chips:
        raise ValueError(f"Chip {variant.upper()} is not available for this model (possible: "
                         + ", ".join(c.upper() for c in chips) + ")")
    gd32e = _gd32e(brand, item, variant)
    drv = PROFILES["drv"]
    exe, target = _target_for(variant)
    kw = dict(dry_run=dry_run, log=log)

    boot, fw, note = drv_files(brand, model, variant, firmware_file)
    if note:
        log("Note: " + note)
    check_firmware(fw, int(drv["firmware_offset"], 16), int(ud_off, 16))
    for f in (boot, fw):
        if not f.exists():
            raise FileNotFoundError(f"Missing file: {f}")
    log(f"Bootloader: {boot.name}   Firmware: {fw.name}   Chip: {variant.upper()}")

    progress(1, 4, "Checking the connection")
    if not dry_run:
        err = check_connection(exe, target, gd32e=gd32e, **kw)
        if err:
            raise RuntimeError(err)
        log("Connection OK")

    # Sequence as in ReFlasher (flash_STM32 / read_UID_STM32 / unlock_GD32E). For Xiaomi+GD32 ("GD32E") an
    # unlock call runs before every session, and the sessions start without the first 'reset halt'.
    TEMP.mkdir(parents=True, exist_ok=True)
    uid_file = TEMP / "uid.bin"
    uid_file.unlink(missing_ok=True)
    wipe = (["init"] if gd32e else ["init", "reset halt"]) + [
        "flash probe 0", "stm32f1x unlock 0", "reset halt", "stm32f1x mass_erase 0"]

    def unlock_gd32e():
        if gd32e:
            log("GD32E: unlock call (a halt error here is normal and ignored)")
            run_openocd(exe, target, ["init", "reset halt"], **kw)

    uid = None
    if copy_uid:
        progress(2, 4, "Removing read protection, erasing, reading the UID")
        unlock_gd32e()
        rc, out = run_openocd(exe, target, wipe + [f"dump_image {tcl_path(uid_file)} "
                              f"{drv['uid_address']} {drv['uid_length']}"], **kw)
        if not dry_run and "mass erase complete" not in "\n".join(out):
            raise RuntimeError("Mass erase failed (see the console)")
        uid = _read_uid(uid_file, dry_run, log)
        if not dry_run:
            log(f"UID: {uid.hex(' ').upper()}")
    else:
        progress(2, 4, "UID copy is off - skipped")

    progress(3, 4, "Erasing and writing")
    unlock_gd32e()
    flash_base = int(drv["flash_base"], 16)
    writes = [(boot, 0), (fw, int(drv["firmware_offset"], 16))]
    page = None
    if userdata_file is not None:
        page = Path(userdata_file)
    elif sn is not None:
        page = TEMP / "drv_user_data.bin"
        page.write_bytes(build_userdata_page(item.get("sn_format", brand), model, sn, mileage_km or 0, uid, activate))
    if page is not None:
        writes.append((page, int(ud_off, 16)))
    cmds = list(wipe) + [f"flash write_bank 0 {tcl_path(f)} 0x{off:X}" for f, off in writes]
    backs = []
    if verify:  # read back in the same session, before the firmware runs (it may lock the chip again)
        for i, (f, off) in enumerate(writes):
            b = TEMP / f"readback_{i}.bin"
            b.unlink(missing_ok=True)
            backs.append(b)
            cmds.append(f"dump_image {tcl_path(b)} 0x{flash_base + off:08X} {f.stat().st_size}")
    cmds.append("reset run")
    rc, out = run_openocd(exe, target, cmds, **kw)
    txt = "\n".join(out)
    wrote = len(re.findall(r"^wrote \d+ bytes", txt, re.M))
    if not dry_run and wrote < len(writes):
        err = connection_error(txt)
        raise RuntimeError(err or f"Flashing failed: only {wrote} of {len(writes)} writes succeeded (see the console)")

    progress(4, 4, "Comparing what was written")
    verified = 0
    if verify and not dry_run:
        for (f, off), b in zip(writes, backs):
            want = f.read_bytes()
            got = b.read_bytes() if b.exists() else b""
            if got != want:
                if len(got) != len(want):
                    raise RuntimeError(f"Verify failed: could not read back {f.name} at 0x{flash_base + off:08X}.")
                diffs = [i for i in range(len(want)) if got[i] != want[i]]
                raise RuntimeError(f"Verify failed: {len(diffs)} byte(s) of {f.name} differ (first at "
                                   f"0x{flash_base + off + diffs[0]:08X}). Flash again.")
            verified += len(want)
        log(f"Verified: {verified} bytes match.")
    if item.get("after_note"):
        log("Note: " + item["after_note"])
    log("Done. Disconnect the ST-Link, reconnect the battery and switch the scooter on.")
    return {"variant": variant, "bootloader": boot.name, "firmware": fw.name, "verified": verified,
            "sn": sn, "km": mileage_km, "uid": uid.hex(" ").upper() if uid and not dry_run else None}


def dump_userdata(brand: str, variant: str, out_path: str, *, size=1024, dry_run=False, log=print, model=None,
                  progress=_noprogress) -> dict:
    """Reads the user-data page and the UID from an (already unlocked) chip. Read-only."""
    prof = PROFILES["models"][brand]
    drv = PROFILES["drv"]
    item = prof["items"].get(model, {}) if model else {}
    if item.get("variant"):
        variant = item["variant"]
    total = 2 if variant == "auto" else 1
    if variant == "auto":
        progress(1, 2, "Detecting the chip")
        variant = "stm32" if dry_run else detect_chip(log=log)["family"]
        if variant not in drv["variants"]:
            raise RuntimeError("Chip not detected reliably. Choose STM32/GD32/AT32 manually.")
    progress(total, total, "Reading the user-data page and UID")
    exe, target = _target_for(variant)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    uid = out.with_suffix(".uid.bin")
    addr = hex(int(drv["flash_base"], 16) + int(item.get("userdata_offset", prof["userdata_offset_drv"]), 16))
    rc, lines = run_openocd(exe, target,
                            ["init", "reset halt",
                             f"dump_image {tcl_path(out)} {addr} {size}",
                             f"dump_image {tcl_path(uid)} {drv['uid_address']} {drv['uid_length']}",
                             "reset run"],
                            dry_run=dry_run, log=log)
    if dry_run:
        return {"path": str(out)}
    err = connection_error("\n".join(lines))
    if err:
        raise RuntimeError(err)
    uid_bytes = uid.read_bytes() if uid.exists() else b""
    page_bytes = out.read_bytes() if out.exists() else b""
    if blank(uid_bytes):
        for f in (out, uid):
            f.unlink(missing_ok=True)
        log("Diagnosis (shows the real state, please include it when asking for help):")
        rdp_on = False
        try:  # read-only: option bytes (read protection), start of firmware, UID area
            _, diag = run_openocd(exe, target, ["init", "reset halt", "flash probe 0", "stm32f1x options_read 0",
                                                "mdw 0x08001000 4", "mdw 0x1FFFF7E8 3"], log=log)
            rdp_on = any("read protection: on" in l.lower() for l in diag)
        except Exception as e:  # noqa
            log(f"(Diagnosis failed: {e})")
        if rdp_on:
            raise RuntimeError("Cannot read: read protection (RDP) is ON according to the option bytes. "
                               "The firmware apparently enables it at start-up. Nothing was saved.")
        raise RuntimeError("Cannot read: the UID is invalid (only 00 or FF), but read protection is not clearly on. "
                           "Address or chip may not match; see the diagnosis in the console. Nothing was saved.")
    if blank(page_bytes):
        log("Note: the user-data page contains only 00/FF - it is empty or was never written.")
    info = parse_userdata_page(page_bytes)
    info.update(path=str(out), uid=uid_bytes.hex(" ").upper())
    log(f"Saved: {out}")
    return info


# ----------------------------------------------------------------------------------------------- setup check
def check_setup() -> list[str]:
    """Checks that everything needed is there. Returns a list of problems (empty = OK)."""
    problems = []
    for rel in ("oocd/scripts/interface/stlink.cfg", "oocd/scripts/target/stm32f1x-nocpuid.cfg",
                "oocd/scripts/target/at32.cfg", "oocd/scripts/target/nrf51.cfg"):
        if not (ROOT / rel).exists():
            problems.append(f"Missing: {rel}")
    for d in ("bin", "bin_at32"):
        try:
            find_openocd(d)
        except FileNotFoundError as e:
            problems.append(str(e))
    if not (ROOT / "binaries").is_dir():
        problems.append("Folder 'binaries' missing: copy it from the ReFlasher folder (bootloader/ and firmware/)")
    else:
        missing = set()
        for b in PROFILES["models"].values():
            for it in b["items"].values():
                fw = it.get("drv") or it.get("default_fw")
                if fw and not (ROOT / "binaries/firmware" / fw).exists():
                    missing.add(f"binaries/firmware/{fw}")
                if it.get("bootloader") and not (ROOT / "binaries/bootloader" / it["bootloader"]).exists():
                    missing.add(f"binaries/bootloader/{it['bootloader']}")
        for f in ("nb_DRV.bin", "nb_DRV_AT32.bin", "mi_DRV.bin", "mi_DRV_GD32.bin"):
            if not (ROOT / "binaries/bootloader" / f).exists():
                missing.add(f"binaries/bootloader/{f}")
        for lay in PROFILES["ble"]["layouts"].values():
            for f in lay["bootloader"].values():
                if not (ROOT / "binaries/bootloader" / f).exists():
                    missing.add(f"binaries/bootloader/{f}")
            if not (ROOT / "binaries" / lay["uicr"]).exists():
                missing.add(f"binaries/{lay['uicr']}")
        for b in PROFILES["ble"]["models"].values():
            for it in b.values():
                if not (ROOT / "binaries/firmware" / it["fw"]).exists():
                    missing.add(f"binaries/firmware/{it['fw']}")
        problems += [f"Missing: {m}" for m in sorted(missing)]
    return problems


# ----------------------------------------------------------------------------------------------- BLE (nRF51822)
def validate_ble_name(name: str) -> None:
    if not name or len(name) > 13 or not all(32 <= ord(c) < 127 for c in name):
        raise ValueError("BLE name: 1 to 13 characters, plain ASCII only")


def build_ble_name_page(name: str, default_name: str | None = None) -> bytes:
    """24 bytes as in ReFlasher: header 55 AA (00 00 for the default name), 6 free bytes, name from offset 8."""
    validate_ble_name(name)
    page = bytearray(24)
    if name != default_name:
        page[0], page[1] = 0x55, 0xAA
    raw = name.encode("ascii")
    page[8:8 + len(raw)] = raw
    return bytes(page)


def ble_model_for(brand: str, model: str) -> str | None:
    """BLE model key that belongs to an ESC model (None if ReFlasher has no BLE file for it)."""
    item = PROFILES["models"][brand]["items"].get(model, {})
    fw = item.get("ble")
    if not fw or fw.endswith("?"):
        return None
    for key, it in PROFILES["ble"]["models"].get(brand, {}).items():
        if it["fw"] == fw:
            return key
    return None


def test_connection_ble(fast=False, dry_run=False, log=print, progress=_noprogress) -> dict:
    ble = PROFILES["ble"]
    progress(1, 1, "Probing the BLE module")
    exe = find_openocd("bin")
    rc, out = run_openocd(exe, ble["targets"]["fast" if fast else "normal"], ["init", "reset halt"],
                          dry_run=dry_run, log=log)
    if dry_run:
        return {}
    text = "\n".join(out)
    err = connection_error(text, "the BLE module")
    if err or rc != 0:
        raise RuntimeError(err or f"OpenOCD exit code {rc} (see the console)")
    info = parse_probe(text)
    log("Connection OK (nRF51 found)")
    return info


def flash_ble(brand: str, model: str, *, name=None, fast=False, dry_run=False, log=print,
              progress=_noprogress) -> dict:
    """Flashes the BLE module. Sequence as in ReFlasher: mass erase, then bootloader, firmware, name page, UICR,
    each written with OpenOCD's 'program ... verify'."""
    ble = PROFILES["ble"]
    item = ble["models"][brand][model]
    lay = ble["layouts"]["v2" if item.get("v2") else "v1"]
    exe = find_openocd("bin")
    target = ble["targets"]["fast" if fast else "normal"]
    boot = ROOT / "binaries/bootloader" / lay["bootloader"][brand]
    fw = ROOT / "binaries/firmware" / item["fw"]
    uicr = ROOT / "binaries" / lay["uicr"]
    for f in (boot, fw, uicr):
        if not f.exists():
            raise FileNotFoundError(f"Missing file: {f}")
    name = (name or ble["default_name"][brand]).strip()
    page = TEMP / "ble_user_data.bin"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(build_ble_name_page(name, ble["default_name"][brand]))
    log(f"Bootloader: {boot.name}   Firmware: {fw.name}   UICR: {uicr.name}   Name: {name}")

    progress(1, 2, "Checking the connection")
    if not dry_run:
        test_connection_ble(fast=fast, log=log)

    progress(2, 2, "Erasing and writing")
    cmds = ["init", "reset halt", "nrf51 mass_erase 0",
            f"program {tcl_path(boot)} 0x000000 verify",
            f"program {tcl_path(fw)} {lay['fw_addr']} verify",
            f"program {tcl_path(page)} {lay['name_addr']} verify",
            f"program {tcl_path(uicr)} {ble['uicr_address']} verify",
            "reset run"]
    rc, out = run_openocd(exe, target, cmds, dry_run=dry_run, log=log)
    text = "\n".join(out)
    # "checksum mismatch - attempting binary compare" is only OpenOCD switching compare method, not an error.
    # Real failures show "Verify Failed", "diff ..." lines or fewer than four "Verified OK".
    failed = ("Verify Failed" in text or "Programming Failed" in text
              or re.search(r"^diff \d+ address", text, re.M) is not None)
    if not dry_run and (text.count("Verified OK") < 4 or failed):
        raise RuntimeError(connection_error(text, "the BLE module") or
                           "BLE flashing failed (see the console). Try again, or with the original ReFlasher.")
    log("Done. Disconnect the ST-Link, reconnect the battery and switch the scooter on.")
    return {"name": name, "firmware": fw.name}


# ----------------------------------------------------------------------------------------------- wiring diagrams
DIAGRAM_DIR = ROOT / "diagrams"


def diagram_path(target: str, brand: str, model: str, chip: str | None = None) -> Path | None:
    entry = PROFILES.get("diagrams", {}).get(target, {}).get(brand, {}).get(model)
    if isinstance(entry, dict):
        entry = entry.get(chip) or entry.get("default")
    if not entry:
        return None
    p = DIAGRAM_DIR / entry
    return p if p.exists() else None
