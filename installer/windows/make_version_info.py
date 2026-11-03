"""Writes version_info.txt (file properties of TorqueFlasher.exe) from core.APP_VERSION."""
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
import core  # noqa: E402

nums = tuple(int(x) for x in core.APP_VERSION.split(".")) + (0,)
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'emilian04'),
      StringStruct('FileDescription', 'TorqueFlasher'),
      StringStruct('FileVersion', '{core.APP_VERSION}'),
      StringStruct('InternalName', 'TorqueFlasher'),
      StringStruct('LegalCopyright', 'MIT License, emilian04'),
      StringStruct('OriginalFilename', 'TorqueFlasher.exe'),
      StringStruct('ProductName', 'TorqueFlasher'),
      StringStruct('ProductVersion', '{core.APP_VERSION}-{core.APP_STAGE.lower()}')])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"""
(pathlib.Path(__file__).parent / "version_info.txt").write_text(text, encoding="utf-8")
print(f"{core.APP_VERSION}-{core.APP_STAGE.lower()}")
