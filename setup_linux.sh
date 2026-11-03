#!/usr/bin/env bash
# Linux setup: OpenOCD, Python/Tkinter and ST-Link USB permissions.
set -e
cd "$(dirname "$0")"
echo "== TorqueFlasher Linux setup =="
if command -v apt-get >/dev/null; then
  sudo apt-get update && sudo apt-get install -y openocd python3 python3-tk
elif command -v dnf >/dev/null; then
  sudo dnf install -y openocd python3 python3-tkinter
elif command -v pacman >/dev/null; then
  sudo pacman -S --needed openocd python tk
else
  echo "Unknown package manager: install openocd, python3 and tkinter yourself."
fi
sudo cp linux/99-stlink.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
echo "Done. Unplug and re-plug the ST-Link, then build the AT32 OpenOCD (bash build_openocd_at32.sh) and run bash start.sh"
