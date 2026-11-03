"""tf_ui: TorqueFlasher's widgets and theme (Tkinter only, no extra packages).

Dark "workbench" look: near-black surfaces, monospace labels, one accent color. The accent can be changed at
runtime (Settings); widgets read it from T when they draw, so the app only has to rebuild its frames."""
from __future__ import annotations

import os
import pathlib
import platform
import shutil
import subprocess
import tkinter as tk
import tkinter.font as tkfont

# ----------------------------------------------------------------------------------------------- palette
BG, BG2 = "#0B0B0C", "#0F0F11"
PANEL, PANEL2, ELEV = "#141416", "#1A1A1D", "#222226"
LINE, LINE2 = "#222225", "#2E2E34"
TXT, DIM, MUT = "#E6E6E6", "#9A9AA3", "#6E6E77"
AMBER, OK, DANGER, INFO = "#FFB224", "#5EE08C", "#FF5468", "#5AA9FF"
CONSOLE_BG = "#09090A"
STATUS_BG = "#111113"
INK = "#0B0B0C"  # text on filled accent / amber surfaces


def mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


ACCENTS = {  # key -> (label, color)
    "lime": ("Lime", "#B6F23E"),
    "cyan": ("Cyan", "#4FD8F0"),
    "violet": ("Violet", "#A99BFF"),
    "pink": ("Pink", "#FF7AB6"),
    "mono": ("Mono", "#E6E6E6"),
}
DEFAULT_ACCENT = "lime"


class T:
    """The current accent. Read it at draw time (T.ACCENT), never copy it into a module constant."""
    name = DEFAULT_ACCENT
    ACCENT = ACCENTS[DEFAULT_ACCENT][1]
    ACCENT_HI = ACCENT
    ACCENT_FG = INK
    ACCENT_DIM = ACCENT
    ACCENT_BG = ACCENT


def set_accent(name: str | None) -> str:
    name = name if name in ACCENTS else DEFAULT_ACCENT
    T.name = name
    T.ACCENT = ACCENTS[name][1]
    T.ACCENT_HI = mix(T.ACCENT, "#FFFFFF", 0.28)
    T.ACCENT_DIM = mix(T.ACCENT, CONSOLE_BG, 0.42)
    T.ACCENT_BG = mix(T.ACCENT, PANEL, 0.86)
    return name


set_accent(DEFAULT_ACCENT)


def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


