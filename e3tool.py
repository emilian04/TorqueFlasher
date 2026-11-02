"""e3tool: backup, restore and serial-number (region) change for the Ninebot E3 / E3 Pro (AT32).

Same logic as the standalone E3 SN Tool (verified on a real E3: backup, SN read, SN change C -> K), but it uses
TorqueFlasher's OpenOCD setup (core.find_openocd / core.run_openocd) and supports dry runs.
Every write is checked by reading the flash back and comparing in Python; OpenOCD's own verify text is not
parsed ("checksum mismatch - attempting binary compare" is only a notice, not an error).
"""
from __future__ import annotations

import datetime
import hashlib
import pathlib

import core

DEFAULT_BACKUPS = core.ROOT / "e3_backups"
_backups_dir: pathlib.Path | None = None   # set by the front end (Settings)

FLASH_BASE, FLASH_SIZE = 0x08000000, 0x20000
PAGE_ADDR, PAGE_LEN = 0x0801C000, 2048
PAGES = (0x000, 0x400)                    # two redundant user-data pages
SN_OFF, SN_LEN = 0x20, 14

# 4th character of the SN (1TE?...) -> (model, region). User-reported; EU, CN, APAC unknown.
LETTERS = {"H": ("E3 Pro", "DE"), "F": ("E3 Pro", "US"), "C": ("E3", "DE"), "K": ("E3", "US")}
CHOICES = [("E3 Pro · Germany", "H"), ("E3 Pro · USA", "F"), ("E3 · Germany", "C"), ("E3 · USA", "K")]


def _noprogress(step, total, label):
    pass


def backups_dir() -> pathlib.Path:
    return _backups_dir or DEFAULT_BACKUPS


def set_backups_dir(path):
    global _backups_dir
    _backups_dir = pathlib.Path(path) if path else None


def work_dir() -> pathlib.Path:
    return backups_dir() / "work"


def stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique(path: pathlib.Path) -> pathlib.Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def describe(letter: str) -> str:
    m = LETTERS.get(letter)
    return f"{m[0]} {m[1]}" if m else "unknown"


def get_openocd():
    """(exe, target_cfg): the same AT32 OpenOCD that G2/F2/E2 Pro use."""
    return core._target_for("at32")


def run(cmds, dry_run=False, log=print) -> str:
    exe, target = get_openocd()
    rc, out = core.run_openocd(exe, target, cmds, dry_run=dry_run, log=log)
    text = "\n".join(out)
    err = core.connection_error(text)
    if err:
        raise RuntimeError(err.replace(core.POWER_HINT.lower(),
                                       "3.3 V from the ST-Link on the back pad, battery disconnected"))
    return text


def dump(addr, size, dest: pathlib.Path, dry_run=False, log=print) -> bytes:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise RuntimeError(f"Internal error: {dest.name} already exists, refusing to overwrite it.")
    run(["init", "halt", f"dump_image {core.tcl_path(dest)} 0x{addr:08X} {size}"], dry_run, log)
    if dry_run:
        return b""
    if not dest.exists() or dest.stat().st_size != size:
        raise RuntimeError("Read failed (file missing or wrong size).")
    return dest.read_bytes()


def write_and_verify(src: pathlib.Path, addr: int, dry_run=False, log=print):
    data = src.read_bytes()
    text = run(["init", "halt", "flash probe 0",
                f"flash write_image erase {core.tcl_path(src)} 0x{addr:08X}", "reset run"], dry_run, log)
    if dry_run:
        return
    if "wrote" not in text:
        raise RuntimeError("Write failed (see the console).")
    check = unique(work_dir() / f"verify_{stamp()}.bin")
    back = dump(addr, len(data), check, dry_run, log)
    check.unlink(missing_ok=True)
    if back != data:
        diffs = [i for i in range(len(data)) if back[i] != data[i]]
        raise RuntimeError(f"Verify failed: {len(diffs)} byte(s) differ (first at 0x{addr + diffs[0]:08X}). "
                           "If in doubt, restore the backup.")
    log(f"Verified: {len(data)} bytes match.")


# ------------------------------------------------------------------------------------------- connection check
def check_connection(dry_run=False, log=print, progress=_noprogress) -> dict:
    progress(1, 1, "Probing ST-Link and target")
    text = run(["init", "halt", "flash probe 0", "stm32f1x options_read 0"], dry_run, log)
    if dry_run:
        return {}
    info = core.parse_probe(text)
    if "cpu" not in info and "device_id" not in info:
        raise RuntimeError("No target information received (see the console).")
    if info.get("rdp") == "on":
        log("Warning: read protection is ON. A backup would only contain 00/FF. "
            "This tool never unlocks (unlocking erases the chip).")
    log("Connection OK")
    return info


