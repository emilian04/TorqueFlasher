#!/usr/bin/env bash
# Builds installer/linux/Output/TorqueFlasher-<version>-Linux-x86_64.AppImage
#
# Run it on Ubuntu 22.04 (x86_64), e.g. the GitHub runner "ubuntu-22.04": an AppImage runs on the distribution it
# was built on and newer ones, so an older base reaches more users. Needs internet and about 10 minutes.
#
# Contents: TorqueFlasher (PyInstaller, with Python and Tk), OpenOCD 0.12.0 (STM32/GD32/nRF51) and the AT32 fork
# of OpenOCD (encryptize/openocd-at32), both built here with only the ST-Link driver, plus libusb.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
B="$HERE/build"
OUT="$HERE/Output"
OPENOCD_REPO="https://github.com/openocd-org/openocd.git"
OPENOCD_REF="v0.12.0"
AT32_REPO="https://github.com/encryptize/openocd-at32.git"
AT32_COMMIT="01a6662400525ba7e3a799b26f9335d0d05f1a1f"
APPIMAGETOOL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
RUNTIME="https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "== Packages =="
$SUDO apt-get update -q
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
  git build-essential autoconf automake libtool pkg-config texinfo libusb-1.0-0-dev \
  python3 python3-dev python3-venv python3-tk patchelf file wget ca-certificates desktop-file-utils
mkdir -p "$B/oocd" "$OUT"

build_openocd() {  # name repo ref-or-commit
  local name="$1" repo="$2" ref="$3" src="$B/src-$1" stage="$B/stage-$1"
  if [ -x "$B/oocd/$name/openocd" ]; then echo "(OpenOCD $name already built)"; return; fi
  echo "== OpenOCD: $name =="
  rm -rf "$src" "$stage"
  git init -q "$src"
  git -C "$src" remote add origin "$repo"
  git -C "$src" fetch -q --depth 1 origin "$ref"
  git -C "$src" checkout -q FETCH_HEAD
  # Only jimtcl is needed; git2cl (ChangeLog) and libjaylink (J-Link) are skipped.
  git -C "$src" submodule init
  git -C "$src" config submodule.tools/git2cl.update none || true
  git -C "$src" config submodule.src/jtag/drivers/libjaylink.update none || true
  git -C "$src" submodule update --depth 1 jimtcl
  (cd "$src" && (./bootstrap nosubmodule || ./bootstrap) \
     && ./configure --prefix="$stage" --enable-stlink --disable-jlink --disable-werror \
          --disable-doxygen-html --disable-doxygen-pdf \
     && make -j"$(nproc)" && make install)
  mkdir -p "$B/oocd/$name"
  install -m 755 "$stage/bin/openocd" "$B/oocd/$name/openocd"
  strip "$B/oocd/$name/openocd"
  # bundle libusb next to it and let openocd find it there
  local libusb
  libusb="$(ldd "$B/oocd/$name/openocd" | awk '/libusb-1.0.so/ {print $3}')"
  cp -L "$libusb" "$B/oocd/$name/"
  patchelf --set-rpath '$ORIGIN' "$B/oocd/$name/openocd"
  "$B/oocd/$name/openocd" --version 2>&1 | head -1
}
build_openocd bin "$OPENOCD_REPO" "$OPENOCD_REF"
build_openocd bin_at32 "$AT32_REPO" "$AT32_COMMIT"

echo "== PyInstaller =="
python3 -m venv "$B/venv"
"$B/venv/bin/pip" install -q --upgrade pip pyinstaller
VER="$(cd "$ROOT" && "$B/venv/bin/python" -c 'import core; print(f"{core.APP_VERSION}-{core.APP_STAGE.lower()}")')"
(cd "$ROOT" && TF_LINUX_OOCD="$B/oocd" "$B/venv/bin/pyinstaller" --noconfirm --clean \
   --distpath "$B/dist" --workpath "$B/pyinstaller" torqueflasher.spec)

echo "== AppDir =="
APPDIR="$B/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/torqueflasher" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$B/dist/TorqueFlasher/." "$APPDIR/usr/lib/torqueflasher/"
install -m 755 "$HERE/AppRun" "$APPDIR/AppRun"
install -m 644 "$HERE/torqueflasher.desktop" "$APPDIR/torqueflasher.desktop"
install -m 644 "$HERE/torqueflasher.desktop" "$APPDIR/usr/share/applications/torqueflasher.desktop"
install -m 644 "$ROOT/assets/icon-256.png" "$APPDIR/torqueflasher.png"
install -m 644 "$ROOT/assets/icon-256.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/torqueflasher.png"
ln -sf torqueflasher.png "$APPDIR/.DirIcon"
desktop-file-validate "$APPDIR/torqueflasher.desktop"

echo "== appimagetool =="
[ -x "$B/appimagetool" ] || { wget -q -O "$B/appimagetool" "$APPIMAGETOOL"; chmod +x "$B/appimagetool"; }
[ -s "$B/runtime-x86_64" ] || wget -q -O "$B/runtime-x86_64" "$RUNTIME"
FILE="$OUT/TorqueFlasher-$VER-Linux-x86_64.AppImage"
rm -f "$FILE"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$B/appimagetool" --no-appstream --runtime-file "$B/runtime-x86_64" \
  "$APPDIR" "$FILE"
chmod +x "$FILE"
echo
echo "Done: $FILE"