# ----------------------------------------------------------------------------------------------- helpers
def short(p, n=64) -> str:
    s = str(p)
    return s if len(s) <= n else s[: n // 2 - 1] + "…" + s[-(n // 2):]


def tail(p, n=2) -> str:
    parts = pathlib.Path(p).parts
    return str(p) if len(parts) <= n + 1 else "…/" + "/".join(parts[-n:])


def ensure_dir(p) -> pathlib.Path:
    p = pathlib.Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def external_env() -> dict:
    """Environment for system programs (xdg-open, xprop, pkexec). In the AppImage, PyInstaller points
    LD_LIBRARY_PATH at its bundled libraries; system programs must get the original value back."""
    env = dict(os.environ)
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        env["LD_LIBRARY_PATH"] = orig
    elif getattr(__import__("sys"), "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    return env


def open_path(p):
    p = str(p)
    try:
        if platform.system() == "Windows":
            os.startfile(p)  # noqa
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", p], env=external_env())
        else:
            subprocess.Popen(["xdg-open", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env=external_env())
    except Exception:  # noqa
        pass


def elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def fit(font: tkfont.Font, text: str, width: int) -> str:
    """Shortens text with … so it fits into width pixels."""
    if font.measure(text) <= width:
        return text
    while len(text) > 2 and font.measure(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _dwm_dark(win):
    import ctypes
    hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
    dwm = ctypes.windll.dwmapi
    on = ctypes.c_int(1)
    for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 before Windows 10 20H1)
        if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
            break
    for attr, color in ((35, BG), (34, LINE2), (36, TXT)):  # caption, border, text color: Windows 11 only
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        c = ctypes.c_int(r | g << 8 | b << 16)
        dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(c), ctypes.sizeof(c))
    # repaint the frame now: SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x1 | 0x2 | 0x4 | 0x10 | 0x20)


def dark_titlebar(win):
    """Dark window title bar. Windows 11: the app background color; Windows 10 (1809+): the dark system variant;
    Linux/X11: asks GNOME (Mutter) for the dark decoration, needs xprop; KDE and others follow the system theme.
    Call it right after creating the window. Does nothing where none of this is available."""
    try:
        if platform.system() == "Windows":
            def on_map(e):  # the native frame exists once the window is mapped
                if e.widget is win and not getattr(win, "_tf_dark", False):
                    win._tf_dark = True
                    apply_window_icon(win, default=win is win._root())
                    try:
                        _dwm_dark(win)
                    except Exception:  # noqa
                        pass
            win.bind("<Map>", on_map, add="+")
            if win.winfo_ismapped():
                on_map(type("E", (), {"widget": win})())
        elif win.tk.call("tk", "windowingsystem") == "x11" and shutil.which("xprop"):
            # before the window is mapped, 'wm frame' is the toplevel window the window manager will decorate
            subprocess.Popen(["xprop", "-id", win.wm_frame(), "-f", "_GTK_THEME_VARIANT", "8u", "-set",
                              "_GTK_THEME_VARIANT", "dark"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env=external_env())
    except Exception:  # noqa - purely cosmetic
        pass


def icon_dir(assets: pathlib.Path, accent: str | None = None) -> pathlib.Path:
    """Folder with the icon files in the given accent color (assets/accents/<name>), else the default ones."""
    d = assets / "accents" / (accent or "")
    return d if accent and (d / "icon-32.png").exists() else assets


_ICON = {"imgs": [], "ico": None}  # the current app icon (PhotoImages must stay referenced)


def set_window_icon(win, assets: pathlib.Path, accent: str | None = None):
    """App icon in the accent color for the window, the taskbar and all dialogs (icon-*.png; on Windows also
    icon.ico). The icon of the .exe / AppImage file itself is fixed when it is built."""
    d = icon_dir(assets, accent)
    try:
        _ICON["imgs"] = [tk.PhotoImage(master=win, file=str(d / f"icon-{s}.png")) for s in (256, 64, 32, 16)
                         if (d / f"icon-{s}.png").exists()]
    except Exception:  # noqa
        _ICON["imgs"] = []
    _ICON["ico"] = d / "icon.ico" if (d / "icon.ico").exists() else None
    apply_window_icon(win, default=True)
    return bool(_ICON["imgs"])


def apply_window_icon(win, default=False):
    """Sets the app icon on one window; default=True also makes it the icon of all later windows. On Windows this
    only works once the window has been shown (a hidden main window has no native frame yet), so dark_titlebar()
    calls it again for every window when it appears."""
    if platform.system() == "Windows" and _ICON["ico"]:
        try:  # classic .ico (BMP entries); the PNG icon below is set last and wins where both work
            if default:
                win.iconbitmap(default=str(_ICON["ico"]))
            else:
                win.iconbitmap(str(_ICON["ico"]))
        except Exception:  # noqa
            pass
    if _ICON["imgs"]:
        try:
            win.iconphoto(default, *_ICON["imgs"])
        except Exception:  # noqa
            pass


def bind_all_children(widget, seq, fn):
    widget.bind(seq, fn, add="+")
    for ch in widget.winfo_children():
        bind_all_children(ch, seq, fn)


class Fonts:
    def __init__(self, root):
        fams = set(tkfont.families(root))

        def first(*names, fallback):
            for n in names:
                if n in fams:
                    return n
            return tkfont.nametofont(fallback).actual("family")

        system = platform.system()
        if system == "Windows":
            ui = first("Segoe UI Variable Text", "Segoe UI", fallback="TkDefaultFont")
            mono = first("Cascadia Mono", "Consolas", fallback="TkFixedFont")
        elif system == "Darwin":
            ui = first("SF Pro Text", "Helvetica Neue", fallback="TkDefaultFont")
            mono = first("SF Mono", "Menlo", fallback="TkFixedFont")
        else:
            ui = first("Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans", "Liberation Sans",
                       fallback="TkDefaultFont")
            mono = first("JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono", "Liberation Mono",
                         "Ubuntu Mono", fallback="TkFixedFont")
        F = tkfont.Font
        self.wordmark = F(root, family=mono, size=13, weight="bold")
        self.wordmark_l = F(root, family=mono, size=20, weight="bold")
        self.big = F(root, family=ui, size=18, weight="bold")
        self.big_s = F(root, family=ui, size=11, weight="bold")
        self.h1 = F(root, family=ui, size=15, weight="bold")
        self.body = F(root, family=ui, size=10)
        self.body_b = F(root, family=ui, size=10, weight="bold")
        self.small = F(root, family=ui, size=9)
        self.small_b = F(root, family=ui, size=9, weight="bold")
        self.eyebrow = F(root, family=mono, size=8, weight="bold")
        self.btn = F(root, family=mono, size=10, weight="bold")
        self.btn_s = F(root, family=mono, size=9, weight="bold")
        self.tab = F(root, family=mono, size=9, weight="bold")
        self.mono = F(root, family=mono, size=9)
        self.mono_m = F(root, family=mono, size=11)
        self.mono_s = F(root, family=mono, size=8)
        self.mono_l = F(root, family=mono, size=17, weight="bold")
        self.icon = F(root, family=ui, size=13)
        self.chip = F(root, family=ui, size=11, weight="bold")
        self.search = F(root, family=ui, size=11)


def eyebrow(parent, text, fonts: Fonts, bg, fg=MUT):
    return tk.Label(parent, text=text.upper(), bg=bg, fg=fg, font=fonts.eyebrow)


# ----------------------------------------------------------------------------------------------- buttons
class Button(tk.Canvas):
    """Flat button. kind: primary | secondary | ghost | amber | danger. expand=True: as wide as its slot."""

    def __init__(self, parent, text, command, fonts: Fonts, kind="primary", bg=PANEL, small=False, expand=False,
                 height=None, width=None):
        self.f = fonts.btn_s if small else fonts.btn
        self.h = height or (30 if small else 44)
        self.padx = 14 if small else 22
        self.kind, self.command, self.text, self.expand, self.fixed_w = kind, command, text, expand, width
        self.enabled, self.hover = True, False
        super().__init__(parent, width=width or (1 if expand else self._width()), height=self.h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Configure>", lambda e: self._draw())
        self._draw()

    def _width(self):
        return self.fixed_w or self.f.measure(self.text) + 2 * self.padx

    def _set_hover(self, v):
        self.hover = v
        self._draw()

    def _click(self, e):
        if self.enabled and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def set_enabled(self, v: bool):
        self.enabled = v
        self.configure(cursor="hand2" if v else "arrow")
        self._draw()

    def set_text(self, text, kind=None):
        self.text = text
        if kind:
            self.kind = kind
        if not self.expand and not self.fixed_w:
            self.configure(width=self._width())
        self._draw()

    def _colors(self):
        bg, h = self["bg"], self.hover
        if not self.enabled:
            c = mix(ELEV, bg, 0.3)
            return c, c, MUT
        if self.kind == "primary":
            c = T.ACCENT_HI if h else T.ACCENT
            return c, c, T.ACCENT_FG
        if self.kind == "secondary":
            c = "#2B2B31" if h else ELEV
            return c, LINE2, TXT
        if self.kind == "ghost":
            return (ELEV if h else bg), LINE2, (TXT if h else DIM)
        if self.kind == "amber":
            return mix(AMBER, bg, 0.78 if h else 0.86), mix(AMBER, bg, 0.3), AMBER
        if self.kind == "danger":
            c = mix(DANGER, "#FFFFFF", 0.2) if h else DANGER
            return c, c, "#FFFFFF"
        return ELEV, LINE2, TXT

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() if self.expand else self._width()
        if w < 8:
            w = self._width()
        fill, outline, fg = self._colors()
        round_rect(self, 1, 1, w - 1, self.h - 1, (self.h - 2) / 2, fill=fill, outline=outline)
        self.create_text(w / 2, self.h / 2, text=fit(self.f, self.text, w - 16), fill=fg, font=self.f)


class Badge(tk.Canvas):
    """Small outlined tag with a dot, e.g. DRY RUN. Empty text hides it."""

    def __init__(self, parent, fonts: Fonts, bg=BG, command=None):
        self.f = fonts.eyebrow
        super().__init__(parent, width=1, height=24, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2" if command else "arrow")
        if command:
            self.bind("<Button-1>", lambda e: command())

    def set(self, color, text, filled=False):
        self.delete("all")
        if not text:
            self.configure(width=1)
            return
        w = self.f.measure(text) + 34
        self.configure(width=w)
        bg = self["bg"]
        if filled:
            round_rect(self, 1, 1, w - 1, 23, 11, fill=color, outline=color)
            self.create_oval(11, 9, 17, 15, fill=INK, outline="")
            self.create_text(23, 12, text=text, fill=INK, font=self.f, anchor="w")
        else:
            round_rect(self, 1, 1, w - 1, 23, 11, fill=mix(color, bg, 0.88), outline=mix(color, bg, 0.5))
            self.create_oval(11, 9, 17, 15, fill=color, outline="")
            self.create_text(23, 12, text=text, fill=color, font=self.f, anchor="w")


class Led(tk.Canvas):
    def __init__(self, parent, bg):
        super().__init__(parent, width=12, height=12, bg=bg, highlightthickness=0, bd=0)

    def set(self, color, bg=None):
        if bg:
            self.configure(bg=bg)
        self.delete("all")
        self.create_oval(1, 1, 11, 11, fill=mix(color, self["bg"], 0.7), outline="")
        self.create_oval(3, 3, 9, 9, fill=color, outline="")


class Link(tk.Label):
    def __init__(self, parent, text, command, fonts: Fonts, bg, color=None, font=None):
        self.color = color or T.ACCENT
        super().__init__(parent, text=text, bg=bg, fg=self.color, font=font or fonts.small_b, cursor="hand2")
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self.configure(fg=mix(self.color, "#ffffff", 0.35)))
        self.bind("<Leave>", lambda e: self.configure(fg=self.color))


class Tooltip:
    def __init__(self, widget, text, font, offset=(-10, 6)):
        self.widget, self.text, self.font, self.tip, self.offset = widget, text, font, None, offset
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<Button-1>", self.hide, add="+")

    def show(self, _e=None, x=None, y=None, text=None):
        self.hide()
        text = text or self.text
        if not text:
            return
        x = self.widget.winfo_rootx() + self.offset[0] if x is None else x
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.offset[1] if y is None else y
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=text, bg=ELEV, fg=TXT, padx=9, pady=5, font=self.font, justify="left",
                 wraplength=360, highlightthickness=1, highlightbackground=LINE2).pack()

    def hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class IconButton(tk.Canvas):
    """Round icon button (⚙, ⓘ)."""

    def __init__(self, parent, text, command, fonts: Fonts, bg, tooltip="", size=34):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.f, self.size, self.hover = text, fonts.icon, size, False
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self._h(True), add="+")
        self.bind("<Leave>", lambda e: self._h(False), add="+")
        if tooltip:
            Tooltip(self, tooltip, fonts.small)
        self.draw()

    def _h(self, v):
        self.hover = v
        self.draw()

    def draw(self):
        self.delete("all")
        s = self.size
        self.create_oval(1, 1, s - 1, s - 1, fill=ELEV if self.hover else self["bg"], outline=LINE2)
        self.create_text(s / 2, s / 2, text=self.text, fill=TXT if self.hover else DIM, font=self.f)


class Pill(tk.Canvas):
    """Static pill-shaped label, e.g. the version tag."""

    def __init__(self, parent, text, font, bg, fg=MUT, outline=LINE2, fill=None, padx=10, height=22):
        w = font.measure(text) + 2 * padx
        super().__init__(parent, width=w, height=height, bg=bg, highlightthickness=0, bd=0)
        round_rect(self, 1, 1, w - 1, height - 1, (height - 2) / 2, fill=fill or bg, outline=outline)
        self.create_text(w / 2, height / 2, text=text, fill=fg, font=font)


class Toggle(tk.Frame):
    """Switch + label. var is a tk.BooleanVar; command is called after a change."""

    def __init__(self, parent, text, var: tk.BooleanVar, fonts: Fonts, bg=PANEL, command=None, sub=None):
        super().__init__(parent, bg=bg, cursor="hand2")
        self.var, self.command, self.enabled = var, command, True
        self.c = tk.Canvas(self, width=36, height=20, bg=bg, highlightthickness=0, bd=0)
        self.c.pack(side="left", anchor="n", pady=(1, 0))
        box = tk.Frame(self, bg=bg)
        box.pack(side="left", padx=(10, 0))
        self.lbl = tk.Label(box, text=text, bg=bg, fg=TXT, font=fonts.body)
        self.lbl.pack(anchor="w")
        if sub:
            tk.Label(box, text=sub, bg=bg, fg=MUT, font=fonts.small).pack(anchor="w")
        bind_all_children(self, "<Button-1>", self._click)
        self.draw()

    def _click(self, _e=None):
        if not self.enabled:
            return
        self.var.set(not self.var.get())
        self.draw()
        if self.command:
            self.command()

    def set_enabled(self, v):
        self.enabled = v
        self.lbl.configure(fg=TXT if v else MUT)
        self.draw()

    def draw(self):
        c = self.c
        c.delete("all")
        on = bool(self.var.get())
        track = (T.ACCENT if on else ELEV) if self.enabled else mix(ELEV, self["bg"], 0.4)
        round_rect(c, 1, 1, 35, 19, 9, fill=track, outline=track if on else LINE2)
        x = 26 if on else 10
        c.create_oval(x - 6, 4, x + 6, 16, fill=T.ACCENT_FG if on else DIM, outline="")


def entry(parent, var, fonts: Fonts, width=16, mono=True, bg=BG, font=None):
    """Borderless entry; put it into a RoundField for the rounded frame."""
    return tk.Entry(parent, textvariable=var, width=width, bg=bg, fg=TXT, insertbackground=T.ACCENT, relief="flat",
                    bd=0, font=font or (fonts.mono_m if mono else fonts.body), highlightthickness=0,
                    disabledbackground=bg, disabledforeground=MUT)


class RoundField(tk.Canvas):
    """Rounded frame around one child widget (Entry, Listbox, Label). make(parent) creates the child. Without a
    height the field is as tall as the child. The border turns accent-colored while the child has the focus."""

    def __init__(self, parent, make, bg=PANEL, fill=BG, height=None, radius=None, padx=12, pady=7, width=None):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, height=height or 10, width=width or 10)
        self.fill, self.padx, self.pady, self.fixed_h = fill, padx, pady, height
        self.child = make(self)
        if not width:  # natural width; fill/sticky can still stretch it
            self.configure(width=self.child.winfo_reqwidth() + 2 * padx)
        self.radius = radius
        self.border, self.focus = LINE2, False
        self.win = self.create_window(padx, pady, window=self.child, anchor="nw")
        self.bind("<Configure>", self._layout)
        self.child.bind("<Configure>", self._layout, add="+")
        self.child.bind("<FocusIn>", lambda e: self._focus(True), add="+")
        self.child.bind("<FocusOut>", lambda e: self._focus(False), add="+")
        self.bind("<Button-1>", lambda e: self.child.focus_set())

    def _focus(self, v):
        self.focus = v
        self._layout()

    def set_border(self, color):
        self.border = color
        self._layout()

    def _layout(self, _e=None):
        if not self.fixed_h:
            want = self.child.winfo_reqheight() + 2 * self.pady
            if want != int(self["height"]):
                self.configure(height=want)
        w, h = self.winfo_width(), max(self.winfo_height(), int(self["height"]))
        if w > 2 * self.padx:
            self.itemconfigure(self.win, width=w - 2 * self.padx)
        if self.fixed_h:
            self.itemconfigure(self.win, height=h - 2 * self.pady)
        self.delete("bg")
        r = self.radius if self.radius is not None else min(14, h / 2)
        line = T.ACCENT if self.focus else self.border
        round_rect(self, 1, 1, w - 2, h - 2, r, fill=self.fill, outline=line, tags="bg")
        self.tag_lower("bg")


# ----------------------------------------------------------------------------------------------- panels
class Card(tk.Canvas):
    """Rounded box whose height follows its content. Put children into .inner."""

    def __init__(self, parent, outer_bg, fill=PANEL, outline=LINE2, radius=18, padx=18, pady=14):
        super().__init__(parent, bg=outer_bg, highlightthickness=0, bd=0, height=2 * pady + 10)
        self.fill, self.outline, self.radius, self.padx, self.pady = fill, outline, radius, padx, pady
        self.inner = tk.Frame(self, bg=fill)
        self.win = self.create_window(padx, pady, window=self.inner, anchor="nw")
        self.bind("<Configure>", self._layout)
        self.inner.bind("<Configure>", self._layout)

    def _layout(self, _e=None):
        w = self.winfo_width()
        if w > 2 * self.padx:
            self.itemconfigure(self.win, width=w - 2 * self.padx)
        want = self.inner.winfo_reqheight() + 2 * self.pady
        if want != int(self["height"]):
            self.configure(height=want)
        h = max(self.winfo_height(), 4)
        self.delete("bg")
        round_rect(self, 1, 1, w - 2, h - 2, self.radius, fill=self.fill, outline=self.outline, tags="bg")
        self.tag_lower("bg")


class FillPanel(tk.Canvas):
    """Rounded box that fills the space it gets; .inner fills the box minus the padding."""

    def __init__(self, parent, outer_bg, fill=PANEL, outline=LINE2, radius=18, pad=1):
        super().__init__(parent, bg=outer_bg, highlightthickness=0, bd=0)
        self.fill, self.outline, self.radius, self.pad = fill, outline, radius, pad
        self.inner = tk.Frame(self, bg=fill)
        self.inner.place(x=pad + radius // 3, y=pad + radius // 3)
        self.bind("<Configure>", self._layout)

    def _layout(self, _e=None):
        w, h = self.winfo_width(), self.winfo_height()
        inset = self.pad + self.radius // 3
        self.inner.place_configure(width=max(10, w - 2 * inset), height=max(10, h - 2 * inset))
        self.delete("bg")
        round_rect(self, 1, 1, w - 2, h - 2, self.radius, fill=self.fill, outline=self.outline, tags="bg")


class RoundPanel(tk.Canvas):
    """Rounded card that fills its space. Children go into .inner. Content starts at the top (valign='top') or is
    centered; when it is taller than the card it scrolls with the mouse wheel and a thin thumb shows the position."""

    def __init__(self, parent, outer_bg, fill=PANEL, outline=LINE2, radius=18, pad=18, valign="top"):
        super().__init__(parent, bg=outer_bg, highlightthickness=0, bd=0)
        self.fill, self.outline, self.radius, self.pad, self.valign = fill, outline, radius, pad, valign
        self.offset = 0
        self.view = tk.Frame(self, bg=fill)
        self.win = self.create_window(pad, 3, window=self.view, anchor="nw")
        self.inner = tk.Frame(self.view, bg=fill)
        self.inner.place(x=0, y=0, relwidth=1)
        self.bind("<Configure>", self.redraw)
        self.inner.bind("<Configure>", self.redraw)
        self.bind("<Enter>", lambda e: self._wheel(True))
        self.bind("<Leave>", self._leave)

    def _wheel(self, on):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            if on:
                self.bind_all(seq, self._on_wheel)
            else:
                self.unbind_all(seq)

    def _leave(self, e):
        if not (0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()):
            self._wheel(False)

    def _view_h(self):
        return max(10, self.winfo_height() - 6)

    def overflow(self):
        return self.inner.winfo_reqheight() + 2 * (self.pad - 3) - self._view_h()

    def _on_wheel(self, e):
        over = self.overflow()
        if over <= 0:
            return
        up = getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0
        self.offset = max(0, min(over, self.offset + (-40 if up else 40)))
        self.redraw()

    def scroll_top(self):
        self.offset = 0

    def redraw(self, _e=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        self.delete("bg")
        round_rect(self, 1, 1, w - 2, h - 2, self.radius, fill=self.fill, outline=self.outline, tags="bg")
        self.tag_lower("bg")
        vh = self._view_h()
        self.itemconfigure(self.win, width=max(10, w - 2 * self.pad), height=vh)
        ih = self.inner.winfo_reqheight()
        inset = self.pad - 4
        over = ih + 2 * inset - vh
        if over > 0:
            self.offset = min(self.offset, over)
            y = inset - self.offset
            track = h - 24
            thumb = max(24, track * vh / (ih + 2 * inset))
            ty = 12 + (track - thumb) * self.offset / over
            round_rect(self, w - 8, ty, w - 5, ty + thumb, 2, fill=LINE2, outline=LINE2, tags="bg")
        else:
            self.offset = 0
            y = inset if self.valign == "top" else (vh - ih) / 2
        self.inner.place_configure(y=y, height=ih)


# ----------------------------------------------------------------------------------------------- tabs, steps
class Tabs(tk.Canvas):
    """Segmented control. items: [(id, label, enabled, tooltip)]. The selected segment is filled with the accent."""

    def __init__(self, parent, fonts: Fonts, on_select, bg=BG, height=40, pad=20, font=None):
        super().__init__(parent, height=height, width=10, bg=bg, highlightthickness=0, bd=0)
        self.f, self.on_select, self.h, self.pad = font or fonts.tab, on_select, height, pad
        self.items, self.sel, self.hover, self.xs = [], None, None, []
        self.locked = False
        self.tip = Tooltip(self, "", fonts.small)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._click)

    def set(self, items, selected, locked=False):
        self.items, self.sel, self.locked = items, selected, locked
        self.xs, x = [], 0
        for _id, label, _en, _tip in items:
            w = self.f.measure(label.upper()) + 2 * self.pad + 4
            self.xs.append((x, x + w))
            x += w
        self.configure(width=x + 2)
        self.draw()

    def _index(self, x):
        for i, (a, b) in enumerate(self.xs):
            if a <= x < b:
                return i
        return None

    def _motion(self, e):
        self._set_hover(self._index(e.x))

    def _set_hover(self, i):
        if i == self.hover:
            return
        self.hover = i
        self.tip.hide()
        if i is not None:
            _id, _label, enabled, tip = self.items[i]
            if tip and not enabled:
                self.tip.show(x=self.winfo_rootx() + self.xs[i][0], y=self.winfo_rooty() + self.h + 4, text=tip)
        self.configure(cursor="hand2" if i is not None and self.items[i][2] and not self.locked else "arrow")
        self.draw()

    def _click(self, e):
        i = self._index(e.x)
        if i is None or self.locked:
            return
        _id, _label, enabled, _tip = self.items[i]
        if enabled:
            self.on_select(_id)

    def draw(self):
        self.delete("all")
        if not self.xs:
            return
        bg, h = self["bg"], self.h
        total = self.xs[-1][1]
        round_rect(self, 1, 1, total, h - 1, (h - 2) / 2, fill=PANEL, outline=LINE2)
        for i, ((a, b), (_id, label, enabled, _tip)) in enumerate(zip(self.xs, self.items)):
            sel = _id == self.sel
            if sel:
                round_rect(self, a + 4, 4, b - 3, h - 4, (h - 8) / 2, fill=T.ACCENT if not self.locked else mix(
                    T.ACCENT, PANEL, 0.35), outline="")
            elif self.hover == i and enabled and not self.locked:
                round_rect(self, a + 4, 4, b - 3, h - 4, (h - 8) / 2, fill=ELEV, outline="")
            elif i > 0 and self.items[i - 1][0] != self.sel and self.hover != i - 1:
                self.create_line(a, 12, a, h - 12, fill=LINE2)
            fg = T.ACCENT_FG if sel else (DIM if enabled else mix(MUT, PANEL, 0.35))
            self.create_text((a + b) / 2 + 0.5, h / 2, text=label.upper(), fill=fg, font=self.f)


class Steps(tk.Canvas):
    """Numbered step list. mode: idle | run | done | fail. current: 1-based index of the running/failed step."""
    ROW = 25

    def __init__(self, parent, fonts: Fonts, bg=PANEL):
        super().__init__(parent, height=self.ROW, bg=bg, highlightthickness=0, bd=0)
        self.f, self.fb, self.fn = fonts.mono, fonts.btn_s, fonts.mono_s
        self.labels, self.current, self.mode = [], 0, "idle"
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, labels, current=0, mode="idle"):
        self.labels, self.current, self.mode = list(labels), current, mode
        self.configure(height=max(1, len(self.labels)) * self.ROW)
        self.draw()

    def draw(self):
        self.delete("all")
        w, R = self.winfo_width(), self.ROW
        for i, label in enumerate(self.labels):
            n, y = i + 1, i * R
            if i:
                self.create_line(0, y, w, y, fill=LINE, dash=(2, 3))
            if self.mode == "done" or (self.mode in ("run", "fail") and n < self.current):
                state = "done"
            elif self.mode == "run" and n == self.current:
                state = "run"
            elif self.mode == "fail" and n == self.current:
                state = "fail"
            else:
                state = "todo"
            box_fill, box_line, num_fg, txt = {
                "done": (T.ACCENT, T.ACCENT, T.ACCENT_FG, TXT),
                "run": (mix(AMBER, self["bg"], 0.85), AMBER, AMBER, AMBER),
                "fail": (mix(DANGER, self["bg"], 0.85), DANGER, DANGER, DANGER),
                "todo": (self["bg"], LINE2, MUT, DIM if self.mode == "idle" else MUT),
            }[state]
            cy = y + R / 2
            self.create_oval(1, cy - 9, 19, cy + 9, fill=box_fill, outline=box_line)
            mark = "✓" if state == "done" else "✕" if state == "fail" else str(n)
            self.create_text(10, cy, text=mark, fill=num_fg, font=self.fn)
            self.create_text(30, cy, text=fit(self.f, label, w - 34), anchor="w", fill=txt,
                             font=self.fb if state == "run" else self.f)


class ProgressBar(tk.Canvas):
    def __init__(self, parent, bg=PANEL):
        super().__init__(parent, height=4, bg=bg, highlightthickness=0, bd=0)
        self.frac, self.color = 0.0, AMBER
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, frac, color):
        self.frac, self.color = max(0.0, min(1.0, frac)), color
        self.draw()

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        round_rect(self, 0, 0, w, 4, 2, fill=ELEV, outline=ELEV)
        if self.frac > 0:
            round_rect(self, 0, 0, max(4, w * self.frac), 4, 2, fill=self.color, outline=self.color)


