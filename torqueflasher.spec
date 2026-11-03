# PyInstaller spec for TorqueFlasher (Windows and Linux).
#   Windows: installer\windows\build.bat      Linux: installer/linux/build_appimage.sh
# Result: dist/TorqueFlasher/ with TorqueFlasher(.exe); data files (profiles, binaries, oocd, ...) in _internal/.
import os
import sys
from pathlib import Path

root = Path(SPECPATH)
win = sys.platform == "win32"

datas = [(str(root / f), ".") for f in ("profiles.json", "LICENSE", "THIRD_PARTY.md", "README.md")]
datas += [(str(root / d), d) for d in ("binaries", "diagrams", "assets", "linux", "oocd/scripts")]
if win:  # OpenOCD for Windows from the repository (as shipped with ReFlasher)
    datas += [(str(root / "oocd/bin"), "oocd/bin"), (str(root / "oocd/bin_at32"), "oocd/bin_at32")]
else:    # OpenOCD for Linux, built by installer/linux/build_appimage.sh
    oocd = Path(os.environ.get("TF_LINUX_OOCD", root / "installer/linux/build/oocd"))
    if not (oocd / "bin/openocd").exists():
        raise SystemExit(f"Linux OpenOCD missing in {oocd}: run installer/linux/build_appimage.sh")
    datas += [(str(oocd / "bin"), "oocd/bin"), (str(oocd / "bin_at32"), "oocd/bin_at32")]

a = Analysis(
    [str(root / "gui.py")],
    pathex=[str(root)],
    datas=datas,
    excludes=["numpy", "PIL", "matplotlib", "pytest", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TorqueFlasher",
    console=False,
    icon=str(root / "assets/icon.ico") if win else None,
    version=str(root / "installer/windows/version_info.txt") if win else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="TorqueFlasher")
