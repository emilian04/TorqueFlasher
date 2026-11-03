#!/usr/bin/env python3
"""TorqueFlasher: flash the ESC (DRV) and BLE module of Ninebot / Xiaomi scooters over an ST-Link, plus backup,
restore and serial-number change for the Ninebot E3 / E3 Pro. Windows and Linux (macOS probably, untested).

Start:  python3 gui.py   (Windows: double-click start.bat)
"""
from __future__ import annotations

import collections
import datetime
import json
import os
import pathlib
import platform
import queue
import re
import shutil
import subprocess
import threading
import time
import traceback
import tkinter as tk
import webbrowser
from tkinter import filedialog, ttk

import core
import e3tool
import tf_ui
from countdown import Countdown
from tf_ui import (AMBER, BG, CONSOLE_BG, DANGER, DIM, ELEV, INK, LINE, LINE2, MUT, OK, PANEL, PANEL2, STATUS_BG,
                   TXT, Badge, Button, Card, Chip, Dialog, FillPanel, Fonts, IconButton, Led, Link, Pill, ProgressBar,
                   RadioCard, RoundField, RoundPanel, Steps, Swatches, T, Tabs, Toggle, bind_all_children, center_on,
                   dark_titlebar, elapsed, ensure_dir, entry, eyebrow, fit, flow, icon_dir, mix, open_path,
                   set_window_icon, short, tail)

CHIP_LABEL = {"stm32": "STM32", "at32": "AT32", "gd32": "GD32", "auto": "Auto"}
BATTERY_NOTE = "Scooter battery disconnected · the ST-Link powers the board"
WIRING_NOTE = ("Disconnect the scooter battery; the ST-Link powers the board. Connect GND, SWDIO, SWCLK and the "
               "supply as shown in the diagram. Never put 5 V on the 3.3 V pad.")
HINT_DRV = "Battery disconnected, ST-Link on the controller? Then press start."
HINT_BLE = "Dashboard connected to the main cable, ST-Link on the BLE pads? Then press start."

ESC_ACTIONS = [
    dict(id="check", tab="Check", title="Check connection", start="Check connection",
         desc="Probes the ST-Link and the controller: chip, flash size, read protection. On an unlocked chip it "
              "also reads serial number and mileage. Writes nothing.",
         plan=["Detect the chip", "Probe flash and read protection", "Read serial number and mileage"]),
    dict(id="flash", tab="Flash ESC", title="Flash ESC", start="Flash ESC",
         desc="Erases the controller and writes bootloader, firmware and a new user-data page (serial number, "
              "mileage), then reads everything back and compares it.",
         plan=["Connect", "Unlock · mass erase · read UID", "Write bootloader, firmware, user data",
               "Read back and compare"]),
    dict(id="ble_check", tab="BLE check", title="Check BLE connection", start="Check BLE", ble=True,
         unavailable="No BLE file for this scooter",
         desc="Probes the BLE module (nRF51822) over its own SWD pads. Writes nothing.",
         plan=["Probe the nRF51"]),
    dict(id="ble_flash", tab="BLE flash", title="Flash BLE", start="Flash BLE", ble=True,
         unavailable="No BLE file for this scooter",
         desc="Erases the BLE module and writes bootloader, firmware, Bluetooth name and UICR, each verified.",
         plan=["Connect", "Erase · write · verify"]),
]
E3_ACTIONS = [
    dict(id="e3_check", tab="Check", title="Check connection", start="Check connection",
         desc="Probes the ST-Link and the controller: CPU, device id, flash size, read protection. Writes nothing.",
         plan=["Probe ST-Link and controller"]),
    dict(id="e3_read", tab="Read SN", title="Read serial number", start="Read serial number",
         desc="Reads both user-data pages and shows the serial number and region. Writes nothing.",
         plan=["Read the user-data pages"]),
    dict(id="e3_backup", tab="Backup", title="Backup", start="Start backup",
         desc="Reads the complete 128 KB flash into the E3 backup folder, with a SHA-256 file next to it.",
         plan=["Read the full flash (128 KB)"]),
    dict(id="e3_change", tab="Change SN", title="Change serial number", start="Change serial number",
         desc="Makes a backup, then rewrites the 4th character of the serial number in both user-data pages "
              "and verifies them.",
         plan=["Read the current serial number", "Backup (mandatory)", "Read the user-data pages",
               "Build the patched pages", "Write and verify"]),
    dict(id="e3_restore", tab="Restore", title="Restore backup", start="Restore backup",
         desc="Writes a full E3 backup back to the scooter and verifies it. Only backups with a matching "
              "checksum are listed.",
         plan=["Check the backup file", "Write 128 KB and read it back"]),
    dict(id="e3_patched", tab="Patch file", title="Make patched dump", start="Create file", offline=True,
         desc="Creates a copy of an E3 backup with a different region character. Nothing is written to the "
              "scooter.",
         plan=["Create the patched file"]),
]
ALL_ACTIONS = {a["id"]: a for a in ESC_ACTIONS + E3_ACTIONS}
STARTUP_WARNING = True   # the tests switch it off
WARNING_POINTS = [
    ("A failed flash stops the scooter",
     "TorqueFlasher erases and rewrites the controller of your scooter. After an interrupted run or a wrong file "
     "the scooter does not work until the controller is flashed again successfully."),
    ("Battery disconnected",
     "When flashing the ESC, always disconnect the scooter battery; the ST-Link powers the board. Wire it as shown "
     "in the diagram."),
    ("Warranty and road use",
     "Changing the firmware, serial number or region can void the warranty and the scooter's road approval. "
     "Only ride it where that is allowed."),
    ("Beta software",
     "Most scooters are not tested on real hardware yet. You use TorqueFlasher at your own risk, without any "
     "warranty (MIT license)."),
]


# ----------------------------------------------------------------------------------------------- settings
def settings_file() -> pathlib.Path:
    return core.config_dir() / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_file().read_text(encoding="utf-8"))
    except Exception:  # noqa
        return {}


def save_settings(d: dict) -> None:
    try:
        f = settings_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:  # noqa
        pass


# ----------------------------------------------------------------------------------------------- models / chips
def models():
    """[(brand, key, item)] for the picker, E3 appended to Ninebot."""
    out = []
    for brand, prof in core.PROFILES["models"].items():
        for key, item in prof["items"].items():
            out.append((brand, key, item))
        if brand == "ninebot":
            e3 = core.PROFILES["e3"]
            out.append((brand, "e3", {"name": e3["name"], "short": e3.get("short"), "chips": ["at32"],
                                      "default_chip": "at32", "tested": e3.get("tested")}))
    return out


def item_for(brand, model):
    for b, k, it in models():
        if b == brand and k == model:
            return it
    return None


def chip_mode(item) -> str:
    """fixed: one possible chip | choose: STM32 or GD32, picked by the user | auto: STM32/AT32, detected."""
    chips = item.get("chips", [])
    if item.get("variant") or len(chips) <= 1:
        return "fixed"
    return "choose" if "gd32" in chips else "auto"


def default_chip(item) -> str:
    mode = chip_mode(item)
    if mode == "fixed":
        return item.get("variant") or (item.get("chips") or ["stm32"])[0]
    return item.get("default_chip", "stm32") if mode == "choose" else "auto"


def chip_valid(item, chip) -> bool:
    mode = chip_mode(item)
    if mode == "fixed":
        return chip == default_chip(item)
    return chip in item.get("chips", []) or (mode == "auto" and chip == "auto")


def draw_wordmark(c: tk.Canvas, font, x, y, accent=None):
    c.create_text(x, y, text="TORQUE", fill=TXT, font=font, anchor="w")
    x2 = x + font.measure("TORQUE")
    c.create_text(x2, y, text="FLASHER", fill=accent or T.ACCENT, font=font, anchor="w")
    return x2 + font.measure("FLASHER")


# ----------------------------------------------------------------------------------------------- dialogs
class ScooterPicker(tk.Toplevel):
    """Models grouped by series, a search over both brands, and the last used scooters."""
    COL_W = 404

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Choose scooter")
        self.configure(bg=PANEL, highlightthickness=1, highlightbackground=LINE2)
        dark_titlebar(self)
        self.resizable(False, False)
        self.transient(app)
        self.brand = tk.StringVar(value=app.brand)   # the selection
        self.model = tk.StringVar(value=app.model)
        self.tab = app.brand                         # brand shown while not searching
        self.scope = "all"                           # brand filter while searching
        self.query = tk.StringVar()
        self.focus_i, self.keys_used = 0, False
        self.visible: list = []
        self.chips: dict = {}
        self._build()
        self._fix_height()
        self.render()
        self.query.trace_add("write", lambda *a: self._on_query())
        for seq, fn in (("<Escape>", self._escape), ("<Return>", self._enter), ("<KP_Enter>", self._enter),
                        ("<Down>", lambda e: self._move(1)), ("<Up>", lambda e: self._move(-1))):
            self.bind(seq, fn)
        self.protocol("WM_DELETE_WINDOW", lambda: self.close(False))
        center_on(self, app)
        self.wait_visibility()
        self.grab_set()
        self.search.focus_set()

    # ---- layout
    def _build(self):
        f = self.app.f
        body = tk.Frame(self, bg=PANEL, padx=26, pady=22)
        body.pack(fill="both", expand=True)
        head = tk.Frame(body, bg=PANEL)
        head.pack(fill="x")
        left = tk.Frame(head, bg=PANEL)
        left.pack(side="left")
        eyebrow(left, "Step 1" if self.app.first_run else "Scooter", f, PANEL).pack(anchor="w")
        tk.Label(left, text="Choose your scooter", bg=PANEL, fg=TXT, font=f.h1).pack(anchor="w")
        self.tabs = Tabs(head, f, self._tab, bg=PANEL, height=36, pad=18)
        self.tabs.pack(side="right", anchor="s")

        self.sfield = RoundField(body, lambda p: entry(p, self.query, f, width=40, font=f.search), height=46,
                                 radius=22, padx=20, pady=11)
        self.sfield.pack(fill="x", pady=(18, 0))
        self.search = self.sfield.child
        self.placeholder = tk.Label(self.sfield, text="Search model, e.g. G30, F2, M365", bg=BG, fg=MUT,
                                    font=f.search, cursor="xterm")
        self.placeholder.bind("<Button-1>", lambda e: self.search.focus_set())
        self.clear_hint = Pill(self.sfield, "ESC · CLEAR", f.eyebrow, BG)

        self.recent_row = tk.Frame(body, bg=PANEL)
        self.recent_row.pack(fill="x", pady=(14, 0))
        self._render_recent()

        self.res = RoundPanel(body, PANEL, fill=PANEL, outline=PANEL, radius=0, pad=6, valign="top")
        self.res.configure(width=2 * self.COL_W + 26 + 12, height=300)
        self.res.pack(fill="x", pady=(12, 0))

        foot = tk.Frame(body, bg=PANEL)
        foot.pack(fill="x", pady=(16, 0))
        self.foot_dot = tk.Canvas(foot, width=10, height=10, bg=PANEL, highlightthickness=0)
        self.foot_dot.create_oval(1, 1, 9, 9, fill=OK, outline="")
        self.foot_dot.pack(side="left")
        self.foot_note = tk.Label(foot, text="", bg=PANEL, fg=MUT, font=f.small)
        self.foot_note.pack(side="left", padx=(8, 0))
        Button(foot, "Done", lambda: self.close(True), f, kind="primary", bg=PANEL, small=True, height=36).pack(
            side="right")
        Button(foot, "Cancel", lambda: self.close(False), f, kind="ghost", bg=PANEL, small=True, height=36).pack(
            side="right", padx=8)

    def _render_recent(self):
        f = self.app.f
        eyebrow(self.recent_row, "Recent", f, PANEL).pack(side="left", padx=(0, 12))
        rec = [(b, k) for b, k in self.app.recent() if item_for(b, k)]
        if not rec:
            tk.Label(self.recent_row, text="your last scooters show up here", bg=PANEL, fg=MUT,
                     font=f.small).pack(side="left", pady=8)
            return
        for b, k in rec:
            it = item_for(b, k)
            Chip(self.recent_row, f, it.get("short") or it["name"], lambda b=b, k=k: self.pick(b, k, close=True),
                 sub=b.capitalize() if b != self.app.brand else None, small=True).pack(side="left", padx=(0, 8))

    def _fix_height(self):
        """Same height for both brands, so the dialog does not jump when switching or searching."""
        h = 0
        for b in ("xiaomi", "ninebot"):
            self.tab = b
            self.render()
            self.update_idletasks()
            h = max(h, self.res.inner.winfo_reqheight())
        self.res.configure(height=h + 16)
        self.tab = self.app.brand

    # ---- content
    def render(self):
        q = self.query.get().strip()
        if q:
            self.tabs.set([("all", "All results", True, ""), ("ninebot", "Ninebot", True, ""),
                           ("xiaomi", "Xiaomi", True, "")], self.scope)
            self.placeholder.place_forget()
            self.clear_hint.place(relx=1, x=-14, rely=0.5, anchor="e")
        else:
            self.tabs.set([("ninebot", "Ninebot", True, ""), ("xiaomi", "Xiaomi", True, "")], self.tab)
            self.placeholder.place(x=20, rely=0.5, anchor="w")
            self.clear_hint.place_forget()
        inner = self.res.inner
        for w in inner.winfo_children():
            w.destroy()
        groups = self._groups(q)
        self.visible = [(b, k) for _, items in groups for b, k, _, _ in items]
        self.focus_i = min(self.focus_i, max(0, len(self.visible) - 1))
        self.chips = {}
        if not groups:
            tk.Label(inner, text=f"No scooter matches “{q}”.", bg=PANEL, fg=DIM, font=self.app.f.body).pack(
                anchor="w", pady=4)
        else:
            cols = [tk.Frame(inner, bg=PANEL) for _ in range(2)]
            cols[0].pack(side="left", anchor="n")
            cols[1].pack(side="left", anchor="n", padx=(26, 0))
            half = (len(groups) + 1) // 2
            for i, (title, items) in enumerate(groups):
                g = tk.Frame(cols[0 if i < half else 1], bg=PANEL)
                g.pack(anchor="w", pady=(0 if i in (0, half) else 16, 0))
                eyebrow(g, title, self.app.f, PANEL).pack(anchor="w", pady=(0, 9))
                flow(g, [lambda row, b=b, k=k, it=it, m=m: self._chip(row, b, k, it, m) for b, k, it, m in items],
                     self.COL_W)
        n = len(self.visible)
        if q:
            self.foot_dot.pack_forget()
            self.foot_note.configure(text=f"{n} match{'' if n == 1 else 'es'} · ↑ ↓ to move, Enter to choose")
        else:
            if not self.foot_dot.winfo_manager():
                self.foot_dot.pack(side="left", before=self.foot_note)
            self.foot_note.configure(text="tested on real hardware")
        self.res.scroll_top()
        self.res.after_idle(self.res.redraw)

    def _chip(self, row, b, k, it, match):
        sel = (b, k) == (self.brand.get(), self.model.get())
        focused = (self.keys_used or self.query.get().strip()) and self.visible and \
            self.visible[self.focus_i] == (b, k)
        c = Chip(row, self.app.f, it.get("short") or it["name"], lambda: self.pick(b, k), match=match,
                 dot=bool(it.get("tested")), state="selected" if sel else "focus" if focused else "normal",
                 on_double=lambda: self.pick(b, k, close=True))
        self.chips[(b, k)] = c
        return c

    def _groups(self, q):
        brands = [self.tab] if not q else (["ninebot", "xiaomi"] if self.scope == "all" else [self.scope])
        out = []
        for b in brands:
            for title, keys in core.PROFILES["picker_groups"][b]:
                items = []
                for k in keys:
                    it = item_for(b, k)
                    m = self._match(q, k, it) if (it and q) else None
                    if it and m is not False:
                        items.append((b, k, it, m or None))
                if items:
                    out.append((f"{b.capitalize()} · {title}" if q else title, items))
        if q:  # best matches first: whole word ("f2" -> F2 / Plus / Pro), then word start (F20), then anywhere
            out.sort(key=lambda grp: min(self._score(q, it) for _b, _k, it, _m in grp[1]))
        return out

    @staticmethod
    def _score(q, it):
        name, ql = (it.get("short") or it["name"]).lower(), re.escape(q.lower())
        if re.search(r"(?<![a-z0-9])" + ql + r"(?![a-z0-9])", name):
            return 0
        return 1 if re.search(r"(?<![a-z0-9])" + ql, name) else 2

    @staticmethod
    def _match(q, key, it):
        """False: no match. (start, end): q found in the short name (shown highlighted). (): other match."""
        short_name = it.get("short") or it["name"]
        i = short_name.lower().find(q.lower())
        if i >= 0:
            return i, i + len(q)
        squash = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())  # noqa: E731
        qs = squash(q)
        if qs and (qs in squash(short_name) or qs in key.lower() or (len(qs) >= 3 and qs in squash(it["name"]))):
            return ()
        return False

    # ---- input
    def pick(self, b, k, close=False):
        self.brand.set(b)
        self.model.set(k)
        if close:
            self.close(True)
            return
        if not self.query.get().strip():
            self.tab = b
        if (b, k) in self.visible:
            self.focus_i = self.visible.index((b, k))
        self.render()

    def _tab(self, v):
        if self.query.get().strip():
            self.scope, self.focus_i = v, 0
        else:
            self.tab = v
        self.render()

    def set_brand(self, b):  # show a brand (kept for callers and tests)
        self._tab(b)

    def on_model(self):
        self.render()

    def _on_query(self):
        self.focus_i = 0
        self.render()

    def _move(self, d):
        if not self.visible:
            return
        if not self.keys_used and not self.query.get().strip():
            cur = (self.brand.get(), self.model.get())
            self.focus_i = self.visible.index(cur) if cur in self.visible else 0
        else:
            self.focus_i = (self.focus_i + d) % len(self.visible)
        self.keys_used = True
        self.render()

    def _enter(self, _e=None):
        if self.visible and (self.keys_used or self.query.get().strip()):
            self.pick(*self.visible[self.focus_i], close=True)
        else:
            self.close(True)

    def _escape(self, _e=None):
        if self.query.get():
            self.query.set("")
        else:
            self.close(False)

    def close(self, apply):
        self.res._wheel(False)
        self.grab_release()
        self.destroy()
        self.app.first_run = False
        if apply:
            self.app.set_scooter(self.brand.get(), self.model.get())


