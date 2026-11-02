#!/usr/bin/env bash
# Starts TorqueFlasher on Linux.
cd "$(dirname "$0")" || exit 1
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "Tkinter is missing. Run ./setup_linux.sh or install it:"
    echo "  Debian/Ubuntu: sudo apt install python3-tk   Fedora: sudo dnf install python3-tkinter   Arch: sudo pacman -S tk"
    exit 1
fi
exec python3 gui.py "$@"
