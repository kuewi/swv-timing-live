#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SWV Live-Ranking / Speakerbildschirm
TAG Heuer Chronoprinter CP 545, Anzeigetafel-Protokoll HL970 / HL980

Abhaengigkeiten : Python 3.9+, pyserial
Optional        : xlrd (Startliste .xls), openpyxl (Startliste .xlsx, Export .xlsx),
                  qrcode + pypng (QR-Code fuer Browser-Anzeige)
Build (.exe)    : build.bat  (PyInstaller --onefile --windowed)

Protokoll (ASCII, STX ... LF):
  \x0223  Nr  22\n     Startnummer (wird nach jeder Zeit wiederholt)
  \x0213 4:32   \n     Laufzeit (ganze Sekunden)  -> nur Live-Anzeige
  \x0213 4:33.00\n     Zielzeit (mit Dezimalpunkt) -> Ranking
  \x0243  Rk  21\n     Rang des CP 545            -> ignoriert

Onlinetool: Die Oberflaeche ist vorbereitet. Die Anbindung (Klasse OnlineClient)
folgt, sobald die API-Dokumentation vorliegt. Gesendet werden nur gefahrene Zeiten,
Strafpunkte kommen vom Onlinetool und dienen nur dem Speaker-Ranking.
"""

import csv
import datetime
import hmac
import io
import ipaddress
import json
import os
import queue
import re
import secrets
import socket
import string
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None
try:
    import xlrd
except ImportError:
    xlrd = None
try:
    import openpyxl
    from openpyxl.styles import Font as XlFont
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None

# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #
APP_TITLE = "SWV Live-Ranking  |  TAG Heuer CP 545"
APP_VERSION = "2026-11-20"
DEFAULT_BAUD = 9600
TOP_N = 5
BLINK_SECONDS = 30
BLINK_INTERVAL_MS = 450
POLL_INTERVAL_MS = 30
RECONNECT_MS = 2000
WEB_SNAPSHOT_MS = 700
LOG_MAX_LINES = 300
TICKER_MAX = 60
NEXT_COUNT = 3

# Apple Dark Mode. Flaechen mit weisser Schrift leicht abgedunkelt (Kontrast >= 4.6:1 fuer Sonnenlicht).
BG = "#000000"            # systemBackground
PANEL = "#1c1c1e"         # secondarySystemBackground
PANEL2 = "#2c2c2e"        # tertiarySystemBackground / Eingabefelder
BUTTON = "#3a3a3c"        # graue Knoepfe
BORDER = "#38383a"        # separator
TEXT = "#ffffff"
MUTED = "#98989d"         # secondaryLabel
BLUE = "#0872dd"          # systemBlue, abgedunkelt fuer weisse Schrift
ACCENT = "#0a84ff"        # systemBlue fuer Text und Linien auf dunklem Grund
GREEN = "#1e8538"         # systemGreen, abgedunkelt fuer weisse Schrift
GREEN_TEXT = "#30d158"    # systemGreen fuer Text auf dunklem Grund
GOLD = "#ffd60a"          # systemYellow
WHITE = "#ffffff"
RED = "#ff453a"           # systemRed
ORANGE = "#ff9f0a"        # systemOrange
LIGHT_YELLOW = "#fff3c4"
DARK_RED = "#d63930"      # systemRed, abgedunkelt fuer weisse Schrift
INPUT_BG = PANEL2
INPUT_FG = TEXT
LIST_BG = "#f2f2f7"       # Aufklappliste der Auswahlfelder: dunkle Schrift auf hellem Grund
LIST_FG = "#000000"

DEFAULT_CATEGORIES = [
    {"name": "AKTIVE", "min": 1, "max": 199, "rekord": ""},
    {"name": "SENIOREN", "min": 300, "max": 399, "rekord": ""},
    {"name": "VETERANEN", "min": 400, "max": 499, "rekord": ""},
    {"name": "FRAUEN", "min": 500, "max": 599, "rekord": ""},
    {"name": "JUNIOREN", "min": 600, "max": 699, "rekord": ""},
    {"name": "JUNGFAHRER", "min": 700, "max": 799, "rekord": ""},
    {"name": "SCHÜLER", "min": 800, "max": 899, "rekord": ""},
]

DEFAULT_SETTINGS = {
    "wettkampf": "einzel",
    "show": {
        "vergleich": True, "prognose": True, "einordnung": True, "ticker": True,
        "naechste": True, "statistik": False, "namen": True, "notizen": True,
    },
    "collapsed": {"wettkampf": False, "verbindung": False, "speaker": False, "daten": False,
                  "kategorien": True, "online": True, "web": True},
    "event": {"name": "", "von": "", "bis": ""},
    "online": {
        "mode": "offline", "url": "", "comp_id": "", "token": "",
        "send_mode": "confirm", "auto_startlist": True,
    },
    "web": {"bind": "", "port": 8080, "key": ""},
    "export_dir": "",
}

SHOW_LABELS = [
    ("vergleich", "Bestzeit-Vergleich"), ("prognose", "Rangprognose"),
    ("einordnung", "Einordnung Ziel"), ("ticker", "Ereignis-Ticker"),
    ("naechste", "Als nächstes"), ("statistik", "Statistik"),
    ("namen", "Namen in Rangliste"), ("notizen", "Notizen"),
]

CATEGORIES_FILE = "swv_kategorien.json"
SETTINGS_FILE = "swv_einstellungen.json"
AUTOSAVE_FILE = "swv_resultate_autosave.json"
ICON_FILES = ("swv_logo.png", "logo.png", "image_928d28.png")

ST_OPEN, ST_APPROVED, ST_SENT, ST_ERROR = "offen", "freigegeben", "gesendet", "Fehler"


# --------------------------------------------------------------------------- #
# Pfade
# --------------------------------------------------------------------------- #
def resource_dirs():
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(getattr(sys, "_MEIPASS", ""))
        dirs.append(os.path.dirname(sys.executable))
    dirs.append(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.getcwd())
    return [d for d in dirs if d]


def data_dir():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    if os.access(base, os.W_OK):
        return base
    fallback = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SWV_LiveRanking")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def deep_merge(defaults, data):
    out = {}
    for key, dval in defaults.items():
        val = data.get(key, dval) if isinstance(data, dict) else dval
        if isinstance(dval, dict):
            out[key] = deep_merge(dval, val if isinstance(val, dict) else {})
        elif isinstance(dval, bool):
            out[key] = val if isinstance(val, bool) else dval
        elif isinstance(dval, int):
            out[key] = val if isinstance(val, int) and not isinstance(val, bool) else dval
        else:
            out[key] = val if isinstance(val, type(dval)) else dval
    return out


# --------------------------------------------------------------------------- #
# Bausteine im Apple-Stil (abgerundete Flaechen, Knoepfe, Schalter, Segmente)
# --------------------------------------------------------------------------- #
def parent_bg(widget):
    try:
        return widget.cget("bg")
    except tk.TclError:
        return BG


def mix(color, other, t):
    """Farbe color um Anteil t Richtung other verschieben."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(a, b))


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Rechteck mit exakt runden Ecken (Kreisboegen), als ein Polygon."""
    import math
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    steps = max(4, int(r / 1.5))
    pts = []
    for cx, cy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
        for k in range(steps + 1):
            a = math.radians(a0 + 90 * k / steps)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
    return canvas.create_polygon(pts, **kw)


class RoundedPanel(tk.Canvas):
    """Flaeche mit abgerundeten Ecken. Inhalt kommt in .inner (normales Frame)."""

    def __init__(self, parent, fill=None, radius=14, pad=0, fit_height=False, outline="", outline_width=0):
        self.fill = fill or PANEL
        super().__init__(parent, bg=parent_bg(parent), highlightthickness=0, bd=0)
        # Inhalt so weit einruecken, dass er die runden Ecken nicht ueberdeckt
        self.radius, self.pad, self.fit = radius, max(pad, int(radius * 0.3) + 1), fit_height
        self.outline, self.outline_width = outline, outline_width
        self.inner = tk.Frame(self, bg=self.fill)
        self._win = self.create_window(self.pad, self.pad, window=self.inner, anchor="nw")
        self._shape = None
        self.bind("<Configure>", self._redraw)
        if fit_height:
            self.inner.bind("<Configure>", self._fit)

    def _fit(self, _e=None):
        h = self.inner.winfo_reqheight() + 2 * self.pad
        if int(self.cget("height")) != h:
            self.configure(height=h)

    def _redraw(self, _e=None):
        w, h = self.winfo_width(), self.winfo_height()
        if self._shape is not None:
            self.delete(self._shape)
        ow = self.outline_width
        self._shape = round_rect(self, ow / 2, ow / 2, w - ow / 2, h - ow / 2, self.radius, fill=self.fill,
                                 outline=self.outline or self.fill, width=max(1, ow))
        self.tag_lower(self._shape)
        self.itemconfigure(self._win, width=max(1, w - 2 * self.pad))
        if not self.fit:
            self.itemconfigure(self._win, height=max(1, h - 2 * self.pad))

    def set_outline(self, color, width=2):
        self.outline, self.outline_width = color, width if color else 0
        self._redraw()


class RoundButton(tk.Canvas):
    """Abgerundeter Knopf. Versteht text, bg, fg, state, command wie tk.Button."""

    _OWN = ("text", "bg", "background", "fg", "foreground", "state", "command", "activebackground", "font")

    def __init__(self, parent, text="", command=None, bg=None, fg=None, font=None, radius=9, padx=14, pady=7,
                 activebackground=None, **_ignored):
        self._o = {"text": text, "command": command, "bg": bg or BUTTON, "fg": fg or WHITE, "state": "normal",
                   "activebackground": activebackground, "font": font}
        self._hover = self._down = False
        self.radius, self.padx, self.pady = radius, padx, pady
        super().__init__(parent, bg=parent_bg(parent), highlightthickness=0, bd=0, cursor="hand2")
        self._size()
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    def _font(self):
        return self._o["font"] or tkfont.nametofont("TkDefaultFont")

    def _size(self):
        f = self._font()
        super().configure(height=f.metrics("linespace") + 2 * self.pady,
                          width=f.measure(self._o["text"]) + 2 * self.padx)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        bg = self._o["bg"]
        if self._o["state"] == "disabled":
            fill, fg = mix(bg, BG, 0.55), "#6e6e73"
        else:
            fill = mix(bg, WHITE, 0.18) if self._down else (mix(bg, WHITE, 0.09) if self._hover else bg)
            fg = self._o["fg"]
        round_rect(self, 0, 0, w, h, self.radius, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=self._o["text"], fill=fg, font=self._font())

    def _set_hover(self, on):
        self._hover = on
        if not on:
            self._down = False
        self._draw()

    def _press(self, _e):
        if self._o["state"] != "disabled":
            self._down = True
            self._draw()

    def _release(self, e):
        was = self._down
        self._down = False
        self._draw()
        inside = 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()
        if was and inside:
            self.invoke()

    def invoke(self):
        if self._o["state"] != "disabled" and self._o["command"]:
            return self._o["command"]()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        own = {k: kw.pop(k) for k in list(kw) if k in self._OWN}
        if "background" in own:
            own["bg"] = own.pop("background")
        if "foreground" in own:
            own["fg"] = own.pop("foreground")
        self._o.update(own)
        if kw:
            super().configure(**kw)
        if "text" in own or "font" in own:
            self._size()
        self._draw()

    config = configure

    def cget(self, key):
        key = {"background": "bg", "foreground": "fg"}.get(key, key)
        if key in self._o:
            return self._o[key] if self._o[key] is not None else ""
        return super().cget(key)


class Switch(tk.Canvas):
    """Ein/Aus-Schalter wie in den iPhone-Einstellungen."""

    def __init__(self, parent, command=None, scale=1.0, on=False):
        self.w, self.h = int(46 * scale), int(28 * scale)
        super().__init__(parent, width=self.w, height=self.h, bg=parent_bg(parent), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.on, self.command = on, command
        self.bind("<Button-1>", lambda e: self.command and self.command())
        self._draw()

    def set(self, on):
        if bool(on) != self.on:
            self.on = bool(on)
            self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.w, self.h
        track = "#30d158" if self.on else "#39393d"
        round_rect(self, 0, 0, w, h, h / 2, fill=track, outline=track)
        m = 2
        d = h - 2 * m
        x = w - m - d if self.on else m
        self.create_oval(x, m, x + d, m + d, fill=WHITE, outline=WHITE)


class Segmented(tk.Canvas):
    """Segment-Schalter (Apple): mehrere Optionen, eine ist aktiv."""

    def __init__(self, parent, options, variable, command=None, font=None, scale=1.0):
        self.options, self.var, self.command, self.font = options, variable, command, font
        self.pad = int(2 * scale)
        h = (font.metrics("linespace") if font else 18) + int(12 * scale)
        super().__init__(parent, height=h, bg=parent_bg(parent), highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self._click)

    def _click(self, e):
        w = self.winfo_width()
        idx = min(len(self.options) - 1, max(0, int(e.x / max(1, w) * len(self.options))))
        value = self.options[idx][0]
        if self.var.get() != value:
            self.var.set(value)
            self.redraw()
            if self.command:
                self.command()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        round_rect(self, 0, 0, w, h, 9, fill="#2c2c2e", outline="#2c2c2e")
        seg = w / len(self.options)
        for i, (value, label) in enumerate(self.options):
            x1, x2 = i * seg, (i + 1) * seg
            active = self.var.get() == value
            if active:
                round_rect(self, x1 + self.pad, self.pad, x2 - self.pad, h - self.pad, 7, fill="#636366",
                           outline="#636366")
            self.create_text((x1 + x2) / 2, h / 2, text=label, fill=WHITE if active else "#c7c7cc", font=self.font)


# --------------------------------------------------------------------------- #
# Protokoll und Zeitformate
# --------------------------------------------------------------------------- #
_TIME_CHARS = re.compile(r"^[0-9:.]+$")


def parse_time(text):
    """'4:33.00' -> 273.0 | '14.20' -> 14.2 | '1:02:03.4' -> 3723.4 | ungueltig -> None"""
    t = str(text).strip().replace(",", ".")
    if not t or not _TIME_CHARS.match(t):
        return None
    parts = t.split(":")
    if not 1 <= len(parts) <= 3 or any(p == "" for p in parts):
        return None
    try:
        secs = float(parts[-1])
        mult = 60
        for p in reversed(parts[:-1]):
            secs += int(p) * mult
            mult *= 60
    except ValueError:
        return None
    return secs


def parse_message(raw):
    """("nr", 22) | ("running", "4:32", 272.0) | ("final", "4:33.00", 273.0) | None"""
    line = raw.replace("\x02", "").replace("\r", "").replace("\n", "").lstrip()
    if len(line) < 2:
        return None
    code, rest = line[:2], line[2:]
    if code == "23":
        m = re.search(r"(\d+)\s*$", rest)
        return ("nr", int(m.group(1))) if m else None
    if code == "13":
        t = rest.strip()
        secs = parse_time(t)
        if secs is None:
            return None
        return ("final" if "." in t else "running", t, secs)
    return None


def format_manual_time(minutes, seconds, tenths):
    if minutes > 0:
        return f"{minutes}:{seconds:02d}.{tenths}"
    return f"{seconds}.{tenths}"


def fmt_secs(secs, decimals=2):
    total = round(secs, decimals)
    m = int(total // 60)
    s = total - m * 60
    if m:
        return f"{m}:{s:0{3 + decimals}.{decimals}f}"
    return f"{s:.{decimals}f}"


def fmt_gap(secs):
    """Abstand: '2.35 s' oder ab einer Minute '1:05.20'."""
    return f"{secs:.2f} s" if secs < 60 else fmt_secs(secs)


def sanitize_filename(name, fallback="Datei"):
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")
    return (clean or fallback)[:80]


def file_part(name, fallback="Datei"):
    """Fuer Dateinamen: unzulaessige Zeichen entfernen, Leerzeichen zu '_'."""
    return re.sub(r"_+", "_", sanitize_filename(name, fallback).replace(" ", "_")).strip("_") or fallback


def parse_date(text):
    """'12.06.2027' / '12.6.27' -> date, sonst None."""
    m = re.fullmatch(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})\s*", str(text))
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def short_date_range(von, bis):
    """Kurzes Datum fuer Kopfzeilen: 12.06.27 | 12.-13.06.27 | 30.06.-01.07.27"""
    if von is None:
        return ""
    if bis is None:
        return von.strftime("%d.%m.%y")
    if (von.year, von.month) == (bis.year, bis.month):
        return f"{von.day:02d}.-{bis.strftime('%d.%m.%y')}"
    if von.year == bis.year:
        return f"{von.strftime('%d.%m.')}-{bis.strftime('%d.%m.%y')}"
    return f"{von.strftime('%d.%m.%y')}-{bis.strftime('%d.%m.%y')}"


def fit_text(font, text, width):
    """Text auf Breite kuerzen und mit '…' enden lassen (nie mitten im Buchstaben abschneiden)."""
    if width <= 10 or font.measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid].rstrip() + "…") <= width:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo].rstrip() + "…") if lo else "…"


# --------------------------------------------------------------------------- #
# Startliste (Excel / CSV)
# --------------------------------------------------------------------------- #
FIELD_DEFS = [
    ("nr", "Startnummer"),
    ("p1", "Name 1 (Steuerfahrer / Vorname)"),
    ("p2", "Name 2 (Vorderfahrer / Nachname)"),
    ("kategorie", "Kategorie"),
    ("verein", "Verein"),
    ("vnr", "VNr (Vereinsnummer)"),
    ("staver", "StaVer (Startverschiebung)"),
    ("fg", "FG"),
    ("bemerkung", "Bemerkung"),
]
FIELD_ALIASES = {
    "nr": ["startnummer", "startnr", "stnr", "nr", "nummer"],
    "p1": ["steuerfahrer", "steuermann", "vorname", "fahrer1", "name1"],
    "p2": ["vorderfahrer", "vordermann", "nachname", "fahrer2", "name2", "name"],
    "kategorie": ["kategorie", "kat", "klasse"],
    "verein": ["verein", "sektion", "club", "klub"],
    "vnr": ["vnr", "vereinsnr", "vereinsnummer"],
    "staver": ["staver", "startverschiebung"],
    "fg": ["fg", "startblock", "block"],
    "bemerkung": ["bemerkungze", "bemerkung", "bem"],
}


def norm_header(text):
    return re.sub(r"[\s._\-]", "", str(text).lower())


def cell_str(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def cell_nr(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    text = str(value).strip()
    if re.fullmatch(r"\d+(\.0+)?", text):
        nr = int(float(text))
        return nr if nr > 0 else None
    return None


# --------------------------------------------------------------------------- #
# Eingebaute Leser und Schreiber fuer Excel (ohne Zusatzmodule)
# --------------------------------------------------------------------------- #
OLE_SIGNATURE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"


class StartlistError(Exception):
    """Verstaendliche Fehlermeldung beim Einlesen einer Startliste."""


def sniff_format(path):
    """Dateiformat am Inhalt erkennen (Endung kann falsch sein)."""
    with open(path, "rb") as fh:
        head = fh.read(4096)
    if head.startswith(OLE_SIGNATURE):
        return "xls"
    if head.startswith(b"PK\x03\x04"):
        return "xlsx"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "text16"
    low = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if low.startswith(b"<"):
        if b"<table" in low or b"<html" in low or b"<!doctype html" in low:
            return "html"
        if b"urn:schemas-microsoft-com:office:spreadsheet" in low:
            return "xml2003"
    if b"\x00" in head:
        return "binary"
    return "text"


def _ole_stream(data, names=("workbook", "book")):
    """Stream aus einer OLE2-Verbunddatei (alte Office-Dateien) lesen."""
    import struct
    if data[:8] != OLE_SIGNATURE:
        raise ValueError("keine OLE2-Datei")
    ssz = 1 << struct.unpack_from("<H", data, 30)[0]
    mssz = 1 << struct.unpack_from("<H", data, 32)[0]
    n_fat = struct.unpack_from("<I", data, 44)[0]
    dir_start = struct.unpack_from("<I", data, 48)[0]
    cutoff = struct.unpack_from("<I", data, 56)[0]
    minifat_start, _n_minifat = struct.unpack_from("<II", data, 60)
    difat_start, n_difat = struct.unpack_from("<II", data, 68)
    difat = list(struct.unpack_from("<109I", data, 76))
    per = ssz // 4
    max_secs = len(data) // ssz + 2

    def sector(i):
        off = (i + 1) * ssz
        return data[off:off + ssz]

    s, guard = difat_start, 0
    while s < 0xFFFFFFFA and guard <= n_difat and (s + 1) * ssz < len(data):
        vals = struct.unpack(f"<{per}I", sector(s))
        difat.extend(vals[:-1])
        s = vals[-1]
        guard += 1
    fat = []
    for fs in [x for x in difat if x < 0xFFFFFFFA][:n_fat]:
        sec = sector(fs)
        if len(sec) == ssz:
            fat.extend(struct.unpack(f"<{per}I", sec))

    def chain(start, table):
        out, s, seen = [], start, set()
        while s < 0xFFFFFFFA and s < len(table) and s not in seen and len(out) < max_secs:
            seen.add(s)
            out.append(s)
            s = table[s]
        return out

    dir_data = b"".join(sector(i) for i in chain(dir_start, fat))
    entries = []
    for off in range(0, len(dir_data) - 127, 128):
        raw = dir_data[off:off + 128]
        nlen = struct.unpack_from("<H", raw, 64)[0]
        name = raw[:max(0, nlen - 2)].decode("utf-16-le", errors="replace")
        etype = raw[66]
        start = struct.unpack_from("<I", raw, 116)[0]
        size = struct.unpack_from("<Q" if ssz == 4096 else "<I", raw, 120)[0]
        entries.append((name, etype, start, size))
    if not entries:
        raise ValueError("leeres Verzeichnis")
    root = entries[0]
    for name, etype, start, size in entries:
        if etype == 2 and name.lower() in names:
            if size < cutoff:
                mini_stream = b"".join(sector(i) for i in chain(root[2], fat))[:root[3]]
                minifat = []
                for sec_i in chain(minifat_start, fat):
                    minifat.extend(struct.unpack(f"<{per}I", sector(sec_i)))
                return b"".join(mini_stream[i * mssz:(i + 1) * mssz] for i in chain(start, minifat))[:size]
            return b"".join(sector(i) for i in chain(start, fat))[:size]
    raise ValueError("kein Workbook-Stream")


class _ChunkCursor:
    """Liest ueber SST- und CONTINUE-Records hinweg."""

    def __init__(self, chunks, pos=0):
        self.chunks, self.ci, self.pos = chunks, 0, pos

    def read(self, n):
        out = bytearray()
        while n > 0 and self.ci < len(self.chunks):
            chunk = self.chunks[self.ci]
            if self.pos >= len(chunk):
                self.ci, self.pos = self.ci + 1, 0
                continue
            take = min(n, len(chunk) - self.pos)
            out += chunk[self.pos:self.pos + take]
            self.pos += take
            n -= take
        return bytes(out)

    def read_string(self):
        import struct
        nch = struct.unpack("<H", self.read(2))[0]
        flags = self.read(1)[0]
        rt = struct.unpack("<H", self.read(2))[0] if flags & 8 else 0
        sz = struct.unpack("<I", self.read(4))[0] if flags & 4 else 0
        wide = flags & 1
        parts, left = [], nch
        while left > 0 and self.ci < len(self.chunks):
            chunk = self.chunks[self.ci]
            bpc = 2 if wide else 1
            take = min(left, (len(chunk) - self.pos) // bpc)
            if take > 0:
                raw = chunk[self.pos:self.pos + take * bpc]
                self.pos += take * bpc
                parts.append(raw.decode("utf-16-le" if wide else "latin-1", errors="replace"))
                left -= take
            if left > 0:  # Fortsetzung im naechsten CONTINUE-Record beginnt mit neuem Flag-Byte
                self.ci, self.pos = self.ci + 1, 0
                if self.ci < len(self.chunks):
                    wide = self.chunks[self.ci][0] & 1
                    self.pos = 1
        self.read(4 * rt + sz)
        return "".join(parts)


def _biff_string(body, pos, len_bytes=2):
    """Einfacher BIFF8-String innerhalb eines Records (LABEL, STRING, BOUNDSHEET)."""
    import struct
    if len_bytes == 2:
        nch = struct.unpack_from("<H", body, pos)[0]
        pos += 2
    else:
        nch = body[pos]
        pos += 1
    flags = body[pos]
    pos += 1
    if flags & 8:
        pos += 2
    if flags & 4:
        pos += 4
    if flags & 1:
        return body[pos:pos + 2 * nch].decode("utf-16-le", errors="replace")
    return body[pos:pos + nch].decode("latin-1", errors="replace")


def _rk_value(rk):
    import struct
    if rk & 2:
        val = rk >> 2
    else:
        val = struct.unpack("<d", struct.pack("<Q", (rk & 0xFFFFFFFC) << 32))[0]
    return val / 100 if rk & 1 else float(val)


def read_xls_builtin(path):
    """Excel 97-2003 (.xls, BIFF8) ohne Zusatzmodule lesen: erste Tabelle, Text und Zahlen."""
    import struct
    with open(path, "rb") as fh:
        data = fh.read()
    wb = _ole_stream(data)
    recs, pos = [], 0
    while pos + 4 <= len(wb):
        rid, ln = struct.unpack_from("<HH", wb, pos)
        recs.append((pos, rid, wb[pos + 4:pos + 4 + ln]))
        pos += 4 + ln
    if not recs or recs[0][1] != 0x0809 or struct.unpack_from("<H", recs[0][2], 0)[0] != 0x0600:
        raise ValueError("nur Excel 97-2003 (BIFF8) wird unterstützt")
    sst, sheets, i = [], [], 1
    while i < len(recs) and recs[i][1] != 0x000A:
        _off, rid, body = recs[i]
        if rid == 0x0085:
            sheets.append((struct.unpack_from("<I", body, 0)[0], body[5], _biff_string(body, 6, 1)))
        elif rid == 0x00FC:
            chunks, j = [body], i + 1
            while j < len(recs) and recs[j][1] == 0x003C:
                chunks.append(recs[j][2])
                j += 1
            unique = struct.unpack_from("<I", body, 4)[0]
            cur = _ChunkCursor(chunks, 8)
            for _ in range(unique):
                if cur.ci >= len(chunks):
                    break
                sst.append(cur.read_string())
        i += 1
    target = next((off for off, typ, _n in sheets if typ == 0), None)
    start = next((k for k, r in enumerate(recs) if r[0] == target), None)
    if start is None:
        raise ValueError("keine Tabelle gefunden")
    cells, pending = {}, None
    for _off, rid, body in recs[start + 1:]:
        if rid == 0x000A:
            break
        if rid == 0x00FD and len(body) >= 10:
            r, c, _xf, idx = struct.unpack_from("<HHHI", body, 0)
            cells[(r, c)] = sst[idx] if idx < len(sst) else ""
        elif rid == 0x0204:
            r, c = struct.unpack_from("<HH", body, 0)
            cells[(r, c)] = _biff_string(body, 6)
        elif rid == 0x0203:
            r, c, _xf, val = struct.unpack_from("<HHHd", body, 0)
            cells[(r, c)] = val
        elif rid == 0x027E:
            r, c, _xf, rk = struct.unpack_from("<HHHi", body, 0)
            cells[(r, c)] = _rk_value(rk)
        elif rid == 0x00BD:
            r, c0 = struct.unpack_from("<HH", body, 0)
            for k in range((len(body) - 6) // 6):
                rk = struct.unpack_from("<i", body, 4 + 6 * k + 2)[0]
                cells[(r, c0 + k)] = _rk_value(rk)
        elif rid == 0x0006 and len(body) >= 14:
            r, c = struct.unpack_from("<HH", body, 0)
            res = body[6:14]
            if res[6:8] == b"\xff\xff":
                if res[0] == 0:
                    pending = (r, c)
                elif res[0] == 1:
                    cells[(r, c)] = bool(res[2])
            else:
                cells[(r, c)] = struct.unpack("<d", res)[0]
        elif rid == 0x0207 and pending is not None:
            cells[pending] = _biff_string(body, 0)
            pending = None
        elif rid == 0x0205:
            r, c, _xf, val, err = struct.unpack_from("<HHHBB", body, 0)
            if not err:
                cells[(r, c)] = bool(val)
    if not cells:
        return []
    n_rows = max(r for r, _c in cells) + 1
    n_cols = max(c for _r, c in cells) + 1
    rows = [[""] * n_cols for _ in range(n_rows)]
    for (r, c), v in cells.items():
        rows[r][c] = v
    return rows


def read_xlsx_builtin(path):
    """Excel .xlsx ohne Zusatzmodule lesen: erste Tabelle."""
    import posixpath
    import zipfile
    import xml.etree.ElementTree as ET
    m = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{{{m}}}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{m}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        first = wb.find(f"{{{m}}}sheets/{{{m}}}sheet")
        rid = first.get(f"{{{rns}}}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels if r.get("Id") == rid)
        part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        sheet = ET.fromstring(z.read(part))
    cells = {}
    for row_i, row in enumerate(sheet.iter(f"{{{m}}}row")):
        r = int(row.get("r", row_i + 1)) - 1
        for col_i, c in enumerate(row.findall(f"{{{m}}}c")):
            ref = c.get("r")
            if ref:
                letters = "".join(ch for ch in ref if ch.isalpha())
                col = 0
                for ch in letters.upper():
                    col = col * 26 + (ord(ch) - 64)
                col -= 1
            else:
                col = col_i
            t = c.get("t", "n")
            v = c.find(f"{{{m}}}v")
            text = v.text if v is not None and v.text is not None else ""
            if t == "s":
                val = shared[int(text)] if text.isdigit() and int(text) < len(shared) else ""
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{m}}}t"))
            elif t in ("str", "e"):
                val = text
            elif t == "b":
                val = text == "1"
            else:
                try:
                    val = float(text) if text else ""
                except ValueError:
                    val = text
            cells[(r, col)] = val
    if not cells:
        return []
    n_rows = max(r for r, _c in cells) + 1
    n_cols = max(c for _r, c in cells) + 1
    rows = [[""] * n_cols for _ in range(n_rows)]
    for (r, c), v in cells.items():
        rows[r][c] = v
    return rows


def read_html_table(text):
    """Erste Tabelle einer als .xls getarnten HTML-Datei lesen."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows, self.row, self.cell, self.depth = [], None, None, 0

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self.depth += 1
            elif tag == "tr" and self.depth == 1:
                self.row = []
            elif tag in ("td", "th") and self.row is not None:
                self.cell = []
            elif tag == "br" and self.cell is not None:
                self.cell.append(" ")

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.cell is not None and self.row is not None:
                self.row.append(" ".join("".join(self.cell).split()))
                self.cell = None
            elif tag == "tr" and self.row is not None:
                self.rows.append(self.row)
                self.row = None
            elif tag == "table":
                self.depth -= 1

        def handle_data(self, data):
            if self.cell is not None:
                self.cell.append(data)

    p = P()
    p.feed(text)
    return p.rows