class SettingsDialog(tk.Toplevel):
    """Settings and Info, as two pages of one dialog."""

    def __init__(self, app, page="settings"):
        super().__init__(app)
        self.app, self.page = app, page
        self.title("Settings" if page == "settings" else f"About {core.APP_NAME}")
        self.configure(bg=PANEL, highlightthickness=1, highlightbackground=LINE2)
        dark_titlebar(self)
        self.resizable(False, False)
        self.transient(app)
        self.body = tk.Frame(self, bg=PANEL, padx=26, pady=20)
        self.body.pack(fill="both", expand=True)
        self.render()
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        center_on(self, app)
        self.wait_visibility()
        self.grab_set()

    # ---- helpers
    def _section(self, title, links=()):
        f = self.app.f
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x", pady=(16, 6))
        eyebrow(row, title, f, PANEL).pack(side="left")
        for label, cmd in reversed(links):
            Link(row, label, cmd, f, PANEL).pack(side="right", padx=(14, 0))
        return row

    def _path(self, path):
        RoundField(self.body, lambda p: tk.Label(p, text=short(path, 64), bg=BG, fg=TXT, font=self.app.f.mono,
                                                 anchor="w")).pack(fill="x", pady=(0, 4))

    def _note(self, text, color=MUT):
        tk.Label(self.body, text=text, bg=PANEL, fg=color, font=self.app.f.small, anchor="w", justify="left",
                 wraplength=520).pack(fill="x")

    def render(self):
        f = self.app.f
        for w in self.body.winfo_children():
            w.destroy()
        head = tk.Frame(self.body, bg=PANEL)
        head.pack(fill="x")
        tabs = Tabs(head, f, self.set_page, bg=PANEL, height=34, pad=18)
        tabs.set([("settings", "Settings", True, ""), ("info", "Info", True, "")], self.page)
        tabs.pack(side="left")
        if self.page == "settings":
            self._settings()
        else:
            self._info()
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x", pady=(22, 0))
        Button(row, "Done", self.close, f, kind="primary", bg=PANEL, small=True, height=34).pack(side="right")

    def set_page(self, page):
        if page != self.page:
            self.page = page
            self.title("Settings" if page == "settings" else f"About {core.APP_NAME}")
            self.render()

    # ---- settings page
    def _settings(self):
        app, f = self.app, self.app.f
        self._section("Accent color")
        Swatches(self.body, f, self.pick_accent, bg=PANEL).pack(anchor="w")

        self._section("Dry run")
        Toggle(self.body, "Show the OpenOCD commands, write nothing", app.dry, f, bg=PANEL,
               command=app.on_dry_changed).pack(anchor="w")

        probs = core.check_setup()
        self._section("Program files", [("Open", lambda: open_path(core.ROOT))])
        self._path(core.ROOT)
        if probs:
            r = tk.Frame(self.body, bg=PANEL)
            r.pack(fill="x")
            tk.Label(r, text=f"{len(probs)} problem(s): {probs[0]}", bg=PANEL, fg=AMBER, font=f.small,
                     wraplength=420, justify="left").pack(side="left")
            Link(r, "Show all", self.show_problems, f, PANEL).pack(side="right")
        else:
            self._note("All bootloader, firmware and OpenOCD files found.", OK)

        self._section("E3 backup folder", [("Browse…", self.browse_e3), ("Default", self.reset_e3),
                                           ("Open", lambda: open_path(ensure_dir(e3tool.backups_dir())))])
        self._path(e3tool.backups_dir())
        self._note("E3 backups are saved here; Restore lists the backups in this folder.")

        self._section("Data folder", [("Browse…", self.browse_data), ("Default", self.reset_data),
                                      ("Open", lambda: open_path(ensure_dir(core.DATA)))])
        self._path(core.DATA)
        self._note("dumps/ (serial number + mileage from Check connection), logs/ (full OpenOCD output) and, unless "
                   "set above, e3_backups/.")

    def pick_accent(self, name):
        self.app.set_accent(name)
        self.render()

    def show_problems(self):
        for p in core.check_setup():
            self.app.console_line("SETUP: " + p, "warn")

    def browse_e3(self):
        p = filedialog.askdirectory(parent=self, title="E3 backup folder", initialdir=str(e3tool.backups_dir()))
        if p:
            e3tool.set_backups_dir(p)
            self.app.cfg["e3_backups"] = p
            self.app.save_cfg()
            self.app.backup_sel = None
            self.render()

    def browse_data(self):
        p = filedialog.askdirectory(parent=self, title="Data folder", initialdir=str(core.DATA))
        if p:
            self.app.cfg["data_dir"] = p
            self.app.save_cfg()
            core.set_data_dir(p)
            self.app.backup_sel = None
            self.render()

    def reset_data(self):
        self.app.cfg.pop("data_dir", None)
        self.app.save_cfg()
        core.set_data_dir(core.resolve_data_dir())
        self.app.backup_sel = None
        self.render()

    def reset_e3(self):
        e3tool.set_backups_dir(None)
        self.app.cfg.pop("e3_backups", None)
        self.app.save_cfg()
        self.app.backup_sel = None
        self.render()

    # ---- info page
    def _info(self):
        f = self.app.f
        top = tk.Frame(self.body, bg=PANEL)
        top.pack(fill="x", pady=(18, 0))
        wm = tk.Canvas(top, height=34, width=10, bg=PANEL, highlightthickness=0)
        end = draw_wordmark(wm, f.wordmark_l, 0, 17)
        wm.configure(width=end + 4)
        wm.pack(side="left")
        Pill(top, f"v{core.APP_VERSION} · {core.APP_STAGE.lower()}", f.mono_s, PANEL).pack(side="left", padx=12)
        tk.Label(self.body, text="Flashes the ESC (DRV) and BLE module of Ninebot and Xiaomi scooters over an "
                                 "ST-Link with OpenOCD, and makes backups and serial-number changes for the "
                                 "Ninebot E3 / E3 Pro. Every write is read back and compared.",
                 bg=PANEL, fg=DIM, font=f.body, wraplength=540, justify="left").pack(anchor="w", pady=(10, 0))

        self._section("Tested on real hardware")
        for _b, _k, it in models():
            if it.get("tested"):
                r = tk.Frame(self.body, bg=PANEL)
                r.pack(fill="x", pady=1)
                tk.Label(r, text="✓", bg=PANEL, fg=OK, font=f.body_b).pack(side="left")
                tk.Label(r, text=it["name"], bg=PANEL, fg=TXT, font=f.body).pack(side="left", padx=(8, 0))
                tk.Label(r, text="·  " + it["tested"], bg=PANEL, fg=DIM, font=f.mono_s).pack(side="left", padx=8)
        self._note("Everything else is untested so far (beta). If you try a scooter, please report the result, "
                   "worked or not, with the console log.")
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x", pady=(10, 0))
        Button(row, "Report a test result", lambda: webbrowser.open(core.TEST_REPORT_URL), f, kind="primary",
               bg=PANEL, small=True, height=32).pack(side="left")
        for label, cmd in (("Project page", lambda: webbrowser.open(core.REPO_URL)),
                           ("ScooterHacking", lambda: webbrowser.open("https://cfw.sh")),
                           ("License", lambda: open_path(core.ROOT / "LICENSE")),
                           ("Third-party files", lambda: open_path(core.ROOT / "THIRD_PARTY.md"))):
            Link(row, label, cmd, f, PANEL).pack(side="left", padx=(16, 0))

        self._section("Credits")
        for who, what in (("ScooterHacking", "flash sequences, bootloader and firmware files, wiring "
                                                     "diagrams from ReFlasher; F2 GD32 files. Used with permission."),
                          ("BastelPichi", "provided the E2 Pro firmware 32kmh.bin (author unnamed) and the OK "
                                          "to include it."),
                          ("OpenOCD", "on-chip debugger, GPL-2.0.")):
            r = tk.Frame(self.body, bg=PANEL)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=who, bg=PANEL, fg=TXT, font=f.small_b, width=22, anchor="w").pack(side="left",
                                                                                           anchor="n")
            tk.Label(r, text=what, bg=PANEL, fg=DIM, font=f.small, wraplength=360, justify="left").pack(
                side="left")
        self._note(f"MIT license (TorqueFlasher's own code). Third-party files keep their own terms. Not "
                   f"affiliated with Segway-Ninebot, Xiaomi or ScooterHacking. Use at your own risk.")

    def close(self):
        self.grab_release()
        self.destroy()


