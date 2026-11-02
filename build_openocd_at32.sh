#!/usr/bin/env bash
# Builds the AT32-capable OpenOCD fork (github.com/encryptize/openocd-at32) into oocd/bin_at32/openocd.
# Needs internet access and a few minutes.
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
echo "== Dependencies =="
if command -v apt-get >/dev/null; then
  sudo apt-get update
  sudo apt-get install -y git build-essential autoconf automake libtool pkg-config texinfo libusb-1.0-0-dev libhidapi-dev
elif command -v dnf >/dev/null; then
  sudo dnf install -y git gcc make autoconf automake libtool pkgconf texinfo libusb1-devel hidapi-devel
elif command -v pacman >/dev/null; then
  sudo pacman -S --needed git base-devel libusb hidapi texinfo
else
  echo "Unknown package manager: install git, gcc, make, autotools, libusb-1.0-dev and texinfo yourself."
fi
echo "== Getting the source =="
mkdir -p build && cd build
[ -d openocd-at32 ] || git clone https://github.com/encryptize/openocd-at32.git
cd openocd-at32
# Only the needed submodule (jimtcl). git2cl (only for the ChangeLog) and libjaylink (only J-Link)
# are skipped: their servers are often unreachable and only ST-Link is needed.
git submodule init
git config submodule.tools/git2cl.update none
git config submodule.src/jtag/drivers/libjaylink.update none
git submodule update jimtcl
echo "== Building =="
./bootstrap nosubmodule || ./bootstrap
./configure --enable-stlink --disable-jlink --disable-werror --prefix="$ROOT/build/install"
make -j"$(nproc)"
make install
mkdir -p "$ROOT/oocd/bin_at32"
cp "$ROOT/build/install/bin/openocd" "$ROOT/oocd/bin_at32/openocd"
echo "== Done =="
echo "Test (with an STM32/AT32 connected):"
echo "  $ROOT/oocd/bin_at32/openocd -s $ROOT/oocd/scripts -f interface/stlink.cfg -f target/at32.cfg -c 'init; flash probe 0; exit'"