# ------------------------------------------------------------------------------------------- backups
def do_backup(dry_run=False, log=print, progress=_noprogress) -> pathlib.Path:
    bdir = backups_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    dest = unique(bdir / f"e3_backup_{stamp()}.bin")
    progress(1, 1, "Reading the full flash (128 KB)")
    log(f"Reading the full flash (128 KB) into {dest.name} …")
    data = dump(FLASH_BASE, FLASH_SIZE, dest, dry_run, log)
    if dry_run:
        return dest
    if core.blank(data[:4096]) or core.blank(data[0x1C000:0x1C800]):
        dest.unlink()
        raise RuntimeError("The content is only 00 or FF: the chip is probably read-protected. This tool does "
                           "not unlock (unlocking erases the chip). Nothing was saved.")
    (bdir / (dest.name + ".sha256")).write_text(sha(data) + "\n")
    log(f"Backup saved: {dest}")
    log(f"SHA-256: {sha(data)}")
    return dest


def list_backups():
    """All *.bin files in the backup folder with a matching .sha256 next to them, newest first."""
    bdir = backups_dir()
    if not bdir.exists():
        return []
    files = [f for f in bdir.glob("*.bin") if (bdir / (f.name + ".sha256")).exists()]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def verified_data(f: pathlib.Path) -> bytes:
    data = f.read_bytes()
    if len(data) != FLASH_SIZE or core.blank(data[:4096]):
        raise RuntimeError("This file is not a valid 128 KB backup.")
    side = f.parent / (f.name + ".sha256")
    if not side.exists() or (side.read_text().split() or [""])[0].strip().lower() != sha(data):
        raise RuntimeError("Checksum mismatch: the backup file was modified or is damaged. Nothing was written.")
    return data


def do_restore(backup: pathlib.Path, dry_run=False, log=print, progress=_noprogress):
    progress(1, 2, "Checking the backup file")
    verified_data(backup)
    log(f"Backup file OK: {backup.name}")
    progress(2, 2, "Writing 128 KB and reading it back")
    write_and_verify(backup, FLASH_BASE, dry_run, log)
    log("Backup restored and verified. Disconnect the ST-Link, reconnect the battery and switch the scooter on.")


# ------------------------------------------------------------------------------------------- serial number
def read_sn(pages: bytes) -> bytes:
    sns = [pages[p + SN_OFF:p + SN_OFF + SN_LEN] for p in PAGES]
    for p, sn in zip(PAGES, sns):
        if not sn.startswith(b"1TE") or not all(32 < c < 127 for c in sn):
            raise RuntimeError(f"No serial number in the expected format (1TE…) at offset 0x{p + SN_OFF:X}: {sn!r}")
    if sns[0] != sns[1]:
        raise RuntimeError("The serial numbers in the two pages differ. Not changing anything.")
    return sns[0]


def patch(data: bytes, base: int, letter: str) -> bytes:
    out = bytearray(data)
    for p in PAGES:
        out[base + p + SN_OFF + 3] = ord(letter)
    return bytes(out)


def read_current_sn(dry_run=False, log=print, progress=_noprogress) -> bytes:
    progress(1, 1, "Reading the user-data pages")
    pages = dump(PAGE_ADDR, PAGE_LEN, unique(work_dir() / f"e3_pages_{stamp()}.bin"), dry_run, log)
    return b"1TE?0000000000" if dry_run else read_sn(pages)


def change_sn(letter: str, dry_run=False, log=print, progress=_noprogress):
    """Backup first, then read the pages, patch and write. Returns (backup_path, out_path, new_sn)."""
    progress(1, 4, "Backup (mandatory)")
    log("Step 1/4: backup (mandatory)")
    backup = do_backup(dry_run, log)
    progress(2, 4, "Reading the user-data pages")
    log("Step 2/4: reading the user-data pages")
    pages = dump(PAGE_ADDR, PAGE_LEN, unique(work_dir() / f"e3_pages_{stamp()}.bin"), dry_run, log)
    progress(3, 4, "Building the patched pages")
    log("Step 3/4: building the patched pages")
    out = unique(work_dir() / f"e3_pages_new_{stamp()}.bin")
    if dry_run:
        new_sn = f"1TE{letter}0000000000".encode()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(bytes(PAGE_LEN))
    else:
        old = read_sn(pages)
        new = patch(pages, 0, letter)
        out.write_bytes(new)
        new_sn = read_sn(new)
        log(f"Old SN: {old.decode()}   New SN: {new_sn.decode()}")
    progress(4, 4, "Writing and verifying")
    log("Step 4/4: writing and verifying")
    write_and_verify(out, PAGE_ADDR, dry_run, log)
    log("Written and verified. Disconnect the ST-Link, reconnect the battery and switch the scooter on.")
    return backup, out, new_sn


def full_patched_file(backup: pathlib.Path, letter: str) -> pathlib.Path:
    """Offline: writes a patched copy of a full backup. Nothing is flashed."""
    data = verified_data(backup)
    base = PAGE_ADDR - FLASH_BASE
    read_sn(data[base:base + PAGE_LEN])
    out = unique(backup.parent / (backup.stem + f"_patched_{letter}.bin"))
    out.write_bytes(patch(data, base, letter))
    return out


def sn_of_backup(backup: pathlib.Path) -> bytes:
    data = verified_data(backup)
    base = PAGE_ADDR - FLASH_BASE
    return read_sn(data[base:base + PAGE_LEN])