class StartupWarning(tk.Toplevel):
    """Shown before the main window opens. 'I understand' opens TorqueFlasher; Quit or closing the window ends it.
    The button unlocks after a few seconds so the text is at least seen."""
    DELAY = 3

    def __init__(self, app, on_accept):
        super().__init__(app)
        self.app, self.on_accept, self.left = app, on_accept, self.DELAY
        self.title(f"{core.APP_NAME} · Before you start")
        self.configure(bg=PANEL, highlightthickness=1, highlightbackground=LINE2)
        dark_titlebar(self)
        self.resizable(False, False)
        f = app.f
        body = tk.Frame(self, bg=PANEL, padx=30, pady=26)
        body.pack(fill="both", expand=True)
        head = tk.Frame(body, bg=PANEL)
        head.pack(fill="x")
        mark = tk.Canvas(head, width=46, height=46, bg=PANEL, highlightthickness=0)
        mark.create_oval(1, 1, 45, 45, fill=mix(AMBER, PANEL, 0.86), outline=mix(AMBER, PANEL, 0.45))
        mark.create_text(23, 24, text="!", fill=AMBER, font=f.h1)
        mark.pack(side="left", padx=(0, 14))
        t = tk.Frame(head, bg=PANEL)
        t.pack(side="left")
        eyebrow(t, "Warning", f, PANEL, fg=AMBER).pack(anchor="w")
        tk.Label(t, text="Before you start", bg=PANEL, fg=TXT, font=f.h1).pack(anchor="w")
        for i, (title, text) in enumerate(WARNING_POINTS, 1):
            row = tk.Frame(body, bg=PANEL)
            row.pack(fill="x", pady=(16 if i == 1 else 12, 0))
            num = tk.Canvas(row, width=22, height=22, bg=PANEL, highlightthickness=0)
            num.create_oval(1, 1, 21, 21, fill=PANEL2, outline=LINE2)
            num.create_text(11, 11, text=str(i), fill=DIM, font=f.mono_s)
            num.pack(side="left", anchor="n", padx=(0, 12))
            col = tk.Frame(row, bg=PANEL)
            col.pack(side="left", fill="x")
            tk.Label(col, text=title, bg=PANEL, fg=TXT, font=f.body_b, anchor="w").pack(anchor="w")
            tk.Label(col, text=text, bg=PANEL, fg=DIM, font=f.small, justify="left", wraplength=470,
                     anchor="w").pack(anchor="w", pady=(2, 0))
        tk.Label(body, text="Not affiliated with Segway-Ninebot, Xiaomi or ScooterHacking.", bg=PANEL, fg=MUT,
                 font=f.small, anchor="w").pack(fill="x", pady=(16, 0))
        foot = tk.Frame(body, bg=PANEL)
        foot.pack(fill="x", pady=(18, 0))
        Pill(foot, f"v{core.APP_VERSION} · {core.APP_STAGE.lower()}", f.mono_s, PANEL).pack(side="left")
        self.ok = Button(foot, f"I understand  ·  {self.left}", self.accept, f, kind="primary", bg=PANEL, small=True,
                         height=38, width=190)
        self.ok.pack(side="right")
        self.ok.set_enabled(False)
        Button(foot, "Quit", self.quit_app, f, kind="ghost", bg=PANEL, small=True, height=38).pack(side="right",
                                                                                                 padx=8)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.bind("<Escape>", lambda e: self.quit_app())
        self.bind("<Return>", lambda e: self.accept())
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_reqwidth()) // 2
        y = (self.winfo_screenheight() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.after(1000, self._tick)
        self.focus_force()

    def _tick(self):
        if not self.winfo_exists():
            return
        self.left -= 1
        if self.left > 0:
            self.ok.set_text(f"I understand  ·  {self.left}")
            self.after(1000, self._tick)
        else:
            self.ok.set_text("I understand")
            self.ok.set_enabled(True)

    def accept(self, force=False):
        if self.left > 0 and not force:
            return
        self.destroy()
        self.on_accept()

    def quit_app(self):
        self.app.destroy()


class DiagramViewer(tk.Toplevel):
    def __init__(self, app, path: pathlib.Path, note: str):
        super().__init__(app)
        self.title(f"Wiring · {path.name}")
        self.configure(bg=BG)
        dark_titlebar(self)
        img = tk.PhotoImage(file=str(path))
        sw, sh = app.winfo_screenwidth() - 120, app.winfo_screenheight() - 200
        factor = max(1, -(-img.width() // max(1, sw)), -(-img.height() // max(1, sh)))
        if factor > 1:
            img = img.subsample(factor, factor)
        self.img = img
        tk.Label(self, text=note, bg=BG, fg=AMBER, font=app.f.small, wraplength=max(400, img.width()),
                 justify="left").pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(self, image=img, bg=BG).pack(padx=10, pady=10)
        tk.Label(self, text="Wiring diagram from ScooterHacking's ReFlasher.", bg=BG, fg=MUT, font=app.f.small).pack(
            pady=(0, 10))
        self.transient(app)


# ----------------------------------------------------------------------------------------------- app
LEFT_W = 452


class App(tk.Tk):
    LEFT_W = LEFT_W

    def __init__(self):
        super().__init__(className="TorqueFlasher")  # window class: Linux taskbars match it to the .desktop file
        self.title(core.APP_NAME)
        if STARTUP_WARNING:
            self.withdraw()  # opens after the startup warning
        dark_titlebar(self)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(1180, max(1000, sw - 80))}x{min(820, max(700, sh - 100))}")
        self.minsize(1000, 700)
        self.configure(bg=BG)
        self.f = Fonts(self)
        self.cfg = load_settings()
        self.first_run = not self.cfg
        tf_ui.set_accent(self.cfg.get("accent"))
        self._style()
        self._icon()

        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.stage = "idle"            # idle | countdown | running | done | fail
        self.step = (0, 0, "")
        self.run_plan: list[str] = []
        self.run_kv: list = []
        self.run_started = 0.0
        self.run_seconds = 0.0
        self.last_msg = ""
        self.result = None
        self.error = ""
        self.last_action = "—"
        self.oocd_version = ""
        self.cd: Countdown | None = None
        self.cd_left = 0
        self.run_backup: str | None = None
        self.last_sn: bytes | None = None
        self.pending_letter = ""
        self.detected: dict | None = None     # chip found by Check connection: key, family, known, idcode
        self.last_check: dict | None = None   # last check result for a scooter: key, time, rdp, userdata
        self.console_buf = collections.deque(maxlen=4000)
        self.ready_state = (False, "", "")
        self._ready_fn = None

        self.brand = self.cfg.get("brand", "ninebot")
        self.model = self.cfg.get("model", "g30")
        if not item_for(self.brand, self.model):
            self.brand, self.model = "ninebot", "g30"
        it = item_for(self.brand, self.model)
        self.chip = self.cfg.get("chip") or default_chip(it)
        if not chip_valid(it, self.chip):
            self.chip = default_chip(it)
        self.countdown = int(self.cfg.get("countdown", 5))
        self.dry = tk.BooleanVar(value=bool(self.cfg.get("dry_run", False)))
        self.ble_fast = tk.BooleanVar(value=bool(self.cfg.get("ble_fast", False)))
        if self.cfg.get("e3_backups"):
            e3tool.set_backups_dir(self.cfg["e3_backups"])

        self.write_ud = tk.BooleanVar(value=True)
        self.sn_var = tk.StringVar()
        self.km_var = tk.StringVar(value="0")
        self.fw_path: str | None = None
        self.ble_name = tk.StringVar()
        self.target = tk.StringVar(value="")
        self.custom = tk.StringVar(value="")
        self.backup_sel: pathlib.Path | None = None
        self.sn_var.trace_add("write", lambda *a: self._sn_changed())
        self.km_var.trace_add("write", lambda *a: self._update_ready())
        self.ble_name.trace_add("write", lambda *a: self._update_ready())
        self._prefill_sn()

        core.RAW_SINK = lambda line: self.q.put(("raw", line))
        self.action_id = self.actions()[0]["id"]
        self._build()
        self.console_line(f"{core.APP_NAME} {core.APP_VERSION} {core.APP_STAGE.lower()} · the OpenOCD output of "
                          f"every run appears here and in logs/.", "raw")
        self.render()
        self.refresh_version()
        self.after(60, self.poll)
        self.after(450, self.tick)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.warning = None
        if STARTUP_WARNING:
            self.after(50, lambda: setattr(self, "warning", StartupWarning(self, self._opened)))
        else:
            self._opened()

    def _opened(self):
        """Main window visible (after the startup warning); on the very first start the scooter picker follows."""
        self.warning = None
        self.deiconify()
        self.update_idletasks()
        tf_ui.apply_window_icon(self, default=True)  # Windows: possible only now that the window is shown
        if self.first_run:
            self.after(400, self.open_picker)

    # ---------------------------------------------------------------- style
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Vertical.TScrollbar", background=ELEV, troughcolor=CONSOLE_BG, bordercolor=CONSOLE_BG,
                    arrowcolor=DIM, lightcolor=ELEV, darkcolor=ELEV, gripcount=0)
        s.map("Vertical.TScrollbar", background=[("active", "#2B2B31")])
        for k, v in (("background", PANEL), ("foreground", TXT), ("activeBackground", T.ACCENT),
                     ("activeForeground", INK), ("relief", "flat"), ("borderWidth", 0)):
            self.option_add(f"*Menu.{k}", v)

    def _icon(self):
        if set_window_icon(self, core.ROOT / "assets", T.name):
            return
        try:  # fallback without the icon files: a small drawn bolt
            img = tk.PhotoImage(width=32, height=32)
            img.put(BG, to=(0, 0, 32, 32))
            for y in range(4, 28):
                cx = 18 - (y - 4) // 2 if y < 17 else 20 - (y - 13) // 2
                img.put(T.ACCENT, to=(max(0, cx - 3), y, min(32, cx + 3), y + 1))
            self.iconphoto(True, img)
            self._icon_img = img
        except Exception:  # noqa
            pass

    def recent(self):
        """Last used scooters [(brand, model)], newest first."""
        out = []
        for entry_ in self.cfg.get("recent", []):
            try:
                b, k = entry_.split("/", 1)
                out.append((b, k))
            except ValueError:
                pass
        return out

    # ---------------------------------------------------------------- scooter helpers
    def is_e3(self):
        return self.model == "e3"

    def item(self):
        return item_for(self.brand, self.model)

    def key(self):
        return self.brand, self.model

    def actions(self):
        return E3_ACTIONS if self.is_e3() else ESC_ACTIONS

    def ble_key(self):
        return None if self.is_e3() else core.ble_model_for(self.brand, self.model)

    def available(self, a):
        return not a.get("ble") or self.ble_key() is not None

    def detected_for(self):
        d = self.detected
        return d if d and d["key"] == self.key() else None

    def effective_chip(self):
        """The chip the next run will use: fixed/chosen chip, the chip detected by Check connection, or 'auto'."""
        it = self.item()
        if chip_mode(it) == "fixed":
            return default_chip(it)
        if self.chip == "auto":
            d = self.detected_for()
            return d["family"] if d else "auto"
        return self.chip

    def scooter_label(self):
        return f"{self.item()['name']} · {CHIP_LABEL[self.effective_chip()]}"

    def sn_format(self):
        it = self.item()
        return "xiaomi" if self.brand == "xiaomi" or it.get("sn_format") == "xiaomi" else "ninebot"

    def wiring_text(self, ble=False):
        if ble:
            return ("BLE module: connect the dashboard to the main cable, and the ST-Link to the SWD pads of the BLE "
                    "board as shown in the diagram.")
        return WIRING_NOTE

    def _prefill_sn(self):
        it = self.item()
        self.sn_var.set(it.get("sn_fixed") or it.get("sn_placeholder") or "")
        self.km_var.set("0")
        self.fw_path = None

    def set_scooter(self, brand, model, chip=None):
        if self.busy or self.stage == "countdown":
            return
        changed = (brand, model) != (self.brand, self.model)
        it = item_for(brand, model)
        if chip is None or not chip_valid(it, chip):
            chip = self.chip if not changed and chip_valid(it, self.chip) else default_chip(it)
        self.brand, self.model, self.chip = brand, model, chip
        if changed:
            self._prefill_sn()
        key = f"{brand}/{model}"
        self.cfg["recent"] = ([key] + [k for k in self.cfg.get("recent", []) if k != key])[:3]
        self.save_cfg()
        ids = [a["id"] for a in self.actions()]
        if self.action_id not in ids or not self.available(ALL_ACTIONS[self.action_id]):
            self.action_id = ids[0]
        self.stage = "idle"
        self.refresh_version()
        self.render()

    def set_chip(self, chip):
        if self.busy or self.stage == "countdown" or not chip_valid(self.item(), chip):
            return
        self.chip = chip
        self.save_cfg()
        if self.stage in ("done", "fail"):
            self.stage = "idle"
        self.render()

    def save_cfg(self):
        self.cfg.update(brand=self.brand, model=self.model, chip=self.chip, countdown=self.countdown,
                        dry_run=bool(self.dry.get()), ble_fast=bool(self.ble_fast.get()), accent=T.name)
        save_settings(self.cfg)

    def set_accent(self, name):
        tf_ui.set_accent(name)
        self.save_cfg()
        self.rebuild_ui()

    # ---------------------------------------------------------------- layout
    def _build(self):
        f = self.f
        self.shell = sh = tk.Frame(self, bg=BG)
        sh.pack(fill="both", expand=True)

        bar = tk.Frame(sh, bg=BG)
        bar.pack(fill="x")
        logo = icon_dir(core.ROOT / "assets", T.name) / "icon-32.png"
        if logo.exists():
            self._bar_icon = tk.PhotoImage(master=self, file=str(logo))
            tk.Label(bar, image=self._bar_icon, bg=BG).pack(side="left", padx=(18, 0))
        wm = tk.Canvas(bar, height=54, width=10, bg=BG, highlightthickness=0)
        wm.configure(width=draw_wordmark(wm, f.wordmark, 10 if logo.exists() else 20, 27) + 6)
        wm.pack(side="left")
        Pill(bar, f"v{core.APP_VERSION} · {core.APP_STAGE.lower()}", f.mono_s, BG).pack(side="left", padx=(6, 0))
        IconButton(bar, "⚙", self.open_settings, f, BG, "Settings").pack(side="right", padx=(6, 18))
        IconButton(bar, "ⓘ", self.open_info, f, BG, "Info, credits, test status").pack(side="right", padx=6)
        self.dry_chip = Badge(bar, f, bg=BG, command=self.toggle_dry)
        self.dry_chip.pack(side="right", padx=6)
        tk.Frame(sh, bg=LINE, height=1).pack(fill="x")

        self.sb = tk.Frame(sh, bg=STATUS_BG, height=28)
        self.sb.pack(side="bottom", fill="x")
        self.sb.pack_propagate(False)
        tk.Frame(sh, bg=LINE, height=1).pack(side="bottom", fill="x")
        self.led = Led(self.sb, STATUS_BG)
        self.led.pack(side="left", padx=(16, 8))
        self.st_state = tk.Label(self.sb, text="", bg=STATUS_BG, fg=TXT, font=f.btn_s)
        self.st_state.pack(side="left")
        self.st_info = tk.Label(self.sb, text="", bg=STATUS_BG, fg=DIM, font=f.mono_s)
        self.st_info.pack(side="left", padx=(16, 0))
        self.st_log = Link(self.sb, f"logs/torqueflasher_{datetime.date.today()}.log",
                           lambda: open_path(ensure_dir(core.LOGS)), f, STATUS_BG, color=MUT, font=f.mono_s)
        self.st_log.pack(side="right", padx=16)

        head = tk.Frame(sh, bg=BG)
        head.pack(fill="x", padx=18, pady=(14, 0))
        for col, weight in enumerate((5, 4, 3)):
            head.columnconfigure(col, weight=weight, uniform="head")
        self.c_scooter = Card(head, BG, padx=18, pady=11)
        self.c_scooter.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self._scooter_w = 0
        self.c_scooter.bind("<Configure>", lambda e: abs(e.width - self._scooter_w) > 8 and self.after_idle(
            self._head_scooter), add="+")
        self.c_chip = Card(head, BG, padx=18, pady=11)
        self.c_chip.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        self.c_count = Card(head, BG, padx=18, pady=11)
        self.c_count.grid(row=0, column=2, sticky="nsew")

        self.trow = trow = tk.Frame(sh, bg=BG)
        trow.pack(fill="x", padx=18, pady=(12, 0))
        self.tabs = Tabs(trow, f, self.select, bg=BG)
        self.tabs.pack(side="left")
        self.tab_desc = tk.Label(trow, text="", bg=BG, fg=DIM, font=f.small, justify="left", anchor="w")
        self.tab_desc.pack(side="left", fill="x", expand=True, padx=(16, 0))
        trow.bind("<Configure>", lambda e: self._wrap_desc())

        main = tk.Frame(sh, bg=BG)
        main.pack(fill="both", expand=True, padx=18, pady=(12, 14))
        left = tk.Frame(main, bg=BG, width=self.LEFT_W)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.c_seq = Card(left, BG, padx=18, pady=14)
        self.c_seq.pack(side="bottom", fill="x")
        self.params = RoundPanel(left, BG, valign="top")
        self.params.pack(side="top", fill="both", expand=True, pady=(0, 12))
        self.params.bind("<Configure>", lambda e: self.after_idle(self._fit_steps), add="+")
        self.p = self.params.inner

        si = self.c_seq.inner
        top = tk.Frame(si, bg=PANEL)
        top.pack(fill="x")
        eyebrow(top, "Sequence", f, PANEL).pack(side="left")
        self.seq_state = tk.Label(top, text="", bg=PANEL, fg=MUT, font=f.eyebrow)
        self.seq_state.pack(side="right")
        self.seq_body = tk.Frame(si, bg=PANEL, height=1)   # progress bar + step list (the list folds away)
        self.seq_body.pack(fill="x")
        self.pbar = ProgressBar(self.seq_body)
        self.steps = Steps(self.seq_body, f)
        self.steps.pack(fill="x", pady=(10, 0))
        self.ready_title = tk.Label(si, text="", bg=PANEL, fg=TXT, font=f.body_b, anchor="w")
        self.ready_title.pack(fill="x", pady=(12, 0))
        self.ready_hint = tk.Label(si, text="", bg=PANEL, fg=DIM, font=f.small, anchor="w", justify="left",
                                   wraplength=self.LEFT_W - 44)
        self.ready_hint.pack(fill="x")
        self.start_btn = Button(si, "▶  START", self.on_main_button, f, kind="primary", expand=True)
        self.start_btn.pack(fill="x", pady=(12, 0))
        self.extra_row = tk.Frame(si, bg=PANEL)
        self.extra_row.pack(fill="x")

        con = FillPanel(main, BG, fill=CONSOLE_BG, outline=LINE2)
        con.pack(side="left", fill="both", expand=True, padx=(14, 0))
        ci = con.inner
        ch = tk.Frame(ci, bg=CONSOLE_BG)
        ch.pack(fill="x", padx=12, pady=(9, 8))
        eyebrow(ch, "Console", f, CONSOLE_BG).pack(side="left")
        tk.Label(ch, text="openocd stdout · stderr", bg=CONSOLE_BG, fg=mix(MUT, CONSOLE_BG, 0.3),
                 font=f.mono_s).pack(side="left", padx=10)
        for label, cmd in reversed((("copy", self.copy_console), ("clear", self.clear_console),
                                    ("logs/", lambda: open_path(ensure_dir(core.LOGS))))):
            Link(ch, label, cmd, f, CONSOLE_BG, color=MUT, font=f.mono_s).pack(side="right", padx=(12, 0))
        tk.Frame(ci, bg=LINE, height=1).pack(fill="x")
        wrap = tk.Frame(ci, bg=CONSOLE_BG)
        wrap.pack(fill="both", expand=True)
        self.text = tk.Text(wrap, bg=CONSOLE_BG, fg=DIM, insertbackground=TXT, relief="flat", bd=0,
                            font=f.mono, padx=12, pady=10, wrap="word", state="disabled",
                            selectbackground=ELEV, highlightthickness=0, spacing1=1, spacing3=1)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        for tag, col in (("cmd", T.ACCENT_DIM), ("err", DANGER), ("warn", AMBER), ("ok", OK), ("msg", TXT),
                         ("raw", DIM)):
            self.text.tag_configure(tag, foreground=col)
        self.text.tag_configure("head", foreground=TXT, spacing1=8)

    def rebuild_ui(self):
        """Rebuilds every frame (after an accent change). State lives in the App, not in the widgets."""
        self.shell.destroy()
        self._style()
        self._icon()
        self._build()
        self.text.configure(state="normal")
        for text, tag in self.console_buf:
            self.text.insert("end", text + "\n", tag)
        self.text.see("end")
        self.text.configure(state="disabled")
        self.render()

    # ---------------------------------------------------------------- header cards
    def draw_header(self):
        self._head_scooter()
        self._head_chip()
        self._head_count()

    @staticmethod
    def _clear(frame):
        for w in frame.winfo_children():
            w.destroy()

    def _head_scooter(self):
        f, it = self.f, self.item()
        inner = self.c_scooter.inner
        self._clear(inner)
        top = tk.Frame(inner, bg=PANEL)
        top.pack(fill="x")
        eyebrow(top, "Scooter", f, PANEL).pack(side="left")
        Link(top, "wiring ›", self.show_wiring, f, PANEL, font=f.mono_s).pack(side="right")
        name_row = tk.Frame(inner, bg=PANEL)
        name_row.pack(fill="x", pady=(4, 0))
        cw = self.c_scooter.winfo_width()
        width = cw - 36 if cw > 100 else 420
        self._scooter_w = cw
        tk.Label(name_row, text=fit(f.big, it["name"], width - 34), bg=PANEL, fg=TXT, font=f.big).pack(side="left")
        tk.Label(name_row, text="▾", bg=PANEL, fg=MUT, font=f.big_s).pack(side="left", padx=(8, 0), pady=(4, 0))
        sub = tk.Frame(inner, bg=PANEL)
        sub.pack(fill="x", pady=(4, 0))
        what = "backup · SN change" if self.is_e3() else ("ESC + BLE" if self.ble_key() else "ESC")
        tag_w = f.eyebrow.measure("✓ TESTED") + 12 if it.get("tested") else 0
        tk.Label(sub, text=fit(f.mono_s, f"{self.brand.capitalize()} · {what}", width - tag_w), bg=PANEL, fg=DIM,
                 font=f.mono_s).pack(side="left")
        if it.get("tested"):
            tk.Label(sub, text="✓ TESTED", bg=PANEL, fg=OK, font=f.eyebrow).pack(side="left", padx=(10, 0))
        locked = self.busy or self.stage == "countdown"
        for w in (self.c_scooter, inner, top.winfo_children()[0], name_row, *name_row.winfo_children(), sub,
                  *sub.winfo_children()):
            w.configure(cursor="arrow" if locked else "hand2")
            w.bind("<Button-1>", lambda e: self.open_picker())

    def _head_chip(self):
        f, it = self.f, self.item()
        inner = self.c_chip.inner
        self._clear(inner)
        mode = chip_mode(it)
        det = self.detected_for()
        locked = self.busy or self.stage == "countdown"
        top = tk.Frame(inner, bg=PANEL)
        top.pack(fill="x")
        eyebrow(top, "Chip", f, PANEL).pack(side="left")
        if mode == "auto" and not locked:
            Link(top, "override ▾", self.chip_menu, f, PANEL, color=MUT, font=f.mono_s).pack(side="right")
        body = tk.Frame(inner, bg=PANEL)
        body.pack(fill="x", pady=(4, 0))
        sub = tk.Frame(inner, bg=PANEL)
        sub.pack(fill="x", pady=(4, 0))

        def sub_text(text, color=DIM):
            tk.Label(sub, text=text, bg=PANEL, fg=color, font=f.mono_s).pack(side="left")

        if mode == "fixed":
            tk.Label(body, text=CHIP_LABEL[default_chip(it)], bg=PANEL, fg=TXT, font=f.big).pack(side="left")
            sub_text("AT32F415 · fixed" if self.is_e3() else
                     "fixed for this model" + (" · GD32E sequence" if it.get("gd32e") else ""), MUT)
        elif mode == "choose":
            tabs = Tabs(body, f, self.set_chip, bg=PANEL, height=36, pad=18, font=f.btn)
            tabs.set([(c, CHIP_LABEL[c], True, "") for c in it["chips"]], self.chip, locked=locked)
            tabs.pack(side="left", pady=(2, 0))
            if det and det["family"] not in ("unknown", self.chip):
                sub_text(f"⚠ check found {det['family'].upper()}", AMBER)
                if not locked:
                    Link(sub, "use it", lambda: self.set_chip(det["family"]), f, PANEL, font=f.mono_s).pack(
                        side="left", padx=8)
            else:
                sub_text("pick by the marking on the chip", MUT)
        elif self.chip == "auto":
            tk.Label(body, text=det["family"].upper() if det else "Auto", bg=PANEL, fg=TXT, font=f.big).pack(
                side="left")
            tag = Badge(sub, f, bg=PANEL)
            tag.set(T.ACCENT, "AUTO", filled=True)
            tag.pack(side="left", padx=(0, 8))
            if det:
                sub_text("✓ detected" + (f" · {det['idcode']}" if det.get("idcode") else ""), T.ACCENT)
            else:
                sub_text("detected by Check connection", MUT)
        else:
            tk.Label(body, text=CHIP_LABEL[self.chip], bg=PANEL, fg=TXT, font=f.big).pack(side="left")
            if det and det["family"] not in ("unknown", self.chip):
                sub_text(f"⚠ set manually, check found {det['family'].upper()}", AMBER)
            else:
                sub_text("set manually", MUT)
            if not locked:
                Link(sub, "use auto", lambda: self.set_chip("auto"), f, PANEL, font=f.mono_s).pack(side="left",
                                                                                                  padx=8)

    def chip_menu(self):
        it = self.item()
        m = tk.Menu(self, tearoff=0, font=self.f.mono)
        for c in ["auto"] + it["chips"]:
            mark = "● " if c == self.chip else "   "
            label = "Auto (recommended)" if c == "auto" else CHIP_LABEL[c]
            m.add_command(label=mark + label, command=lambda c=c: self.set_chip(c))
        w = self.c_chip
        m.tk_popup(w.winfo_rootx() + w.winfo_width() - 190, w.winfo_rooty() + 34)

    def _head_count(self):
        f = self.f
        inner = self.c_count.inner
        self._clear(inner)
        eyebrow(inner, "Countdown", f, PANEL).pack(anchor="w")
        row = tk.Frame(inner, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        counting = self.stage == "countdown"
        locked = self.busy or counting
        minus = Button(row, "−", lambda: self.bump_countdown(-1), f, kind="ghost", bg=PANEL, small=True,
                       width=34, height=34)
        minus.pack(side="left")
        self.cd_value = tk.Label(row, text=f"{self.cd_left if counting else self.countdown} s", bg=PANEL,
                                 fg=AMBER if counting else TXT, font=f.big, width=4)
        self.cd_value.pack(side="left")
        plus = Button(row, "+", lambda: self.bump_countdown(1), f, kind="ghost", bg=PANEL, small=True, width=34,
                      height=34)
        plus.pack(side="left")
        for b in (minus, plus):
            b.set_enabled(not locked)
        tk.Label(inner, text="before each start · 0 = off", bg=PANEL, fg=MUT, font=f.mono_s).pack(anchor="w",
                                                                                               pady=(4, 0))

    def bump_countdown(self, d):
        if self.busy or self.stage == "countdown":
            return
        self.countdown = max(0, min(60, self.countdown + d))
        self.save_cfg()
        self.cd_value.configure(text=f"{self.countdown} s")

    # ---------------------------------------------------------------- status
    def refresh_version(self):
        def probe():
            try:
                v = core.openocd_version(core.find_openocd("bin_at32" if self.is_e3() else "bin"))
            except FileNotFoundError:
                v = ""
            self.q.put(("version", v))
        threading.Thread(target=probe, daemon=True).start()

    def update_status(self):
        probs = self.action_problems(ALL_ACTIONS[self.action_id])
        bg, fg, led = STATUS_BG, TXT, OK
        if self.stage in ("running", "countdown"):
            bg, fg, led = T.ACCENT, INK, INK
            state = "RUNNING" if self.stage == "running" else f"STARTING IN {self.cd_left}"
        elif self.stage == "fail":
            state, fg, led = "FAILED", DANGER, DANGER
        elif probs:
            state, fg, led = "SETUP NEEDED", AMBER, DANGER
        else:
            state = "READY"
        info = [f"openocd {self.oocd_version}" if self.oocd_version else "openocd ?", f"last: {self.last_action}"]
        if self.dry.get():
            info.append("DRY RUN")
        self.sb.configure(bg=bg)
        self.led.configure(bg=bg)
        self.led.set(led)
        self.st_state.configure(text=state, bg=bg, fg=fg)
        self.st_info.configure(text="   ·   ".join(info), bg=bg, fg=INK if bg != STATUS_BG else DIM)
        self.st_log.configure(bg=bg, fg=INK if bg != STATUS_BG else MUT)
        self.st_log.color = INK if bg != STATUS_BG else MUT
        if self.dry.get():
            self.dry_chip.set(AMBER, "DRY RUN: ON", filled=True)
        else:
            self.dry_chip.set(MUT, "DRY RUN: OFF")

    def toggle_dry(self):
        if self.busy or self.stage == "countdown":
            return
        self.dry.set(not self.dry.get())
        self.on_dry_changed()

    def on_dry_changed(self):
        self.save_cfg()
        self.update_status()
        if self.stage == "idle":
            self._update_ready()

    def action_problems(self, a) -> list[str]:
        if a.get("offline"):
            return []
        probs = []
        scripts = core.ROOT / "oocd" / "scripts"
        if a["id"].startswith("e3"):
            dirs, cfgs = ["bin_at32"], ["target/at32.cfg"]
        elif a.get("ble"):
            dirs, cfgs = ["bin"], ["target/nrf51-fast.cfg" if self.ble_fast.get() else "target/nrf51.cfg"]
        else:
            chip = self.effective_chip()
            drv = core.PROFILES["drv"]
            if chip == "auto":
                dirs, cfgs = ["bin"], [drv["openocd_target"]]
            else:
                var = drv["variants"][chip]
                dirs, cfgs = [var["openocd_dir"]], [var.get("openocd_target", drv["openocd_target"])]
        for d in dirs:
            try:
                core.find_openocd(d)
            except FileNotFoundError as e:
                probs.append(str(e))
        for c in ["interface/stlink.cfg"] + cfgs:
            if not (scripts / c).exists():
                probs.append(f"Missing: oocd/scripts/{c}")
        if a["id"] == "flash" and self.effective_chip() != "auto":
            try:
                boot, fw, _ = core.drv_files(self.brand, self.model, self.effective_chip(), self.fw_path)
                for p in (boot, fw):
                    if not p.exists():
                        probs.append(f"Missing: {p.relative_to(core.ROOT) if core.ROOT in p.parents else p}")
            except ValueError:
                pass  # no firmware chosen yet: handled as "not ready", not as setup problem
        if a["id"] == "ble_flash" and self.ble_key():
            ble = core.PROFILES["ble"]
            item = ble["models"][self.brand][self.ble_key()]
            lay = ble["layouts"]["v2" if item.get("v2") else "v1"]
            for p in (core.ROOT / "binaries/bootloader" / lay["bootloader"][self.brand],
                      core.ROOT / "binaries/firmware" / item["fw"], core.ROOT / "binaries" / lay["uicr"]):
                if not p.exists():
                    probs.append(f"Missing: {p.relative_to(core.ROOT)}")
        return probs

    # ---------------------------------------------------------------- selection
    def select(self, action_id):
        a = ALL_ACTIONS[action_id]
        if self.busy or self.stage == "countdown" or not self.available(a):
            return
        self.action_id = action_id
        self.stage = "idle"
        self.result, self.error = None, ""
        self.render()

    def open_picker(self):
        if self.busy or self.stage == "countdown":
            return
        ScooterPicker(self)

    # ---------------------------------------------------------------- rendering
    def render(self):
        a = ALL_ACTIONS[self.action_id]
        locked = self.busy or self.stage == "countdown"
        self.draw_header()
        self.tabs.set([(x["id"], x["tab"], self.available(x), "" if self.available(x) else x.get("unavailable", ""))
                       for x in self.actions()], self.action_id, locked=locked)
        self.tab_desc.configure(text=a["desc"])
        self._wrap_desc()
        self._clear(self.p)
        self._clear(self.extra_row)
        self._ready_fn = None
        getattr(self, f"_render_{self.stage}")(a)
        self.update_status()
        self.params.scroll_top()
        self.params.after_idle(self.params.redraw)
        self.after_idle(self._fit_steps)

    def _wrap_desc(self):
        self.tab_desc.configure(wraplength=max(180, self.trow.winfo_width() - self.tabs.winfo_reqwidth() - 20))

    def _ptitle(self, text, right="", color=MUT, right_color=MUT):
        row = tk.Frame(self.p, bg=PANEL)
        row.pack(fill="x", pady=(0, 10))
        eyebrow(row, text, self.f, PANEL, fg=color).pack(side="left")
        if right:
            tk.Label(row, text=right, bg=PANEL, fg=right_color, font=self.f.eyebrow).pack(side="right")
        return row

    def _kv(self, parent, rows, wrap=LEFT_W - 140):
        grid = tk.Frame(parent, bg=PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        for i, row in enumerate(rows):
            k, v = row[0], row[1]
            col = row[2] if len(row) > 2 else None
            tk.Label(grid, text=k, bg=PANEL, fg=MUT, font=self.f.small, anchor="w").grid(
                row=i, column=0, sticky="nw", padx=(0, 14), pady=2)
            tk.Label(grid, text=v, bg=PANEL, fg=col or TXT, font=self.f.mono, anchor="w", justify="left",
                     wraplength=wrap).grid(row=i, column=1, sticky="w", pady=2)
        return grid

    def _note(self, text, color=MUT, pady=(10, 0)):
        tk.Label(self.p, text=text, bg=PANEL, fg=color, font=self.f.small, anchor="w", justify="left",
                 wraplength=self.LEFT_W - 48).pack(fill="x", pady=pady)

    def _seq(self, labels, current=0, mode="idle", state="", state_color=MUT, bar=None):
        self.steps.set(labels, current, mode)
        self.seq_state.configure(text=state, fg=state_color)
        if bar is None:
            self.pbar.pack_forget()
        else:
            if not self.pbar.winfo_manager():
                if self.steps.winfo_manager():
                    self.pbar.pack(fill="x", pady=(10, 0), before=self.steps)
                else:
                    self.pbar.pack(fill="x", pady=(10, 0))
            self.pbar.set(*bar)
        self._seq_body_size()

    def _seq_body_size(self):
        if not self.seq_body.pack_slaves():  # an emptied frame would keep its old height
            self.seq_body.configure(height=1)

    def _fit_steps(self):
        """The step list is shown while running and after a failure, otherwise only if the parameter card above
        still has room for its content; on small windows it folds away instead of hiding the parameters."""
        if not self.winfo_exists() or not self.params.winfo_exists():
            return
        shown = bool(self.steps.winfo_manager())
        if self.stage in ("running", "fail"):
            if not shown:
                self.steps.pack(fill="x", pady=(10, 0))
            return
        self.update_idletasks()
        over = self.params.overflow()
        if shown and over > 0:
            self.steps.pack_forget()
            self._seq_body_size()
        elif not shown and over + self.steps.winfo_reqheight() + 10 <= 0:
            self.steps.pack(fill="x", pady=(10, 0))

    def _main(self, text, kind="primary", enabled=True):
        self.start_btn.set_text(text, kind)
        self.start_btn.set_enabled(enabled)

    def on_main_button(self):
        if self.stage == "idle":
            self.start()
        elif self.stage == "countdown":
            self.cancel_countdown()
        elif self.stage in ("done", "fail"):
            self.back()

    # ---- idle
    def _render_idle(self, a):
        probs = self.action_problems(a)
        self._seq(a["plan"], state=f"{len(a['plan'])} STEP" + ("S" if len(a["plan"]) > 1 else ""))
        self._main("▶  " + a["start"].upper())
        if probs:
            self._ptitle("Setup needed", color=AMBER)
            self._note("TorqueFlasher needs the OpenOCD, bootloader and firmware files next to it (folders "
                       "binaries, oocd, diagrams).", DIM, pady=(0, 8))
            text = "\n".join(short(p, 54) for p in probs[:6]) + ("\n…" if len(probs) > 6 else "")
            RoundField(self.p, lambda p: tk.Label(p, text=text, bg=BG, fg=TXT, font=self.f.mono_s, justify="left",
                                                  anchor="w"), pady=9).pack(fill="x")
            Link(self.p, "Open settings", self.open_settings, self.f, PANEL).pack(anchor="w", pady=(10, 0))
            self._ready_fn = lambda: (False, "Files missing", "See Settings → Program folder.")
            self._update_ready()
            return
        builder = getattr(self, f"_idle_{a['id']}")
        self._ready_fn = builder(a)
        self._update_ready()

    def _update_ready(self):
        if self.stage != "idle" or self._ready_fn is None:
            return
        ok, title, hint = self._ready_fn()
        self.ready_state = (ok, title, hint)
        self.ready_title.configure(text=("✓  " if ok else "") + title, fg=T.ACCENT if ok else AMBER)
        if self.dry.get() and ok:
            hint = "Dry run: shows the OpenOCD commands, writes nothing."
        self.ready_hint.configure(text=hint, fg=DIM)
        self.start_btn.set_enabled(ok)

    # ---- idle builders: build inputs into self.p, return a readiness function
    def _chip_text(self):
        eff, det = self.effective_chip(), self.detected_for()
        if eff == "auto":
            return "detected when you start"
        if self.chip == "auto" and det:
            return f"{eff.upper()} · from last check"
        return eff.upper()

    def _idle_check(self, a):
        self._ptitle("Check connection")
        self._kv(self.p, [("Chip", self._chip_text()), ("Reads", "chip · flash size · read protection"),
                          ("Unlocked", "also serial number, mileage, UID"), ("Writes", "nothing")])
        lc = self.last_check if self.last_check and self.last_check["key"] == self.key() else None
        if lc:
            ud = lc.get("userdata") or {}
            txt = f"Last check {lc['time']} · {lc['variant'].upper()} · read protection {lc.get('rdp', '?')}"
            if ud.get("sn"):
                txt += f" · SN {ud['sn']}"
            self._note(txt, DIM, pady=(12, 0))
        return lambda: (True, "Ready", HINT_DRV)

    def _idle_flash(self, a):
        it, f, p = self.item(), self.f, self.p
        fixed = it.get("sn_fixed")
        head = self._ptitle("Parameters")
        if it.get("bring_fw"):  # firmware in the title row; choosable for the E2 Pro
            if self.fw_path:
                Link(head, "default", self.reset_fw, f, PANEL, font=f.mono_s).pack(side="right", padx=(10, 0))
            Link(head, "choose…", self.pick_fw, f, PANEL, font=f.mono_s).pack(side="right", padx=(10, 0))
            default = it.get("default_fw")
            dpath = core.ROOT / "binaries/firmware" / default if default else None
            fwname = (pathlib.Path(self.fw_path).name if self.fw_path else
                      default if dpath and dpath.exists() else "no firmware")
        else:
            fwname = it.get("drv") or "?"
        tk.Label(head, text=short(fwname, 28), bg=PANEL, fg=TXT, font=f.mono_s).pack(side="right")
        trow = tk.Frame(p, bg=PANEL)
        trow.pack(fill="x", pady=(0, 8))
        Toggle(trow, "Write serial number and mileage", self.write_ud, f, bg=PANEL, command=self._ud_toggled).pack(
            side="left")
        lc = self.last_check if self.last_check and self.last_check["key"] == self.key() else None
        ud = (lc or {}).get("userdata") or {}
        if ud.get("sn") and not fixed:
            km = ud.get("km")
            use = Link(trow, "use check values", lambda: self._use_check_values(ud), f, PANEL, font=f.mono_s)
            use.pack(side="right")
            tf_ui.Tooltip(use, f"From check {lc['time']}: {ud['sn']}" + (f" · {km:g} km" if km is not None else ""),
                          f.mono_s)
        form = tk.Frame(p, bg=PANEL)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Serial number", bg=PANEL, fg=DIM, font=f.body).grid(row=0, column=0, sticky="w",
                                                                                 padx=(0, 12), pady=4)
        self.sn_field = RoundField(form, lambda p: entry(p, self.sn_var, f, width=16), pady=8)
        self.sn_field.grid(row=0, column=1, sticky="we", pady=4)
        self.sn_entry = self.sn_field.child
        self.sn_info = tk.Label(form, text="", bg=PANEL, fg=MUT, font=f.mono_s, width=7, anchor="e")
        self.sn_info.grid(row=0, column=2, sticky="e", padx=(8, 0))
        tk.Label(form, text="Mileage (km)", bg=PANEL, fg=DIM, font=f.body).grid(row=1, column=0, sticky="w",
                                                                                padx=(0, 12), pady=4)
        self.km_field = RoundField(form, lambda p: entry(p, self.km_var, f, width=16), pady=8)
        self.km_field.grid(row=1, column=1, sticky="we", pady=4)
        self.km_entry = self.km_field.child
        note = it.get("gui_note")
        if note:
            self._note(note)
        self._ud_toggled(render=False)
        if fixed:
            self.sn_var.set(fixed)
            self.sn_entry.configure(state="disabled")

        def ready():
            on = self.write_ud.get()
            sn = self.sn_var.get().strip()
            if on and not fixed:
                try:
                    core.validate_sn(sn, self.sn_format())
                except ValueError as e:
                    return False, "Check the serial number", str(e) + "."
            if on:
                try:
                    km = float(self.km_var.get().replace(",", ".") or 0)
                    if km < 0 or km > 2_000_000:
                        raise ValueError
                except ValueError:
                    return False, "Check the mileage", "Enter the mileage in km, e.g. 1234.5"
            if it.get("bring_fw"):
                try:
                    core.drv_files(self.brand, self.model, "at32", self.fw_path)
                except ValueError as e:
                    return False, "Choose a firmware file", str(e) + "."
            return True, "Ready", HINT_DRV
        return ready

    def _use_check_values(self, ud):
        self.write_ud.set(True)
        self.sn_var.set(ud["sn"])
        if ud.get("km") is not None:
            self.km_var.set(f"{ud['km']:g}")
        self.render()

    def _ud_toggled(self, render=True):
        on = self.write_ud.get()
        fixed = self.item().get("sn_fixed")
        if hasattr(self, "sn_entry") and self.sn_entry.winfo_exists():
            self.sn_entry.configure(state="normal" if on and not fixed else "disabled")
            self.km_entry.configure(state="normal" if on else "disabled")
            if not on:
                self.sn_info.configure(text="off", fg=MUT)
            else:
                self._sn_changed()
        self._update_ready()

    def _sn_changed(self):
        v = self.sn_var.get()
        if v != v.upper():  # change it after Tk has finished updating the entry, so the entry shows it too
            self.after_idle(lambda: self.sn_var.set(self.sn_var.get().upper()))
            return
        if hasattr(self, "sn_info") and self.sn_info.winfo_exists() and self.write_ud.get():
            ok = core.sn_valid(v.strip(), self.sn_format())
            self.sn_info.configure(text=f"{len(v.strip())}/14" + (" ✓" if ok else ""), fg=T.ACCENT if ok else MUT)
            self.sn_field.set_border(mix(T.ACCENT, PANEL, 0.45) if ok else LINE2)
        self._update_ready()

    def pick_fw(self):
        p = filedialog.askopenfilename(parent=self, title="Firmware (.bin) for address 0x1000",
                                       filetypes=[("BIN", "*.bin"), ("All files", "*.*")])
        if p:
            self.fw_path = p
            self.render()

    def reset_fw(self):
        self.fw_path = None
        self.render()

    def _idle_ble_check(self, a):
        self._ptitle("Check BLE connection")
        self._kv(self.p, [("Module", "nRF51822 on the BLE board"), ("Wiring", "SWD pads of the BLE board"),
                          ("Writes", "nothing")])
        Toggle(self.p, "Fast mode", self.ble_fast, self.f, bg=PANEL, command=self.save_cfg,
               sub="higher SWD clock (nrf51-fast.cfg); turn off if it fails").pack(anchor="w", pady=(12, 0))
        return lambda: (True, "Ready", HINT_BLE)

    def _idle_ble_flash(self, a):
        f, p = self.f, self.p
        self._ptitle("Parameters")
        form = tk.Frame(p, bg=PANEL)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Bluetooth name", bg=PANEL, fg=DIM, font=f.body).grid(row=0, column=0, sticky="w",
                                                                                  padx=(0, 12), pady=4)
        RoundField(form, lambda p: entry(p, self.ble_name, f, width=16), pady=8).grid(row=0, column=1, sticky="we",
                                                                                    pady=4)
        default = core.PROFILES["ble"]["default_name"][self.brand]
        tk.Label(form, text=f"empty = {default}", bg=PANEL, fg=MUT, font=f.mono_s).grid(row=1, column=1, sticky="w")
        fw = core.PROFILES["ble"]["models"][self.brand][self.ble_key()]["fw"]
        tk.Label(form, text="Firmware", bg=PANEL, fg=DIM, font=f.body).grid(row=2, column=0, sticky="w",
                                                                            padx=(0, 12), pady=(8, 4))
        tk.Label(form, text=fw, bg=PANEL, fg=TXT, font=f.mono).grid(row=2, column=1, sticky="w", pady=(8, 4))
        Toggle(p, "Fast mode", self.ble_fast, f, bg=PANEL, command=self.save_cfg,
               sub="higher SWD clock (nrf51-fast.cfg)").pack(anchor="w", pady=(10, 0))

        def ready():
            name = self.ble_name.get().strip()
            if name:
                try:
                    core.validate_ble_name(name)
                except ValueError as e:
                    return False, "Check the name", str(e) + "."
            return True, "Ready", HINT_BLE
        return ready

    # ---- E3 builders
    def _idle_e3_check(self, a):
        self._ptitle("Check connection")
        self._kv(self.p, [("Scooter", self.item()["name"]), ("Chip", "AT32F415 (patched OpenOCD)"),
                          ("Reads", "CPU, device id, flash size, read protection"), ("Writes", "nothing")])
        return lambda: (True, "Ready", HINT_DRV)

    def _idle_e3_read(self, a):
        self._ptitle("Read serial number")
        rows = [("Reads", "both user-data pages (0x0801C000)"), ("Writes", "nothing")]
        if self.last_sn:
            rows.insert(0, ("Last read", f"{self.last_sn.decode()} · {e3tool.describe(chr(self.last_sn[3]))}"))
        self._kv(self.p, rows)
        return lambda: (True, "Ready", HINT_DRV)

    def _idle_e3_backup(self, a):
        self._ptitle("Backup")
        self._kv(self.p, [("Reads", "complete flash, 128 KB"), ("Saves to", tail(e3tool.backups_dir(), 3)),
                          ("Also", "a .sha256 file to check it later")])
        Link(self.p, "Open the backup folder", lambda: open_path(ensure_dir(e3tool.backups_dir())), self.f,
             PANEL).pack(anchor="w", pady=(10, 0))
        return lambda: (True, "Ready", HINT_DRV)

    def _idle_e3_change(self, a):
        self._ptitle("Target region")
        self._build_targets(self.p, with_current=True)
        return lambda: ((True, "Ready", "A backup is made first. " + HINT_DRV)
                        if self._target_letter() else
                        (False, "Choose a target", "A full backup is made automatically before anything is "
                                                   "written."))

    def _idle_e3_restore(self, a):
        files = e3tool.list_backups()
        if self.backup_sel not in files:
            self.backup_sel = None
        self._ptitle("Backup to restore")
        self._build_backup_list(self.p, files)

        def ready():
            if not files:
                return False, "No backups yet", "Make a backup first, or choose another folder in Settings."
            if not self.backup_sel:
                return False, "Choose a backup", "Only backups with a matching .sha256 file are listed."
            return True, "Ready", "The complete flash is overwritten with this backup and verified."
        return ready

    def _idle_e3_patched(self, a):
        files = e3tool.list_backups()
        if self.backup_sel not in files:
            self.backup_sel = None
        self._ptitle("Backup")
        self._build_backup_list(self.p, files)
        tk.Frame(self.p, bg=PANEL, height=10).pack()
        self._ptitle("Target region")
        self._build_targets(self.p, with_current=False)

        def ready():
            if not files:
                return False, "No backups yet", "Make a backup first, or choose another folder in Settings."
            if not self.backup_sel:
                return False, "Choose a backup", "Only backups with a matching .sha256 file are listed."
            if not self._target_letter():
                return False, "Choose a target", "The patched copy is saved next to the backup."
            return True, "Ready", "The patched copy is saved next to the backup. Nothing is flashed."
        return ready

    def _target_letter(self):
        v = self.target.get()
        if v == "custom":
            c = self.custom.get().strip().upper()
            return c if len(c) == 1 and c.isascii() and c.isalnum() else ""
        return v

    def _build_targets(self, parent, with_current):
        box = tk.Frame(parent, bg=PANEL)
        box.pack(fill="x")
        if with_current:
            sn = self.last_sn
            cur = (f"Current  {sn.decode()} · {e3tool.describe(chr(sn[3]))}" if sn else
                   "The current serial number is read and shown before anything is written.")
            tk.Label(box, text=cur, bg=PANEL, fg=DIM, font=self.f.mono_s if sn else self.f.small, anchor="w",
                     justify="left", wraplength=self.LEFT_W - 48).pack(fill="x", pady=(0, 8))
        grid = tk.Frame(box, bg=PANEL)
        grid.pack(anchor="w")
        for i, (name, letter) in enumerate(e3tool.CHOICES):
            RadioCard(grid, self, name, None, letter, self.target, self.render, width=200, height=40,
                      tag=letter, tag_color=DIM).grid(row=i // 2, column=i % 2, padx=(0, 8), pady=(0, 8))
        crow = tk.Frame(box, bg=PANEL)
        crow.pack(anchor="w")
        RadioCard(crow, self, "Custom character", None, "custom", self.target, self._focus_custom, width=200,
                  height=40).pack(side="left")
        cf = RoundField(crow, lambda p: tk.Entry(p, textvariable=self.custom, width=2, bg=BG, fg=TXT,
                                                  insertbackground=T.ACCENT, relief="flat", bd=0, font=self.f.mono_l,
                                                  justify="center", highlightthickness=0), padx=10, pady=5)
        cf.pack(side="left", padx=8)
        self.custom_entry = cf.child
        tk.Label(crow, text="only if you\nknow the value", bg=PANEL, fg=MUT, font=self.f.mono_s,
                 justify="left").pack(side="left")
        self.custom_entry.bind("<KeyRelease>", self._custom_typed)
        letter = self._target_letter()
        if with_current and self.last_sn and letter:
            new = bytearray(self.last_sn)
            new[3] = ord(letter)
            tk.Label(box, text=f"→  {new.decode()} · {e3tool.describe(letter)}", bg=PANEL, fg=T.ACCENT,
                     font=self.f.mono, anchor="w").pack(fill="x", pady=(10, 0))

    def _focus_custom(self):
        self.render()
        self.after_idle(lambda: (self.custom_entry.focus_set(), self.custom_entry.icursor("end")))

    def _custom_typed(self, _e):
        self.custom.set(self.custom.get().strip().upper()[-1:])
        self.target.set("custom")
        self._focus_custom()

    def _build_backup_list(self, parent, files):
        box = tk.Frame(parent, bg=PANEL)
        box.pack(fill="x")
        head = tk.Frame(box, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text=tail(e3tool.backups_dir(), 2), bg=PANEL, fg=MUT, font=self.f.mono_s).pack(side="left")
        Link(head, "refresh", self.render, self.f, PANEL, font=self.f.mono_s).pack(side="right")
        Link(head, "open", lambda: open_path(ensure_dir(e3tool.backups_dir())), self.f, PANEL,
             font=self.f.mono_s).pack(side="right", padx=10)
        field = RoundField(box, lambda p: tk.Listbox(p, bg=BG, fg=TXT, selectbackground=T.ACCENT_BG,
                                                     selectforeground=TXT, font=self.f.mono_s,
                                                     height=min(5, max(3, len(files))), relief="flat",
                                                     highlightthickness=0, activestyle="none", bd=0,
                                                     exportselection=False), padx=8, pady=8)
        field.pack(fill="x", pady=(6, 0))
        lb = field.child
        for fpath in files:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(fpath.stat().st_mtime))
            lb.insert("end", f" {short(fpath.name, 36):<37} {ts}")
        if not files:
            lb.insert("end", " (no backups in this folder)")
        detail = tk.Label(box, text="", bg=PANEL, fg=DIM, font=self.f.small, anchor="w")
        detail.pack(fill="x", pady=(6, 0))
        if self.backup_sel in files:
            i = files.index(self.backup_sel)
            lb.selection_set(i)
            lb.see(i)
            detail.configure(text=self._backup_detail(self.backup_sel))

        def on_sel(_e):
            sel = lb.curselection()
            if sel and sel[0] < len(files) and files[sel[0]] != self.backup_sel:
                self.backup_sel = files[sel[0]]
                self.render()
        lb.bind("<<ListboxSelect>>", on_sel)

    @staticmethod
    def _backup_detail(f):
        try:
            sn = e3tool.sn_of_backup(f)
            return f"Checksum OK · SN {sn.decode()} · {e3tool.describe(chr(sn[3]))}"
        except RuntimeError as e:
            return f"⚠ {e}"

    # ---- other stages
    def _run_summary(self):
        self._ptitle("This run", right="DRY RUN" if self.dry.get() else "", right_color=AMBER)
        self._kv(self.p, self.run_kv)

    def _render_countdown(self, a):
        self._run_summary()
        self._note("Connect the ST-Link (and its power) now if needed. Cancel stops the start.", DIM, pady=(12, 0))
        self._seq(a["plan"], state=f"STARTING IN {self.cd_left} S", state_color=AMBER)
        self._main(f"✕  CANCEL  ·  {self.cd_left}", kind="amber")
        self.ready_title.configure(text=f"Starting in {self.cd_left} s", fg=AMBER)
        self.ready_hint.configure(text="", fg=DIM)

    def _render_running(self, a):
        if not self.steps.winfo_manager():
            self.steps.pack(fill="x", pady=(10, 0))
        self._run_summary()
        self._note("Do not disconnect the ST-Link while this runs.", AMBER, pady=(12, 0))
        self._main("■  RUNNING — DO NOT DISCONNECT", kind="secondary", enabled=False)
        self._render_running_light()

    def _render_running_light(self):
        step, total, label = self.step
        t = elapsed(time.time() - self.run_started)
        frac = (max(0, step - 1) + 0.5) / max(1, total)
        self._seq(self.run_plan, step, "run", f"STEP {step}/{total} · {t}" if total else f"WORKING · {t}", AMBER,
                  (frac, AMBER))
        self.ready_title.configure(text=(label or "Working") + " …", fg=TXT)
        self.ready_hint.configure(text=self.last_msg or "Talking to the ST-Link …", fg=DIM)

    def _render_done(self, a):
        r = self.result or {}
        dry = r.get("dry")
        self._ptitle("Dry run" if dry else "Result", right=f"{self.run_seconds:.1f} s",
                     color=AMBER if dry else OK)
        tk.Label(self.p, text=r.get("title", "Done"), bg=PANEL, fg=TXT, font=self.f.h1, anchor="w").pack(fill="x")
        if r.get("msg"):
            self._note(r["msg"], DIM, pady=(4, 10))
        if r.get("kv"):
            self._kv(self.p, r["kv"])
        if r.get("sn"):
            tk.Label(self.p, text=r["sn"], bg=PANEL, fg=TXT, font=self.f.mono_l, anchor="w").pack(fill="x",
                                                                                               pady=(8, 0))
            if r.get("sn_note"):
                self._note(r["sn_note"], DIM, pady=(2, 0))
        if r.get("path"):
            self._path_row(self.p, r["path"])
        n = len(self.run_plan) or 1
        self._seq(self.run_plan or a["plan"], n, "done",
                  ("DRY RUN" if dry else "DONE") + f" · {self.run_seconds:.1f} S", AMBER if dry else OK,
                  (1.0, AMBER if dry else OK))
        self.ready_title.configure(text="✓  " + r.get("title", "Done"), fg=AMBER if dry else OK)
        self.ready_hint.configure(text="Nothing was written." if dry else "", fg=DIM)
        self._main("↺  BACK", kind="secondary")

    def _render_fail(self, a):
        step, total, _ = self.step
        self._ptitle("Failed", color=DANGER, right=f"{self.run_seconds:.1f} s")
        tk.Label(self.p, text="Something went wrong", bg=PANEL, fg=TXT, font=self.f.h1, anchor="w").pack(fill="x")
        tk.Label(self.p, text=self.error, bg=PANEL, fg=TXT, font=self.f.body, anchor="w", justify="left",
                 wraplength=self.LEFT_W - 48).pack(fill="x", pady=(6, 0))
        self._note("The full OpenOCD output is in the console and in logs/.", DIM)
        if self.run_backup:
            self._note("Backup made before the failure:", DIM)
            self._path_row(self.p, self.run_backup)
        plan = self.run_plan or a["plan"]
        self._seq(plan, max(1, step), "fail", "FAILED", DANGER, ((max(1, step) - 0.5) / max(1, len(plan)), DANGER))
        self.ready_title.configure(text="✕  Failed", fg=DANGER)
        self.ready_hint.configure(text="Fix the cause, then try again.", fg=DIM)
        self._main("↺  TRY AGAIN", kind="primary")
        if self.action_id == "e3_change" and self.run_backup:
            Button(self.extra_row, "Restore the new backup…", self.goto_restore_run_backup, self.f, kind="ghost",
                   bg=PANEL, small=True, expand=True, height=34).pack(fill="x", pady=(8, 0))
        if platform.system() == "Linux" and "no permission" in self.error:
            Button(self.extra_row, "Set up ST-Link access…", self.setup_stlink_access, self.f, kind="ghost",
                   bg=PANEL, small=True, expand=True, height=34).pack(fill="x", pady=(8, 0))

    def setup_stlink_access(self):
        """Linux: installs the udev rule that lets the logged-in user use the ST-Link (asks for the password with
        pkexec). The rule is copied to the data folder first: root cannot read inside a mounted AppImage."""
        rules = core.ROOT / "linux" / "99-stlink.rules"
        target = "/etc/udev/rules.d/99-stlink.rules"
        manual = (f"sudo cp \"{rules}\" {target}\nsudo udevadm control --reload-rules\nsudo udevadm trigger")
        pk = shutil.which("pkexec")
        if not rules.exists() or not pk:
            Dialog.info(self, "ST-Link access", "Run these commands once in a terminal, then unplug the ST-Link and "
                                                "plug it in again:", detail=manual)
            return
        tmp = ensure_dir(core.TEMP) / "99-stlink.rules"
        tmp.write_bytes(rules.read_bytes())
        script = f'install -m 644 "$1" {target} && udevadm control --reload-rules && udevadm trigger'

        def work():
            try:
                r = subprocess.run([pk, "sh", "-c", script, "sh", str(tmp)], capture_output=True, text=True,
                                   timeout=300, env=tf_ui.external_env())
                self.q.put(("udev", (r.returncode, (r.stderr or "").strip())))
            except Exception as e:  # noqa
                self.q.put(("udev", (-1, str(e))))
        self.console_line("Installing the ST-Link udev rule (password prompt) …", "msg")
        threading.Thread(target=work, daemon=True).start()

    def _udev_done(self, payload):
        rc, err = payload
        if rc == 0:
            self.console_line(f"udev rule installed: /etc/udev/rules.d/99-stlink.rules", "ok")
            Dialog.info(self, "ST-Link access", "Done. Unplug the ST-Link, plug it in again and try again.")
        else:
            self.console_line(f"udev rule not installed ({err or rc})", "warn")
            Dialog.info(self, "ST-Link access", "Not installed (cancelled or no permission). You can also run "
                                                "setup_linux.sh, or these commands in a terminal:",
                        detail=f"sudo cp linux/99-stlink.rules /etc/udev/rules.d/\nsudo udevadm control "
                               f"--reload-rules\nsudo udevadm trigger")

    def _path_row(self, parent, path):
        RoundField(parent, lambda p: tk.Label(p, text=short(path, 56), bg=BG, fg=TXT, font=self.f.mono_s,
                                              anchor="w")).pack(fill="x", pady=(10, 0))
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=(6, 0))
        Link(row, "open folder", lambda: open_path(pathlib.Path(path).parent), self.f, PANEL,
             font=self.f.mono_s).pack(side="left")
        Link(row, "copy path", lambda: self._copy(str(path)), self.f, PANEL, font=self.f.mono_s).pack(side="left",
                                                                                                    padx=12)

    def show_wiring(self):
        a = ALL_ACTIONS[self.action_id]
        ble = bool(a.get("ble"))
        path = core.diagram_path("ble" if ble else "drv", self.brand, self.ble_key() if ble else self.model,
                                 self.effective_chip())
        if path and path.suffix.lower() == ".png":
            try:
                DiagramViewer(self, path, self.wiring_text(ble))
                return
            except tk.TclError:
                pass
        if path:
            open_path(path)
        Dialog.info(self, "Wiring", self.wiring_text(ble))

    # ---------------------------------------------------------------- start / countdown
    def start(self):
        if self.busy or self.stage != "idle":
            return
        a = ALL_ACTIONS[self.action_id]
        if not self.ready_state[0]:
            return
        try:
            job = self.make_job(a)
        except (ValueError, RuntimeError, FileNotFoundError) as e:
            Dialog.info(self, "Check the input", str(e), accent=AMBER)
            return
        if job is None:
            return
        self.save_cfg()
        if a.get("offline") or self.countdown <= 0 or self.dry.get():
            self.run_job(*job)
            return
        self.stage = "countdown"
        self.cd_left = self.countdown
        self.cd = Countdown(self.after, self.after_cancel, self.countdown, self._cd_tick, lambda: self.run_job(*job))
        self.render()
        self.cd.start()

    def _cd_tick(self, n):
        self.cd_left = n
        if self.stage != "countdown":
            return
        self.cd_value.configure(text=f"{n} s", fg=AMBER)
        self.seq_state.configure(text=f"STARTING IN {n} S")
        self.ready_title.configure(text=f"Starting in {n} s")
        self.start_btn.set_text(f"✕  CANCEL  ·  {n}")
        self.update_status()

    def cancel_countdown(self):
        if self.cd:
            self.cd.cancel()
        self.stage = "idle"
        self.console_line("Start cancelled.", "warn")
        self.render()

    def _base_kv(self, chip=None):
        return [("Scooter", self.item()["name"]), ("Chip", chip or self._chip_text())]

    def make_job(self, a):
        """Checks inputs (raises ValueError), asks for confirmation, returns (fn, on_done) or None.
        Also sets run_plan and run_kv for the run view."""
        dry, aid = bool(self.dry.get()), a["id"]
        brand, model = self.brand, self.model
        it = self.item()
        self.run_plan = list(a["plan"])
        self.run_kv = self._base_kv()
        if aid == "check":
            chip = default_chip(it) if chip_mode(it) == "fixed" else self.chip
            return (lambda log, prog: core.check_drv(brand, model, chip, dry_run=dry, log=log, progress=prog),
                    self.done_check)
        if aid == "flash":
            fixed = it.get("sn_fixed")
            if self.write_ud.get():
                sn = fixed or self.sn_var.get().strip().upper()
                if not fixed:
                    core.validate_sn(sn, self.sn_format())
                km = float(self.km_var.get().replace(",", ".") or 0)
            else:
                sn, km = fixed or it.get("sn_placeholder") or core.DEFAULT_SN, 0.0
            fw = self.fw_path if it.get("bring_fw") else None
            det = self.detected_for()
            if chip_mode(it) == "auto" and self.chip == "auto":
                variant, expect = "auto", (det["family"] if det else None)
            else:
                variant, expect = self.effective_chip(), None
            eff = expect or (variant if variant != "auto" else None)
            boot, fwp = None, None
            if eff:
                boot, fwp, _ = core.drv_files(brand, model, eff, fw)
            self.run_kv = self._base_kv() + [("Serial number", sn), ("Mileage", f"{km:g} km"),
                                             ("Firmware", fwp.name if fwp else (pathlib.Path(fw).name if fw else
                                                                                it.get("drv") or "?"))]
            if not dry:
                detail = (f"{it['name']}  ·  {CHIP_LABEL[eff] if eff else 'chip detected at start'}\n"
                          + (f"Bootloader {boot.name}\nFirmware   {fwp.name}\n" if boot else "")
                          + f"SN         {sn}\nMileage    {km:g} km")
                if not Dialog.ask(self, "Flash ESC?", "The controller is erased and flashed. Its previous firmware "
                                                      "and user data are replaced.", ok="Flash", detail=detail):
                    return None
            return (lambda log, prog: core.flash_drv(model, brand, variant, sn=sn, mileage_km=km, firmware_file=fw,
                                                     expect=expect, dry_run=dry, log=log, progress=prog),
                    self.done_flash)
        if aid == "ble_check":
            fast = bool(self.ble_fast.get())
            self.run_kv = [("Scooter", it["name"]), ("Module", "nRF51822"), ("Fast mode", "on" if fast else "off")]
            return (lambda log, prog: core.test_connection_ble(fast, dry, log, prog), self.done_ble_check)
        if aid == "ble_flash":
            name = self.ble_name.get().strip() or None
            if name:
                core.validate_ble_name(name)
            fast, key = bool(self.ble_fast.get()), self.ble_key()
            bitem = core.PROFILES["ble"]["models"][brand][key]
            shown = name or core.PROFILES["ble"]["default_name"][brand]
            self.run_kv = [("Scooter", it["name"]), ("Firmware", bitem["fw"]), ("Name", shown),
                           ("Fast mode", "on" if fast else "off")]
            if not dry and not Dialog.ask(self, "Flash BLE?", "The BLE module is erased and flashed again.",
                                          ok="Flash", detail=f"{bitem['name']}\nName  {shown}"):
                return None
            return (lambda log, prog: core.flash_ble(brand, key, name=name, fast=fast, dry_run=dry, log=log,
                                                     progress=prog), self.done_ble_flash)
        self.run_kv = [("Scooter", it["name"]), ("Chip", "AT32F415")]
        if aid == "e3_check":
            return (lambda log, prog: e3tool.check_connection(dry, log, prog), self.done_e3_check)
        if aid == "e3_read":
            return (lambda log, prog: e3tool.read_current_sn(dry, log, prog), self.done_e3_read)
        if aid == "e3_backup":
            self.run_kv.append(("Saves to", tail(e3tool.backups_dir(), 3)))
            return (lambda log, prog: e3tool.do_backup(dry, log, prog), self.done_e3_backup)
        if aid == "e3_change":
            self.pending_letter = self._target_letter()
            if not self.pending_letter:
                return None
            self.run_kv.append(("Target", f"{self.pending_letter} · {e3tool.describe(self.pending_letter)}"))
            return (lambda log, prog: e3tool.read_current_sn(
                dry, log, lambda i, n, l: prog(1, 5, "Reading the current serial number")), self.e3_change_confirm)
        if aid == "e3_restore":
            f = self.backup_sel
            e3tool.verified_data(f)
            self.run_kv.append(("Backup", short(f.name, 34)))
            if not dry and not Dialog.ask(self, "Restore backup?",
                                          "The complete flash of the scooter is overwritten with this backup and "
                                          "verified afterwards. Do not disconnect anything while it runs.",
                                          ok="Restore", kind="amber", accent=AMBER,
                                          detail=f"{f.name}\n{self._backup_detail(f)}"):
                return None
            return (lambda log, prog: e3tool.do_restore(f, dry, log, prog), self.done_e3_restore)
        if aid == "e3_patched":
            f, letter = self.backup_sel, self._target_letter()
            self.run_kv = [("Backup", short(f.name, 34)), ("Target", f"{letter} · {e3tool.describe(letter)}")]

            def job(log, prog):
                prog(1, 1, "Creating the patched file")
                out = e3tool.full_patched_file(f, letter)
                log(f"Patched copy saved: {out}")
                return out
            return (job, self.done_e3_patched)
        return None

    # ---------------------------------------------------------------- running jobs
    def run_job(self, fn, on_done, keep_step=False):
        self.busy = True
        self.stage = "running"
        if not keep_step:
            self.step = (0, len(self.run_plan), "")
            self.run_started = time.time()
            self.last_msg = ""
            self.run_backup = None
            self.console_line(f"── {ALL_ACTIONS[self.action_id]['title']}  ·  {self.item()['name']}  ·  "
                              f"{time.strftime('%H:%M:%S')}" + ("  ·  DRY RUN" if self.dry.get() else "") + " ──",
                              "head")
        self.render()

        def work():
            try:
                result = fn(lambda t: self.q.put(("log", str(t))),
                            lambda i, n, label: self.q.put(("progress", (i, n, label))))
                self.q.put(("done", (result, on_done)))
            except (RuntimeError, ValueError, FileNotFoundError) as e:
                self.q.put(("fail", str(e)))
            except Exception as e:  # noqa
                self.q.put(("raw", traceback.format_exc()))
                self.q.put(("fail", f"Unexpected error: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "raw":
                    for line in str(payload).splitlines() or [""]:
                        tag = ("cmd" if line.startswith("$ ") else "err" if line.startswith("Error") else
                               "warn" if line.startswith("Warn") else "raw")
                        self.console_line(line, tag)
                elif kind == "log":
                    ok = payload.startswith(("Backup saved", "Verified", "Written", "Backup restored", "Done",
                                             "Patched copy", "Connection OK", "Saved", "Detected chip"))
                    warn = payload.startswith(("Warning", "Step", "Note", "(Dry run", "Read protection", "GD32E",
                                               "Serial number and mileage"))
                    self.console_line(payload, "ok" if ok else "warn" if warn else "msg")
                    if payload.startswith("Backup saved: "):
                        self.run_backup = payload[len("Backup saved: "):].strip()
                    if not payload.startswith(("Step ", "SHA-256")):
                        self.last_msg = payload.strip()
                        if self.stage == "running":
                            self.ready_hint.configure(text=self.last_msg)
                elif kind == "progress":
                    i, n, label = payload
                    if n != len(self.run_plan):
                        self.run_plan = (self.run_plan + [f"Step {k + 1}" for k in range(len(self.run_plan), n)])[:n]
                    self.step = payload
                    if self.stage == "running":
                        self._render_running_light()
                elif kind == "udev":
                    self._udev_done(payload)
                elif kind == "version":
                    self.oocd_version = payload
                    self.update_status()
                elif kind == "done":
                    result, on_done = payload
                    self.busy = False
                    self.run_seconds = time.time() - self.run_started
                    on_done(result)
                elif kind == "fail":
                    self.busy = False
                    self.run_seconds = time.time() - self.run_started
                    self.error = payload
                    self.stage = "fail"
                    self.last_action = f"{ALL_ACTIONS[self.action_id]['title']} failed {time.strftime('%H:%M')}"
                    self.console_line("ERROR: " + payload, "err")
                    self.render()
        except queue.Empty:
            pass
        self.after(60, self.poll)

    def tick(self):
        if self.stage == "running":
            self._render_running_light()
        self.after(450, self.tick)

    def finish(self, title, msg="", **extra):
        dry = bool(self.dry.get())
        if dry:
            title, msg = "Dry run finished", "Nothing was written. The OpenOCD commands are in the console."
            extra = {}
        self.stage = "done"
        self.result = dict(title=title, msg=msg, dry=dry, **extra)
        self.last_action = f"{ALL_ACTIONS[self.action_id]['title']} {'dry run' if dry else 'OK'} " \
                           f"{time.strftime('%H:%M')}"
        self.render()

    def back(self):
        self.stage = "idle"
        self.render()

    def goto_restore_run_backup(self):
        path = pathlib.Path(self.run_backup)
        self.stage = "idle"
        self.select("e3_restore")
        if path in e3tool.list_backups():
            self.backup_sel = path
            self.render()

    # ---------------------------------------------------------------- results
    def _probe_kv(self, info):
        rdp = info.get("rdp", "?")
        kv = [("ST-Link", info.get("stlink", "?")),
              ("Target voltage", f"{info.get('voltage', '?')} V"),
              ("CPU", info.get("cpu", "?")),
              ("Device id", info.get("device_id", "?")),
              ("Flash", f"{info.get('flash_kb', '?')} KB"),
              ("Read protection", rdp, AMBER if rdp == "on" else OK if rdp == "off" else None)]
        if info.get("known"):
            kv.append(("Known as", info["known"], DIM))
        return kv

    def done_check(self, info):
        dry = self.dry.get()
        det = info.get("detected")
        if det and det != "unknown" and not dry:
            self.detected = dict(key=self.key(), family=det, known=info.get("known"), idcode=info.get("idcode"))
        if not dry:
            self.last_check = dict(key=self.key(), time=time.strftime("%H:%M"), variant=info.get("variant", "?"),
                                   rdp=info.get("rdp"), userdata=info.get("userdata"))
        kv = []
        if det:
            col = T.ACCENT if det == info.get("variant") else AMBER
            note = " (adopted)" if self.chip == "auto" and chip_mode(self.item()) == "auto" else \
                "" if det == info.get("variant") else f" (selected: {info.get('variant', '?').upper()})"
            kv.append(("Chip", det.upper() + note, col))
        else:
            kv.append(("Chip", info.get("variant", "?").upper()))
        probe = self._probe_kv(info)
        kv += [r for r in probe if r[0] == "Read protection"]
        ud = info.get("userdata")
        path = None
        if ud:
            kv += [("Serial number", ud.get("sn") or "(empty)", T.ACCENT if ud.get("sn") else MUT),
                   ("Mileage", f"{ud['km']:g} km" if ud.get("km") is not None else "?"),
                   ("UID", ud.get("uid", "?"))]
            path = ud.get("path")
        kv += [r for r in probe if r[0] != "Read protection"]
        if ud:
            msg = "Serial number and mileage read; the dump is saved."
        elif info.get("rdp") == "on":
            msg = "Read protection is on (normal for a stock ESC), so serial number and mileage can't be read. " \
                  "Flashing removes it with a full erase."
        else:
            msg = "The ST-Link and the controller respond."
        self.finish("Connected", msg, kv=kv, path=path)

    def done_flash(self, r):
        kv = [("Chip", r["variant"].upper()), ("Bootloader", r["bootloader"]), ("Firmware", r["firmware"]),
              ("Serial number", r.get("sn") or "—"), ("Mileage", f"{(r.get('km') or 0):g} km"),
              ("Verified", f"{r['verified']} bytes", OK)]
        note = self.item().get("after_note")
        self.finish("ESC flashed", note or "Disconnect the ST-Link, reconnect the battery and switch the scooter on.",
                    kv=kv)

    def done_ble_check(self, info):
        kv = [("ST-Link", info.get("stlink", "?")), ("Target voltage", f"{info.get('voltage', '?')} V"),
              ("CPU", info.get("cpu", "?"))]
        self.finish("BLE module found", "The ST-Link and the nRF51 respond.", kv=kv)

    def done_ble_flash(self, r):
        self.finish("BLE flashed", "Disconnect the ST-Link, reconnect the battery and switch the scooter on.",
                    kv=[("Firmware", r["firmware"]), ("Name", r["name"])])

    def done_e3_check(self, info):
        msg = ("Read protection is ON: a backup would only contain 00/FF. TorqueFlasher never unlocks an E3."
               if info.get("rdp") == "on" else "The ST-Link and the controller respond.")
        self.finish("Connected", msg, kv=self._probe_kv(info))

    def done_e3_read(self, sn: bytes):
        if not self.dry.get():
            self.last_sn = sn
            self.console_line(f"SN: {sn.decode()}  ({e3tool.describe(chr(sn[3]))})", "ok")
        self.finish("Serial number read", "", sn=sn.decode(),
                    sn_note=f"4th character {chr(sn[3])} · {e3tool.describe(chr(sn[3]))}")

    def done_e3_backup(self, path):
        self.finish("Backup saved", "Keep this file safe — it is your way back.", path=str(path))

    def e3_change_confirm(self, sn: bytes):
        letter = self.pending_letter
        if self.dry.get():
            self.run_job(lambda log, prog: e3tool.change_sn(letter, True, log, lambda i, n, l: prog(i + 1, n + 1, l)),
                         self.done_e3_change, keep_step=True)
            return
        self.last_sn = sn
        cur = chr(sn[3])
        if letter == cur:
            self.stage = "idle"
            self.render()
            Dialog.info(self, "Nothing to change", f"The serial number already uses character {letter}.")
            return
        new = bytearray(sn)
        new[3] = ord(letter)
        extra, accent = "", AMBER
        if cur in e3tool.LETTERS and letter in e3tool.LETTERS and \
                e3tool.LETTERS[cur][0] != e3tool.LETTERS[letter][0]:
            extra, accent = "\n\nWarning: this switches between E3 and E3 Pro.", DANGER
        if letter not in e3tool.LETTERS:
            extra += f"\n\n{letter!r} is not in the known list. Only continue if you know the value for sure."
            accent = DANGER
        self.stage = "running"
        self.busy = True
        self.step = (1, 5, "Waiting for confirmation")
        self.last_msg = "Confirm the change in the dialog."
        self._render_running_light()
        ok = Dialog.ask(self, "Change serial number?",
                        "A full backup is made first. Then both user-data pages are rewritten and verified." + extra,
                        ok="Change", kind="amber", accent=accent,
                        detail=f"{sn.decode()}  ·  {e3tool.describe(cur)}\n→ {new.decode()}  ·  "
                               f"{e3tool.describe(letter)}")
        self.busy = False
        if not ok:
            self.console_line("Cancelled, nothing changed.", "warn")
            self.stage = "idle"
            self.render()
            return
        self.run_job(lambda log, prog: e3tool.change_sn(letter, False, log, lambda i, n, l: prog(i + 1, n + 1, l)),
                     self.done_e3_change, keep_step=True)

    def done_e3_change(self, result):
        backup, _out, new_sn = result
        if not self.dry.get():
            self.last_sn = new_sn
        self.finish("Serial number changed", "Written and verified. Disconnect the ST-Link, reconnect the battery "
                                             "and switch the scooter on.",
                    sn=new_sn.decode(), sn_note=e3tool.describe(chr(new_sn[3])), path=str(backup))

    def done_e3_restore(self, _r):
        self.last_sn = None
        self.finish("Backup restored", "Written and verified. Disconnect the ST-Link, reconnect the battery and "
                                       "switch the scooter on.")

    def done_e3_patched(self, out):
        self.finish("File created", "Nothing was written to the scooter.", path=str(out))

    # ---------------------------------------------------------------- console
    def console_line(self, text, tag="raw"):
        self.console_buf.append((text, tag))
        self.text.configure(state="normal")
        self.text.insert("end", text + "\n", tag)
        if int(self.text.index("end-1c").split(".")[0]) > 6000:
            self.text.delete("1.0", "1000.0")
        self.text.see("end")
        self.text.configure(state="disabled")

    def copy_console(self):
        self._copy(self.text.get("1.0", "end-1c"))

    def clear_console(self):
        self.console_buf.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _copy(self, s):
        self.clipboard_clear()
        self.clipboard_append(s)
        self.st_info.configure(text="copied to clipboard")
        self.after(1600, self.update_status)

    # ---------------------------------------------------------------- settings / info
    def open_settings(self, page="settings"):
        if self.busy or self.stage == "countdown":
            return
        d = SettingsDialog(self, page)
        self.wait_window(d)
        self.save_cfg()
        self.refresh_version()
        if self.stage == "idle":
            self.render()
        else:
            self.update_status()

    def open_info(self):
        self.open_settings("info")

    def on_close(self):
        if self.busy and not Dialog.ask(self, "Operation running",
                                        "Quitting now can leave the controller half-written. Quit anyway?",
                                        ok="Quit", kind="danger", accent=DANGER):
            return
        self.save_cfg()
        self.destroy()


def main():
    if platform.system() == "Windows":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa
            pass
        try:  # own taskbar entry with our icon, instead of being grouped under python.exe
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("emilian04.TorqueFlasher")
        except Exception:  # noqa
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