def _xml(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _col_letter(idx):
    out = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def write_xlsx_builtin(path, sheets, title="", subject="", decimal_cols=()):
    """Einfache .xlsx-Datei ohne Zusatzmodule schreiben.
    sheets: [(tabellenname, [kopfzeile, zeile, ...])], decimal_cols: Spaltentitel mit Format 0.00."""
    import zipfile
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>',
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>']
    wb_sheets, wb_rels, sheet_xml = [], [], []
    for i, (name, rows) in enumerate(sheets, start=1):
        ct.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                  'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        wb_sheets.append(f'<sheet name="{_xml(name)}" sheetId="{i}" r:id="rId{i}"/>')
        wb_rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                       f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
        header = rows[0] if rows else []
        dec = {k for k, h in enumerate(header) if h in decimal_cols}
        widths = [max([len(str(r[k])) for r in rows if k < len(r)] + [4]) for k in range(len(header))]
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
               '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
               'state="frozen"/></sheetView></sheetViews>']
        if widths:
            out.append("<cols>" + "".join(f'<col min="{k + 1}" max="{k + 1}" width="{min(45, w + 2)}" customWidth="1"/>'
                                          for k, w in enumerate(widths)) + "</cols>")
        out.append("<sheetData>")
        for r_i, row in enumerate(rows, start=1):
            cells = []
            for c_i, val in enumerate(row):
                ref = f"{_col_letter(c_i)}{r_i}"
                if val is None or val == "":
                    continue
                if isinstance(val, bool):
                    cells.append(f'<c r="{ref}" t="b"><v>{int(val)}</v></c>')
                elif isinstance(val, (int, float)):
                    style = ' s="2"' if (c_i in dec and r_i > 1) else ""
                    cells.append(f'<c r="{ref}"{style}><v>{val!r}</v></c>')
                else:
                    style = ' s="1"' if r_i == 1 else ""
                    cells.append(f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{_xml(val)}</t></is></c>')
            out.append(f'<row r="{r_i}">' + "".join(cells) + "</row>")
        out.append("</sheetData></worksheet>")
        sheet_xml.append("".join(out))
    ct.append("</Types>")
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.00"/></numFmts>'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
              '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill>'
              '<fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
              '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Standard" xfId="0" builtinId="0"/></cellStyles>'
              '</styleSheet>')
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets>' + "".join(wb_sheets) + '</sheets></workbook>')
    n = len(sheets)
    wb_rels.append(f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/styles" Target="styles.xml"/>')
    workbook_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     + "".join(wb_rels) + '</Relationships>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                 'officeDocument" Target="xl/workbook.xml"/>'
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
                 'core-properties" Target="docProps/core.xml"/></Relationships>')
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_xml(title)}</dc:title><dc:subject>{_xml(subject)}</dc:subject>'
            '<dc:creator>SWV Live-Ranking</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(ct))
        z.writestr("_rels/.rels", root_rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/styles.xml", styles)
        for i, xml_text in enumerate(sheet_xml, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml_text)


def _decode_text(raw):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _read_delimited(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    first = lines[0] if lines else ""
    delim = max(";,\t", key=first.count)
    # newline="" laesst csv alle Zeilenenden (Windows, Linux, alter Mac) selbst behandeln
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delim))


def read_table(path):
    """Startliste lesen. Format wird am Inhalt erkannt; Zusatzmodule nur, wenn vorhanden."""
    try:
        kind = sniff_format(path)
    except OSError as exc:
        raise StartlistError(f"Die Datei kann nicht geöffnet werden:\n{exc}")
    try:
        if kind == "xls":
            rows = None
            if xlrd is not None:
                try:
                    wb = xlrd.open_workbook(path, ignore_workbook_corruption=True)
                    sh = wb.sheet_by_index(0)
                    rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
                except Exception:
                    rows = None
            if rows is None:
                rows = read_xls_builtin(path)
        elif kind == "xlsx":
            rows = None
            if openpyxl is not None:
                try:
                    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
                    try:
                        rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
                    finally:
                        wb.close()
                except Exception:
                    rows = None
            if rows is None:
                rows = read_xlsx_builtin(path)
        elif kind in ("text", "text16", "html"):
            with open(path, "rb") as fh:
                raw = fh.read()
            text = raw.decode("utf-16") if kind == "text16" else _decode_text(raw)
            rows = read_html_table(text) if kind == "html" else _read_delimited(text)
        elif kind == "xml2003":
            raise StartlistError("Die Datei ist im Format «XML-Kalkulationstabelle 2003».\n"
                                 "Bitte in Excel als .xlsx oder als CSV speichern und erneut einlesen.")
        else:
            raise StartlistError("Die Datei ist keine Startliste im Format .xls, .xlsx oder .csv.")
    except StartlistError:
        raise
    except Exception as exc:
        raise StartlistError("Die Datei konnte nicht als Startliste gelesen werden.\n"
                             "Bitte in Excel öffnen und als .xlsx oder als CSV speichern.\n\n"
                             f"Technische Details: {exc}")
    rows = [["" if c is None else c for c in r] for r in rows]
    while rows and not any(cell_str(c) for c in rows[-1]):
        rows.pop()
    return rows


def detect_header(rows):
    aliases = {norm_header(a) for a in FIELD_ALIASES["nr"]}
    for i, row in enumerate(rows[:10]):
        if any(norm_header(c) in aliases for c in row):
            return i
    return 0


def auto_map(headers):
    mapping, used = {}, set()
    normed = [norm_header(h) for h in headers]
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            alias_n = norm_header(alias)
            hit = next((i for i, h in enumerate(normed) if h == alias_n and i not in used), None)
            if hit is not None:
                mapping[field] = hit
                used.add(hit)
                break
    return mapping


def build_startlist(rows, header_idx, mapping):
    order, parts = [], {}
    issues = {"ohne_nr": 0, "doppelt": []}
    nr_col = mapping.get("nr")
    for row in rows[header_idx + 1:]:
        def get(field):
            col = mapping.get(field)
            return cell_str(row[col]) if col is not None and col < len(row) else ""
        nr = cell_nr(row[nr_col]) if nr_col is not None and nr_col < len(row) else None
        if nr is None:
            if any(cell_str(c) for c in row):
                issues["ohne_nr"] += 1
            continue
        if nr in parts:
            issues["doppelt"].append(nr)
            continue
        parts[nr] = {
            "nr": nr, "p1": get("p1"), "p2": get("p2"), "kategorie": get("kategorie"),
            "verein": get("verein"), "vnr": get("vnr"), "staver": get("staver"), "fg": get("fg"),
            "bemerkung": get("bemerkung"), "notiz": "", "strafpunkte": 0, "unknown": False,
        }
        order.append(nr)
    return order, parts, issues


def guess_mode(path, parts):
    name = os.path.basename(path).lower()
    if "paar" in name:
        return "paar"
    if "einzel" in name:
        return "einzel"
    names = [p["p1"] for p in parts.values() if p["p1"]]
    if names and sum(" " in n for n in names) / len(names) > 0.5:
        return "paar"
    return "einzel"


def display_name(p, mode):
    if not p:
        return ""
    names = [x for x in (p.get("p1", ""), p.get("p2", "")) if x]
    return (" / " if mode == "paar" else " ").join(names)


def derive_category_ranges(order, parts):
    groups = {}
    for nr in order:
        cat = parts[nr]["kategorie"].strip()
        if cat:
            groups.setdefault(cat, []).append(nr)
    ranges = {}
    for cat, nrs in groups.items():
        blocks = {n // 100 for n in nrs}
        if len(blocks) == 1:
            b = blocks.pop()
            ranges[cat] = [max(1, b * 100), b * 100 + 99]
        else:
            ranges[cat] = [min(nrs), max(nrs)]
    names = list(ranges)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ra, rb = ranges[a], ranges[b]
            if ra[0] <= rb[1] and rb[0] <= ra[1]:
                ranges[a] = [min(groups[a]), max(groups[a])]
                ranges[b] = [min(groups[b]), max(groups[b])]
    return [(cat, ranges[cat][0], ranges[cat][1], len(groups[cat])) for cat in names]


# --------------------------------------------------------------------------- #
# Netzwerk / Laufwerke
# --------------------------------------------------------------------------- #
def ip_allowed(ip_text):
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_loopback or addr.is_link_local or (addr.is_private and not addr.is_unspecified)


def local_ipv4s():
    preferred, ips = None, set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.254.254.254", 1))
            preferred = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    if preferred:
        ips.add(preferred)
    lan = sorted(ip for ip in ips if ip_allowed(ip) and not ipaddress.ip_address(ip).is_loopback)
    if preferred in lan:
        lan.remove(preferred)
        lan.insert(0, preferred)
    return lan


def removable_drives():
    """[(pfad, anzeige)] fuer Wechseldatentraeger (USB-Sticks)."""
    drives = []
    if sys.platform.startswith("win"):
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            old_mode = k32.SetErrorMode(1)  # keine "Kein Datentraeger"-Dialoge
            try:
                mask = k32.GetLogicalDrives()
                for i, letter in enumerate(string.ascii_uppercase):
                    if not mask & (1 << i):
                        continue
                    root = f"{letter}:\\"
                    if k32.GetDriveTypeW(ctypes.c_wchar_p(root)) != 2:
                        continue
                    label = ctypes.create_unicode_buffer(261)
                    ok = k32.GetVolumeInformationW(ctypes.c_wchar_p(root), label, 261, None, None, None, None, 0)
                    if ok:
                        drives.append((root, f"{root}  {label.value}".strip()))
            finally:
                k32.SetErrorMode(old_mode)
        except Exception:
            pass
    else:
        user = os.environ.get("USER", "")
        for base in ("/Volumes", f"/media/{user}", "/media", f"/run/media/{user}"):
            try:
                for name in sorted(os.listdir(base)):
                    path = os.path.join(base, name)
                    if os.path.ismount(path) and path != "/":
                        drives.append((path, path))
            except OSError:
                pass
    return drives


# --------------------------------------------------------------------------- #
# QR-Code ohne Zusatzmodul (ISO/IEC 18004, Byte-Modus, Fehlerkorrektur M)
# --------------------------------------------------------------------------- #
# Version: (EC-Codewoerter pro Block, [(Anzahl Bloecke, Datencodewoerter pro Block), ...])
_QR_M = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]),
    5: (24, [(2, 43)]), 6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]), 10: (26, [(4, 43), (1, 44)]),
}
_QR_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38],
             8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}


def _gf_tables():
    exp, log = [0] * 512, [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_GF_EXP, _GF_LOG = _gf_tables()


def _gf_mul(a, b):
    return 0 if a == 0 or b == 0 else _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_remainder(data, degree):
    gen = [1]
    for i in range(degree):
        nxt = [0] * (len(gen) + 1)
        for j, coef in enumerate(gen):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, _GF_EXP[i])
        gen = nxt
    rem = [0] * degree
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for k in range(degree):
            rem[k] ^= _gf_mul(gen[k + 1], factor)
    return rem