class Swatches(tk.Canvas):
    """Accent color picker: one circle per entry of ACCENTS, the selected one ringed."""

    def __init__(self, parent, fonts: Fonts, on_pick, bg=PANEL):
        self.keys = list(ACCENTS)
        self.f, self.on_pick = fonts.mono_s, on_pick
        super().__init__(parent, width=len(self.keys) * 70, height=58, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.bind("<Button-1>", self._click)
        self.draw()

    def _click(self, e):
        i = int(e.x // 70)
        if 0 <= i < len(self.keys):
            self.on_pick(self.keys[i])
            if self.winfo_exists():  # the dialog may have rebuilt itself
                self.draw()

    def draw(self):
        self.delete("all")
        for i, k in enumerate(self.keys):
            label, color = ACCENTS[k]
            cx = i * 70 + 35
            if k == T.name:
                self.create_oval(cx - 17, 3, cx + 17, 37, outline=color, width=2)
            self.create_oval(cx - 12, 8, cx + 12, 32, fill=color, outline="")
            self.create_text(cx, 49, text=label.upper(), fill=TXT if k == T.name else MUT, font=self.f)


class RadioCard(tk.Canvas):
    """Selectable card. tag: short text on the right (on the sub line when there is one)."""

    def __init__(self, parent, app, title, sub, value, var: tk.StringVar, on_change, bg=PANEL, width=232,
                 height=50, tag=None, tag_color=None):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.app, self.title, self.sub, self.value, self.var = app, title, sub, value, var
        self.on_change, self.w, self.h, self.tag, self.tag_color = on_change, width, height, tag, tag_color or OK
        self.hover = False
        self.bind("<Enter>", lambda e: self._h(True))
        self.bind("<Leave>", lambda e: self._h(False))
        self.bind("<Button-1>", self._pick)
        self.draw()

    def _h(self, v):
        self.hover = v
        self.draw()

    def _pick(self, _e):
        self.var.set(self.value)
        self.on_change()

    def draw(self):
        self.delete("all")
        sel = self.var.get() == self.value
        fill = T.ACCENT_BG if sel else (ELEV if self.hover else PANEL2)
        w, h = self.w, self.h
        round_rect(self, 1, 1, w - 1, h - 1, 14, fill=fill, outline=T.ACCENT if sel else LINE2)
        cy = h / 2
        self.create_oval(12, cy - 7, 26, cy + 7, outline=T.ACCENT if sel else MUT, width=2)
        if sel:
            self.create_oval(16, cy - 3, 22, cy + 3, fill=T.ACCENT, outline="")
        f = self.app.f
        tag_w = f.eyebrow.measure(self.tag) + 12 if self.tag else 0
        ty = cy + 9 if self.sub else cy
        self.create_text(36, cy - 8 if self.sub else cy, text=fit(f.body_b, self.title, w - 46 - (0 if self.sub
                         else tag_w)), anchor="w", font=f.body_b, fill=TXT)
        if self.sub:
            self.create_text(36, cy + 9, text=fit(f.mono_s, self.sub, w - 46 - tag_w), anchor="w", font=f.mono_s,
                             fill=DIM)
        if self.tag:
            self.create_text(w - 10, ty, text=self.tag, anchor="e", font=f.eyebrow, fill=self.tag_color)


class Chip(tk.Canvas):
    """Pill-like model button for the scooter picker. match=(start, end) colors that part of the text;
    sub: dim text after the name; dot: green 'tested' dot; state: normal | selected | focus."""
    H = 44

    def __init__(self, parent, fonts: Fonts, text, command, bg=PANEL, sub=None, match=None, dot=False,
                 state="normal", small=False, min_w=110, on_double=None):
        self.f, self.fs = (fonts.body_b if small else fonts.chip), fonts.small
        self.text, self.sub, self.match, self.dot, self.state, self.small = text, sub, match, dot, state, small
        self.h = 32 if small else self.H
        pad = 14 if small else 18
        w = self.f.measure(text) + 2 * pad + (self.fs.measure(sub) + 8 if sub else 0) + (8 if dot else 0)
        self.w = max(w, 0 if small else min_w)
        self.pad, self.hover = pad, False
        super().__init__(parent, width=self.w, height=self.h, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self._h(True))
        self.bind("<Leave>", lambda e: self._h(False))
        self.bind("<Button-1>", lambda e: command())
        if on_double:
            self.bind("<Double-Button-1>", lambda e: on_double())
        self.draw()

    def _h(self, v):
        self.hover = v
        self.draw()

    def set_state(self, state):
        self.state = state
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.w, self.h
        if self.state == "selected":
            fill, line = T.ACCENT_BG, T.ACCENT
        elif self.state == "focus":
            fill, line = ELEV, "#55555E"
        else:
            fill, line = (ELEV if self.hover else PANEL2), LINE2
        round_rect(self, 1, 1, w - 1, h - 1, 16 if not self.small else (h - 2) / 2, fill=fill, outline=line)
        x, cy = self.pad, h / 2
        if self.match:
            a, b = self.match
            for part, col in ((self.text[:a], TXT), (self.text[a:b], T.ACCENT), (self.text[b:], TXT)):
                if part:
                    self.create_text(x, cy, text=part, anchor="w", fill=col, font=self.f)
                    x += self.f.measure(part)
        else:
            self.create_text(x, cy, text=self.text, anchor="w", fill=TXT, font=self.f)
            x += self.f.measure(self.text)
        if self.sub:
            self.create_text(x + 8, cy + 1, text=self.sub, anchor="w", fill=MUT, font=self.fs)
        if self.dot:
            self.create_oval(w - 15, 7, w - 8, 14, fill=OK, outline="")
        if self.state == "selected" and not self.small:
            self.create_text(w - 12, h - 11, text="✓", fill=T.ACCENT, font=self.fs)


def flow(parent, makers, width, gap=8, bg=PANEL):
    """Places widgets left to right and wraps at width. makers: functions row_frame -> widget (with a width)."""
    out, row, used = [], None, 0
    for make in makers:
        if row is None:
            row = tk.Frame(parent, bg=bg)
            row.pack(anchor="w")
        w = make(row)
        need = int(w["width"])
        if used and used + gap + need > width:
            w.destroy()
            row = tk.Frame(parent, bg=bg)
            row.pack(anchor="w", pady=(gap, 0))
            used = 0
            w = make(row)
        w.pack(side="left", padx=(gap if used else 0, 0))
        used += (gap if used else 0) + need
        out.append(w)
    return out


# ----------------------------------------------------------------------------------------------- dialogs
def center_on(win, app):
    win.update_idletasks()
    x = app.winfo_rootx() + (app.winfo_width() - win.winfo_reqwidth()) // 2
    y = app.winfo_rooty() + (app.winfo_height() - win.winfo_reqheight()) // 3
    win.geometry(f"+{max(0, x)}+{max(0, y)}")


class Dialog(tk.Toplevel):
    """Dark modal dialog. buttons: list of (label, kind, value)."""

    def __init__(self, app, title, message, buttons, accent=None, detail=None):
        super().__init__(app)
        self.app, self.result = app, None
        self.title(title)
        self.configure(bg=PANEL, highlightthickness=1, highlightbackground=LINE2)
        dark_titlebar(self)
        self.resizable(False, False)
        self.transient(app)
        body = tk.Frame(self, bg=PANEL, padx=26, pady=22)
        body.pack(fill="both", expand=True)
        head = tk.Frame(body, bg=PANEL)
        head.pack(fill="x")
        dot = tk.Canvas(head, width=10, height=10, bg=PANEL, highlightthickness=0)
        dot.create_rectangle(0, 0, 10, 10, fill=accent or T.ACCENT, outline="")
        dot.pack(side="left", padx=(0, 10))
        tk.Label(head, text=title, bg=PANEL, fg=TXT, font=app.f.h1).pack(side="left")
        tk.Label(body, text=message, bg=PANEL, fg=DIM, font=app.f.body, justify="left", wraplength=460).pack(
            anchor="w", pady=(12, 0))
        if detail:
            RoundField(body, lambda p: tk.Label(p, text=detail, bg=BG, fg=TXT, font=app.f.mono, justify="left",
                                                anchor="w"), pady=10).pack(fill="x", pady=(12, 0))
        row = tk.Frame(body, bg=PANEL)
        row.pack(fill="x", pady=(20, 0))
        for label, kind, value in reversed(buttons):
            Button(row, label, lambda v=value: self._done(v), app.f, kind=kind, bg=PANEL, small=True,
                   height=34).pack(side="right", padx=(8, 0))
        self.bind("<Escape>", lambda e: self._done(None))
        self.protocol("WM_DELETE_WINDOW", lambda: self._done(None))
        center_on(self, app)
        self.wait_visibility()
        self.grab_set()
        self.focus_set()

    def _done(self, v):
        self.result = v
        self.grab_release()
        self.destroy()

    @classmethod
    def ask(cls, app, title, message, ok="OK", kind="primary", cancel="Cancel", accent=None, detail=None):
        d = cls(app, title, message, [(cancel, "ghost", False), (ok, kind, True)], accent, detail)
        app.wait_window(d)
        return bool(d.result)

    @classmethod
    def info(cls, app, title, message, accent=None, detail=None):
        d = cls(app, title, message, [("OK", "primary", True)], accent, detail)
        app.wait_window(d)