def qr_matrix(text, mask=None):
    """QR-Code als Liste von Zeilen (True = dunkel). mask=None waehlt die beste Maske."""
    data = text.encode("utf-8")
    version = None
    for v in range(1, 11):
        ec, groups = _QR_M[v]
        capacity = sum(n * k for n, k in groups)
        count_bits = 8 if v <= 9 else 16
        if 4 + count_bits + 8 * len(data) <= capacity * 8:
            version = v
            break
    if version is None:
        raise ValueError("Text zu lang für den QR-Code")
    ec, groups = _QR_M[version]
    capacity = sum(n * k for n, k in groups)
    count_bits = 8 if version <= 9 else 16

    # Bitstrom: Modus 0100, Laenge, Daten, Abschluss, Fuellbytes
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in range(count_bits - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(codewords) < capacity:
        codewords.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC

    # Bloecke, Fehlerkorrektur, Verschraenkung
    blocks, pos = [], 0
    for n, k in groups:
        for _ in range(n):
            blocks.append(codewords[pos:pos + k])
            pos += k
    ecs = [_rs_remainder(b, ec) for b in blocks]
    final = []
    for i in range(max(len(b) for b in blocks)):
        final += [b[i] for b in blocks if i < len(b)]
    for i in range(ec):
        final += [e[i] for e in ecs]

    size = 17 + 4 * version
    mod = [[False] * size for _ in range(size)]
    func = [[False] * size for _ in range(size)]

    def put(x, y, dark):
        mod[y][x] = dark
        func[y][x] = True

    for i in range(size):
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    put(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    al = _QR_ALIGN[version]
    for i, ax in enumerate(al):
        for j, ay in enumerate(al):
            if (i == 0 and j == 0) or (i == 0 and j == len(al) - 1) or (i == len(al) - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    put(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def format_bits(m):
        d = (0 << 3) | m  # Stufe M = 00
        rem = d
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        return ((d << 10) | rem) ^ 0x5412

    def draw_format(m):
        b = format_bits(m)
        for i in range(6):
            put(8, i, (b >> i) & 1)
        put(8, 7, (b >> 6) & 1)
        put(8, 8, (b >> 7) & 1)
        put(7, 8, (b >> 8) & 1)
        for i in range(9, 15):
            put(14 - i, 8, (b >> i) & 1)
        for i in range(8):
            put(size - 1 - i, 8, (b >> i) & 1)
        for i in range(8, 15):
            put(8, size - 15 + i, (b >> i) & 1)
        put(8, size - 8, True)

    draw_format(0)  # reserviert die Formatbereiche
    if version >= 7:
        rem = version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        vb = (version << 12) | rem
        for i in range(18):
            bit = (vb >> i) & 1
            a, b = size - 11 + i % 3, i // 3
            put(a, b, bit)
            put(b, a, bit)

    # Daten im Zickzack platzieren
    i, right = 0, size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not func[y][x] and i < len(final) * 8:
                    mod[y][x] = bool((final[i >> 3] >> (7 - (i & 7))) & 1)
                    i += 1
        right -= 2

    masks = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
             lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
             lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
             lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

    def apply(m):
        out = [row[:] for row in mod]
        for y in range(size):
            for x in range(size):
                if not func[y][x] and masks[m](x, y):
                    out[y][x] = not out[y][x]
        return out

    def penalty(g):
        p = 0
        lines = g + [list(col) for col in zip(*g)]
        for line in lines:
            run, prev = 0, None
            for v in line:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        p += 3 + run - 5
                    run, prev = 1, v
            if run >= 5:
                p += 3 + run - 5
            s = "".join("1" if v else "0" for v in line)
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
        for y in range(size - 1):
            for x in range(size - 1):
                if g[y][x] == g[y][x + 1] == g[y + 1][x] == g[y + 1][x + 1]:
                    p += 3
        dark = sum(sum(row) for row in g)
        p += 10 * (abs(dark * 20 - size * size * 10) // (size * size))
        return p

    def with_format(m):
        draw_format(m)
        g = apply(m)
        return g

    if mask is None:
        best = min(range(8), key=lambda m: penalty(with_format(m)))
        return with_format(best)
    return with_format(mask)


# --------------------------------------------------------------------------- #
# Onlinetool (Platzhalter)
# --------------------------------------------------------------------------- #
class OnlineClient:
    """
    Platzhalter fuer die API des Onlinetools.
    Vorgesehen:
      fetch_startlist()  -> Startliste inkl. Strafpunkte (Onlinetool ist Master)
      send_result(dict)  -> nur gefahrene Zeit, keine Strafpunkte
    """
    connected = False

    def __init__(self, settings):
        self.settings = settings

    def fetch_startlist(self):
        raise NotImplementedError("Onlinetool noch nicht angebunden")

    def send_result(self, payload):
        raise NotImplementedError("Onlinetool noch nicht angebunden")


# --------------------------------------------------------------------------- #
# Browser-Anzeige im lokalen Netz (nur lesend)
# --------------------------------------------------------------------------- #
WEB_HTML = """<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>SWV Live-Ranking</title>
<link rel="stylesheet" href="/app.css?key=__KEY__"></head>
<body data-key="__KEY__">
<header><div id="live" class="bar blue"></div><div id="ziel" class="bar green"></div></header>
<div id="wrap"><main id="cats"></main><aside id="next" hidden></aside></div>
<footer id="state">Verbinde ...</footer>
<script src="/app.js?key=__KEY__"></script>
</body></html>"""

WEB_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#000;color:#fff;
 font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI Variable Display","Segoe UI",Inter,Roboto,sans-serif;
 -webkit-font-smoothing:antialiased}
header{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:10px}
.bar{padding:12px 18px;border-radius:16px;min-height:3.4em}.blue{background:#0872dd}.green{background:#1e8538}
.big{font-size:clamp(20px,3vw,36px);font-weight:700;letter-spacing:-.01em}
.sub{font-size:clamp(13px,1.6vw,19px);font-weight:500;opacity:.96}
#wrap{display:flex;gap:10px;padding:0 10px 10px}
#cats{flex:1;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.card,aside{background:#1c1c1e;border-radius:18px;padding:14px 16px}
aside{width:320px}h2{margin:0 0 8px;font-size:15px;font-weight:600;color:#98989d;letter-spacing:.02em}
.row{font-size:22px;font-weight:700;display:flex;gap:10px;align-items:baseline}.row.first{color:#ffd60a;font-size:26px}
.pen{color:#ff9f0a;font-size:15px}.who{color:#98989d;font-size:14px;margin:0 0 6px}.empty{color:#98989d;font-size:18px}
footer{padding:6px 14px 12px;font-size:12px;color:#98989d}footer.err{color:#ff453a}
@media(max-width:700px){header{grid-template-columns:1fr}#wrap{flex-direction:column}aside{width:auto}}
"""

WEB_JS = r"""
(function(){
  var key=document.body.getAttribute('data-key'), last='', lastOk=0, lastTry=0, busy=false;
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
  function clear(n){while(n.firstChild)n.removeChild(n.firstChild);}
  function lines(box,arr){clear(box);(arr||[]).forEach(function(t,i){if(t)box.appendChild(el('div',i===0?'big':'sub',t));});}
  function render(d){
    lines(document.getElementById('live'),d.live);lines(document.getElementById('ziel'),d.ziel);
    var cats=document.getElementById('cats');clear(cats);
    d.cats.forEach(function(c){
      var card=el('section','card');card.appendChild(el('h2',null,c.name));
      if(!c.rows.length)card.appendChild(el('div','empty','Noch keine Zeiten'));
      c.rows.forEach(function(r){
        var line=el('div',r.rank===1?'row first':'row');
        line.appendChild(el('span',null,r.rank+'. Nr. '+r.nr));line.appendChild(el('span',null,'➔'));
        line.appendChild(el('span',null,r.time+'s'));if(r.pen)line.appendChild(el('span','pen','+'+r.pen));
        card.appendChild(line);if(r.who)card.appendChild(el('div','who',r.who));
      });
      cats.appendChild(card);
    });
    var nx=document.getElementById('next');clear(nx);
    if(d.next&&d.next.length){nx.hidden=false;nx.appendChild(el('h2',null,'Als nächstes am Start'));
      d.next.forEach(function(n){nx.appendChild(el('div','row','Nr '+n.nr+'  '+n.name));nx.appendChild(el('div','who',n.info));});}
    else nx.hidden=true;
  }
  function state(){
    var s=document.getElementById('state'), age=(Date.now()-lastOk)/1000;
    if(lastOk&&age<=5){s.className='';}
    else{s.className='err';s.textContent=lastOk?('Verbindung unterbrochen, Daten '+Math.round(age)+' s alt. Neuer Versuch läuft ...'):'Keine Verbindung zum Speaker-PC';}
  }
  function tick(){
    busy=true;lastTry=Date.now();
    var x=new XMLHttpRequest(), done=false;
    function finish(){if(done)return;done=true;busy=false;state();setTimeout(tick,1000);}
    // eindeutige Adresse pro Abfrage: nie eine Antwort aus dem Zwischenspeicher
    x.open('GET','/data?key='+encodeURIComponent(key)+'&t='+Date.now(),true);
    x.timeout=3000;
    x.onload=function(){
      if(x.status===200){
        try{var t=x.responseText,d=JSON.parse(t);if(t!==last){last=t;render(d);}
          lastOk=Date.now();document.getElementById('state').textContent='Verbunden, Stand '+d.time;}catch(e){}
      }
      finish();
    };
    x.onerror=finish;x.ontimeout=finish;x.onabort=finish;
    try{x.send();}catch(e){finish();}
  }
  // Notbremse: falls die Abfrageschleife trotzdem stehen bleibt, neu starten
  setInterval(function(){if(busy&&Date.now()-lastTry>8000){busy=false;tick();}else if(!busy&&Date.now()-lastTry>15000){tick();}state();},2000);
  tick();
})();
"""


class _WebHandler(BaseHTTPRequestHandler):
    server_version = "SWV"
    sys_version = ""
    timeout = 10

    def log_message(self, *args):  # kein stderr (in der .exe nicht vorhanden)
        pass

    def do_GET(self):
        self._serve(send_body=True)

    def do_HEAD(self):
        self._serve(send_body=False)

    def _deny(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def _serve(self, send_body):
        lan = self.server.lan
        if not ip_allowed(self.client_address[0]):
            return self._deny(403)
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in lan.allowed_hosts:
            return self._deny(403)
        parts = urllib.parse.urlsplit(self.path)
        key = urllib.parse.parse_qs(parts.query).get("key", [""])[0]
        if not hmac.compare_digest(key.encode("utf-8"), lan.key.encode("utf-8")):
            return self._deny(403)
        if parts.path == "/":
            ctype, data = "text/html; charset=utf-8", WEB_HTML.replace("__KEY__", lan.key).encode("utf-8")
        elif parts.path == "/app.js":
            ctype, data = "application/javascript; charset=utf-8", WEB_JS.encode("utf-8")
        elif parts.path == "/app.css":
            ctype, data = "text/css; charset=utf-8", WEB_CSS.encode("utf-8")
        elif parts.path == "/data":
            ctype, data = "application/json; charset=utf-8", lan.snapshot
        else:
            return self._deny(404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                         "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        if send_body:
            self.wfile.write(data)


class LanServer:
    """Nur lesender Webserver: GET auf 4 feste Pfade, Schluessel, nur private Adressen."""

    def __init__(self):
        self.httpd = None
        self.key = ""
        self.allowed_hosts = set()
        self.snapshot = b"{}"
        self.url = ""

    @property
    def running(self):
        return self.httpd is not None

    def start(self, bind, port, key):
        if not ip_allowed(bind):
            raise ValueError("Nur private Netzwerkadressen (z.B. 192.168.x.x) sind erlaubt.")
        if not re.fullmatch(r"[A-Za-z0-9_\-]{16,}", key):
            raise ValueError("Ungültiger Schlüssel.")
        httpd = ThreadingHTTPServer((bind, port), _WebHandler)
        httpd.daemon_threads = True
        httpd.lan = self
        self.key = key
        self.allowed_hosts = {f"{bind}:{port}", f"localhost:{port}", f"127.0.0.1:{port}"}
        if port == 80:
            self.allowed_hosts |= {bind, "localhost", "127.0.0.1"}
        self.url = f"http://{bind}:{port}/?key={key}"
        self.httpd = httpd
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True).start()

    def stop(self):
        if self.httpd is not None:
            httpd, self.httpd = self.httpd, None
            httpd.shutdown()
            httpd.server_close()


def friendly_open_error(port, exc):
    """Verstaendliche Meldung, wenn ein COM-Port nicht geoeffnet werden kann."""
    text = str(exc)
    low = text.lower()
    if "permissionerror" in low or "zugriff verweigert" in low or "access is denied" in low or "errno 13" in low:
        return (f"{port} wird von einem anderen Programm verwendet oder ist blockiert.\n"
                "Anderes Programm mit dem CP 545 schliessen (z.B. ein Terminalprogramm) und erneut verbinden.")
    if ("filenotfounderror" in low or "nicht gefunden" in low or "cannot find" in low
            or "no such file" in low or "could not open port" in low):
        return f"{port} wurde nicht gefunden.\nIst der USB-Adapter eingesteckt? Danach ⟳ drücken und erneut verbinden."
    return f"{port} konnte nicht geöffnet werden.\nUSB-Adapter aus- und wieder einstecken und erneut verbinden."


def port_identity(device):
    """Geraetekennung (Hersteller, Produkt, Seriennummer) eines COM-Ports, sofern vorhanden."""
    if serial is None:
        return None
    for p in serial.tools.list_ports.comports():
        if p.device == device and p.vid is not None:
            return {"vid": p.vid, "pid": p.pid, "serial": p.serial_number or ""}
    return None


def find_port(device, identity):
    """Adapter wiederfinden: zuerst ueber die Geraetekennung (COM-Nummer kann wechseln), sonst gleiche COM-Nummer."""
    if serial is None:
        return None
    ports = list(serial.tools.list_ports.comports())
    if identity:
        same = [p for p in ports if p.vid == identity["vid"] and p.pid == identity["pid"]]
        if identity.get("serial"):
            exact = [p for p in same if (p.serial_number or "") == identity["serial"]]
            if exact:
                return exact[0].device
        if len(same) == 1:
            return same[0].device
        if any(p.device == device for p in same):
            return device
    if any(p.device == device for p in ports):
        return device
    return None


# --------------------------------------------------------------------------- #
# Serieller Lese-Thread
# --------------------------------------------------------------------------- #
class SerialReader(threading.Thread):
    def __init__(self, port, baud, out_queue):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.q = out_queue
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            ser = serial.serial_for_url(
                self.port, baudrate=self.baud, bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=0.1,
            )
        except Exception as exc:
            self.q.put(("open_error", exc, self))
            return
        self.q.put(("connected", self.port, self))
        buf = bytearray()
        try:
            while not self.stop_event.is_set():
                chunk = ser.read(ser.in_waiting or 1)
                if not chunk:
                    continue
                buf.extend(chunk)
                while True:
                    idx = buf.find(b"\n")
                    if idx < 0:
                        break
                    frame = bytes(buf[:idx])
                    del buf[: idx + 1]
                    stx = frame.rfind(b"\x02")
                    if stx >= 0:
                        frame = frame[stx + 1:]
                    self.q.put(("line", frame.decode("latin-1", errors="replace"), self))
                if len(buf) > 4096:
                    buf.clear()
        except Exception as exc:
            if not self.stop_event.is_set():
                self.q.put(("lost", exc, self))
        finally:
            try:
                ser.close()
            except Exception:
                pass
            self.q.put(("disconnected", self.port, self))


# --------------------------------------------------------------------------- #
# Anwendung
# --------------------------------------------------------------------------- #
class LiveRankingApp:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.reader = None
        self.data_path = data_dir()

        self.settings = self.load_settings()
        self.categories = self.load_categories()
        self._cat_lookup = {}
        self.rebuild_cat_lookup()

        self.results = {}       # nr -> {"secs","str","ts","source","run","prev","status"}
        self.participants = {}  # nr -> Startlisten-Eintrag
        self.start_order = []
        self.order_index = {}
        self.startlist_source = ""
        self._rank_cache = None

        self.current_nr = None
        self.live_time = None
        self.live_secs = None
        self.live_final = False
        self.ziel_nr = None
        self.last_club = None
        self.last_block = None

        self.blink = {}
        self.blink_phase = False
        self.prev_top = {}
        self.cards = []
        self.ticker = []
        self.port_map = {}
        self._scale_job = None
        self._text_cache = {}
        self.participant_dialogs = {}
        self.upload_win = None
        self.note_win = None
        self._full_text = {}
        self._event_job = None
        self._last_suggested = None
        self.card_cols = 3
        self.cards_scrolling = False
        self.panel_orient = "right"
        self._drag = None
        self.card_inner_w = 300
        self.reconnecting = False
        self._reconnect_job = None
        self.conn_target = {"port": "", "baud": DEFAULT_BAUD, "identity": None}
        self._row_tpl = ("5. Nr. 888", "8:88.88s", "")

        self.online = OnlineClient(self.settings["online"])
        self.web = LanServer()

        self.setup_window()
        self.setup_fonts()
        self.setup_styles()
        self.build_ui()
        self.refresh_ports()
        self.build_cards()
        self.apply_show_settings()
        self.load_autosave()
        self.update_live_info()
        self.update_ziel_info()
        self.update_window_title()
        self.report_missing_modules()

        self.root.after(POLL_INTERVAL_MS, self.poll_queue)
        self.root.after(BLINK_INTERVAL_MS, self.blink_tick)
        self.root.after(WEB_SNAPSHOT_MS, self.web_tick)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ================================================================== #
    # Fenster / Stil
    # ================================================================== #
    def setup_window(self):
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG)
        self.root.minsize(1000, 600)
        try:
            self.root.state("zoomed")
        except tk.TclError:
            try:
                self.root.attributes("-zoomed", True)
            except tk.TclError:
                self.root.geometry("1600x900")
        self.icon_img = None
        for name in ICON_FILES:
            for d in resource_dirs():
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    try:
                        self.icon_img = tk.PhotoImage(file=path)
                        self.root.iconphoto(True, self.icon_img)
                        return
                    except tk.TclError:
                        pass

    def setup_fonts(self):
        families = set(tkfont.families(self.root))
        fam = next((f for f in ("SF Pro Display", "SF Pro Text", ".AppleSystemUIFont", "Segoe UI Variable Display",
                                "Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", "Inter", "DejaVu Sans")
                    if f in families), "TkDefaultFont")
        mono = next((f for f in ("SF Mono", "Menlo", "Cascadia Mono", "Consolas", "DejaVu Sans Mono")
                     if f in families), "TkFixedFont")
        try:
            dpi = float(self.root.winfo_fpixels("1i"))
        except tk.TclError:
            dpi = 96.0
        self.ui_scale = max(1.0, min(3.0, dpi / 96.0))
        self.side_w = int(358 * self.ui_scale)
        self.wrap_w = self.side_w - int(70 * self.ui_scale)
        self.f_status = tkfont.Font(family=fam, size=-28, weight="bold")
        self.f_status_name = tkfont.Font(family=fam, size=-18, weight="bold")
        self.f_status_sub = tkfont.Font(family=fam, size=-16)
        self.f_ticker = tkfont.Font(family=fam, size=-20)
        self.f_ticker_bold = tkfont.Font(family=fam, size=-20, weight="bold")
        self.f_ticker_time = tkfont.Font(family=fam, size=-15)
        self._mf_bold = tkfont.Font(family=fam, size=-30, weight="bold")
        self._mf_row = tkfont.Font(family=fam, size=-30, weight="bold")
        self._mf_title = tkfont.Font(family=fam, size=-20, weight="bold")
        self._mf_sub = tkfont.Font(family=fam, size=-15)
        self._mf_pen = tkfont.Font(family=fam, size=-16, weight="bold")
        self.f_title = tkfont.Font(family=fam, size=-22, weight="bold")
        self.f_row = tkfont.Font(family=fam, size=-28, weight="bold")
        self.f_first = tkfont.Font(family=fam, size=-36, weight="bold")
        self.f_sub = tkfont.Font(family=fam, size=-15)
        self.f_pen = tkfont.Font(family=fam, size=-16, weight="bold")
        self.f_panel = tkfont.Font(family=fam, size=-15)
        self.f_panel_bold = tkfont.Font(family=fam, size=-15, weight="bold")
        self.f_panel_head = tkfont.Font(family=fam, size=-16, weight="bold")
        self.f_side = tkfont.Font(family=fam, size=10)
        self.f_side_bold = tkfont.Font(family=fam, size=10, weight="bold")
        self.f_side_head = tkfont.Font(family=fam, size=11, weight="bold")
        self.f_log = tkfont.Font(family=mono, size=9)
        self.f_dialog = tkfont.Font(family=fam, size=-40, weight="bold")

    def setup_styles(self):
        self.root.option_add("*TCombobox*Listbox.background", LIST_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", LIST_FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", BLUE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", WHITE)
        self.root.option_add("*TCombobox*Listbox.font", self.f_side)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Port.TCombobox", fieldbackground=INPUT_BG, background=BUTTON, foreground=INPUT_FG,
                        arrowcolor=WHITE, padding=4, bordercolor=BORDER, lightcolor=INPUT_BG, darkcolor=INPUT_BG,
                        insertcolor=WHITE)
        style.map("Port.TCombobox",
                  fieldbackground=[("readonly", INPUT_BG), ("!disabled", INPUT_BG)],
                  foreground=[("readonly", INPUT_FG), ("!disabled", INPUT_FG)],
                  selectbackground=[("!disabled", BLUE)],
                  selectforeground=[("!disabled", WHITE)])
        style.configure("Dark.Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=int(26 * self.ui_scale), font=self.f_side, borderwidth=0)
        style.map("Dark.Treeview", background=[("selected", BLUE)], foreground=[("selected", WHITE)])
        style.configure("Dark.Treeview.Heading", background=PANEL2, foreground=MUTED, font=self.f_side_bold,
                        relief="flat", borderwidth=0)
        style.map("Dark.Treeview.Heading", background=[("active", BLUE)])

    # ---------------- Widget-Helfer ---------------- #
    def _button(self, parent, text, cmd, color=None):
        color = BUTTON if color in (None, BORDER) else color
        return RoundButton(parent, text=text, command=cmd, bg=color, fg=WHITE, font=self.f_side_bold,
                           radius=int(9 * self.ui_scale), padx=int(12 * self.ui_scale), pady=int(6 * self.ui_scale))

    def _entry(self, parent, width=10, **kw):
        return tk.Entry(parent, width=width, bg=INPUT_BG, fg=INPUT_FG, insertbackground=INPUT_FG,
                        relief="flat", font=self.f_side, highlightthickness=1, selectbackground=BLUE,
                        highlightbackground=BORDER, highlightcolor=ACCENT, **kw)

    def _label(self, parent, text, bold=False, fg=TEXT, bg=PANEL, **kw):
        return tk.Label(parent, text=text, bg=bg, fg=fg,
                        font=self.f_side_bold if bold else self.f_side, anchor="w", **kw)

    # Auswahl als Umschaltknoepfe: aktiv = blau. Eindeutig auf jedem System, unabhaengig vom Theme.
    def _check(self, parent, text, var, bg=PANEL):
        return tk.Checkbutton(parent, text=text, variable=var, indicatoron=False, bg=BUTTON, fg=WHITE,
                              selectcolor=BLUE, activebackground=BLUE, activeforeground=WHITE,
                              font=self.f_side, relief="flat", offrelief="flat", overrelief="flat",
                              bd=0, padx=10, pady=4, highlightthickness=0, cursor="hand2")

    def _radio(self, parent, text, var, value, bg=PANEL, command=None):
        return tk.Radiobutton(parent, text=text, variable=var, value=value, indicatoron=False, bg=BUTTON,
                              fg=WHITE, selectcolor=BLUE, activebackground=BLUE, activeforeground=WHITE,
                              font=self.f_side, relief="flat", offrelief="flat", overrelief="flat",
                              bd=0, padx=10, pady=4, highlightthickness=0, cursor="hand2", command=command)

    def _combo(self, parent, values=(), width=20, state="normal"):
        cb = ttk.Combobox(parent, style="Port.TCombobox", font=self.f_side, values=list(values),
                          width=width, state=state)
        return cb

    def _section(self, parent, title, key=None, status=False):
        box = RoundedPanel(parent, fill=PANEL, radius=int(12 * self.ui_scale), fit_height=True)
        box.pack(fill="x", padx=10, pady=(10, 0))
        frm = box.inner
        headf = tk.Frame(frm, bg=PANEL, cursor="hand2" if key else "")
        headf.pack(fill="x", padx=12, pady=(10, 8))
        head = tk.Label(headf, bg=PANEL, fg=TEXT, font=self.f_side_head, anchor="w")
        head.pack(side="left")
        stat = None
        if status:
            stat = tk.Label(headf, bg=PANEL, fg=MUTED, font=self.f_side_bold, anchor="w")
            stat.pack(side="left", padx=(8, 0))
        body = tk.Frame(frm, bg=PANEL)

        def render():
            collapsed = bool(key) and self.settings["collapsed"].get(key, False)
            head.configure(text=(("›  " if collapsed else "⌄  ") if key else "") + title)
            if collapsed:
                body.pack_forget()
            else:
                body.pack(fill="x", padx=12, pady=(0, 12))

        if key:
            def toggle(_e=None):
                self.settings["collapsed"][key] = not self.settings["collapsed"].get(key, False)
                render()
                self.save_settings()
            for w in (headf, head, stat):
                if w is not None:
                    w.bind("<Button-1>", toggle)
                    w.configure(cursor="hand2")
        render()
        return (body, stat) if status else body

    def _toplevel(self, title):
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=PANEL, padx=18, pady=14)
        dlg.transient(self.root)
        if self.icon_img is not None:
            dlg.iconphoto(False, self.icon_img)
        return dlg

    def _center(self, dlg):
        dlg.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dlg.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dlg.winfo_height()) // 3
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")

    def confirm_danger(self, title, message, action_label):
        """Sichere Rückfrage: 'Abbrechen' ist vorausgewählt, Enter und Escape brechen ab."""
        dlg = self._toplevel(title)
        dlg.resizable(False, False)
        result = {"ok": False}
        row = tk.Frame(dlg, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="⚠", bg=PANEL, fg=GOLD, font=self.f_dialog).pack(side="left", padx=(0, 14), anchor="n")
        tk.Label(row, text=message, bg=PANEL, fg=TEXT, font=self.f_side, justify="left", anchor="w",
                 wraplength=int(460 * self.ui_scale)).pack(side="left", fill="x")
        btns = tk.Frame(dlg, bg=PANEL)
        btns.pack(fill="x", pady=(16, 0))

        def ok():
            result["ok"] = True
            dlg.destroy()

        cancel = self._button(btns, "Abbrechen", dlg.destroy, BLUE)
        cancel.pack(side="right")
        self._button(btns, action_label, ok, DARK_RED).pack(side="right", padx=(0, 8))
        cancel.bind("<Return>", lambda e: dlg.destroy())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        for w in (dlg, cancel):
            w.bind("<Escape>", lambda e: dlg.destroy())
        self._center(dlg)
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()
        cancel.focus_set()
        self.root.wait_window(dlg)
        return result["ok"]

    @staticmethod
    def _set(widget, **kw):
        changed = {k: v for k, v in kw.items() if str(widget.cget(k)) != str(v)}
        if changed:
            widget.configure(**changed)

    def _set_text(self, widget, segments):
        """Text-Widget nur neu befuellen, wenn sich der Inhalt geaendert hat."""
        key = repr(segments)
        if self._text_cache.get(str(widget)) == key:
            return
        self._text_cache[str(widget)] = key
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for text, tag in segments:
            tags = tag if isinstance(tag, tuple) else ((tag,) if tag else ())
            widget.insert("end", text, tags)
        widget.configure(state="disabled")

    def _set_fit(self, label, text, font=None, width=None, **kw):
        """Text setzen und bei Platzmangel sauber mit '…' kuerzen (Volltext bleibt gespeichert)."""
        self._full_text[str(label)] = text
        font = font or self._label_font(label)
        if width is None:
            width = label.winfo_width() - 6
        self._set(label, text=fit_text(font, text, width), **kw)

    def _label_font(self, label):
        name = str(label.cget("font"))
        for f in (self.f_status, self.f_status_name, self.f_status_sub, self.f_title, self.f_sub):
            if str(f) == name:
                return f
        return tkfont.nametofont(name) if name in tkfont.names(self.root) else self.f_side

    # ================================================================== #
    # Aufbau UI
    # ================================================================== #
    def build_ui(self):
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Seitenleiste (scrollbar)
        outer = tk.Frame(self.root, bg=BG, width=self.side_w)
        outer.grid(row=0, column=0, sticky="ns")
        outer.grid_propagate(False)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        sbar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        sbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=sbar.set)
        side = tk.Frame(canvas, bg=BG)
        win = canvas.create_window(0, 0, window=side, anchor="nw")

        def update_scroll(_event=None):
            canvas.configure(scrollregion=(0, 0, side.winfo_reqwidth(), side.winfo_reqheight()))
            if side.winfo_reqheight() <= canvas.winfo_height():
                sbar.grid_remove()
                canvas.yview_moveto(0)
            else:
                sbar.grid()

        side.bind("<Configure>", update_scroll)
        canvas.bind("<Configure>", lambda e: (canvas.itemconfigure(win, width=e.width), update_scroll()))

        def on_wheel(event):
            w = self.root.winfo_containing(event.x_root, event.y_root)
            if w is None:
                return
            if event.num == 4:
                step = -1
            elif event.num == 5:
                step = 1
            else:
                step = -1 if event.delta > 0 else 1
            path = str(w)
            if path.startswith(str(outer)):
                if isinstance(w, (tk.Listbox, tk.Text)) or not sbar.winfo_ismapped():
                    return
                canvas.yview_scroll(step * 3, "units")
            elif path.startswith(str(self.cards_canvas)) and self.cards_scrolling:
                self.cards_canvas.yview_scroll(step * 3, "units")

        self.root.bind_all("<MouseWheel>", on_wheel, add="+")
        self.root.bind_all("<Button-4>", on_wheel, add="+")
        self.root.bind_all("<Button-5>", on_wheel, add="+")
        self.side_canvas = canvas

        # Hauptbereich
        main = tk.Frame(self.root, bg=BG)
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=10)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        self.main = main

        status = tk.Frame(main, bg=BG)
        status.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        status.columnconfigure(0, weight=1, uniform="status")
        status.columnconfigure(1, weight=1, uniform="status")
        self.live_labels = self._status_box(status, 0, BLUE, "LAUFEND: -")
        self.ziel_labels = self._status_box(status, 1, GREEN, "ZIEL: -")
        self.lbl_live = self.live_labels[0]
        self.lbl_ziel = self.ziel_labels[0]

        content = tk.Frame(main, bg=BG)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.content = content
        self.cards_canvas = tk.Canvas(content, bg=BG, highlightthickness=0, bd=0)
        self.cards_canvas.grid(row=0, column=0, sticky="nsew")
        self.cards_sb = tk.Scrollbar(content, orient="vertical", command=self.cards_canvas.yview)
        self.cards_canvas.configure(yscrollcommand=self.cards_sb.set)
        self.cards_area = tk.Frame(self.cards_canvas, bg=BG)
        self.cards_win = self.cards_canvas.create_window(0, 0, window=self.cards_area, anchor="nw")
        self.cards_canvas.bind("<Configure>", lambda e: self.schedule_font_scale())

        self.right_panel = tk.Frame(content, bg=BG, width=400, height=240)
        self.right_panel.grid_propagate(False)
        self.right_panel.pack_propagate(False)
        self.panel_next, self.txt_next = self._panel(self.right_panel, "Als nächstes am Start", NEXT_COUNT * 2 + 3)
        self.panel_note, self.txt_note = self._panel(self.right_panel, "Notiz", 3)
        self.panel_note.set_outline(GOLD, 2)
        self.txt_note.configure(font=self.f_ticker, fg=WHITE)
        self.txt_note.tag_configure("nr", font=self.f_ticker_bold, foreground=GOLD, spacing1=0)
        self.txt_note.tag_configure("sub", font=self.f_ticker_time, foreground=MUTED)
        self._note_visible = False
        self.panel_ticker, self.txt_ticker = self._panel(self.right_panel, "Ereignis-Ticker", 6, fit=False)
        self.panel_stats, self.txt_stats = self._panel(self.right_panel, "Statistik", 9)
        # Ticker: groessere, kontrastreichere Schrift (Punkt 9)
        self.txt_ticker.configure(font=self.f_ticker, fg=WHITE, spacing1=0, spacing3=0)
        self.txt_ticker.tag_configure("time", font=self.f_ticker_time, foreground=MUTED)
        self.txt_ticker.tag_configure("ziel", foreground=GREEN_TEXT)
        self.txt_ticker.tag_configure("warn", foreground=GOLD)
        self.txt_ticker.tag_configure("test", foreground=MUTED)
        self.txt_ticker.tag_configure("entry", spacing1=8)
        self.txt_ticker.tag_configure("newest", font=self.f_ticker_bold)

        # Seitenleiste erst jetzt, weil sie auf Kartenbereich und Panels verweist
        self.build_sidebar(side)

    def _status_box(self, parent, col, color, text):
        panel = RoundedPanel(parent, fill=color, radius=int(16 * self.ui_scale), fit_height=True)
        panel.grid(row=0, column=col, sticky="nsew", padx=(6, 3) if col == 0 else (3, 6))
        box = panel.inner
        box.configure(padx=int(18 * self.ui_scale), pady=int(8 * self.ui_scale))
        big = tk.Label(box, text=text, bg=color, fg=WHITE, font=self.f_status, anchor="w", width=1)
        big.pack(fill="x")
        sub1 = tk.Label(box, text="", bg=color, fg=WHITE, font=self.f_status_name, anchor="w", width=1)
        sub1.pack(fill="x")
        sub2 = tk.Label(box, text="", bg=color, fg=WHITE, font=self.f_status_sub, anchor="w", width=1)
        sub2.pack(fill="x")
        return big, sub1, sub2

    def _panel(self, parent, title, height, fit=True):
        box = RoundedPanel(parent, fill=PANEL, radius=int(16 * self.ui_scale), pad=2, fit_height=fit)
        if not fit:
            box.configure(width=1, height=1)
        frm = box.inner
        tk.Label(frm, text=title, bg=PANEL, fg=MUTED, font=self.f_panel_head, anchor="w").pack(
            fill="x", padx=12, pady=(8, 2))
        txt = tk.Text(frm, height=height, width=1, bg=PANEL, fg=TEXT, font=self.f_panel, relief="flat",
                      wrap="word", state="disabled", highlightthickness=0, padx=12, pady=4, cursor="arrow", bd=0)
        txt.pack(fill="both", expand=True, pady=(0, 8))
        txt.tag_configure("nr", font=self.f_panel_bold, foreground=WHITE, spacing1=6)
        txt.tag_configure("sub", foreground=MUTED)
        txt.tag_configure("note", foreground=GOLD)
        txt.tag_configure("ziel", foreground=GREEN)
        txt.tag_configure("warn", foreground=GOLD)
        txt.tag_configure("error", foreground=RED)
        txt.tag_configure("time", foreground=MUTED)
        txt.tag_configure("bold", font=self.f_panel_bold)
        txt.tag_configure("ziel", foreground=GREEN_TEXT)
        return box, txt

    def build_sidebar(self, side):
        wrap = self.wrap_w

        # Wettkampf (Punkt 13)
        b, self.lbl_event_head = self._section(side, "Wettkampf", "wettkampf", status=True)
        b.columnconfigure(1, weight=1)
        b.columnconfigure(3, weight=1)
        ev = self.settings["event"]
        self._label(b, "Name").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.e_event_name = self._entry(b, width=18)
        self.e_event_name.grid(row=0, column=1, columnspan=3, sticky="ew")
        self._label(b, "Datum").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        self.e_event_from = self._entry(b, width=10)
        self.e_event_from.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self._label(b, "bis").grid(row=1, column=2, sticky="w", padx=6, pady=(6, 0))
        self.e_event_to = self._entry(b, width=10)
        self.e_event_to.grid(row=1, column=3, sticky="ew", pady=(6, 0))
        self.lbl_event_hint = self._label(b, "Datum als TT.MM.JJJJ, «bis» leer lassen bei einem Tag",
                                          fg=MUTED, wraplength=wrap, justify="left")
        self.lbl_event_hint.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        for entry, key in ((self.e_event_name, "name"), (self.e_event_from, "von"), (self.e_event_to, "bis")):
            entry.insert(0, ev.get(key, ""))
            entry.bind("<KeyRelease>", lambda e: self.schedule_event_save())
            entry.bind("<FocusOut>", lambda e: self.save_event_fields(normalize=True))
            entry.bind("<Return>", lambda e: self.save_event_fields(normalize=True))

        # Verbindung (Punkt 6: aufklappbar, Status immer in der Kopfzeile)
        b, self.lbl_conn_head = self._section(side, "Verbindung", "verbindung", status=True)
        b.columnconfigure(0, weight=1)
        self._label(b, "COM-Port").grid(row=0, column=0, columnspan=2, sticky="w")
        self.cmb_port = self._combo(b)
        self.cmb_port.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self._button(b, "⟳", self.refresh_ports).grid(row=1, column=1, sticky="e", padx=(6, 0), pady=(2, 6))
        self._label(b, "Baudrate").grid(row=2, column=0, columnspan=2, sticky="w")
        self.e_baud = self._entry(b, width=10)
        self.e_baud.insert(0, str(DEFAULT_BAUD))
        self.e_baud.grid(row=3, column=0, sticky="w", pady=(2, 6))
        self._label(b, "8N1", fg=MUTED).grid(row=3, column=1, sticky="e")
        self.btn_connect = self._button(b, "Verbinden", self.toggle_connection, GREEN)
        self.btn_connect.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.set_conn_status("nicht verbunden", MUTED)

        # Startliste
        b = self._section(side, "Startliste")
        b.columnconfigure(0, weight=1)
        b.columnconfigure(1, weight=1)
        self.lbl_startlist = self._label(b, "Keine Startliste geladen", fg=MUTED, wraplength=wrap, justify="left")
        self.lbl_startlist.grid(row=0, column=0, columnspan=2, sticky="w")
        self.var_mode = tk.StringVar(value=self.settings["wettkampf"])
        self.mode_seg = Segmented(b, (("einzel", "Einzelwettfahren"), ("paar", "Paarwettfahren")), self.var_mode,
                                  command=self.on_mode_change, font=self.f_side_bold, scale=self.ui_scale)
        self.mode_seg.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._button(b, "Excel / CSV laden", self.import_startlist, BLUE).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._label(b, "Startnummer").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.e_part_nr = self._entry(b, width=8)
        self.e_part_nr.grid(row=3, column=1, sticky="ew", pady=(6, 0))
        self.e_part_nr.bind("<Return>", lambda e: self.edit_participant_from_entry())
        self._button(b, "Teilnehmer bearbeiten", self.edit_participant_from_entry).grid(
            row=4, column=0, sticky="ew", pady=(6, 0), padx=(0, 3))
        self._button(b, "Notiz hinzufügen", self.open_note_search).grid(
            row=4, column=1, sticky="ew", pady=(6, 0), padx=(3, 0))
        self._button(b, "Startliste entfernen", self.clear_startlist, DARK_RED).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # Manuelle Zeiterfassung
        b = self._section(side, "Manuelle Zeiterfassung")
        b.columnconfigure(1, weight=1)
        self._label(b, "Startnummer").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.e_manual_nr = self._entry(b, width=8)
        self.e_manual_nr.grid(row=0, column=1, sticky="ew")
        self.e_manual_nr.bind("<Return>", lambda e: self.open_manual_dialog())
        self._button(b, "Zeit manuell erfassen", self.open_manual_dialog, BLUE).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # Speaker-Anzeige
        b, self.lbl_speaker_head = self._section(side, "Speaker-Anzeige", "speaker", status=True)
        b.columnconfigure(0, weight=1)
        self.show_buttons = {}
        for i, (key, label) in enumerate(SHOW_LABELS):
            if i:
                tk.Frame(b, bg=BORDER, height=1).grid(row=2 * i - 1, column=0, columnspan=2, sticky="ew")
            lbl = tk.Label(b, text=label, bg=PANEL, fg=TEXT, font=self.f_side, anchor="w", cursor="hand2")
            lbl.grid(row=2 * i, column=0, sticky="w", pady=int(5 * self.ui_scale))
            sw = Switch(b, command=lambda k=key: self.toggle_show(k), scale=self.ui_scale)
            sw.grid(row=2 * i, column=1, sticky="e", pady=int(5 * self.ui_scale))
            lbl.bind("<Button-1>", lambda e, k=key: self.toggle_show(k))
            self.show_buttons[key] = sw
        self.update_show_buttons()

        # Kategorien
        b = self._section(side, "Kategorien & Nummern-Range", "kategorien")
        for c in range(3):
            b.columnconfigure(c, weight=1)
        self.lst_cat = tk.Listbox(b, height=7, bg=BG, fg=TEXT, selectbackground=BLUE,
                                  selectforeground=WHITE, relief="flat", font=self.f_side,
                                  highlightthickness=1, highlightbackground=BORDER,
                                  exportselection=False, activestyle="none")
        self.lst_cat.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.lst_cat.bind("<<ListboxSelect>>", self.on_category_select)
        mv = tk.Frame(b, bg=PANEL)
        mv.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        mv.columnconfigure(0, weight=1)
        mv.columnconfigure(1, weight=1)
        self._button(mv, "▲ nach oben", lambda: self.move_selected_category(-1)).grid(
            row=0, column=0, sticky="ew", padx=(0, 3))
        self._button(mv, "▼ nach unten", lambda: self.move_selected_category(1)).grid(
            row=0, column=1, sticky="ew", padx=(3, 0))
        self._label(b, "Name").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self._label(b, "Von").grid(row=2, column=1, sticky="w", pady=(6, 0))
        self._label(b, "Bis").grid(row=2, column=2, sticky="w", pady=(6, 0))
        self.e_cat_name = self._entry(b, width=12)
        self.e_cat_name.grid(row=3, column=0, sticky="ew", padx=(0, 4))
        self.e_cat_min = self._entry(b, width=5)
        self.e_cat_min.grid(row=3, column=1, sticky="ew", padx=(0, 4))
        self.e_cat_max = self._entry(b, width=5)
        self.e_cat_max.grid(row=3, column=2, sticky="ew")
        self._label(b, "Rekord / Referenzzeit (optional, z.B. 1:18.20)", wraplength=wrap, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.e_cat_rekord = self._entry(b, width=12)
        self.e_cat_rekord.grid(row=5, column=0, columnspan=3, sticky="ew")
        self._button(b, "Übernehmen", self.category_update).grid(row=6, column=0, sticky="ew", pady=(6, 0), padx=(0, 4))
        self._button(b, "Hinzufügen", self.category_add).grid(row=6, column=1, sticky="ew", pady=(6, 0), padx=(0, 4))
        self._button(b, "Löschen", self.category_delete, DARK_RED).grid(row=6, column=2, sticky="ew", pady=(6, 0))
        self._label(b, "Karten lassen sich auch direkt an der Titelzeile verschieben.", fg=MUTED,
                    wraplength=wrap, justify="left").grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.refresh_category_list()

        # Onlinetool
        b = self._section(side, "Onlinetool", "online")
        b.columnconfigure(0, weight=1)
        self.lbl_online = self._label(b, "", fg=MUTED, wraplength=wrap, justify="left")
        self.lbl_online.grid(row=0, column=0, sticky="w")
        self.lbl_upload = self._label(b, "", fg=MUTED)
        self.lbl_upload.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self._button(b, "Einstellungen Onlinetool", self.open_online_settings).grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._button(b, "Upload-Warteschlange", self.open_upload_window, BLUE).grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self._button(b, "Startliste vom Onlinetool laden",
                     lambda: self.request_startlist_update("manuell", manual=True)).grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.update_online_labels()

        # Browser-Anzeige (Punkte 10 und 12)
        b = self._section(side, "Browser-Anzeige (lokales Netz)", "web")
        b.columnconfigure(0, weight=1)
        self._label(b, "Netzwerkadresse dieses PCs").grid(row=0, column=0, columnspan=2, sticky="w")
        self.cmb_bind = self._combo(b, width=16, state="readonly")
        self.cmb_bind.grid(row=1, column=0, sticky="ew", pady=(2, 4))
        self._button(b, "⟳", self.refresh_bind_ips).grid(row=1, column=1, sticky="e", padx=(6, 0), pady=(2, 4))
        self._label(b, "Port").grid(row=2, column=0, sticky="w")
        self.e_port = self._entry(b, width=6)
        self.e_port.insert(0, str(self.settings["web"]["port"]))
        self.e_port.grid(row=2, column=1, sticky="e")
        self.btn_web = self._button(b, "Browser-Anzeige starten", self.toggle_web, GREEN)
        self.btn_web.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.lbl_web_url = self._label(b, "Aus", fg=MUTED, wraplength=wrap, justify="left")
        self.lbl_web_url.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        btns = tk.Frame(b, bg=PANEL)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        btns.columnconfigure(0, weight=1, uniform="wb")
        btns.columnconfigure(1, weight=1, uniform="wb")
        self._button(btns, "Link kopieren", self.copy_web_url).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self._button(btns, "QR-Code", self.show_web_qr).grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self._button(btns, "Neuer Schlüssel", self.new_web_key).grid(row=1, column=0, columnspan=2, sticky="ew",
                                                                      pady=(6, 0))
        self._label(b, "Nur lesend, nur private Netzwerke, Zugriff nur mit Schlüssel im Link.",
                    fg=MUTED, wraplength=wrap, justify="left").grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.refresh_bind_ips()

        # Daten
        b, self.lbl_data_head = self._section(side, "Daten", "daten", status=True)
        b.columnconfigure(0, weight=1)
        self._button(b, "Resultate als CSV exportieren", self.export_csv, GREEN).grid(row=0, column=0, sticky="ew")
        self._button(b, "Export pro Verein (USB-Stick)", self.open_club_export, GREEN).grid(
            row=1, column=0, sticky="ew", pady=(6, 0))
        self._button(b, "Resultate zurücksetzen", self.reset_results, DARK_RED).grid(
            row=2, column=0, sticky="ew", pady=(6, 0))
        self.lbl_count = self._label(b, "0 Resultate erfasst", fg=MUTED)
        self.lbl_count.grid(row=3, column=0, sticky="w", pady=(4, 0))

        # Log
        logbox = RoundedPanel(side, fill=PANEL, radius=int(12 * self.ui_scale), fit_height=True)
        logbox.pack(fill="x", padx=10, pady=10)
        frm = logbox.inner
        tk.Label(frm, text="Empfangene Daten", bg=PANEL, fg=TEXT, font=self.f_side_head,
                 anchor="w").pack(fill="x", padx=12, pady=(10, 6))
        self.var_logtab = tk.StringVar(value="focus")
        self.log_seg = Segmented(frm, (("focus", "Fokussiert"), ("all", "Alle")), self.var_logtab,
                                 command=lambda: self.show_log_tab(self.var_logtab.get()), font=self.f_side_bold,
                                 scale=self.ui_scale)
        self.log_seg.pack(fill="x", padx=12, pady=(0, 6))
        holder = tk.Frame(frm, bg=PANEL)
        holder.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.log_tabs = {}
        for key, label in (("focus", "Fokussiert"), ("all", "Alle")):
            btn = None
            txt = tk.Text(holder, height=10, width=1, bg=BG, fg=MUTED, font=self.f_log, relief="flat",
                          state="disabled", wrap="word" if key == "focus" else "none",
                          highlightthickness=0)
            txt.grid(row=0, column=0, sticky="nsew")
            txt.tag_configure("ziel", foreground=GREEN_TEXT)
            txt.tag_configure("warn", foreground=GOLD)
            txt.tag_configure("error", foreground=RED)
            txt.tag_configure("ok", foreground=ACCENT)
            txt.tag_configure("test", foreground="#64748b")
            self.log_tabs[key] = (btn, txt)
        self.show_log_tab("focus")

    def show_log_tab(self, key):
        self.var_logtab.set(key)
        self.log_seg.redraw()
        txt = self.log_tabs[key][1]
        txt.tkraise()
        txt.see("end")

    def set_conn_status(self, text, color):
        self._set(self.lbl_conn_head, text=text, fg=color)

    # ---------------- Wettkampf (Punkt 13) ---------------- #
    def schedule_event_save(self):
        if self._event_job is not None:
            self.root.after_cancel(self._event_job)
        self._event_job = self.root.after(600, self.save_event_fields)

    def save_event_fields(self, normalize=False):
        self._event_job = None
        ev = self.settings["event"]
        name = self.e_event_name.get().strip()
        von_txt, bis_txt = self.e_event_from.get().strip(), self.e_event_to.get().strip()
        von, bis = parse_date(von_txt), parse_date(bis_txt)
        ok_von = not von_txt or von is not None
        ok_bis = not bis_txt or (bis is not None and (von is None or bis >= von))
        self.e_event_from.configure(highlightbackground=BORDER if ok_von else RED,
                                    highlightcolor=BLUE if ok_von else RED)
        self.e_event_to.configure(highlightbackground=BORDER if ok_bis else RED,
                                  highlightcolor=BLUE if ok_bis else RED)
        if not ok_von or not ok_bis:
            hint = "Datum ungültig (TT.MM.JJJJ)" if not (ok_von and (not bis_txt or bis is not None)) \
                else "«bis» liegt vor «von»"
            self._set(self.lbl_event_hint, text=hint, fg=RED)
        else:
            self._set(self.lbl_event_hint, text="Datum als TT.MM.JJJJ, «bis» leer lassen bei einem Tag", fg=MUTED)
        new = {"name": name,
               "von": von.strftime("%d.%m.%Y") if von else ("" if not von_txt else ev["von"]),
               "bis": bis.strftime("%d.%m.%Y") if (bis and ok_bis) else ("" if not bis_txt else ev["bis"])}
        if new != ev:
            ev.update(new)
            self.save_settings()
        if normalize:
            for entry, date in ((self.e_event_from, von), (self.e_event_to, bis if ok_bis else None)):
                if date is not None and entry.get().strip() != date.strftime("%d.%m.%Y"):
                    entry.delete(0, "end")
                    entry.insert(0, date.strftime("%d.%m.%Y"))
        self.update_window_title()

    def event_dates(self):
        ev = self.settings["event"]
        von, bis = parse_date(ev["von"]), parse_date(ev["bis"])
        if von is None:
            return None, None
        if bis is not None and bis <= von:
            bis = None
        return von, bis

    def event_label(self):
        ev = self.settings["event"]
        von, bis = self.event_dates()
        dates = ""
        if von:
            dates = von.strftime("%d.%m.%Y") + (f" bis {bis.strftime('%d.%m.%Y')}" if bis else "")
        return "  ".join(x for x in (ev["name"].strip(), dates) if x)

    def event_prefix(self):
        """Dateinamen-Praefix: 2027-06-12[_bis_2027-06-13]_Wettkampfname."""
        von, bis = self.event_dates()
        if von is None:
            von, bis = datetime.date.today(), None
        dates = von.isoformat() + (f"_bis_{bis.isoformat()}" if bis else "")
        return f"{dates}_{file_part(self.settings['event']['name'].strip() or 'SWV')}"

    def update_window_title(self):
        label = self.event_label()
        self.root.title(f"{APP_TITLE}  |  {label}" if label else APP_TITLE)
        if hasattr(self, "lbl_event_head"):
            avail = self.wrap_w - self.f_side_head.measure("⌄  Wettkampf") - int(14 * self.ui_scale)
            if label:
                von, bis = self.event_dates()
                dates = short_date_range(von, bis)
                name = self.settings["event"]["name"].strip()
                tail = f"  {dates}" if dates and name else dates
                name_w = avail - self.f_side_bold.measure(tail)
                text = (fit_text(self.f_side_bold, name, name_w) if name and name_w > 30 else "") + tail
                self._set(self.lbl_event_head, text=text.strip(), fg=TEXT)
            else:
                self._set(self.lbl_event_head, text="nicht erfasst", fg=GOLD)

    # ---------------- Speaker-Anzeige ein/aus ---------------- #
    def update_show_buttons(self):
        for key, sw in self.show_buttons.items():
            sw.set(self.settings["show"].get(key, False))
        on = sum(1 for key, _l in SHOW_LABELS if self.settings["show"].get(key))
        self._set(self.lbl_speaker_head, text=f"{on} von {len(SHOW_LABELS)} ein", fg=MUTED)

    def toggle_show(self, key):
        self.settings["show"][key] = not self.settings["show"].get(key, False)
        self.update_show_buttons()
        self.save_settings()
        self.apply_show_settings()

    def any_panel(self):
        show = self.settings["show"]
        return any(show.get(k) for k in ("naechste", "ticker", "statistik")) or self._note_visible

    def note_segments(self):
        """Notiz der Nummer auf der Strecke, leer wenn nichts erfasst ist."""
        nr = self.current_nr
        if nr is None or not self.settings["show"].get("notizen") or self.is_test(nr):
            return []
        p = self.participants.get(nr) or {}
        notiz, bem = p.get("notiz", "").strip(), p.get("bemerkung", "").strip()
        if not notiz and not bem:
            return []
        name = display_name(p, self.settings["wettkampf"])
        seg = [(f"Nr {nr}" + (f"  {name}" if name else "") + "\n", "nr")]
        if notiz:
            seg.append((notiz + ("\n" if bem else ""), None))
        if bem:
            seg.append((f"Bemerkung (Startliste): {bem}", "sub"))
        return seg

    def update_note_panel(self):
        seg = self.note_segments()
        visible = bool(seg)
        if visible:
            self._set_text(self.txt_note, seg)
            lines = sum(t.count("\n") for t, _tag in seg) + 1
            self.txt_note.configure(height=max(2, lines + 1))
        if visible == self._note_visible:
            return
        self._note_visible = visible
        if not visible:
            self.panel_note.pack_forget()
        else:
            ticker_packed = self.panel_ticker.winfo_manager() == "pack"
            if self.panel_orient == "right":
                opts = {"side": "top", "fill": "x", "pady": (0, 6)}
            else:
                opts = {"side": "left", "fill": "both", "expand": True, "padx": (0, 6)}
            if ticker_packed:
                opts["before"] = self.panel_ticker
            self.panel_note.pack(**opts)
        self.place_right_panel()

    def apply_show_settings(self):
        show = self.settings["show"]
        for frame in (self.panel_next, self.panel_note, self.panel_ticker, self.panel_stats):
            frame.pack_forget()
        self._note_visible = False
        self.txt_stats.configure(height=len(self.categories) + 3)
        if self.panel_orient == "right":
            layout = ((self.panel_next, "naechste", "top", False), (self.panel_stats, "statistik", "bottom", False),
                      (self.panel_ticker, "ticker", "top", True))
            for frame, key, side, expand in layout:
                if show.get(key):
                    frame.pack(side=side, fill="both" if expand else "x", expand=expand,
                               pady=(6, 0) if side == "bottom" else (0, 6))
        else:
            for frame, key in ((self.panel_next, "naechste"), (self.panel_ticker, "ticker"),
                               (self.panel_stats, "statistik")):
                if show.get(key):
                    frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.place_right_panel()
        for card in self.cards:
            for row in card["rows"]:
                if show.get("namen"):
                    row["sub"].grid()
                else:
                    row["sub"].grid_remove()
        self.update_live_info()
        self.update_ziel_info()
        self.update_panels()
        self.schedule_font_scale()

    def place_right_panel(self):
        if not self.any_panel():
            self.right_panel.grid_remove()
            return
        if self.panel_orient == "right":
            self.right_panel.grid(row=0, column=2, rowspan=1, columnspan=1, sticky="ns", padx=(6, 6), pady=6)
        else:
            self.right_panel.grid(row=1, column=0, rowspan=1, columnspan=3, sticky="ew", padx=6, pady=(6, 6))

    # ================================================================== #
    # Kategorie-Karten (Punkte 7 und 14)
    # ================================================================== #
    def build_cards(self):
        for card in self.cards:
            card["box"].destroy()
        self.cards = []
        for cat in self.categories:
            box = RoundedPanel(self.cards_area, fill=PANEL, radius=int(18 * self.ui_scale), pad=3)
            box.configure(width=1, height=1)
            f = box.inner
            for c, w in ((0, 0), (1, 0), (2, 0), (3, 1)):
                f.columnconfigure(c, weight=w)
            title = tk.Label(f, text="", font=self.f_title, bg=PANEL, fg=MUTED, anchor="w", cursor="fleur")
            title.grid(row=0, column=0, columnspan=4, sticky="ew", padx=14, pady=(8, 2))
            rows_w = []
            for k in range(TOP_N):
                font = self.f_first if k == 0 else self.f_row
                r_main, r_sub = 1 + 2 * k, 2 + 2 * k
                l_txt = tk.Label(f, text="", font=font, bg=PANEL, fg=WHITE, anchor="w")
                l_arr = tk.Label(f, text="", font=font, bg=PANEL, fg=WHITE)
                l_time = tk.Label(f, text="", font=font, bg=PANEL, fg=WHITE, anchor="w")
                l_pen = tk.Label(f, text="", font=self.f_pen, bg=PANEL, fg=ORANGE, anchor="w")
                l_sub = tk.Label(f, text="", font=self.f_sub, bg=PANEL, fg=MUTED, anchor="w")
                l_txt.grid(row=r_main, column=0, sticky="sw", padx=(14, 4))
                l_arr.grid(row=r_main, column=1, sticky="s", padx=6)
                l_time.grid(row=r_main, column=2, sticky="sw", padx=(4, 4))
                l_pen.grid(row=r_main, column=3, sticky="sw", padx=(0, 14), pady=(0, 4))
                l_sub.grid(row=r_sub, column=0, columnspan=4, sticky="nw", padx=(14, 14))
                f.rowconfigure(r_main, weight=1)
                f.rowconfigure(r_sub, weight=0)
                rows_w.append({"txt": l_txt, "arrow": l_arr, "time": l_time, "pen": l_pen, "sub": l_sub,
                               "nr": None, "rank": None, "color": WHITE, "sub_full": ""})
            card = {"cat": cat, "frame": f, "box": box, "title": title, "rows": rows_w}
            title.bind("<ButtonPress-1>", lambda e, c=card: self.drag_start(c))
            title.bind("<B1-Motion>", self.drag_motion)
            title.bind("<ButtonRelease-1>", self.drag_end)
            self.cards.append(card)

        self.layout_cards()
        self.prev_top = {}
        self.update_rankings(initial=True)
        if hasattr(self, "lbl_count"):
            self.apply_show_settings()
        self.schedule_font_scale()

    def layout_cards(self):
        nc = max(1, self.card_cols)
        rows = max(1, -(-len(self.cards) // nc))
        for r in range(40):
            self.cards_area.rowconfigure(r, weight=1 if r < rows else 0, uniform="row" if r < rows else "")
        for c in range(3):
            self.cards_area.columnconfigure(c, weight=1 if c < nc else 0, uniform="col" if c < nc else "")
        for i, card in enumerate(self.cards):
            card["box"].grid(row=i // nc, column=i % nc, sticky="nsew", padx=6, pady=6)

    def card_title(self, cat):
        title = f"{cat['name']}   {cat['min']}-{cat['max']}"
        if cat.get("rekord"):
            title += f"   Rekord {cat['rekord']}s"
        return title

    # ---------------- Karten verschieben (Punkt 7) ---------------- #
    def card_from_widget(self, widget):
        frames = {str(c["frame"]): c for c in self.cards}
        frames.update({str(c["box"]): c for c in self.cards})
        while widget is not None:
            card = frames.get(str(widget))
            if card:
                return card
            widget = widget.master
        return None

    def drag_start(self, card):
        self._drag = {"card": card, "target": None}
        card["box"].set_outline(ACCENT, 3)

    def drag_motion(self, event):
        if not self._drag:
            return
        target = self.card_from_widget(self.root.winfo_containing(event.x_root, event.y_root))
        if target is self._drag["card"]:
            target = None
        if target is not self._drag["target"]:
            if self._drag["target"] is not None:
                self._drag["target"]["box"].set_outline("", 0)
            if target is not None:
                target["box"].set_outline(GOLD, 3)
            self._drag["target"] = target

    def drag_end(self, _event=None):
        if not self._drag:
            return
        source, target = self._drag["card"], self._drag["target"]
        self._drag = None
        source["box"].set_outline("", 0)
        if target is not None:
            target["box"].set_outline("", 0)
            self.move_category(self.cards.index(source), self.cards.index(target))

    def move_selected_category(self, delta):
        sel = self.lst_cat.curselection()
        if not sel:
            messagebox.showinfo("Kategorie", "Zuerst eine Kategorie in der Liste anklicken.")
            return
        i = sel[0]
        j = i + delta
        if 0 <= j < len(self.categories):
            self.move_category(i, j)

    def move_category(self, i, j):
        """Kategorie i an Position j verschieben, Karten nur neu anordnen (kein Neuaufbau)."""
        if i == j:
            return
        self.categories.insert(j, self.categories.pop(i))
        if len(self.cards) == len(self.categories):
            self.cards.insert(j, self.cards.pop(i))
            self.layout_cards()
        else:
            self.build_cards()
        self.rebuild_cat_lookup()
        self.save_categories()
        self.refresh_category_list()
        self.lst_cat.selection_clear(0, "end")
        self.lst_cat.selection_set(j)
        self.lst_cat.see(j)
        self.log("Reihenfolge der Kategorien: " + ", ".join(c["name"] for c in self.categories))
        self.update_panels()

    # ---------------- Layout und Schriftgroessen (Punkt 14) ---------------- #
    def schedule_font_scale(self):
        if self._scale_job is not None:
            self.root.after_cancel(self._scale_job)
        self._scale_job = self.root.after(80, self.apply_font_scale)

    def row_template(self):
        """Laengste tatsaechlich vorkommende Zeile: Nummernlaenge, Zeitformat, Strafpunkte."""
        real = self.real_results()
        nrs = [n for n in self.start_order] + real
        digits = max([3] + [len(str(n)) for n in nrs])
        times = [self.disp_time(n) for n in real]
        longest = max(times + ["1:23.45"], key=len)
        time_txt = re.sub(r"\d", "8", longest) + "s"
        pen = max([self.penalty(n) for n in real] + [0])
        return (f"5. Nr. {'8' * digits}", time_txt, f"+{'8' * len(str(pen))}" if pen else "")

    def row_width(self, px):
        """Benoetigte Kartenbreite fuer die laengste vorkommende Zeile bei Schriftgroesse px."""
        rank_txt, time_txt, pen_txt = self._row_tpl
        self._mf_bold.configure(size=-max(1, int(px * 1.25)))
        self._mf_pen.configure(size=-max(10, int(px * 0.6)))
        return (self._mf_bold.measure(rank_txt) + self._mf_bold.measure("➔") + self._mf_bold.measure(time_txt) +
                (self._mf_pen.measure(pen_txt) if pen_txt else 0) + 64)

    def card_sizes(self, px):
        """Schriftgroessen der Karte aus der Grundgroesse px (identisch zu apply_font_scale)."""
        s = self.ui_scale
        return {"row": px, "first": int(px * 1.25), "title": max(int(11 * s), int(px * 0.72)),
                "sub": max(int(10 * s), int(px * 0.58)), "pen": max(10, int(px * 0.6))}

    def card_height(self, px):
        """Benoetigte Kartenhoehe bei Schriftgroesse px, gemessen mit echten Zeilenhoehen."""
        sz = self.card_sizes(px)
        self._mf_title.configure(size=-sz["title"])
        self._mf_bold.configure(size=-sz["first"])
        self._mf_row.configure(size=-sz["row"])
        self._mf_sub.configure(size=-sz["sub"])
        lines = (self._mf_title.metrics("linespace") + 10 + self._mf_bold.metrics("linespace")
                 + 4 * self._mf_row.metrics("linespace"))
        if self.settings["show"].get("namen"):
            lines += 5 * self._mf_sub.metrics("linespace")
        return lines + 16  # Rahmen und Abstaende

    def fit_px_h(self, card_h):
        lo, hi = 6, int(110 * self.ui_scale)
        if self.card_height(lo) > card_h:
            return lo
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.card_height(mid) <= card_h:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def fit_px(self, card_w):
        lo, hi = 6, int(110 * self.ui_scale)
        if self.row_width(lo) > card_w:
            return lo
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.row_width(mid) <= card_w:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def apply_font_scale(self):
        self._scale_job = None
        mw, mh = self.main.winfo_width(), self.main.winfo_height()
        if mw < 50 or mh < 50:
            return
        s = self.ui_scale

        # Status-Balken und Seitenpanels
        sp = max(int(14 * s), min(int(52 * s), int(min(mw / 48, mh / 22))))
        self.f_status.configure(size=-sp)
        self.f_status_name.configure(size=-max(int(12 * s), int(sp * 0.62)))
        self.f_status_sub.configure(size=-max(int(11 * s), int(sp * 0.55)))
        pp = max(int(12 * s), min(int(17 * s), int(mh / 62)))
        self.f_panel.configure(size=-pp)
        self.f_panel_bold.configure(size=-pp)
        self.f_panel_head.configure(size=-pp)
        tp = int(pp * 1.33)
        self.f_ticker.configure(size=-tp)
        self.f_ticker_bold.configure(size=-tp)
        self.f_ticker_time.configure(size=-max(int(10 * s), int(tp * 0.78)))

        # Seitenpanels rechts nur, wenn daneben zwei Kartenspalten gut lesbar Platz haben
        self._row_tpl = self.row_template()
        panel_w = int(max(260 * s, min(420 * s, mw * 0.22)))
        orient = "right"
        if self.any_panel() and (mw - panel_w - 12) / 2 - 12 < self.row_width(int(16 * s)):
            orient = "below"
        changed = orient != self.panel_orient
        self.panel_orient = orient
        if orient == "right":
            if int(self.right_panel.cget("width")) != panel_w:
                self.right_panel.configure(width=panel_w)
        else:
            panel_h = int(max(200 * s, min(320 * s, mh * 0.3)))
            if int(self.right_panel.cget("height")) != panel_h:
                self.right_panel.configure(height=panel_h)
        if changed:
            self.apply_show_settings()
            return

        # Kartenraster: Spaltenzahl und Schrift nach gemessener Textbreite
        w, h = self.cards_canvas.winfo_width(), self.cards_canvas.winfo_height()
        if w < 50 or h < 50:
            return
        n = max(1, len(self.cards))
        self._row_tpl = self.row_template()
        cols = [c for c in (3, 2, 1) if c <= n] or [1]
        best = None
        for nc in cols:
            rows = -(-n // nc)
            px_w = self.fit_px(w / nc - 12)
            px_h = self.fit_px_h(h / rows - 12)
            px = min(px_w, px_h, int(110 * s))
            if best is None or px > best[0]:
                best = (px, nc, rows)
        px, nc, rows = best
        min_px = int(13 * s)
        inner_h = h
        if px < min_px:
            # Zu wenig Platz: Schrift lesbar halten und den Kartenbereich scrollen statt unlesbar klein.
            # Mehr Spalten bevorzugt, solange die Schrift dort mindestens 'target' erreicht.
            target = int(16 * s)
            widths = {c: min(self.fit_px(w / c - 12), int(110 * s)) for c in cols}
            good = [c for c in cols if widths[c] >= target]
            nc = max(good) if good else max(cols, key=lambda c: (widths[c], c))
            rows = -(-n // nc)
            px = min(widths[nc], target)
            inner_h = max(h, int(rows * (self.card_height(px) + 12)))
        scrolling = inner_h > h + 1
        if nc != self.card_cols:
            self.card_cols = nc
            self.layout_cards()
        self.cards_scrolling = scrolling
        self.cards_canvas.itemconfigure(self.cards_win, width=w, height=inner_h)
        self.cards_canvas.configure(scrollregion=(0, 0, w, inner_h))
        if scrolling:
            self.cards_sb.grid(row=0, column=1, sticky="ns")
        else:
            self.cards_sb.grid_remove()
            self.cards_canvas.yview_moveto(0)

        sz = self.card_sizes(max(6, px))
        self.f_row.configure(size=-sz["row"])
        self.f_first.configure(size=-sz["first"])
        self.f_title.configure(size=-sz["title"])
        self.f_sub.configure(size=-sz["sub"])
        self.f_pen.configure(size=-sz["pen"])
        col0 = self.f_first.measure("5. Nr. 8888")
        for card in self.cards:
            card["frame"].columnconfigure(0, minsize=col0)
        self.card_inner_w = int(w / nc - 12 - 28 - 4)
        self.root.after_idle(self.refit_texts)

    def refit_texts(self):
        """Titel, Namen und Status-Zeilen an die aktuelle Breite anpassen ('…' statt Abschneiden)."""
        for card in self.cards:
            self._set_fit(card["title"], self.card_title(card["cat"]), self.f_title, self.card_inner_w)
            for row in card["rows"]:
                self._set(row["sub"], text=fit_text(self.f_sub, row["sub_full"], self.card_inner_w))
        for label in self.live_labels + self.ziel_labels:
            self._set_fit(label, self._full_text.get(str(label), label.cget("text")))

    # ================================================================== #
    # Kategorien / Ranking
    # ================================================================== #
    def rebuild_cat_lookup(self):
        self._cat_lookup = {c["name"].casefold(): c for c in self.categories}
        self._rank_cache = None

    def range_category(self, nr):
        for cat in self.categories:
            if cat["min"] <= nr <= cat["max"]:
                return cat
        return None

    def category_of(self, nr):
        p = self.participants.get(nr)
        if p and p.get("kategorie"):
            cat = self._cat_lookup.get(p["kategorie"].strip().casefold())
            if cat:
                return cat
        return self.range_category(nr)

    def is_test(self, nr):
        """Testnummer: in keinem Kategorienbereich und nicht (mit Kategorie) in der Startliste."""
        if nr is None:
            return False
        p = self.participants.get(nr)
        if p and not p.get("unknown"):
            return False
        if p and p.get("kategorie") and self._cat_lookup.get(p["kategorie"].strip().casefold()):
            return False
        return self.range_category(nr) is None

    def real_results(self):
        return [nr for nr in self.results if not self.is_test(nr)]

    def penalty(self, nr):
        p = self.participants.get(nr)
        try:
            return max(0, int(p.get("strafpunkte", 0))) if p else 0
        except (TypeError, ValueError):
            return 0

    def total_secs(self, nr):
        return self.results[nr]["secs"] + self.penalty(nr)

    def disp_time(self, nr):
        """Anzeigezeit fuer Ranking: gefahrene Zeit oder Total inkl. Strafpunkte."""
        if self.penalty(nr):
            return fmt_secs(self.total_secs(nr))
        return self.results[nr]["str"]

    def rankings(self):
        if self._rank_cache is None:
            groups = {c["name"]: [] for c in self.categories}
            for nr in self.results:
                cat = self.category_of(nr)
                if cat:
                    groups[cat["name"]].append((round(self.total_secs(nr), 3), nr))
            out = {}
            for name, entries in groups.items():
                entries.sort()
                ranked, prev, rank = [], None, 0
                for i, (t, nr) in enumerate(entries):
                    if t != prev:
                        rank, prev = i + 1, t
                    ranked.append((rank, nr, t))
                out[name] = ranked
            self._rank_cache = out
        return self._rank_cache

    def ranking(self, cat):
        return self.rankings().get(cat["name"], [])

    def rank_of(self, nr):
        cat = self.category_of(nr)
        if not cat or nr not in self.results:
            return None, None, cat
        ranked = self.ranking(cat)
        for rank, n, _t in ranked:
            if n == nr:
                return rank, len(ranked), cat
        return None, len(ranked), cat

    def _arrow_color(self, row, now):
        until = self.blink.get(row["nr"])
        if until and now < until:
            return RED if self.blink_phase else row["color"]
        return row["color"]

    def who_text(self, nr):
        p = self.participants.get(nr)
        if not p:
            return ""
        name = display_name(p, self.settings["wettkampf"])
        parts = [x for x in (name, p.get("verein", "")) if x]
        if not parts and p.get("unknown"):
            return "nicht in Startliste"
        return ", ".join(parts)

    def update_rankings(self, initial=False):
        now = time.time()
        for card in self.cards:
            cat = card["cat"]
            ranked = self.ranking(cat)[:TOP_N]
            top = {nr for _, nr, _ in ranked}
            prev = self.prev_top.get(cat["name"])
            if not initial and prev is not None:
                for nr in top - prev:
                    self.blink[nr] = now + BLINK_SECONDS
            self.prev_top[cat["name"]] = top

            for k, row in enumerate(card["rows"]):
                pen_txt, sub_txt = "", ""
                if k < len(ranked):
                    rank, nr, _ = ranked[k]
                    color = GOLD if rank == 1 else WHITE
                    font = self.f_first if rank == 1 else self.f_row
                    txt, arrow, tstr = f"{rank}. Nr. {nr}", "➔", f"{self.disp_time(nr)}s"
                    pen = self.penalty(nr)
                    pen_txt = f"+{pen}" if pen else ""
                    sub_txt = self.who_text(nr)
                else:
                    rank = nr = None
                    color, font = WHITE, self.f_row
                    txt = arrow = tstr = ""
                    if k == 0 and not ranked:
                        color, txt = MUTED, "Noch keine Zeiten"
                row["nr"], row["rank"], row["color"] = nr, rank, color
                self._set(row["txt"], text=txt, fg=color, font=font)
                self._set(row["time"], text=tstr, fg=color, font=font)
                self._set(row["arrow"], text=arrow, fg=self._arrow_color(row, now), font=font)
                self._set(row["pen"], text=pen_txt)
                row["sub_full"] = sub_txt
                self._set(row["sub"], text=fit_text(self.f_sub, sub_txt, self.card_inner_w))

        if hasattr(self, "_row_tpl") and self.row_template() != self._row_tpl:
            self.schedule_font_scale()
        n = len(self.real_results())
        tests = len(self.results) - n
        self._set(self.lbl_count, text=f"{n} Resultat{'e' if n != 1 else ''} erfasst"
                                       + (f" (+{tests} Test)" if tests else ""))
        self._set(self.lbl_data_head, text=f"{n} Resultat{'e' if n != 1 else ''}"
                                           + (f" (+{tests} Test)" if tests else ""), fg=MUTED)

    def blink_tick(self):
        self.blink_phase = not self.blink_phase
        now = time.time()
        for nr in [n for n, until in self.blink.items() if until <= now]:
            del self.blink[nr]
        for card in self.cards:
            for row in card["rows"]:
                if row["nr"] is not None:
                    self._set(row["arrow"], fg=self._arrow_color(row, now))
        self.root.after(BLINK_INTERVAL_MS, self.blink_tick)

    def on_data_changed(self, save=True):
        self._rank_cache = None
        self.update_rankings()
        self.update_live_info()
        self.update_ziel_info()
        self.update_panels()
        self.update_online_labels()
        self.refresh_upload_window()
        if save:
            self.save_autosave()

    # ================================================================== #
    # Zielzeiten
    # ================================================================== #
    def register_final(self, nr, secs, tstr, source="CP 545"):
        if self.is_test(nr):
            prev = self.results.get(nr)
            self.results[nr] = {"secs": secs, "str": tstr, "ts": time.time(), "source": source,
                                "run": (prev.get("run", 1) + 1) if prev else 1, "prev": None, "status": ST_OPEN}
            self.log(f"TEST Nr {nr} {tstr}s [{source}]", tag="test")
            self.add_ticker(f"Test: Nr {nr} im Ziel, {tstr}s", "test")
            self.on_data_changed()
            return
        cat = self.category_of(nr)
        before = list(self.ranking(cat)) if cat else []
        prev = self.results.get(nr)
        online = self.settings["online"]
        status = ST_APPROVED if (online["mode"] == "online" and online["send_mode"] == "auto") else ST_OPEN
        self.results[nr] = {
            "secs": secs, "str": tstr, "ts": time.time(), "source": source,
            "run": (prev.get("run", 1) + 1) if prev else 1,
            "prev": {"secs": prev["secs"], "str": prev["str"]} if prev else None,
            "status": status,
        }
        self._rank_cache = None
        self.ziel_nr = nr
        cat_name = cat["name"] if cat else "ohne Kategorie"
        self.log(f"ZIEL Nr {nr} ({cat_name}) {tstr}s [{source}]", tag="ziel")
        self.ticker_for_final(nr, cat, before, prev)
        self.on_data_changed()

    def ticker_for_final(self, nr, cat, before, prev):
        who = self.who_text(nr)
        who_txt = f" {who}" if who else ""
        disp = f"{self.disp_time(nr)}s"
        if not cat:
            self.add_ticker(f"Nr {nr}{who_txt} im Ziel: {disp} (ohne Kategorie)", "warn")
            return
        after = self.ranking(cat)
        rank, n, _ = self.rank_of(nr)
        total = round(self.total_secs(nr), 3)
        others_before = [(t, n2) for _r, n2, t in before if n2 != nr]
        rekord = parse_time(cat.get("rekord", "")) if cat.get("rekord") else None
        if rekord is not None and total < rekord:
            best_before = others_before[0][0] if others_before else None
            if best_before is None or best_before >= rekord:
                self.add_ticker(f"REKORD {cat['name']}: Nr {nr}{who_txt} {disp}, "
                                f"{rekord - total:.2f} s unter {cat['rekord']}s", "warn")
        if rank == 1:
            if others_before:
                lead_t, lead_nr = others_before[0]
                diff = lead_t - total
                if diff > 0:
                    self.add_ticker(f"Neue Bestzeit {cat['name']}: Nr {nr}{who_txt} {disp}, "
                                    f"{fmt_gap(diff)} vor Nr {lead_nr}", "ziel")
                elif diff == 0:
                    self.add_ticker(f"Bestzeit {cat['name']} egalisiert: Nr {nr}{who_txt} {disp}, "
                                    f"zeitgleich mit Nr {lead_nr}", "ziel")
            else:
                self.add_ticker(f"Erste Zeit {cat['name']}: Nr {nr}{who_txt} {disp}", None)
        elif rank is not None and rank <= TOP_N:
            old_top = {n2 for _r, n2, _t in before[:TOP_N]}
            new_rank = {n2: r2 for r2, n2, _t in after}
            pushed = sorted(n2 for n2 in old_top if n2 != nr and new_rank.get(n2, TOP_N + 1) > TOP_N)
            txt = f"Nr {nr}{who_txt} fährt mit {disp} auf Rang {rank} {cat['name']}"
            if pushed:
                txt += f", Nr {', '.join(map(str, pushed))} fällt aus den Top {TOP_N}"
            self.add_ticker(txt, None)
        if prev:
            delta = self.results[nr]["secs"] - prev["secs"]
            self.add_ticker(f"Wiederholungsfahrt Nr {nr}: {self.results[nr]['str']}s statt {prev['str']}s "
                            f"({delta:+.2f} s)", None)

    def add_ticker(self, text, tag):
        self.ticker.insert(0, (time.strftime("%H:%M"), text, tag))
        del self.ticker[TICKER_MAX:]
        self.update_panels()

    # ================================================================== #
    # Status-Balken
    # ================================================================== #
    def participant_line(self, nr):
        p = self.participants.get(nr)
        cat = self.category_of(nr)
        parts = []
        if p:
            name = display_name(p, self.settings["wettkampf"])
            if name:
                parts.append(name)
            if p.get("verein"):
                parts.append(p["verein"])
            if not name and p.get("unknown"):
                parts.append("nicht in Startliste")
        if cat:
            parts.append(cat["name"])
        return "  ·  ".join(parts)

    def update_live_info(self):
        if not hasattr(self, "live_labels"):
            return
        big, sub1, sub2 = self.live_labels
        nr = self.current_nr
        test = self.is_test(nr)
        self._set_fit(big, f"LAUFEND: Nr {nr if nr is not None else '-'} ➔ {self.live_time or '-'}"
                           + ("   TEST" if test else ""))
        if nr is None or test:
            self._set_fit(sub1, "Testfahrt, Nummer liegt in keinem Kategorienbereich" if test else "")
            self._set_fit(sub2, "", fg=WHITE)
            return
        self._set_fit(sub1, self.participant_line(nr))
        show = self.settings["show"]
        cat = self.category_of(nr)
        info, behind = [], False
        if self.live_final:
            info.append("Im Ziel")
        elif cat:
            others = [(t, n) for _r, n, t in self.ranking(cat) if n != nr]
            running = self.live_secs
            if show.get("vergleich"):
                if others:
                    lead_t, lead_nr = others[0]
                    if running is None:
                        info.append(f"Bestzeit {fmt_secs(lead_t)}s (Nr {lead_nr})")
                    elif lead_t - running > 0:
                        info.append(f"Bestzeit {fmt_secs(lead_t)}s (Nr {lead_nr}): noch {int(lead_t - running)} s")
                    else:
                        behind = True
                        info.append(f"Bestzeit {fmt_secs(lead_t)}s (Nr {lead_nr}) überschritten: "
                                    f"+{int(running - lead_t)} s")
                else:
                    info.append(f"Erste Zeit in {cat['name']}")
                rekord = parse_time(cat.get("rekord", "")) if cat.get("rekord") else None
                if rekord is not None and running is not None and rekord - running > 0:
                    info.append(f"Rekord {cat['rekord']}s: noch {int(rekord - running)} s")
            if show.get("prognose") and others and running is not None:
                possible = 1 + sum(1 for t, _n in others if t < running)
                info.append(f"Rang {possible} von {len(others) + 1} möglich")
        self._set_fit(sub2, "  ·  ".join(info), fg=LIGHT_YELLOW if behind else WHITE)

    def update_ziel_info(self):
        if not hasattr(self, "ziel_labels"):
            return
        big, sub1, sub2 = self.ziel_labels
        nr = self.ziel_nr
        if nr is None or nr not in self.results or self.is_test(nr):
            self._set_fit(big, "ZIEL: -")
            self._set_fit(sub1, "")
            self._set_fit(sub2, "")
            return
        res = self.results[nr]
        cat = self.category_of(nr)
        cat_name = cat["name"] if cat else "ohne Kategorie"
        pen = self.penalty(nr)
        pen_txt = f"  (+{pen} = {fmt_secs(self.total_secs(nr))}s)" if pen else ""
        self._set_fit(big, f"ZIEL: Nr {nr} ({cat_name}) ➔ {res['str']}s{pen_txt}")
        self._set_fit(sub1, self.participant_line(nr))
        info = []
        if self.settings["show"].get("einordnung") and cat:
            ranked = self.ranking(cat)
            rank, n, _ = self.rank_of(nr)
            total = round(self.total_secs(nr), 3)
            if rank == 1:
                others = [(t, n2) for _r, n2, t in ranked if n2 != nr]
                if not others:
                    info.append(f"Erste Zeit in {cat_name}")
                elif others[0][0] == total:
                    info.append(f"Rang 1 von {n}, zeitgleich mit Nr {others[0][1]}")
                else:
                    info.append(f"Rang 1 von {n}, {fmt_gap(others[0][0] - total)} vor Nr {others[0][1]}")
            elif rank is not None:
                lead_t, lead_nr = ranked[0][2], ranked[0][1]
                info.append(f"Rang {rank} von {n}, +{fmt_gap(total - lead_t)} auf Nr {lead_nr}")
            if res.get("prev"):
                info.append(f"Wiederholung: {res['secs'] - res['prev']['secs']:+.2f} s "
                            f"gegenüber {res['prev']['str']}s")
            rekord = parse_time(cat.get("rekord", "")) if cat.get("rekord") else None
            if rekord is not None and total < rekord:
                info.append(f"unter Rekord {cat['rekord']}s")
        self._set_fit(sub2, "  ·  ".join(info))

    # ================================================================== #
    # Seitenpanels (Als naechstes, Ticker, Statistik)
    # ================================================================== #
    def next_starters(self, count=NEXT_COUNT):
        if not self.start_order:
            return []
        idx = self.order_index.get(self.current_nr, -1)
        out = []
        for nr in self.start_order[idx + 1:]:
            if nr not in self.results:
                out.append(nr)
                if len(out) >= count:
                    break
        return out

    def update_panels(self):
        if not hasattr(self, "txt_next"):
            return
        self.update_note_panel()
        show = self.settings["show"]
        mode = self.settings["wettkampf"]
        if show.get("naechste"):
            seg = []
            if not self.start_order:
                seg.append(("Keine Startliste geladen", "sub"))
            else:
                nxt = self.next_starters()
                if not nxt:
                    seg.append(("Keine weiteren Starts in der Startliste", "sub"))
                for i, nr in enumerate(nxt):
                    p = self.participants.get(nr, {})
                    cat = self.category_of(nr)
                    seg.append((f"Nr {nr}  {display_name(p, mode) or '-'}\n", "nr"))
                    info = "  ·  ".join(x for x in (p.get("verein", ""), cat["name"] if cat else "") if x)
                    seg.append((f"{info}\n", "sub"))
                    notes = "  ·  ".join(x for x in (p.get("notiz", ""), p.get("bemerkung", "")) if x)
                    if notes and show.get("notizen"):
                        seg.append((f"{notes}\n", "note"))
            self._set_text(self.txt_next, seg)
        if show.get("ticker"):
            seg = []
            if not self.ticker:
                seg.append(("Noch keine Ereignisse", "sub"))
            for i, (t, text, tag) in enumerate(self.ticker):
                seg.append((f"{t}  ", ("time", "entry")))
                tags = tuple(x for x in (tag, "entry", "newest" if i == 0 else None) if x)
                seg.append((f"{text}\n", tags))
            self._set_text(self.txt_ticker, seg)
        if show.get("statistik"):
            self._set_text(self.txt_stats, self.stats_segments())

    def stats_segments(self):
        seg = []
        rankings = self.rankings()
        listed = {}
        for nr in self.start_order:
            cat = self.category_of(nr)
            if cat:
                listed[cat["name"]] = listed.get(cat["name"], 0) + 1
        for cat in self.categories:
            ranked = rankings.get(cat["name"], [])
            done = len(ranked)
            total = listed.get(cat["name"])
            count = f"{done}/{total}" if total else f"{done}"
            avg = f"  Ø {fmt_secs(sum(t for _r, _n, t in ranked) / done)}s" if done else ""
            seg.append((f"{cat['name']}  ", "bold"))
            seg.append((f"{count}{avg}\n", None))
        n_res = len(self.real_results())
        total_listed = len(self.start_order)
        seg.append((f"Gesamt  {n_res}/{total_listed} gefahren\n" if total_listed
                    else f"Gesamt  {n_res} gefahren\n", "bold"))
        best = None
        for nr in self.results:
            if self.category_of(nr) is None:
                continue
            t = self.total_secs(nr)
            if best is None or t < best[0]:
                best = (t, nr)
        if best:
            cat = self.category_of(best[1])
            seg.append((f"Tagesbestzeit  {fmt_secs(best[0])}s  Nr {best[1]}"
                        f"{' ' + cat['name'] if cat else ''}", "ziel"))
        return seg

    # ================================================================== #
    # Serielle Daten
    # ================================================================== #
    def poll_queue(self):
        try:
            while True:
                kind, payload, reader = self.q.get_nowait()
                if reader is not self.reader:
                    continue  # Nachzuegler einer frueheren Verbindung
                if kind == "line":
                    self.handle_line(payload)
                elif kind == "connected":
                    self.on_serial_connected(reader)
                elif kind == "lost":
                    self.on_serial_lost(reader, payload)
                elif kind == "open_error":
                    self.on_serial_open_error(reader, payload)
                elif kind == "disconnected":
                    self.reader = None
                    if not self.reconnecting:
                        self.set_connected(False, "nicht verbunden")
                        self.log(f"Verbindung zu {payload} getrennt", tag="warn")
        except queue.Empty:
            pass
        self.root.after(POLL_INTERVAL_MS, self.poll_queue)

    def handle_line(self, text):
        self.log("<STX>" + text.replace("\r", "<CR>"), focus=False)
        msg = parse_message(text)
        if msg is None:
            return
        if msg[0] == "nr":
            nr = msg[1]
            if nr <= 0:
                return
            # Der CP 545 wiederholt die Startnummer nach jeder Zeit: nur bei neuer Nummer reagieren
            if nr != self.current_nr:
                prev, self.current_nr = self.current_nr, nr
                self.live_time, self.live_secs, self.live_final = None, None, False
                self.on_new_starter(prev, nr)
            self.update_live_info()
        elif msg[0] in ("running", "final"):
            kind, tstr, secs = msg
            self.live_time, self.live_secs, self.live_final = tstr, secs, kind == "final"
            self.update_live_info()
            if kind == "final":
                if self.current_nr is None:
                    self.log("Zielzeit ohne aktive Startnummer verworfen", tag="warn")
                    return
                prev = self.results.get(self.current_nr)
                if prev and prev["str"] == tstr and time.time() - prev["ts"] < 10:
                    return
                self.register_final(self.current_nr, secs, tstr)

    def suggest_part_nr(self, nr):
        """Aktuelle Startnummer im Feld 'Startnummer' (Startliste) vorschlagen, Eingaben nie ueberschreiben."""
        entry = self.e_part_nr
        try:
            if self.root.focus_get() is entry:
                return
        except (KeyError, tk.TclError):  # Fokus in einem Combobox-Popup
            pass
        current = entry.get().strip()
        if current in ("", str(self._last_suggested)):
            entry.delete(0, "end")
            entry.insert(0, str(nr))
            self._last_suggested = nr

    def on_new_starter(self, prev_nr, nr):
        if self.is_test(nr):
            self.update_panels()
            return
        self.suggest_part_nr(nr)
        if self.start_order and nr not in self.participants:
            self.ensure_participant(nr, after=prev_nr, prompt=True)
        pn = self.participants.get(nr)
        club = (pn.get("vnr") or pn.get("verein") or "") if pn else ""
        if club:  # Boote ohne Verein (z.B. unbekannte Nummern) unterbrechen keinen Vereinsblock
            block = (pn.get("staver", ""), pn.get("fg", ""))
            club_change = club != self.last_club
            block_change = self.last_block is not None and block != self.last_block
            if club_change and pn.get("verein"):
                count = sum(1 for p in self.participants.values() if p.get("verein") == pn["verein"])
                prefix = "Am Start" if self.last_club is None else "Neuer Verein am Start"
                self.add_ticker(f"{prefix}: {pn['verein']} ({count} Starts)", "warn")
            if ((club_change and self.last_club is not None) or block_change) \
                    and self.settings["online"]["mode"] == "online" and self.settings["online"]["auto_startlist"]:
                self.request_startlist_update("Vereinswechsel" if club_change else "Startblock-Wechsel")
            self.last_club, self.last_block = club, block
        self.update_panels()

    def refresh_ports(self):
        self.port_map = {}
        values = []
        if serial is not None:
            for p in sorted(serial.tools.list_ports.comports(), key=lambda x: x.device):
                label = f"{p.device} - {p.description}" if p.description and p.description != "n/a" else p.device
                self.port_map[label] = p.device
                values.append(label)
        self.cmb_port["values"] = values
        if values and self.cmb_port.get() not in values:
            self.cmb_port.set(values[0])

    def toggle_connection(self):
        if self.reconnecting:
            self.stop_reconnect()
            if self.reader is not None:
                self.reader.stop()
                self.reader = None
            self.set_connected(False, "nicht verbunden")
            self.log("Warten auf den USB-Adapter abgebrochen", tag="warn")
            return
        if self.reader is not None and self.reader.is_alive():
            self.reader.stop()
            self.set_conn_status("trenne ...", GOLD)
            return
        if serial is None:
            messagebox.showerror("pyserial fehlt", "Modul 'pyserial' ist nicht installiert:\npip install pyserial")
            return
        sel = self.cmb_port.get().strip()
        port = self.port_map.get(sel, sel.split(" - ")[0].strip())
        if not port:
            messagebox.showwarning("Verbindung", "Kein COM-Port ausgewählt.")
            return
        try:
            baud = int(self.e_baud.get().strip())
        except ValueError:
            messagebox.showwarning("Verbindung", "Baudrate ist ungültig.")
            return
        self.conn_target = {"port": port, "baud": baud, "identity": port_identity(port)}
        self.reader = SerialReader(port, baud, self.q)
        self.reader.start()
        self.set_conn_status(f"verbinde mit {port} ...", GOLD)

    def on_serial_connected(self, reader):
        was_reconnecting = self.reconnecting
        self.stop_reconnect()
        self.conn_target["port"] = reader.port
        if self.conn_target.get("identity") is None:
            self.conn_target["identity"] = port_identity(reader.port)
        self.set_connected(True, f"{reader.port} verbunden")
        if was_reconnecting:
            self.log(f"{reader.port} wieder verbunden", tag="ok")
            self.add_ticker(f"Verbindung zum CP 545 wieder hergestellt ({reader.port})", "ziel")
            if self.cmb_port.get().split(" - ")[0].strip() != reader.port:
                self.refresh_ports()
                match = next((label for label, dev in self.port_map.items() if dev == reader.port), reader.port)
                self.cmb_port.set(match)
        else:
            self.log(f"Verbunden mit {reader.port}", tag="ok")

    def on_serial_lost(self, reader, exc):
        """Unerwarteter Abbruch (z.B. USB ausgesteckt): kein Fenster, automatisch wieder verbinden."""
        self.reader = None
        self.log(f"Verbindung zu {reader.port} unterbrochen, USB-Adapter ausgesteckt?", tag="error")
        self.log(f"Details: {exc}", focus=False, tag="error")
        self.add_ticker("Verbindung zum CP 545 unterbrochen, warte auf USB-Adapter", "warn")
        self.start_reconnect()

    def on_serial_open_error(self, reader, exc):
        self.reader = None
        if self.reconnecting:
            self.log(f"Wiederverbinden mit {reader.port}: {exc}", focus=False, tag="warn")
            return  # naechster Versuch folgt
        msg = friendly_open_error(reader.port, exc)
        self.set_connected(False, "Fehler beim Verbinden", RED)
        self.log(msg.replace("\n", " "), tag="error")
        self.log(f"Details: {exc}", focus=False, tag="error")
        messagebox.showerror("Verbindung", msg)

    def start_reconnect(self):
        self.reconnecting = True
        self.set_conn_status("USB getrennt, warte auf Gerät ...", RED)
        self.btn_connect.configure(text="Warten abbrechen", bg=DARK_RED)
        if self._reconnect_job is None:
            self._reconnect_job = self.root.after(RECONNECT_MS, self.try_reconnect)

    def stop_reconnect(self):
        self.reconnecting = False
        if self._reconnect_job is not None:
            self.root.after_cancel(self._reconnect_job)
            self._reconnect_job = None

    def try_reconnect(self):
        self._reconnect_job = None
        if not self.reconnecting:
            return
        if self.reader is None:
            port = self.find_reconnect_port()
            if port:
                self.set_conn_status(f"USB erkannt, verbinde mit {port} ...", GOLD)
                self.reader = SerialReader(port, self.conn_target["baud"], self.q)
                self.reader.start()
            else:
                self.set_conn_status("USB getrennt, warte auf Gerät ...", RED)
        self._reconnect_job = self.root.after(RECONNECT_MS, self.try_reconnect)

    def find_reconnect_port(self):
        return find_port(self.conn_target["port"], self.conn_target.get("identity"))

    def set_connected(self, connected, text, color=None):
        self.set_conn_status(text, color or (GREEN if connected else MUTED))
        self.btn_connect.configure(text="Trennen" if connected else "Verbinden",
                                   bg=DARK_RED if connected else GREEN)

    def log(self, text, focus=True, tag=None):
        """focus=False: nur im Tab 'Alle' (Rohdaten). Sonst in beiden Tabs."""
        line = f"{time.strftime('%H:%M:%S')}  {text}\n"
        for key in (("all", "focus") if focus else ("all",)):
            txt = self.log_tabs[key][1]
            txt.configure(state="normal")
            txt.insert("end", line, (tag,) if tag else ())
            lines = int(txt.index("end-1c").split(".")[0])
            if lines > LOG_MAX_LINES:
                txt.delete("1.0", f"{lines - LOG_MAX_LINES}.0")
            txt.see("end")
            txt.configure(state="disabled")

    # ================================================================== #
    # Startliste
    # ================================================================== #
    def rebuild_order_index(self):
        self.order_index = {nr: i for i, nr in enumerate(self.start_order)}

    def update_startlist_label(self):
        if not self.start_order:
            self._set(self.lbl_startlist, text="Keine Startliste geladen", fg=MUTED)
            return
        clubs = len({p.get("verein") for p in self.participants.values() if p.get("verein")})
        added = sum(1 for p in self.participants.values() if p.get("unknown"))
        mode = "Einzel" if self.settings["wettkampf"] == "einzel" else "Paar"
        txt = f"{len(self.start_order)} Starts, {clubs} Vereine, {mode}"
        if added:
            txt += f", {added} nachgetragen"
        if self.startlist_source:
            txt += f"\n{self.startlist_source}"
        self._set(self.lbl_startlist, text=txt, fg=TEXT)

    def update_mode_buttons(self):
        self.mode_seg.redraw()

    def on_mode_change(self):
        self.update_mode_buttons()
        self.settings["wettkampf"] = self.var_mode.get()
        self.save_settings()
        self.update_startlist_label()
        self.on_data_changed(save=False)

    def import_startlist(self):
        path = filedialog.askopenfilename(
            title="Startliste laden",
            filetypes=[("Startliste", "*.xls *.xlsx *.xlsm *.csv"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            rows = read_table(path)
        except StartlistError as exc:
            messagebox.showerror("Startliste", str(exc))
            return
        if not rows:
            messagebox.showerror("Startliste", "Die Datei ist leer.")
            return
        self.open_import_dialog(path, rows)

    def open_import_dialog(self, path, rows):
        header_idx = detect_header(rows)
        headers = [cell_str(c) for c in rows[header_idx]]
        mapping = auto_map(headers)
        _, parts0, _ = build_startlist(rows, header_idx, mapping)

        dlg = self._toplevel("Startliste importieren")
        dlg.columnconfigure(1, weight=1)
        tk.Label(dlg, text=os.path.basename(path), bg=PANEL, fg=GOLD, font=self.f_side_head, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w")
        var_mode = tk.StringVar(value=guess_mode(path, parts0))
        mf = tk.Frame(dlg, bg=PANEL)
        mf.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 4))
        col_names = ["(keine)"] + [f"{i + 1}: {h or '(ohne Titel)'}" for i, h in enumerate(headers)]
        combos = {}

        def current_mapping():
            m = {}
            for field, cb in combos.items():
                idx = cb.current()
                if idx > 0:
                    m[field] = idx - 1
            return m

        preview = tk.Text(dlg, height=12, width=90, bg="#020617", fg=TEXT, font=self.f_log, relief="flat",
                          highlightthickness=0, wrap="none")
        lbl_sum = tk.Label(dlg, text="", bg=PANEL, fg=TEXT, font=self.f_side, anchor="w", justify="left")
        var_cats = tk.BooleanVar(value=True)

        def refresh(*_a):
            m = current_mapping()
            mode = var_mode.get()
            order, parts, issues = build_startlist(rows, header_idx, m)
            preview.configure(state="normal")
            preview.delete("1.0", "end")
            if "nr" not in m:
                preview.insert("end", "Spalte für die Startnummer wählen.")
            for nr in order[:12]:
                p = parts[nr]
                preview.insert("end", f"Nr {nr:>4}  {display_name(p, mode)[:38]:<38}  {p['kategorie'][:12]:<12}  "
                                      f"{p['verein'][:28]}\n")
            preview.configure(state="disabled")
            clubs = len({p["verein"] for p in parts.values() if p["verein"]})
            cats = derive_category_ranges(order, parts)
            text = f"{len(order)} Starts, {clubs} Vereine, {len(cats)} Kategorien in der Datei."
            if issues["ohne_nr"]:
                text += f"\n{issues['ohne_nr']} Zeilen ohne gültige Startnummer werden übersprungen."
            if issues["doppelt"]:
                text += f"\nDoppelte Startnummern (nur erster Eintrag): {', '.join(map(str, issues['doppelt'][:15]))}"
            if cats:
                text += "\nKategorien: " + ", ".join(f"{c} {lo}-{hi} ({n})" for c, lo, hi, n in cats)
            lbl_sum.configure(text=text, wraplength=720)

        self._radio(mf, "Einzelwettfahren", var_mode, "einzel", command=refresh).pack(side="left", padx=(0, 6))
        self._radio(mf, "Paarwettfahren", var_mode, "paar", command=refresh).pack(side="left")
        r = 2
        for field, label in FIELD_DEFS:
            tk.Label(dlg, text=label, bg=PANEL, fg=TEXT, font=self.f_side, anchor="w").grid(
                row=r, column=0, sticky="w", padx=(0, 10), pady=1)
            cb = self._combo(dlg, col_names, width=30, state="readonly")
            cb.current(mapping[field] + 1 if field in mapping else 0)
            cb.bind("<<ComboboxSelected>>", refresh)
            cb.grid(row=r, column=1, sticky="w", pady=1)
            combos[field] = cb
            r += 1
        tk.Label(dlg, text="Vorschau (Startreihenfolge wie in der Datei)", bg=PANEL, fg=MUTED, font=self.f_side,
                 anchor="w").grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 2))
        preview.grid(row=r + 1, column=0, columnspan=2, sticky="nsew")
        lbl_sum.grid(row=r + 2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._check(dlg, "Kategorien und Nummernbereiche aus der Startliste übernehmen", var_cats).grid(
            row=r + 3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def do_import():
            m = current_mapping()
            if "nr" not in m:
                messagebox.showwarning("Startliste", "Spalte für die Startnummer fehlt.", parent=dlg)
                return
            order, parts, _issues = build_startlist(rows, header_idx, m)
            if not order:
                messagebox.showwarning("Startliste", "Keine gültigen Einträge gefunden.", parent=dlg)
                return
            if self.start_order and not messagebox.askyesno(
                    "Startliste", "Bestehende Startliste ersetzen?\nNotizen und Strafpunkte bleiben pro "
                                  "Startnummer erhalten, Resultate bleiben bestehen.", parent=dlg):
                return
            for nr, p in parts.items():
                old = self.participants.get(nr)
                if old:
                    p["notiz"] = old.get("notiz", "")
                    p["strafpunkte"] = old.get("strafpunkte", 0)
            self.participants = parts
            self.start_order = order
            self.rebuild_order_index()
            self.startlist_source = os.path.basename(path)
            self.settings["wettkampf"] = var_mode.get()
            self.var_mode.set(var_mode.get())
            self.update_mode_buttons()
            self.save_settings()
            if var_cats.get():
                self.apply_startlist_categories(order, parts)
            else:
                self.rebuild_cat_lookup()
            self.update_startlist_label()
            self.log(f"Startliste geladen: {len(order)} Starts aus {self.startlist_source}", tag="ok")
            dlg.destroy()
            self.on_data_changed()

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=r + 4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._button(btns, "Importieren", do_import, BLUE).pack(side="right")
        self._button(btns, "Abbrechen", dlg.destroy).pack(side="right", padx=(0, 8))
        refresh()
        self._center(dlg)
        dlg.grab_set()

    def apply_startlist_categories(self, order, parts):
        changed = []
        for name, lo, hi, _n in derive_category_ranges(order, parts):
            cat = self._cat_lookup.get(name.casefold())
            if cat:
                cat["min"], cat["max"] = lo, hi
            else:
                cat = {"name": name.upper(), "min": lo, "max": hi, "rekord": ""}
                self.categories.append(cat)
                self.rebuild_cat_lookup()
            changed.append(f"{cat['name']} {lo}-{hi}")
        self.rebuild_cat_lookup()
        self.save_categories()
        self.refresh_category_list()
        self.build_cards()
        if changed:
            self.log("Kategorien aus Startliste: " + ", ".join(changed))

    def clear_startlist(self):
        if not self.start_order:
            return
        clubs = len({p.get("verein") for p in self.participants.values() if p.get("verein")})
        if not self.confirm_danger(
                "Startliste entfernen",
                f"Startliste mit {len(self.start_order)} Starts aus {clubs} Vereinen wirklich entfernen?\n\n"
                "Verloren gehen: Namen, Vereine, Startreihenfolge, nachgetragene Teilnehmer und Speaker-Notizen.\n"
                "Die erfassten Zeiten bleiben bestehen.", "Startliste entfernen"):
            return
        removed = f"{len(self.start_order)} Starts aus {clubs} Vereinen ({self.startlist_source or 'ohne Dateiname'})"
        self.start_order, self.participants, self.startlist_source = [], {}, ""
        self.rebuild_order_index()
        self.rebuild_cat_lookup()
        self.update_startlist_label()
        self.log(f"Startliste entfernt: {removed}", tag="warn")
        self.on_data_changed()

    def ensure_participant(self, nr, after=None, prompt=True):
        """Unbekannte Startnummer hinter 'after' in die Startreihenfolge einfuegen (nie fuer Testnummern)."""
        if nr in self.participants or nr <= 0 or self.range_category(nr) is None:
            return
        cat = self.range_category(nr)
        self.participants[nr] = {
            "nr": nr, "p1": "", "p2": "", "kategorie": cat["name"] if cat else "", "verein": "",
            "vnr": "", "staver": "", "fg": "", "bemerkung": "", "notiz": "", "strafpunkte": 0,
            "unknown": bool(self.start_order),
        }
        if self.start_order:
            pos = self.order_index[after] + 1 if after in self.order_index else len(self.start_order)
            self.start_order.insert(pos, nr)
            self.rebuild_order_index()
            where = f"nach Nr {after}" if after in self.order_index else "am Ende"
            self.log(f"Nr {nr} nicht in Startliste, {where} eingefügt", tag="warn")
            self.add_ticker(f"Nr {nr} nicht in Startliste, bitte Name und Verein erfassen", "warn")
        self.update_startlist_label()
        self.save_autosave()
        if prompt:
            self.open_participant_dialog(nr, unknown=True)

    def edit_participant_from_entry(self):
        try:
            nr = int(self.e_part_nr.get().strip())
            if nr <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Teilnehmer", "Gültige Startnummer eingeben.")
            return
        if nr not in self.participants and self.range_category(nr) is None:
            messagebox.showinfo("Teilnehmer", f"Nr {nr} liegt in keinem Kategorienbereich und gilt als "
                                              "Testnummer.\nFür einen Teilnehmer zuerst den Nummernbereich "
                                              "einer Kategorie anpassen.")
            return
        if nr not in self.participants:
            self.ensure_participant(nr, after=None, prompt=False)
        self.open_participant_dialog(nr)

    def order_label(self, nr):
        p = self.participants.get(nr, {})
        name = display_name(p, self.settings["wettkampf"])
        return f"Nr {nr}" + (f" {name}" if name else "")

    def parse_after(self, text, own_nr):
        """'Einfuegen nach Nr': ('start', None) | ('after', nr) | (None, Fehlertext)."""
        t = text.strip().casefold()
        if t in ("", "0", "anfang", "start"):
            return "start", None
        if not t.isdigit():
            return None, "Startnummer, 0 oder «Anfang» eingeben"
        after = int(t)
        if after == own_nr:
            return None, "Nicht die eigene Startnummer"
        if after not in self.order_index:
            return None, f"Nr {after} ist nicht in der Startliste"
        return "after", after

    def move_in_order(self, nr, kind, after):
        if nr not in self.order_index:
            return False
        order = [n for n in self.start_order if n != nr]
        pos = 0 if kind == "start" else order.index(after) + 1
        order.insert(pos, nr)
        if order == self.start_order:
            return False
        self.start_order = order
        self.rebuild_order_index()
        return True

    def open_participant_dialog(self, nr, unknown=False):
        if nr in self.participant_dialogs and self.participant_dialogs[nr].winfo_exists():
            self.participant_dialogs[nr].lift()
            self.participant_dialogs[nr].focus_force()
            return
        p = self.participants.get(nr)
        if p is None:
            return
        mode = self.settings["wettkampf"]
        dlg = self._toplevel(f"{'Unbekannte Startnummer' if unknown else 'Teilnehmer'} Nr {nr}")
        self.participant_dialogs[nr] = dlg
        dlg.columnconfigure(1, weight=1)
        head = f"Nr {nr} ist nicht in der Startliste. Bitte erfassen:" if unknown else f"Teilnehmer Nr {nr}"
        tk.Label(dlg, text=head, bg=PANEL, fg=GOLD, font=self.f_side_head, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        labels = ("Vorname", "Nachname") if mode == "einzel" else ("Steuerfahrer", "Vorderfahrer")
        fields = {}
        clubs = sorted({x.get("verein") for x in self.participants.values() if x.get("verein")}, key=str.casefold)
        specs = [("p1", labels[0], "entry"), ("p2", labels[1], "entry"), ("verein", "Verein", "club"),
                 ("notiz", "Notiz für Speaker", "entry")]
        if nr in self.order_index:
            specs.append(("after", "Einfügen nach Nr", "entry"))
        for i, (key, label, kind) in enumerate(specs, start=1):
            tk.Label(dlg, text=label, bg=PANEL, fg=TEXT, font=self.f_side, anchor="w").grid(
                row=i, column=0, sticky="w", padx=(0, 10), pady=2)
            if kind == "club":
                w = self._combo(dlg, clubs, width=34)
                w.set(p.get("verein", ""))
            else:
                w = self._entry(dlg, width=36)
                if key == "after":
                    idx = self.order_index[nr]
                    w.insert(0, str(self.start_order[idx - 1]) if idx > 0 else "Anfang")
                else:
                    w.insert(0, str(p.get(key, "") or ""))
            w.grid(row=i, column=1, sticky="ew", pady=2)
            fields[key] = w
        row_after = len(specs) + 1
        lbl_pos = tk.Label(dlg, text="", bg=PANEL, fg=MUTED, font=self.f_side, anchor="w", justify="left",
                           wraplength=int(420 * self.ui_scale))
        if "after" in fields:
            lbl_pos.grid(row=row_after, column=1, sticky="w", pady=(0, 4))

        def preview(_e=None):
            if "after" not in fields:
                return True
            kind, val = self.parse_after(fields["after"].get(), nr)
            entry = fields["after"]
            if kind is None:
                entry.configure(highlightbackground=RED, highlightcolor=RED)
                lbl_pos.configure(text=val, fg=RED)
                return False
            entry.configure(highlightbackground=BORDER, highlightcolor=BLUE)
            order = [n for n in self.start_order if n != nr]
            pos = 0 if kind == "start" else order.index(val) + 1
            before = order[pos - 1] if pos > 0 else None
            after_nr = order[pos] if pos < len(order) else None
            if before is None:
                text = "am Anfang der Startliste" + (f", vor {self.order_label(after_nr)}" if after_nr else "")
            elif after_nr is None:
                text = f"am Ende, nach {self.order_label(before)}"
            else:
                text = f"zwischen {self.order_label(before)} und {self.order_label(after_nr)}"
            lbl_pos.configure(text=text, fg=MUTED)
            return True

        if "after" in fields:
            fields["after"].bind("<KeyRelease>", preview)
            preview()

        def close():
            self.participant_dialogs.pop(nr, None)
            dlg.destroy()

        def save():
            if not preview():
                fields["after"].focus_set()
                return
            for key in ("p1", "p2", "verein", "notiz"):
                p[key] = fields[key].get().strip()
            moved = ""
            if "after" in fields:
                kind, val = self.parse_after(fields["after"].get(), nr)
                if self.move_in_order(nr, kind, val):
                    moved = ", verschoben " + ("an den Anfang" if kind == "start" else f"nach Nr {val}")
            self.log(f"Teilnehmer Nr {nr} gespeichert: {display_name(p, mode) or '-'}, {p['verein'] or '-'}{moved}")
            close()
            self.update_startlist_label()
            self.on_data_changed()

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=row_after + 1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._button(btns, "Speichern", save, BLUE).pack(side="right")
        self._button(btns, "Später", close).pack(side="right", padx=(0, 8))
        dlg.bind("<Return>", lambda e: save())
        dlg.bind("<Escape>", lambda e: close())
        dlg.protocol("WM_DELETE_WINDOW", close)
        self._center(dlg)
        fields["p1"].focus_set()

    # ---------------- Notiz hinzufuegen mit Suche ---------------- #
    @staticmethod
    def fold(text):
        """Fuer die Suche: Kleinschreibung, ohne Akzente, ue/oe/ae wie u/o/a."""
        import unicodedata
        t = unicodedata.normalize("NFKD", str(text).casefold())
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        return t.replace("ae", "a").replace("oe", "o").replace("ue", "u").replace("ß", "ss")

    def search_participants(self, query, limit=300):
        terms = [self.fold(t) for t in query.split()]
        order = self.start_order + sorted(n for n in self.participants if n not in self.order_index)
        hits = []
        for nr in order:
            p = self.participants.get(nr, {})
            hay = self.fold(" ".join([display_name(p, self.settings["wettkampf"]), p.get("p1", ""), p.get("p2", ""),
                                      p.get("verein", "")]))
            ok = True
            for t in terms:
                if t.isdigit():
                    if not str(nr).startswith(t) and t not in hay:
                        ok = False
                        break
                elif t not in hay:
                    ok = False
                    break
            if ok:
                hits.append(nr)
                if len(hits) >= limit:
                    break
        return hits

    def open_note_search(self):
        if self.note_win is not None and self.note_win.winfo_exists():
            self.note_win.lift()
            self.note_win.focus_force()
            return
        win = self._toplevel("Notiz hinzufügen")
        self.note_win = win
        win.geometry(f"{int(760 * self.ui_scale)}x{int(560 * self.ui_scale)}")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)
        top = tk.Frame(win, bg=PANEL)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.columnconfigure(1, weight=1)
        tk.Label(top, text="Suche", bg=PANEL, fg=TEXT, font=self.f_side_bold).grid(row=0, column=0, padx=(0, 8))
        e_q = self._entry(top, width=30)
        e_q.grid(row=0, column=1, sticky="ew")
        tk.Label(top, text="Name, Verein oder Startnummer", bg=PANEL, fg=MUTED, font=self.f_side).grid(
            row=1, column=1, sticky="w")
        lbl_n = tk.Label(win, text="", bg=PANEL, fg=MUTED, font=self.f_side, anchor="w")
        lbl_n.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 2))
        cols = [("mark", "", 30), ("nr", "Nr", 60), ("name", "Name", 230), ("verein", "Verein", 220), ("kat", "Kategorie", 110)]
        tree = ttk.Treeview(win, columns=[c[0] for c in cols], show="headings", style="Dark.Treeview",
                            selectmode="browse")
        for key, label, width in cols:
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w", stretch=key in ("name", "verein"))
        tree.grid(row=2, column=0, sticky="nsew")
        sb = tk.Scrollbar(win, orient="vertical", command=tree.yview)
        sb.grid(row=2, column=1, sticky="ns")
        tree.configure(yscrollcommand=sb.set)
        lbl_sel = tk.Label(win, text="Teilnehmer in der Liste anklicken", bg=PANEL, fg=GOLD, font=self.f_side_bold,
                           anchor="w")
        lbl_sel.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 2))
        txt = tk.Text(win, height=4, bg=INPUT_BG, fg=INPUT_FG, insertbackground=INPUT_FG, font=self.f_side,
                      relief="flat", wrap="word", highlightthickness=1, highlightbackground=BORDER,
                      highlightcolor=BLUE, state="disabled")
        txt.grid(row=4, column=0, columnspan=2, sticky="ew")
        lbl_ok = tk.Label(win, text="", bg=PANEL, fg=GREEN, font=self.f_side, anchor="w")
        lbl_ok.grid(row=5, column=0, sticky="w", pady=(6, 0))
        btns = tk.Frame(win, bg=PANEL)
        btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        state = {"nr": None}
        mode = self.settings["wettkampf"]

        def fill(_e=None):
            q = e_q.get().strip()
            hits = self.search_participants(q)
            new_nr = None
            if q.isdigit() and int(q) not in self.participants and int(q) > 0 and self.range_category(int(q)):
                new_nr = int(q)
            tree.delete(*tree.get_children())
            for nr in hits:
                p = self.participants.get(nr, {})
                cat = self.category_of(nr)
                tree.insert("", "end", iid=str(nr), values=("✎" if p.get("notiz") else "", nr, display_name(p, mode),
                                                            p.get("verein", ""), cat["name"] if cat else ""))
            if new_nr is not None:
                tree.insert("", "end", iid=f"new{new_nr}", values=("", new_nr, "neu anlegen", "", ""))
            total = len(hits)
            lbl_n.configure(text=f"{total} Treffer" + (" (es werden höchstens 300 angezeigt)" if total >= 300 else ""))

        def select(_e=None):
            sel = tree.selection()
            if not sel:
                return
            iid = sel[0]
            if iid.startswith("new"):
                nr = int(iid[3:])
                if nr not in self.participants:
                    self.ensure_participant(nr, after=self.current_nr if self.start_order else None, prompt=False)
                fill()
                if str(nr) in tree.get_children():
                    tree.selection_set(str(nr))
                    tree.see(str(nr))
                return
            nr = int(iid)
            state["nr"] = nr
            p = self.participants.get(nr, {})
            lbl_sel.configure(text=f"Notiz für {self.order_label(nr)}" + (f", {p['verein']}" if p.get("verein") else ""))
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", p.get("notiz", ""))
            lbl_ok.configure(text="")

        def save(_e=None):
            nr = state["nr"]
            if nr is None or nr not in self.participants:
                lbl_ok.configure(text="Zuerst einen Teilnehmer wählen", fg=RED)
                return "break"
            note = " ".join(txt.get("1.0", "end").split())
            self.participants[nr]["notiz"] = note
            self.log(f"Notiz Nr {nr}: {note or '(gelöscht)'}")
            if tree.exists(str(nr)):
                tree.set(str(nr), "mark", "✎" if note else "")
            lbl_ok.configure(text=f"Gespeichert: {self.order_label(nr)}" if note else f"Notiz gelöscht: Nr {nr}", fg=GREEN)
            self.on_data_changed()
            return "break"

        def close(_e=None):
            self.note_win = None
            win.destroy()

        def first_hit(_e=None):
            kids = tree.get_children()
            if kids:
                tree.selection_set(kids[0])
                tree.focus(kids[0])
                tree.focus_set()
                select()
            return "break"

        e_q.bind("<KeyRelease>", lambda e: fill() if e.keysym not in ("Return", "Down", "Up", "Escape") else None)
        e_q.bind("<Return>", first_hit)
        e_q.bind("<Down>", first_hit)
        tree.bind("<<TreeviewSelect>>", select)
        tree.bind("<Return>", lambda e: (txt.focus_set(), "break")[1])
        txt.bind("<Control-Return>", save)
        self._button(btns, "Speichern", save, BLUE).pack(side="right")
        self._button(btns, "Schliessen", close).pack(side="right", padx=(0, 8))
        tk.Label(btns, text="Strg+Enter speichert", bg=PANEL, fg=MUTED, font=self.f_side).pack(side="left")
        win.bind("<Escape>", close)
        win.protocol("WM_DELETE_WINDOW", close)
        fill()
        self._center(win)
        e_q.focus_set()

    # ================================================================== #
    # Kategorien-Editor
    # ================================================================== #
    def refresh_category_list(self):
        self.lst_cat.delete(0, "end")
        for cat in self.categories:
            rek = f", Rekord {cat['rekord']}" if cat.get("rekord") else ""
            self.lst_cat.insert("end", f"{cat['name']}  ({cat['min']}-{cat['max']}{rek})")

    def on_category_select(self, _event=None):
        sel = self.lst_cat.curselection()
        if not sel:
            return
        cat = self.categories[sel[0]]
        for entry, value in ((self.e_cat_name, cat["name"]), (self.e_cat_min, cat["min"]),
                             (self.e_cat_max, cat["max"]), (self.e_cat_rekord, cat.get("rekord", ""))):
            entry.delete(0, "end")
            entry.insert(0, str(value))

    def read_category_fields(self, ignore_index=None):
        name = self.e_cat_name.get().strip()
        rekord = self.e_cat_rekord.get().strip().replace(",", ".")
        try:
            lo = int(self.e_cat_min.get().strip())
            hi = int(self.e_cat_max.get().strip())
        except ValueError:
            messagebox.showwarning("Kategorie", "Von/Bis müssen ganze Zahlen sein.")
            return None
        if not name:
            messagebox.showwarning("Kategorie", "Name fehlt.")
            return None
        if lo > hi:
            messagebox.showwarning("Kategorie", "'Von' ist grösser als 'Bis'.")
            return None
        if rekord and parse_time(rekord) is None:
            messagebox.showwarning("Kategorie", "Rekord im Format m:ss.hh oder ss.hh eingeben.")
            return None
        for i, cat in enumerate(self.categories):
            if i != ignore_index and cat["name"].casefold() == name.casefold():
                messagebox.showwarning("Kategorie", f"Kategorie '{name}' existiert bereits.")
                return None
        for i, cat in enumerate(self.categories):
            if i != ignore_index and lo <= cat["max"] and hi >= cat["min"]:
                if not messagebox.askyesno("Kategorie", f"Range überschneidet sich mit {cat['name']} "
                                           f"({cat['min']}-{cat['max']}). Trotzdem speichern?"):
                    return None
                break
        return {"name": name, "min": lo, "max": hi, "rekord": rekord}

    def category_update(self):
        sel = self.lst_cat.curselection()
        if not sel:
            messagebox.showinfo("Kategorie", "Zuerst eine Kategorie in der Liste anklicken.")
            return
        cat = self.read_category_fields(ignore_index=sel[0])
        if cat:
            old_name = self.categories[sel[0]]["name"]
            if old_name.casefold() != cat["name"].casefold():
                for p in self.participants.values():
                    if p.get("kategorie", "").casefold() == old_name.casefold():
                        p["kategorie"] = cat["name"]
            self.categories[sel[0]] = cat
            self.categories_changed(select=sel[0])

    def category_add(self):
        cat = self.read_category_fields()
        if cat:
            self.categories.append(cat)
            self.categories_changed(select=len(self.categories) - 1)

    def category_delete(self):
        sel = self.lst_cat.curselection()
        if not sel:
            return
        cat = self.categories[sel[0]]
        if self.confirm_danger("Kategorie löschen", f"Kategorie '{cat['name']}' ({cat['min']}-{cat['max']}) "
                               "wirklich löschen?\n\nZeiten dieser Kategorie erscheinen danach nicht mehr im "
                               "Ranking, bleiben aber gespeichert.", "Kategorie löschen"):
            del self.categories[sel[0]]
            self.categories_changed()

    def categories_changed(self, select=None):
        self.rebuild_cat_lookup()
        self.save_categories()
        self.log("Kategorien geändert: " + ", ".join(f"{c['name']} {c['min']}-{c['max']}" for c in self.categories))
        self.refresh_category_list()
        if select is not None:
            self.lst_cat.selection_set(select)
            self.lst_cat.see(select)
        self.build_cards()
        self.on_data_changed()

    def load_categories(self):
        path = os.path.join(self.data_path, CATEGORIES_FILE)
        try:
            with open(path, encoding="utf-8") as fh:
                cats = json.load(fh)
            cats = [{"name": str(c["name"]), "min": int(c["min"]), "max": int(c["max"]),
                     "rekord": str(c.get("rekord", "") or "")} for c in cats]
            if cats:
                return cats
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return [dict(c) for c in DEFAULT_CATEGORIES]

    def save_categories(self):
        try:
            with open(os.path.join(self.data_path, CATEGORIES_FILE), "w", encoding="utf-8") as fh:
                json.dump(self.categories, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            self.log(f"Kategorien nicht gespeichert: {exc}", tag="error")

    # ================================================================== #
    # Einstellungen
    # ================================================================== #
    def load_settings(self):
        try:
            with open(os.path.join(self.data_path, SETTINGS_FILE), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        settings = deep_merge(DEFAULT_SETTINGS, data)
        if settings["wettkampf"] not in ("einzel", "paar"):
            settings["wettkampf"] = "einzel"
        if not re.fullmatch(r"[A-Za-z0-9_\-]{16,}", settings["web"]["key"]):
            settings["web"]["key"] = secrets.token_urlsafe(18)
        return settings

    def save_settings(self):
        try:
            with open(os.path.join(self.data_path, SETTINGS_FILE), "w", encoding="utf-8") as fh:
                json.dump(self.settings, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            if hasattr(self, "log_tabs"):
                self.log(f"Einstellungen nicht gespeichert: {exc}", tag="error")

    # ================================================================== #
    # Onlinetool (Oberflaeche vorbereitet, ohne Anbindung)
    # ================================================================== #
    def pending_uploads(self):
        return [nr for nr, r in self.results.items() if r.get("status") != ST_SENT and not self.is_test(nr)]

    def update_online_labels(self):
        if not hasattr(self, "lbl_online"):
            return
        o = self.settings["online"]
        if o["mode"] == "online":
            mode = "Sofort senden" if o["send_mode"] == "auto" else "Senden nach Bestätigung"
            self._set(self.lbl_online, text=f"Modus: Online ({mode})\nStatus: noch nicht angebunden", fg=GOLD)
        else:
            self._set(self.lbl_online, text="Modus: Offline", fg=MUTED)
        self._set(self.lbl_upload, text=f"Upload: {len(self.pending_uploads())} offen")

    def build_upload_payload(self, nr):
        """Vorbereitet fuer die API: nur gefahrene Zeit, keine Strafpunkte."""
        r = self.results[nr]
        return {
            "wettkampf_id": self.settings["online"]["comp_id"],
            "startnummer": nr,
            "lauf": r.get("run", 1),
            "zeit": r["str"],
            "zeit_sekunden": round(r["secs"], 3),
            "quelle": r.get("source", ""),
            "erfasst_um": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(r["ts"])),
        }

    def request_startlist_update(self, reason, manual=False):
        if self.settings["online"]["mode"] != "online":
            if manual:
                messagebox.showinfo("Onlinetool", "Modus ist Offline. Online-Modus in den Einstellungen aktivieren.")
            return
        try:
            self.online.fetch_startlist()
        except NotImplementedError as exc:
            self.log(f"Startliste-Update ({reason}): {exc}", tag="warn")
            if manual:
                messagebox.showinfo("Onlinetool", f"{exc}.\nDie Anbindung folgt mit der API-Dokumentation.")

    def open_online_settings(self):
        o = self.settings["online"]
        dlg = self._toplevel("Einstellungen Onlinetool")
        dlg.columnconfigure(1, weight=1)
        var_mode = tk.StringVar(value=o["mode"])
        var_send = tk.StringVar(value=o["send_mode"])
        var_auto = tk.BooleanVar(value=o["auto_startlist"])
        r = 0
        tk.Label(dlg, text="Betriebsart", bg=PANEL, fg=GOLD, font=self.f_side_head, anchor="w").grid(
            row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self._radio(dlg, "Offline (Startliste aus Excel)", var_mode, "offline").grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
        r += 1
        self._radio(dlg, "Online (Onlinetool ist Master)", var_mode, "online").grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
        r += 1
        entries = {}
        for key, label, show in (("url", "API-Adresse (https://...)", ""), ("comp_id", "Wettkampf-ID", ""),
                                 ("token", "API-Schlüssel", "•")):
            tk.Label(dlg, text=label, bg=PANEL, fg=TEXT, font=self.f_side, anchor="w").grid(
                row=r, column=0, sticky="w", padx=(0, 10), pady=(6, 0))
            e = self._entry(dlg, width=40, show=show)
            e.insert(0, o[key])
            e.grid(row=r, column=1, sticky="ew", pady=(6, 0))
            entries[key] = e
            r += 1
        tk.Label(dlg, text="Senden der Zeiten", bg=PANEL, fg=GOLD, font=self.f_side_head, anchor="w").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(10, 0))
        r += 1
        self._radio(dlg, "Sofort (Echtzeit)", var_send, "auto").grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
        r += 1
        self._radio(dlg, "Nach Bestätigung in der Upload-Warteschlange", var_send, "confirm").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=2)
        r += 1
        self._check(dlg, "Startliste automatisch aktualisieren bei Vereins- oder Startblockwechsel", var_auto).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))
        r += 1
        tk.Label(dlg, text="Gesendet werden nur gefahrene Zeiten. Strafpunkte kommen vom Onlinetool und "
                           "zählen nur im Speaker-Ranking.\nDie Anbindung ist vorbereitet und folgt mit der "
                           "API-Dokumentation.", bg=PANEL, fg=MUTED, font=self.f_side, justify="left",
                 anchor="w").grid(row=r, column=0, columnspan=2, sticky="w", pady=(10, 0))
        r += 1

        def save():
            url = entries["url"].get().strip()
            if url and not url.lower().startswith("https://"):
                messagebox.showwarning("Onlinetool", "Die API-Adresse muss mit https:// beginnen.", parent=dlg)
                return
            o.update(mode=var_mode.get(), send_mode=var_send.get(), auto_startlist=bool(var_auto.get()),
                     url=url, comp_id=entries["comp_id"].get().strip(), token=entries["token"].get().strip())
            self.save_settings()
            self.log(f"Onlinetool: Modus {o['mode']}, Senden {o['send_mode']}")
            dlg.destroy()
            self.update_online_labels()

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self._button(btns, "Speichern", save, BLUE).pack(side="right")
        self._button(btns, "Abbrechen", dlg.destroy).pack(side="right", padx=(0, 8))
        test = self._button(btns, "Verbindung testen (folgt)", None)
        test.configure(state="disabled")
        test.pack(side="left")
        self._center(dlg)
        dlg.grab_set()

    def open_upload_window(self):
        if self.upload_win is not None and self.upload_win.winfo_exists():
            self.upload_win.lift()
            return
        win = self._toplevel("Upload-Warteschlange")
        win.geometry("980x520")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        self.upload_win = win
        tk.Label(win, text="Onlinetool noch nicht angebunden. Gesendet werden nur gefahrene Zeiten, keine Strafpunkte.",
                 bg=PANEL, fg=GOLD, font=self.f_side_bold, anchor="w").grid(row=0, column=0, columnspan=2, sticky="w")
        cols = [("nr", "Nr", 60), ("name", "Name", 230), ("verein", "Verein", 200), ("kat", "Kategorie", 110),
                ("zeit", "Zeit", 90), ("lauf", "Lauf", 50), ("quelle", "Quelle", 80), ("status", "Status", 100)]
        tree = ttk.Treeview(win, columns=[c[0] for c in cols], show="headings", style="Dark.Treeview",
                            selectmode="extended")
        for key, label, width in cols:
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w", stretch=key in ("name", "verein"))
        tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        sb = tk.Scrollbar(win, orient="vertical", command=tree.yview)
        sb.grid(row=1, column=1, sticky="ns", pady=(8, 0))
        tree.configure(yscrollcommand=sb.set)
        tree.tag_configure(ST_OPEN, foreground=GOLD)
        tree.tag_configure(ST_APPROVED, foreground="#38bdf8")
        tree.tag_configure(ST_SENT, foreground=GREEN)
        tree.tag_configure(ST_ERROR, foreground=RED)
        self.upload_tree = tree

        def approve(nrs):
            n = 0
            for nr in nrs:
                if nr in self.results and not self.is_test(nr) and self.results[nr].get("status") in (ST_OPEN, ST_ERROR):
                    self.results[nr]["status"] = ST_APPROVED
                    n += 1
            if n:
                self.log(f"{n} Zeit{'en' if n != 1 else ''} freigegeben (Senden folgt mit API-Anbindung)")
                self.on_data_changed()

        btns = tk.Frame(win, bg=PANEL)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._button(btns, "Ausgewählte freigeben",
                     lambda: approve([int(i) for i in tree.selection()]), BLUE).pack(side="left")
        self._button(btns, "Alle freigeben", lambda: approve(list(self.results)), BLUE).pack(side="left", padx=(8, 0))
        send = self._button(btns, "Jetzt senden (folgt)", None)
        send.configure(state="disabled")
        send.pack(side="left", padx=(8, 0))

        def close():
            self.upload_win = None
            win.destroy()

        self._button(btns, "Schliessen", close).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", close)
        self.refresh_upload_window()
        self._center(win)

    def refresh_upload_window(self):
        if self.upload_win is None or not self.upload_win.winfo_exists():
            return
        tree = self.upload_tree
        selected = set(tree.selection())
        tree.delete(*tree.get_children())
        mode = self.settings["wettkampf"]
        for nr, r in sorted(self.results.items(), key=lambda kv: kv[1]["ts"], reverse=True):
            if self.is_test(nr):
                continue
            p = self.participants.get(nr, {})
            cat = self.category_of(nr)
            status = r.get("status", ST_OPEN)
            tree.insert("", "end", iid=str(nr), tags=(status,), values=(
                nr, display_name(p, mode), p.get("verein", ""), cat["name"] if cat else "",
                f"{r['str']}s", r.get("run", 1), r.get("source", ""), status))
        keep = [i for i in selected if tree.exists(i)]
        if keep:
            tree.selection_set(keep)

    # ================================================================== #
    # Browser-Anzeige
    # ================================================================== #
    def refresh_bind_ips(self):
        ips = local_ipv4s()
        self.cmb_bind["values"] = ips
        saved = self.settings["web"]["bind"]
        self.cmb_bind.set(saved if saved in ips else (ips[0] if ips else ""))

    def set_web_url(self, text, fg=MUTED):
        self._set(self.lbl_web_url, text=text, fg=fg)

    def toggle_web(self):
        if self.web.running:
            self.web.stop()
            self.btn_web.configure(text="Browser-Anzeige starten", bg=GREEN)
            self.set_web_url("Aus")
            self.log("Browser-Anzeige gestoppt", tag="warn")
            return
        bind = self.cmb_bind.get().strip()
        if not bind:
            self.refresh_bind_ips()
            bind = self.cmb_bind.get().strip()
        if not bind:
            messagebox.showwarning("Browser-Anzeige", "Kein lokales Netzwerk gefunden.\n"
                                                      "WLAN oder LAN verbinden und ⟳ drücken.")
            return
        try:
            port = int(self.e_port.get().strip())
            if not 1024 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Browser-Anzeige", "Port zwischen 1024 und 65535 wählen (Standard 8080).")
            return
        try:
            self.web.snapshot = self.build_web_snapshot()
            self.web.start(bind, port, self.settings["web"]["key"])
        except (OSError, ValueError) as exc:
            messagebox.showerror("Browser-Anzeige", f"Start nicht möglich:\n{exc}")
            return
        self.settings["web"]["bind"], self.settings["web"]["port"] = bind, port
        self.save_settings()
        self.btn_web.configure(text="Browser-Anzeige stoppen", bg=DARK_RED)
        self.set_web_url(f"Läuft: http://{bind}:{port}\nSchlüssel im Link verborgen, mit «Link kopieren» "
                         f"oder «QR-Code» weitergeben.", GREEN)
        self.log(f"Browser-Anzeige läuft: http://{bind}:{port}/", tag="ok")

    def copy_web_url(self):
        if not self.web.running:
            messagebox.showinfo("Browser-Anzeige", "Browser-Anzeige ist nicht gestartet.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.web.url)

    def show_web_qr(self):
        if not self.web.running:
            messagebox.showinfo("Browser-Anzeige", "Browser-Anzeige ist nicht gestartet.")
            return
        try:
            matrix = qr_matrix(self.web.url)
        except ValueError as exc:
            messagebox.showerror("QR-Code", str(exc))
            return
        n = len(matrix)
        quiet = 4  # Ruhezone, noetig fuer zuverlaessiges Erkennen
        box = max(4, int(360 * self.ui_scale) // (n + 2 * quiet))
        side = (n + 2 * quiet) * box
        dlg = self._toplevel("QR-Code Browser-Anzeige")
        cv = tk.Canvas(dlg, width=side, height=side, bg=WHITE, highlightthickness=0, bd=0)
        cv.pack()
        for y, row in enumerate(matrix):
            x = 0
            while x < n:  # zusammenhaengende dunkle Felder einer Zeile als ein Rechteck zeichnen
                if row[x]:
                    start = x
                    while x < n and row[x]:
                        x += 1
                    cv.create_rectangle((quiet + start) * box, (quiet + y) * box, (quiet + x) * box,
                                        (quiet + y + 1) * box, fill="#000000", width=0)
                else:
                    x += 1
        tk.Label(dlg, text=f"Nur im selben WLAN / Netzwerk erreichbar\n{self.web.url.split('?')[0]}",
                 bg=PANEL, fg=MUTED, font=self.f_side, justify="center").pack(pady=(8, 0))
        self._center(dlg)

    def new_web_key(self):
        if not messagebox.askyesno("Browser-Anzeige", "Neuen Schlüssel erzeugen?\nBisherige Links und QR-Codes "
                                                      "funktionieren danach nicht mehr."):
            return
        self.settings["web"]["key"] = secrets.token_urlsafe(18)
        self.save_settings()
        if self.web.running:
            self.toggle_web()
            self.toggle_web()
        self.log("Neuer Schlüssel für Browser-Anzeige erzeugt", tag="ok")

    def build_web_snapshot(self):
        mode = self.settings["wettkampf"]
        cats = []
        for cat in self.categories:
            rows = []
            for rank, nr, _t in self.ranking(cat)[:TOP_N]:
                rows.append({"rank": rank, "nr": nr, "time": self.disp_time(nr), "pen": self.penalty(nr),
                             "who": self.who_text(nr) if self.settings["show"].get("namen") else ""})
            cats.append({"name": cat["name"], "rows": rows})
        nxt = []
        if self.settings["show"].get("naechste"):
            for nr in self.next_starters():
                p = self.participants.get(nr, {})
                cat = self.category_of(nr)
                nxt.append({"nr": nr, "name": display_name(p, mode) or "-",
                            "info": "  ·  ".join(x for x in (p.get("verein", ""), cat["name"] if cat else "") if x)})
        live = [self.live_labels[0].cget("text"), self.who_line(self.current_nr), self.live_labels[2].cget("text")]
        ziel = [self.ziel_labels[0].cget("text"), self.who_line(self.ziel_nr), self.ziel_labels[2].cget("text")]
        data = {"time": time.strftime("%H:%M:%S"), "live": live, "ziel": ziel, "cats": cats, "next": nxt}
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def who_line(self, nr):
        """Wie participant_line, aber ohne Speaker-Notizen (nicht oeffentlich)."""
        if nr is None:
            return ""
        cat = self.category_of(nr)
        parts = [x for x in (self.who_text(nr), cat["name"] if cat else "") if x]
        return "  ·  ".join(parts)

    def web_tick(self):
        if self.web.running:
            try:
                self.web.snapshot = self.build_web_snapshot()
            except Exception as exc:
                self.log(f"Browser-Anzeige: {exc}", tag="error")
        self.root.after(WEB_SNAPSHOT_MS, self.web_tick)

    # ================================================================== #
    # Manuelle Zeiterfassung
    # ================================================================== #
    def open_manual_dialog(self):
        try:
            nr = int(self.e_manual_nr.get().strip())
            if nr <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Manuelle Zeit", "Gültige Startnummer eingeben.")
            return

        dlg = self._toplevel(f"Zeit manuell erfassen - Nr {nr}")
        dlg.configure(padx=24, pady=20)
        dlg.resizable(False, False)
        cat = self.category_of(nr)
        who = self.who_text(nr)
        head = f"Nr {nr}  ({cat['name'] if cat else 'ohne Kategorie'})" + (f"  {who}" if who else "")
        if self.is_test(nr):
            head = f"Nr {nr}  (Testnummer, erscheint nicht im Ranking)"
        tk.Label(dlg, text=head,
                 bg=PANEL, fg=GOLD, font=self.f_side_head).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 12))
        for col, text in ((0, "Min"), (2, "Sek"), (4, "1/10")):
            tk.Label(dlg, text=text, bg=PANEL, fg=MUTED, font=self.f_side).grid(row=1, column=col)

        def make_vcmd(maxlen):
            return (dlg.register(lambda v: v == "" or (v.isdigit() and len(v) <= maxlen)), "%P")

        fields = []
        for col, maxlen in ((0, 2), (2, 2), (4, 1)):
            e = tk.Entry(dlg, width=maxlen + 1, justify="center", font=self.f_dialog, bg=INPUT_BG, fg=INPUT_FG,
                         insertbackground=INPUT_FG, relief="flat", validate="key", validatecommand=make_vcmd(maxlen))
            e.grid(row=2, column=col, padx=2)
            fields.append((e, maxlen))
        tk.Label(dlg, text=":", bg=PANEL, fg=TEXT, font=self.f_dialog).grid(row=2, column=1)
        tk.Label(dlg, text=".", bg=PANEL, fg=TEXT, font=self.f_dialog).grid(row=2, column=3)

        def auto_advance(event, idx):
            entry, maxlen = fields[idx]
            if event.char and event.char.isdigit() and len(entry.get()) >= maxlen and idx + 1 < len(fields):
                fields[idx + 1][0].focus_set()
                fields[idx + 1][0].select_range(0, "end")

        for i, (e, _) in enumerate(fields):
            e.bind("<KeyRelease>", lambda ev, i=i: auto_advance(ev, i))

        def save():
            mm, ss, zz = (f[0].get().strip() for f in fields)
            if ss == "":
                messagebox.showwarning("Manuelle Zeit", "Sekunden fehlen.", parent=dlg)
                return
            m, s, z = int(mm or 0), int(ss), int(zz or 0)
            if s > 59:
                messagebox.showwarning("Manuelle Zeit", "Sekunden müssen 0-59 sein.", parent=dlg)
                return
            if nr in self.results and not messagebox.askyesno(
                    "Manuelle Zeit", f"Nr {nr} hat bereits {self.results[nr]['str']}s. Überschreiben?", parent=dlg):
                return
            dlg.destroy()
            if self.start_order and nr not in self.participants:
                self.ensure_participant(nr, after=self.current_nr, prompt=False)
            self.register_final(nr, m * 60 + s + z / 10, format_manual_time(m, s, z), source="manuell")
            self.e_manual_nr.delete(0, "end")
            if self.participants.get(nr, {}).get("unknown") and not display_name(self.participants[nr], "einzel"):
                self.open_participant_dialog(nr, unknown=True)

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=3, column=0, columnspan=5, sticky="ew", pady=(16, 0))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        self._button(btns, "Abbrechen", dlg.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._button(btns, "Speichern", save, BLUE).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        dlg.bind("<Return>", lambda e: save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        self._center(dlg)
        dlg.grab_set()
        fields[0][0].focus_set()

    # ================================================================== #
    # Export
    # ================================================================== #
    def export_rows(self):
        rows = []
        for cat in self.categories:
            for rank, nr, _t in self.ranking(cat):
                rows.append([cat["name"], rank, nr, self.results[nr]["str"], f"{self.results[nr]['secs']:.2f}"])
        for nr in sorted(n for n in self.results if self.category_of(n) is None and not self.is_test(n)):
            r = self.results[nr]
            rows.append(["OHNE KATEGORIE", "", nr, r["str"], f"{r['secs']:.2f}"])
        for nr in sorted(n for n in self.results if self.is_test(n)):
            r = self.results[nr]
            rows.append(["TEST", "", nr, r["str"], f"{r['secs']:.2f}"])
        return rows

    def export_csv(self):
        if not self.results:
            messagebox.showinfo("Export", "Noch keine Resultate vorhanden.")
            return
        path = filedialog.asksaveasfilename(
            title="Resultate exportieren", defaultextension=".csv",
            filetypes=[("CSV (Excel)", "*.csv")],
            initialfile=f"{self.event_prefix()}_Resultate.csv")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["Kategorie", "Rang", "Startnummer", "Zeit (String)", "Zeit (Sekunden)"])
                w.writerows(self.export_rows())
        except OSError as exc:
            messagebox.showerror("Export", f"Datei konnte nicht geschrieben werden:\n{exc}")
            return
        self.log(f"Export: {path}", tag="ok")
        messagebox.showinfo("Export", f"{len(self.results)} Resultate exportiert:\n{path}")

    def club_columns(self):
        names = ["Name"] if self.settings["wettkampf"] == "einzel" else ["Steuerfahrer", "Vorderfahrer"]
        return (["Verein", "Kategorie", "Rang (provisorisch)", "Startnummer"] + names +
                ["Gefahrene Zeit", "Gefahrene Zeit (s)", "Strafpunkte", "Total (s)", "Lauf", "Quelle", "Status"])

    def club_data(self, include_missing):
        """{verein: [zeilen]} in Startlisten-Reihenfolge der Vereine."""
        mode = self.settings["wettkampf"]
        cat_order = {c["name"]: i for i, c in enumerate(self.categories)}
        nrs = set(self.real_results())
        if include_missing:
            nrs |= {n for n in self.participants if not self.is_test(n)}
        clubs = {}
        club_pos = {}
        for nr in sorted(nrs, key=lambda n: (self.order_index.get(n, 10 ** 6), n)):
            p = self.participants.get(nr, {})
            club = p.get("verein") or "OHNE VEREIN"
            club_pos.setdefault(club, len(club_pos))
            cat = self.category_of(nr)
            cat_name = cat["name"] if cat else (p.get("kategorie") or "OHNE KATEGORIE")
            r = self.results.get(nr)
            rank = self.rank_of(nr)[0] if r else None
            names = [display_name(p, mode)] if mode == "einzel" else [p.get("p1", ""), p.get("p2", "")]
            pen = self.penalty(nr)
            if r:
                vals = [r["str"], round(r["secs"], 2), pen, round(r["secs"] + pen, 2), r.get("run", 1),
                        r.get("source", ""), "nachgetragen" if p.get("unknown") else ""]
            else:
                vals = ["", "", pen, "", "", "", "ohne Zeit"]
            row = [club, cat_name, rank if rank is not None else "", nr] + names + vals
            sort_key = (cat_order.get(cat_name, 99), rank if rank is not None else 10 ** 6, nr)
            clubs.setdefault(club, []).append((sort_key, row))
        ordered = sorted(clubs, key=lambda c: club_pos[c])
        return {c: [row for _k, row in sorted(clubs[c], key=lambda x: x[0])] for c in ordered}

    def club_choices(self):
        """[(anzeige, schluessel)] fuer die Vereinsauswahl: alle, jeder Verein, ohne Verein."""
        counts = {}
        for nr in self.real_results():
            club = self.participants.get(nr, {}).get("verein") or "OHNE VEREIN"
            counts[club] = counts.get(club, 0) + 1
        order = []
        for nr in self.start_order:
            club = self.participants.get(nr, {}).get("verein")
            if club and club not in order:
                order.append(club)
        for club in sorted((c for c in counts if c not in order and c != "OHNE VEREIN"), key=str.casefold):
            order.append(club)
        choices = [("Alle Vereine", None)]
        for club in order:
            n = counts.get(club, 0)
            choices.append((f"{club} ({n} Zeit{'en' if n != 1 else ''})", club))
        n = counts.get("OHNE VEREIN", 0)
        choices.append((f"Ohne Verein ({n} Zeit{'en' if n != 1 else ''})", "OHNE VEREIN"))
        return choices

    def open_club_export(self):
        if not self.real_results():
            messagebox.showinfo("Export", "Noch keine Resultate vorhanden.")
            return
        dlg = self._toplevel("Export pro Verein")
        dlg.columnconfigure(1, weight=1)
        fmt_values = ["xlsx", "csv", "txt"]
        var_fmt = tk.StringVar(value=fmt_values[0])
        var_split = tk.StringVar(value="einzeln")
        var_missing = tk.BooleanVar(value=False)
        tk.Label(dlg, text="Format", bg=PANEL, fg=GOLD, font=self.f_side_head, anchor="w").grid(row=0, column=0, sticky="w")
        ff = tk.Frame(dlg, bg=PANEL)
        ff.grid(row=0, column=1, sticky="w")
        labels = {"xlsx": "Excel (.xlsx)", "csv": "CSV (.csv)", "txt": "Text (.txt)"}
        for v in fmt_values:
            self._radio(ff, labels[v], var_fmt, v).pack(side="left", padx=(0, 6))
        tk.Label(dlg, text="Dateien", bg=PANEL, fg=GOLD, font=self.f_side_head, anchor="w").grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        sf = tk.Frame(dlg, bg=PANEL)
        sf.grid(row=1, column=1, sticky="w", pady=(8, 0))
        club_row = tk.Frame(dlg, bg=PANEL)
        tk.Label(club_row, text="Verein", bg=PANEL, fg=TEXT, font=self.f_side, anchor="w").pack(side="left", padx=(0, 8))
        choices = self.club_choices()
        cmb_club = self._combo(club_row, [c[0] for c in choices], width=40, state="readonly")
        cmb_club.current(0)
        cmb_club.pack(side="left", fill="x", expand=True)

        def on_split():
            if var_split.get() == "einzeln":
                club_row.grid(row=2, column=1, sticky="ew", pady=(6, 0))
            else:
                club_row.grid_remove()

        self._radio(sf, "Eine Datei pro Verein", var_split, "einzeln", command=on_split).pack(side="left", padx=(0, 6))
        self._radio(sf, "Eine Datei für alle Vereine", var_split, "gesamt", command=on_split).pack(side="left")
        on_split()
        self._check(dlg, "Teilnehmer ohne Zeit mitexportieren", var_missing).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tk.Label(dlg, text="Ziel", bg=PANEL, fg=GOLD, font=self.f_side_head, anchor="w").grid(
            row=4, column=0, sticky="nw", pady=(8, 0))
        tf = tk.Frame(dlg, bg=PANEL)
        tf.grid(row=4, column=1, sticky="ew", pady=(8, 0))
        tf.columnconfigure(0, weight=1)
        cmb = self._combo(tf, width=40, state="readonly")
        cmb.grid(row=0, column=0, sticky="ew")
        lbl_path = tk.Label(tf, text="", bg=PANEL, fg=MUTED, font=self.f_side, anchor="w", justify="left",
                            wraplength=int(520 * self.ui_scale))
        lbl_path.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        targets = {}

        def short(path):
            path = os.path.normpath(path)
            return path if len(path) <= 44 else "…" + path[-43:]

        def show_path(_e=None):
            path = targets.get(cmb.get(), "")
            lbl_path.configure(text=f"Zielordner: {path}" if path else "Kein Ziel gewählt")

        def refresh_targets():
            targets.clear()
            for path, label in removable_drives():
                targets[f"USB: {label}"] = path
            if self.settings["export_dir"]:
                targets[short(self.settings["export_dir"])] = self.settings["export_dir"]
            cmb["values"] = list(targets)
            if cmb.get() not in targets:
                cmb.set(next(iter(targets), ""))
            show_path()

        def choose():
            path = filedialog.askdirectory(title="Zielordner wählen", parent=dlg)
            if path:
                targets[short(path)] = path
                cmb["values"] = list(targets)
                cmb.set(short(path))
                show_path()

        cmb.bind("<<ComboboxSelected>>", show_path)
        self._button(tf, "⟳", refresh_targets).grid(row=0, column=1, padx=(6, 0))
        self._button(tf, "Ordner wählen", choose).grid(row=0, column=2, padx=(6, 0))
        refresh_targets()

        def do_export():
            sel = cmb.get().strip()
            base = targets.get(sel, "")
            if not base or not os.path.isdir(base):
                messagebox.showwarning("Export", "Gültigen Zielordner oder USB-Stick wählen.", parent=dlg)
                return
            per_club = var_split.get() == "einzeln"
            only = choices[cmb_club.current()][1] if per_club and cmb_club.current() >= 0 else None
            try:
                folder, files = self.write_club_export(base, var_fmt.get(), per_club, var_missing.get(), only)
            except Exception as exc:
                messagebox.showerror("Export", f"Export fehlgeschlagen:\n{exc}", parent=dlg)
                return
            if not files:
                messagebox.showinfo("Export", "Für diese Auswahl sind keine Zeiten vorhanden.", parent=dlg)
                return
            if not sel.startswith("USB: "):
                self.settings["export_dir"] = base
                self.save_settings()
            self.log(f"Export pro Verein: {len(files)} Datei(en) in {folder}", tag="ok")
            dlg.destroy()
            messagebox.showinfo("Export", f"{len(files)} Datei(en) geschrieben:\n{folder}\n\n"
                                          "USB-Stick vor dem Entfernen sicher auswerfen.")

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self._button(btns, "Exportieren", do_export, BLUE).pack(side="right")
        self._button(btns, "Abbrechen", dlg.destroy).pack(side="right", padx=(0, 8))
        self._center(dlg)
        dlg.grab_set()

    def write_club_export(self, base, fmt, per_club, include_missing, only_club=None):
        data = self.club_data(include_missing)
        if per_club and only_club is not None:
            data = {c: rows for c, rows in data.items() if c == only_club}
        if not data:
            return "", []
        cols = self.club_columns()
        folder = os.path.join(base, f"{self.event_prefix()}_Resultate_{time.strftime('%H%M')}")
        os.makedirs(folder, exist_ok=True)
        files = []
        all_clubs = list(self.club_data(include_missing))
        groups = ([(c, {c: rows}) for c, rows in data.items()] if per_club else [("Alle_Vereine", data)])
        for fname, subset in groups:
            prefix = f"{all_clubs.index(fname) + 1:02d}_" if per_club and fname in all_clubs else ""
            path = os.path.join(folder, f"{prefix}{file_part(fname, 'Verein')}.{fmt}")
            if fmt == "xlsx":
                self._write_xlsx(path, cols, subset)
            elif fmt == "csv":
                self._write_csv(path, cols, subset)
            else:
                self._write_txt(path, cols, subset)
            files.append(path)
        return folder, files

    @staticmethod
    def _fsync_close(fh):
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass

    def _write_csv(self, path, cols, subset):
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(cols)
            for rows in subset.values():
                for row in rows:
                    w.writerow([f"{v:.2f}" if isinstance(v, float) else v for v in row])
            self._fsync_close(fh)

    def _write_txt(self, path, cols, subset):
        stamp = time.strftime("%d.%m.%Y %H:%M")
        paar = self.settings["wettkampf"] == "paar"
        with open(path, "w", encoding="utf-8-sig", newline="\r\n") as fh:
            event = self.event_label() or "SWV"
            for club, rows in subset.items():
                fh.write(f"{event}\n")
                fh.write(f"Resultate  |  Verein: {club}\n")
                fh.write(f"Stand {stamp}  (Rang provisorisch, Speaker-Auswertung)\n\n")
                fh.write(f"{'Kategorie':<12} {'Rang':>4} {'Nr':>5}  {'Name':<40} {'Zeit':>9} {'Straf':>5} "
                         f"{'Total':>9}  Status\n")
                fh.write("-" * 100 + "\n")
                for row in rows:
                    if paar:
                        name = " / ".join(x for x in (row[4], row[5]) if x)
                        rest = row[6:]
                    else:
                        name, rest = row[4], row[5:]
                    zeit, _zs, pen, total, _lauf, _quelle, status = rest
                    total_txt = fmt_secs(total) if isinstance(total, float) else ""
                    fh.write(f"{row[1][:12]:<12} {str(row[2]):>4} {row[3]:>5}  {name[:40]:<40} "
                             f"{zeit:>9} {pen if pen else '':>5} {total_txt:>9}  {status}\n")
                fh.write("\n\n")
            self._fsync_close(fh)

    def _write_xlsx(self, path, cols, subset):
        if openpyxl is None:
            sheets, used = [], set()
            for club, rows in subset.items():
                title = re.sub(r"[\[\]:*?/\\]", "_", club)[:31] or "Verein"
                base, n = title, 2
                while title.casefold() in used:
                    suffix = f" ({n})"
                    title = base[:31 - len(suffix)] + suffix
                    n += 1
                used.add(title.casefold())
                sheets.append((title, [cols] + rows))
            tmp = path + ".tmp"
            write_xlsx_builtin(tmp, sheets, self.settings["event"]["name"].strip() or "SWV Resultate",
                               self.event_label(), ("Gefahrene Zeit (s)", "Total (s)"))
            with open(tmp, "rb+") as fh:
                self._fsync_close(fh)
            os.replace(tmp, path)
            return
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        used = set()
        for club, rows in subset.items():
            title = re.sub(r"[\[\]:*?/\\]", "_", club)[:31] or "Verein"
            base, n = title, 2
            while title.casefold() in used:
                suffix = f" ({n})"
                title = base[:31 - len(suffix)] + suffix
                n += 1
            used.add(title.casefold())
            ws = wb.create_sheet(title)
            ws.append(cols)
            for cell in ws[1]:
                cell.font = XlFont(bold=True)
            for row in rows:
                ws.append(row)
            for idx, col in enumerate(cols, start=1):
                letter = get_column_letter(idx)
                width = max(len(str(col)), *(len(str(r[idx - 1])) for r in rows)) if rows else len(col)
                ws.column_dimensions[letter].width = min(45, width + 2)
                if col in ("Gefahrene Zeit (s)", "Total (s)"):
                    for c in ws[letter][1:]:
                        c.number_format = "0.00"
            ws.freeze_panes = "A2"
        wb.properties.title = self.settings["event"]["name"].strip() or "SWV Resultate"
        wb.properties.subject = self.event_label()
        wb.properties.creator = "SWV Live-Ranking"
        tmp = path + ".tmp"
        wb.save(tmp)
        with open(tmp, "rb+") as fh:
            self._fsync_close(fh)
        os.replace(tmp, path)

    def report_missing_modules(self):
        mods = (("pyserial", serial is not None, "Verbindung zum CP 545"),)
        frozen = getattr(sys, "frozen", False)
        try:
            stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(
                os.path.getmtime(sys.executable if frozen else os.path.abspath(__file__))))
        except OSError:
            stamp = "unbekannt"
        available = ", ".join([mod for mod, ok, _u in mods if ok] +
                              [mod for mod, mo in (("xlrd", xlrd), ("openpyxl", openpyxl)) if mo is not None]) or "keine"
        self.log(f"Version {APP_VERSION}, {'gebaut' if frozen else 'Skript vom'} {stamp}, "
                 f"Python {sys.version.split()[0]}, Module: {available}. "
                 "Excel-Startlisten, Excel-Export und QR-Code funktionieren auch ohne Zusatzmodule.", tag="ok")
        missing = [(mod, use) for mod, ok, use in mods if not ok]
        for mod, use in missing:
            self.log(f"Modul {mod} fehlt: {use} nicht verfügbar. build.bat neu ausführen.", tag="warn")

    # ================================================================== #
    # Persistenz
    # ================================================================== #
    def save_autosave(self):
        data = {
            "version": 2,
            "results": {str(k): v for k, v in self.results.items()},
            "startlist": {"order": self.start_order, "source": self.startlist_source,
                          "participants": {str(k): v for k, v in self.participants.items()}},
        }
        try:
            tmp = os.path.join(self.data_path, AUTOSAVE_FILE + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.data_path, AUTOSAVE_FILE))
        except OSError as exc:
            self.log(f"Autosave fehlgeschlagen: {exc}", tag="error")

    def load_autosave(self):
        path = os.path.join(self.data_path, AUTOSAVE_FILE)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if "version" not in data:
                data = {"results": data, "startlist": {}}
            results = {}
            for k, v in data.get("results", {}).items():
                results[int(k)] = {
                    "secs": float(v["secs"]), "str": str(v["str"]), "ts": float(v.get("ts", 0)),
                    "source": str(v.get("source", "")), "run": int(v.get("run", 1)),
                    "prev": v.get("prev") if isinstance(v.get("prev"), dict) else None,
                    "status": v.get("status", ST_OPEN),
                }
            sl = data.get("startlist") or {}
            parts = {int(k): v for k, v in (sl.get("participants") or {}).items()}
            order = [int(n) for n in sl.get("order", []) if int(n) in parts]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return
        if not results and not order:
            return
        text = f"{len(results)} Resultate" + (f" und eine Startliste mit {len(order)} Starts" if order else "")
        if messagebox.askyesno("Gespeicherte Sitzung", f"{text} aus der letzten Sitzung gefunden.\nWiederherstellen?"):
            self.results = results
            self.participants, self.start_order = parts, order
            self.startlist_source = str(sl.get("source", ""))
            self.rebuild_order_index()
            self.update_startlist_label()
            self._rank_cache = None
            self.update_rankings(initial=True)
            self.on_data_changed(save=False)
            self.log(f"Wiederhergestellt: {text}", tag="ok")
        else:
            self.save_autosave()

    def reset_results(self):
        if not self.results:
            return
        if not self.confirm_danger("Resultate zurücksetzen",
                                   f"Alle {len(self.results)} Resultate wirklich löschen?\n\n"
                                   "Vorher exportieren! Die Startliste bleibt erhalten.", "Alle löschen"):
            return
        self.results.clear()
        self.blink.clear()
        self.ticker.clear()
        self.current_nr = None
        self.live_time, self.live_secs, self.live_final = None, None, False
        self.ziel_nr = None
        self.last_club, self.last_block = None, None
        self._rank_cache = None
        self.update_rankings(initial=True)
        self.on_data_changed()
        self.log("Resultate zurückgesetzt", tag="warn")

    def on_close(self):
        self.stop_reconnect()
        if self.reader is not None:
            self.reader.stop()
        self.web.stop()
        self.save_autosave()
        self.save_settings()
        self.root.destroy()


def main():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    LiveRankingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
