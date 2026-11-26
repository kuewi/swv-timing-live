#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SWV Live-Ranking / Speakerbildschirm
TAG Heuer Chronoprinter CP 545, Anzeigetafel-Protokoll HL970 / HL980

Abhaengigkeiten : Python 3.9+, pyserial
Optional        : xlrd (Startliste .xls), openpyxl (Startliste .xlsx, Export .xlsx),
                  qrcode + pypng (QR-Code fuer Browser-Anzeige)
Build (.exe)    : build.bat  (PyInstaller --onefile --windowed)

Verbindung zum CP 545:
  RS232   Anzeigetafel-Ausgang HL970/HL980, nur auswerten (siehe unten)
  Ethernet THCOM08 ueber TCP (Port 13500): Zeiten TN/T-/T*/TC, Resultate RR, Steuerung mit
           #WP 026 (naechste Start-/Zielnummer) und #WC 013 (Zeit umbuchen oder stornieren).
           Die Netzwerkkarte wird auf 192.168.1.55/24 gestellt und beim Beenden auf DHCP zurueck.

Protokoll RS232 (ASCII, STX ... LF):
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
import logging
import logging.handlers
import os
import queue
import re
import secrets
import socket
import ssl
import string
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.parse
import urllib.request
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import filedialog, ttk
from tkinter import messagebox as _tkmsg

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
APP_VERSION = "1.22.0"
ORANGE = "#D9730D"   # Update geladen, wartet auf Installation
APP_NAME = "SWV Live-Ranking"
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

# Farben im Apple-Stil. Dunkel: Flaechen mit weisser Schrift leicht abgedunkelt (Kontrast >= 4.6:1).
# Hell: Textfarben abgedunkelt, damit sie auf weissem Grund mindestens 4.5:1 erreichen.
# WHITE ist immer weiss (Schrift auf farbigen Balken und Knoepfen), TEXT ist die normale Schriftfarbe.
WHITE = "#ffffff"
PALETTES = {
    "dark": {
        "BG": "#000000", "PANEL": "#1c1c1e", "PANEL2": "#2c2c2e", "BUTTON": "#3a3a3c", "BUTTON_FG": "#ffffff",
        "BORDER": "#38383a", "TEXT": "#ffffff", "MUTED": "#98989d", "BLUE": "#0872dd", "ACCENT": "#0a84ff",
        "GREEN": "#1e8538", "GREEN_TEXT": "#30d158", "GOLD": "#ffd60a", "RED": "#ff453a", "ORANGE": "#ff9f0a",
        "LIGHT_YELLOW": "#fff3c4", "DARK_RED": "#d63930", "LIST_BG": "#2c2c2e", "LIST_FG": "#ffffff",
        "SEG_BG": "#2c2c2e", "SEG_ACTIVE": "#636366", "SEG_TEXT": "#c7c7cc", "SEG_TEXT_ACTIVE": "#ffffff",
        "SWITCH_OFF": "#39393d", "SWITCH_ON": "#30d158", "DISABLED_FG": "#6e6e73", "LOG_TEST": "#64748b",
        "CHECK_SEL": "#0872dd", "CHECK_SEL_FG": "#ffffff", "CAPTION": 0x00000000, "CAPTION_TEXT": 0x00FFFFFF,
    },
    "light": {
        "BG": "#f2f2f7", "PANEL": "#ffffff", "PANEL2": "#eeeef0", "BUTTON": "#e5e5ea", "BUTTON_FG": "#000000",
        "BORDER": "#d1d1d6", "TEXT": "#000000", "MUTED": "#5c5c60", "BLUE": "#0872dd", "ACCENT": "#0062c4",
        "GREEN": "#1e8538", "GREEN_TEXT": "#18752f", "GOLD": "#8a5d00", "RED": "#c9001a", "ORANGE": "#b34a00",
        "LIGHT_YELLOW": "#fff3c4", "DARK_RED": "#d63930", "LIST_BG": "#ffffff", "LIST_FG": "#000000",
        "SEG_BG": "#e3e3e8", "SEG_ACTIVE": "#ffffff", "SEG_TEXT": "#3a3a3c", "SEG_TEXT_ACTIVE": "#000000",
        "SWITCH_OFF": "#d1d1d6", "SWITCH_ON": "#28a745", "DISABLED_FG": "#8e8e93", "LOG_TEST": "#6b7280",
        "CHECK_SEL": "#bcd8ff", "CHECK_SEL_FG": "#000000", "CAPTION": None, "CAPTION_TEXT": None,
    },
}
THEME = "dark"


def apply_palette(name):
    """Farbsatz setzen. Die Oberflaeche muss danach neu aufgebaut werden."""
    global THEME, INPUT_BG, INPUT_FG
    THEME = name if name in PALETTES else "dark"
    globals().update(PALETTES[THEME])
    INPUT_BG, INPUT_FG = PANEL2, TEXT


apply_palette("dark")


def set_titlebar(win):
    """Windows 10/11: Titelleiste passend zum Farbsatz (dunkel: schwarz mit weisser Schrift)."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1 if THEME == "dark" else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 2004+ / aeltere Win10)
            if dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(dark), ctypes.sizeof(dark)) == 0:
                break
        for attr, val in ((35, CAPTION), (36, CAPTION_TEXT), (34, CAPTION)):  # Win11: Farbe Titel / Schrift / Rand
            v = ctypes.c_uint(0xFFFFFFFF if val is None else val)
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # Rahmen neu zeichnen
    except Exception:
        pass


class _Messages:
    """Ersetzt tkinter.messagebox: eigene Meldungsfenster im Farbsatz der App, links ueber der Seitenleiste."""
    app = None

    def _call(self, kind, title, message, **kw):
        if self.app is None:
            fn = {"info": _tkmsg.showinfo, "warning": _tkmsg.showwarning, "error": _tkmsg.showerror,
                  "ask": _tkmsg.askyesno}[kind]
            return fn(title, message, **kw)
        return self.app.message_dialog(kind, title, message, **kw)

    def showinfo(self, title, message, **kw):
        return self._call("info", title, message, **kw)

    def showwarning(self, title, message, **kw):
        return self._call("warning", title, message, **kw)

    def showerror(self, title, message, **kw):
        return self._call("error", title, message, **kw)

    def askyesno(self, title, message, **kw):
        return bool(self._call("ask", title, message, **kw))


messagebox = _Messages()


class LoggedMenu(tk.Menu):
    """Kontextmenue, das jede gewaehlte Aktion ins Diagnose-Log schreibt."""

    def add_command(self, cnf=None, **kw):
        cmd, label = kw.get("command"), kw.get("label", "")
        if cmd is not None:
            def run(c=cmd, lab=label):
                DIAG.info(f"UI Menü: {lab}")
                return c()
            kw["command"] = run
        return super().add_command(cnf or {}, **kw)


def widget_desc(w):
    """Kurzbeschreibung eines Widgets fuers Log: Klasse und sichtbarer Text."""
    try:
        if isinstance(w, str):
            return w
        text = ""
        if hasattr(w, "_o"):
            text = w._o.get("text", "")
        else:
            try:
                text = w.cget("text")
            except (tk.TclError, AttributeError):
                text = ""
        name = w.winfo_class()
        return f"{name} «{str(text)[:40]}»" if text else f"{name} {str(w)[-40:]}"
    except Exception:
        return "?"

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
    "collapsed": {"zeitmessung": True, "wettkampf": False, "verbindung": False, "speaker": False, "daten": False,
                  "kategorien": True, "online": True, "web": True, "startliste": False, "manuell": False},
    "event": {"name": "", "von": "", "bis": ""},
    "online": {
        "mode": "offline", "url": "", "comp_id": "", "token": "",
        "send_mode": "confirm", "auto_startlist": True,
    },
    "web": {"bind": "", "port": 8080, "key": ""},
    "export_dir": "",
    "theme": "dark",
    "sidebar_pinned": True,
    "ui_size": "auto",      # Groesse der Oberflaeche: "auto" (nach Bildschirm) oder Faktor "0.9", "1.0", "1.1"
    "nav_layout": "top",    # "top": Menueleiste oben mit Ausklappfeldern (Standard), "side": Seitenleiste
    "cats_auto": True,
    "timing": {"prell_start_ms": 300, "prell_finish_ms": 300, "min_run_s": 0, "lock_start": False,
               "lock_finish": False, "ch_start": 1, "ch_finish": 4, "print_club": True, "prec_digits": 1,
               "lock_nr": 9999},
    "conn": {"mode": "rs232", "device": "cp545", "cp_ip": "", "cp_ip_b": "", "backup_mode": "", "backup_wait_s": 3.0,
             "adapter": "",
             "usb_port": "", "usb_baud": 9600, "usb_ack": False},
    "net_restore": {"pending": False, "adapter": ""},
    "updates": {"check": True, "last_check": 0, "declined": "", "declined_at": 0, "ready_path": "", "ready_tag": "",
                "install_on_exit": False},
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
ICON_FILES = (os.path.join("assets", "swv_icon_256.png"), "swv_logo.png", "logo.png", "image_928d28.png")
ICON_ICO = os.path.join("assets", "swv_logo.ico")
LOGO_SIZES = (32, 44, 60, 80)   # assets/swv_logo_h<Hoehe>.png


def resource_file(name):
    for d in resource_dirs():
        path = os.path.join(d, name)
        if os.path.isfile(path):
            return path
    return None

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


DATA_FOLDER_NAME = "SWV Live-Ranking"
LOG_DIR = "logs"
REPORT_DIR = "fehlerberichte"


UPDATE_API = "https://api.github.com/repos/kuewi/swv-timing-live/releases/latest"
UPDATE_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
                "api.github.com")


_SSL_CTX = []


def _ssl_contexts():
    """Zertifikatspruefung fuer GitHub: zuerst die von Windows (truststore, laedt fehlende Stammzertifikate wie
    der Browser nach), dann Python mit den Zertifikaten aus certifi. Pruefung wird nie abgeschaltet."""
    if not _SSL_CTX:
        try:
            import truststore
            _SSL_CTX.append(("windows", truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)))
        except Exception:
            pass
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
            name = "python+certifi"
        except Exception:
            name = "python"
        _SSL_CTX.append((name, ctx))
    return list(_SSL_CTX)


def _is_cert_error(exc):
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc)


def _urlopen(req, timeout):
    """urlopen mit dem ersten Zertifikatspruefer, der klappt."""
    last = None
    for name, ctx in _ssl_contexts():
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except Exception as exc:
            if not _is_cert_error(exc):
                raise
            last = exc
            DIAG.info(f"Zertifikat mit {name} nicht prüfbar: {exc}")
    raise last


CP_PRINT_WIDTH = 24  # Zeichen pro Zeile am CP-Drucker (Annahme, am Geraet pruefen)


def cp_print_text(club, count):
    """Zeile fuer den CP-Drucker: nur ASCII, Umlaute umschreiben, auf Druckbreite kuerzen."""
    t = str(club)
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss"),
                 ("é", "e"), ("è", "e"), ("à", "a"), ("ç", "c")):
        t = t.replace(a, b)
    t = "".join(ch for ch in t if 32 <= ord(ch) < 127 and ch not in "#\t").strip()
    tail = f" ({count})"
    room = CP_PRINT_WIDTH - 2 - len(tail)
    if len(t) > room:
        t = t[:max(1, room)].rstrip()
    return f"> {t}{tail}"


def parse_version(text):
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:4]) if nums else ()


def _https_allowed(url):
    u = urllib.parse.urlparse(url)
    return u.scheme == "https" and (u.hostname or "").lower() in UPDATE_HOSTS


def fetch_latest_release(url=UPDATE_API, timeout=8):
    """Neuestes Release von GitHub: {'version','tag','body','html_url','setup','setup_url','sums_url'}."""
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"SWV-Live-Ranking/{APP_VERSION}"})
    with _urlopen(req, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assets = {a.get("name", ""): a.get("browser_download_url", "") for a in data.get("assets", [])}
    setup = next((n for n in assets if n.startswith("SWV_LiveRanking_Setup_") and n.endswith(".exe")), None)
    return {"version": parse_version(data.get("tag_name")), "tag": data.get("tag_name", ""),
            "body": data.get("body") or "", "html_url": data.get("html_url", ""), "setup": setup,
            "setup_url": assets.get(setup, "") if setup else "", "sums_url": assets.get("SHA256SUMS.txt", "")}


def download_file(url, path, progress=None, timeout=30):
    if not _https_allowed(url):
        raise ValueError(f"Download nur von GitHub über HTTPS erlaubt: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": f"SWV-Live-Ranking/{APP_VERSION}"})
    h = hashlib.sha256()
    with _urlopen(req, timeout) as resp, open(path + ".part", "wb") as fh:
        if not _https_allowed(resp.geturl()):
            raise ValueError(f"Umleitung auf fremden Server: {resp.geturl()}")
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            fh.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    os.replace(path + ".part", path)
    return h.hexdigest()


def fetch_text(url, timeout=10):
    if not _https_allowed(url):
        raise ValueError(f"nur GitHub über HTTPS erlaubt: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": f"SWV-Live-Ranking/{APP_VERSION}"})
    with _urlopen(req, timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


DOC_API = "https://api.github.com/repos/kuewi/swv-timing-live/contents/docs/handbuch"
DOC_PAGE = "https://github.com/kuewi/swv-timing-live/blob/main/docs/handbuch/README.md"
DOC_HOSTS = UPDATE_HOSTS + ("raw.githubusercontent.com",)


def fetch_doc_list(timeout=8):
    """PDF im Ordner docs/handbuch auf GitHub: {Dateiname: Download-Adresse}. Nur lesen, ohne Anmeldung."""
    req = urllib.request.Request(DOC_API, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"SWV-Live-Ranking/{APP_VERSION}"})
    with _urlopen(req, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = {}
    for item in data if isinstance(data, list) else []:
        name, url = item.get("name", ""), item.get("download_url") or ""
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if name.lower().endswith(".pdf") and url.startswith("https://") and host in DOC_HOSTS:
            out[name] = url
    return out


def pick_doc(names, kind):
    """Neuestes PDF einer Art (Benutzerhandbuch, Training) nach Versionsnummer im Namen."""
    cands = [n for n in names if n.startswith(f"SWV_Live-Ranking_{kind}")]
    return max(cands, key=lambda n: parse_version(re.search(r"_v([0-9.]+)\.pdf$", n).group(1))
               if re.search(r"_v([0-9.]+)\.pdf$", n) else (0,), default=None)


def documents_dir():
    """Ordner «Dokumente» des Benutzers, auch wenn er auf OneDrive umgeleitet ist."""
    if IS_WINDOWS:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def legacy_data_dirs():
    """Fruehere Ablageorte: neben der .exe und %APPDATA%\\SWV_LiveRanking."""
    out = []
    if getattr(sys, "frozen", False):
        out.append(os.path.dirname(sys.executable))
    out.append(os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SWV_LiveRanking"))
    return out


def migrate_data(target):
    """Beim ersten Start im neuen Datenordner: Einstellungen, Kategorien, Autosave, Rohdaten und PDFs
    aus einem frueheren Ablageort kopieren (die alten Dateien bleiben liegen)."""
    import shutil
    if os.path.exists(os.path.join(target, SETTINGS_FILE)):
        return None
    for old in legacy_data_dirs():
        if os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(target)):
            continue
        if not os.path.exists(os.path.join(old, SETTINGS_FILE)):
            continue
        for name in (SETTINGS_FILE, CATEGORIES_FILE, AUTOSAVE_FILE):
            src = os.path.join(old, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(target, name))
        for sub in (RAW_DIR, "pdf"):
            src = os.path.join(old, sub)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(target, sub), dirs_exist_ok=True)
        return old
    return None


def data_dir():
    """Installierte App: Dokumente\\SWV Live-Ranking. Beim Entwickeln: Ordner des Skripts."""
    if getattr(sys, "frozen", False):
        base = os.path.join(documents_dir(), DATA_FOLDER_NAME)
        try:
            os.makedirs(base, exist_ok=True)
            return base
        except OSError:
            pass
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SWV_LiveRanking")
        os.makedirs(base, exist_ok=True)
        return base
    base = os.path.dirname(os.path.abspath(__file__))
    if os.access(base, os.W_OK):
        return base
    fallback = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SWV_LiveRanking")
    os.makedirs(fallback, exist_ok=True)
    return fallback


# --------------------------------------------------------------------------- #
# Diagnose-Log (Datei, rotierend) fuer Fehlersuche
# --------------------------------------------------------------------------- #
DIAG = logging.getLogger("swv")
DIAG.setLevel(logging.DEBUG)
DIAG.propagate = False


def setup_diag(folder):
    """Rotierendes Log: 10 Dateien zu je 5 MB in <Datenordner>/logs."""
    for h in list(DIAG.handlers):
        DIAG.removeHandler(h)
        h.close()
    path = os.path.join(folder, LOG_DIR)
    try:
        os.makedirs(path, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(os.path.join(path, "swv_live_ranking.log"),
                                                 maxBytes=5 * 1024 * 1024, backupCount=9, encoding="utf-8")
    except OSError:
        return None
    h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)-7s [%(threadName)s] %(message)s",
                                     "%Y-%m-%d %H:%M:%S"))
    DIAG.addHandler(h)
    return path


def is_secret_key(key):
    return any(w in key.lower() for w in ("token", "key", "pass", "secret"))


def flatten_settings(d, prefix=""):
    for k, v in d.items():
        name = f"{prefix}{k}"
        if isinstance(v, dict):
            yield from flatten_settings(v, name + ".")
        else:
            yield name, (json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v)


def redact_settings(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = redact_settings(v)
        else:
            out[k] = "***" if (is_secret_key(k) and v) else v
    return out


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
        if not self.fit:
            return
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
        self._o = {"text": text, "command": command, "bg": bg or BUTTON,
                   "fg": fg or (BUTTON_FG if (bg or BUTTON) == BUTTON else WHITE), "state": "normal",
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
            fill, fg = mix(bg, BG, 0.55), DISABLED_FG
        else:
            tone = "#000000" if THEME == "light" and bg == BUTTON else WHITE
            fill = mix(bg, tone, 0.18) if self._down else (mix(bg, tone, 0.09) if self._hover else bg)
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

    def __init__(self, parent, command=None, scale=1.0, on=False, on_color=None):
        self.on_color = on_color
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

    def blink(self, phase):
        """Eingeschaltet rot blinken (Start/Ziel gesperrt)."""
        if self.on:
            self._blink = phase
            self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.w, self.h
        track = (self.on_color or SWITCH_ON) if self.on else SWITCH_OFF
        if self.on and getattr(self, "_blink", None) is not None:
            track = RED if self._blink else "#5c1a16"
        round_rect(self, 0, 0, w, h, h / 2, fill=track, outline=track)
        m = 2
        d = h - 2 * m
        x = w - m - d if self.on else m
        self.create_oval(x, m, x + d, m + d, fill=WHITE, outline=WHITE)


class _CableToggle:
    """Netzwerkkabel an der Rueckseite im Trainingsfenster: Lämpchen an der Buchse."""

    def __init__(self, canvas):
        self.cv, self.on = canvas, True

    def set(self, on):
        self.on = bool(on)
        try:
            self.cv.itemconfigure("ethled", fill="#3DDC5A" if self.on else "#3A3A3A")
        except tk.TclError:
            pass

    def winfo_exists(self):
        try:
            return bool(self.cv.winfo_exists())
        except tk.TclError:
            return False


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
        round_rect(self, 0, 0, w, h, 9, fill=SEG_BG, outline=SEG_BG)
        seg = w / len(self.options)
        for i, (value, label) in enumerate(self.options):
            x1, x2 = i * seg, (i + 1) * seg
            active = self.var.get() == value
            if active:
                round_rect(self, x1 + self.pad, self.pad, x2 - self.pad, h - self.pad, 7, fill=SEG_ACTIVE,
                           outline=SEG_ACTIVE)
            self.create_text((x1 + x2) / 2, h / 2, text=label, fill=SEG_TEXT_ACTIVE if active else SEG_TEXT,
                             font=self.font)


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


RESULT_DEC = 2   # Nachkommastellen der Resultate (Einstellung Praezision, 0-3)
PREC_LABEL = {0: "1 s", 1: "1/10 s", 2: "1/100 s", 3: "1/1000 s", 4: "1/10000 s", 5: "1/100000 s"}


def fmt_secs(secs, decimals=None):
    if decimals is None:
        decimals = RESULT_DEC
    total = round(secs, decimals)
    m = int(total // 60)
    s = total - m * 60
    if m:
        return f"{m}:{s:0{3 + decimals}.{decimals}f}"
    return f"{s:.{decimals}f}"


def fmt_tod(tod):
    h, rest = divmod(tod, 3600)
    m, sec = divmod(rest, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:05.2f}"


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
    ("bestaetigt", "Bestätigt (Onlinetool)"),
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
    "bestaetigt": ["bestaetigt", "bestätigt", "confirmed", "bestaetigung"],
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
        if get("bestaetigt").strip().lower() in ("1", "x", "ja", "yes", "true", "✓", "wahr"):
            parts[nr]["best_online"] = True  # vom Onlinetool bestaetigt (blauer Haken)
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


TEST_RANGE = (951, 999)


def derive_category_ranges(order, parts):
    """Nummernbereiche pro Kategorie aus der Startliste: ([(kat, von, bis, anzahl)], [warnungen]).
    Bereich von der vollen Hundert unter der kleinsten bis ..99 ueber der groessten Nummer
    (Senioren 200-244 -> 200-299, 300-480 -> 300-499). Ab 900 endet der Bereich bei 950,
    951-999 bleiben fuer Testnummern frei. Ueberschneiden sich zwei Bereiche, gelten fuer beide
    die exakte kleinste und groesste Nummer."""
    from collections import Counter
    by_key, spell = {}, {}
    for nr in order:
        cat = (parts.get(nr) or {}).get("kategorie", "").strip()  # Testnummern ohne Teilnehmerdaten
        if cat:
            # «JUNGFAHRER» und «Jungfahrer» sind dieselbe Kategorie: Schreibweise der Mehrheit gilt
            by_key.setdefault(cat.casefold(), []).append(nr)
            spell.setdefault(cat.casefold(), Counter())[cat] += 1
    groups = {spell[k].most_common(1)[0][0]: nrs for k, nrs in by_key.items()}
    ranges, warnings = {}, []
    for cat, nrs in groups.items():
        lo, hi = min(nrs), max(nrs)
        r_lo, r_hi = max(1, lo // 100 * 100), hi // 100 * 100 + 99
        if r_hi >= 900:
            r_hi = TEST_RANGE[0] - 1
        r_lo = min(r_lo, r_hi)
        ranges[cat] = [r_lo, r_hi]
        high = sorted(n for n in nrs if n >= TEST_RANGE[0])
        if high:
            warnings.append(f"{cat}: Nr {', '.join(map(str, high[:8]))}{' ...' if len(high) > 8 else ''} liegt im "
                            f"Testbereich {TEST_RANGE[0]}-{TEST_RANGE[1]}. Die Kategorie endet bei {r_hi}, "
                            "die Startliste ordnet diese Nummern trotzdem richtig zu.")
    names = list(ranges)
    exact = set()
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ra, rb = ranges[a], ranges[b]
            if ra[0] <= rb[1] and rb[0] <= ra[1]:
                exact |= {a, b}
    for cat in exact:
        ranges[cat] = [min(groups[cat]), max(groups[cat])]
    if exact:
        warnings.append("Bereiche überschneiden sich, deshalb exakte Grenzen für: " + ", ".join(sorted(exact)))
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ra, rb = ranges[a], ranges[b]
                if ra[0] <= rb[1] and rb[0] <= ra[1]:
                    warnings.append(f"{a} ({ra[0]}-{ra[1]}) und {b} ({rb[0]}-{rb[1]}) überschneiden sich "
                                    "auch mit exakten Grenzen. Startnummern sind gemischt, die Startliste "
                                    "ordnet die Teilnehmer trotzdem richtig zu.")
    return [(cat, ranges[cat][0], ranges[cat][1], len(groups[cat])) for cat in names], warnings


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
<div id="wrap"><main id="cats"></main><div id="side"><aside id="note" hidden></aside><aside id="next" hidden></aside><aside id="ticker" hidden></aside></div></div>
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
#side{width:320px;display:flex;flex-direction:column;gap:10px}#note{border:2px solid #ffd60a}
.tk{font-size:17px;margin:0 0 6px}.tk.new{font-weight:700}.tk .t{color:#98989d;font-size:13px;margin-right:6px}
.tk.warn{color:#ffd60a}.tk.ziel{color:#30d158}.tk.test{color:#98989d}
body.light .tk.warn{color:#8a5d00}body.light .tk.ziel{color:#1e8538}
aside{width:auto}h2{margin:0 0 8px;font-size:15px;font-weight:600;color:#98989d;letter-spacing:.02em}
.row{font-size:22px;font-weight:700;display:flex;gap:10px;align-items:baseline}.row.first{color:#ffd60a;font-size:26px}
.pen{color:#ff9f0a;font-size:15px}.who{color:#98989d;font-size:14px;margin:0 0 6px}.empty{color:#98989d;font-size:18px}
footer{padding:6px 14px 12px;font-size:12px;color:#98989d}footer.err{color:#ff453a}
@media(max-width:700px){header{grid-template-columns:1fr}#wrap{flex-direction:column}#side{width:auto}}
body.light{background:#f2f2f7;color:#000}body.light .card,body.light aside{background:#fff}
body.light h2,body.light .who,body.light .empty,body.light footer{color:#5c5c60}
body.light .row.first{color:#8a5d00}body.light .pen{color:#b34a00}body.light footer.err{color:#c9001a}
"""

WEB_JS = r"""
(function(){
  var key=document.body.getAttribute('data-key'), last='', lastOk=0, lastTry=0, busy=false;
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
  function clear(n){while(n.firstChild)n.removeChild(n.firstChild);}
  function lines(box,arr){clear(box);(arr||[]).forEach(function(t,i){if(t)box.appendChild(el('div',i===0?'big':'sub',t));});}
  function render(d){
    document.body.className=d.theme==='light'?'light':'';
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
    var no=document.getElementById('note');clear(no);
    if(d.note&&d.note.length){no.hidden=false;no.appendChild(el('h2',null,'Notiz'));
      d.note.forEach(function(t,i){no.appendChild(el('div',i===0?'row':'tk',t));});}
    else no.hidden=true;
    var tk=document.getElementById('ticker');clear(tk);
    if(d.ticker){tk.hidden=false;tk.appendChild(el('h2',null,'Ereignis-Ticker'));
      if(!d.ticker.length)tk.appendChild(el('div','empty','Noch keine Ereignisse'));
      d.ticker.forEach(function(e,i){var r=el('div','tk'+(e.tag?' '+e.tag:'')+(i===0?' new':''));
        r.appendChild(el('span','t',e.t));r.appendChild(document.createTextNode(e.text));tk.appendChild(r);});}
    else tk.hidden=true;
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
  // WebSocket: Daten kommen sofort; faellt er aus, Abfrage jede Sekunde wie bisher
  var ws=null, wsOk=false, polling=false;
  function startPolling(){if(!polling){polling=true;tick();}}
  function connectWs(){
    if(!window.WebSocket){startPolling();return;}
    try{ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws?key='+encodeURIComponent(key));}
    catch(e){startPolling();return;}
    ws.onmessage=function(ev){
      try{var t=ev.data,d=JSON.parse(t);wsOk=true;lastOk=Date.now();lastTry=Date.now();
        if(t!==last){last=t;render(d);}document.getElementById('state').textContent='Live verbunden, Stand '+d.time;}catch(e){}
    };
    ws.onclose=function(){wsOk=false;startPolling();setTimeout(connectWs,10000);};
    ws.onerror=function(){try{ws.close();}catch(e){}};
  }
  var tick0=tick; tick=function(){if(wsOk){polling=false;busy=false;return;}tick0();};
  // Notbremse: falls die Abfrageschleife trotzdem stehen bleibt, neu starten
  setInterval(function(){if(wsOk){state();return;}if(busy&&Date.now()-lastTry>8000){busy=false;tick();}else if(!busy&&Date.now()-lastTry>15000){tick();}state();},2000);
  connectWs();
  setTimeout(function(){if(!wsOk)startPolling();},1500);
})();
"""


API_DOC = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8"><title>SWV Live-Ranking API</title>
<link rel="stylesheet" href="/app.css?key=__KEY__"></head><body><main style="padding:24px;max-width:900px">
<h1>SWV Live-Ranking API</h1>
<p>Nur lesen, nur im lokalen Netz, jede Abfrage braucht <code>?key=…</code>. Antworten im JSON-Format (UTF-8).</p>
<table>
<tr><td><code>GET /api/v1/live</code></td><td>laufendes Boot, Laufzeit, letzter Zieleinlauf, Wettkampf</td></tr>
<tr><td><code>GET /api/v1/results</code></td><td>Ranglisten pro Kategorie mit Rang, Zeit, Strafpunkten, nicht klassiert (DNS, DNF, DSQ)</td></tr>
<tr><td><code>GET /api/v1/course</code></td><td>Boote auf der Fahrstrecke mit Startzeit und Laufzeit</td></tr>
<tr><td><code>GET /api/v1/startlist</code></td><td>nächste Starter in Startreihenfolge</td></tr>
<tr><td><code>GET /api/v1/events</code></td><td>die letzten 30 Ereignisse des Tickers</td></tr>
<tr><td><code>WS /ws</code></td><td>WebSocket: bei jeder Änderung der Stand der Browser-Anzeige.
Mit <code>&amp;stream=all</code> zusätzlich live, results, course, startlist und events in einer Nachricht.</td></tr>
</table></main></body></html>"""


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
        elif parts.path == "/ws":
            return self._websocket(urllib.parse.parse_qs(parts.query).get("stream", ["display"])[0], host)
        elif parts.path in ("/api", "/api/"):
            ctype, data = "text/html; charset=utf-8", API_DOC.replace("__KEY__", lan.key).encode("utf-8")
        elif parts.path.startswith("/api/v1/") and parts.path[8:] in lan.api:
            ctype, data = "application/json; charset=utf-8", lan.api[parts.path[8:]]
        else:
            return self._deny(404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if parts.path.startswith("/api/v1/"):
            self.send_header("Access-Control-Allow-Origin", "*")  # nur lesen, Schluessel noetig
        self.send_header("Content-Security-Policy",
                         f"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self' ws://{host}; "
                         "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        if send_body:
            self.wfile.write(data)

    def _websocket(self, stream, host):
        """WebSocket (RFC 6455), nur Server -> Browser: schickt bei jeder Aenderung den aktuellen Stand."""
        import base64
        import hashlib
        lan = self.server.lan
        ws_key = self.headers.get("Sec-WebSocket-Key", "")
        origin = (self.headers.get("Origin") or "").lower()
        if (self.headers.get("Upgrade", "").lower() != "websocket" or not ws_key
                or (origin and urllib.parse.urlsplit(origin).netloc not in lan.allowed_hosts)):
            return self._deny(400 if not origin else 403)
        with lan.cond:
            if lan.ws_count >= 20:
                return self._deny(503)
            lan.ws_count += 1
        try:
            accept = base64.b64encode(hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
                                                   .encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.wfile.flush()
            sock = self.connection
            sock.settimeout(0.2)
            sent = -1
            last_ping = time.time()
            while lan.running:
                with lan.cond:
                    if lan.version == sent:
                        lan.cond.wait(1.0)
                    version = lan.version
                    payload = lan.snapshot if stream != "all" else lan.bundle
                if version != sent:
                    self._ws_send(sock, payload, 0x1)
                    sent = version
                if time.time() - last_ping > 20:
                    self._ws_send(sock, b"", 0x9)
                    last_ping = time.time()
                try:
                    head = sock.recv(2)
                except socket.timeout:
                    continue
                if not head or (head[0] & 0x0F) == 0x8:
                    break  # Browser hat geschlossen
                ln = head[1] & 0x7F
                if ln == 126:
                    ln = int.from_bytes(sock.recv(2), "big")
                elif ln == 127:
                    ln = int.from_bytes(sock.recv(8), "big")
                if ln > 4096:
                    break
                sock.recv(4 + ln if head[1] & 0x80 else ln)  # Daten vom Browser werden ignoriert
        except OSError:
            pass
        finally:
            with lan.cond:
                lan.ws_count -= 1
            self.close_connection = True

    @staticmethod
    def _ws_send(sock, data, opcode):
        n = len(data)
        head = bytes([0x80 | opcode]) + (bytes([n]) if n < 126 else bytes([126]) + n.to_bytes(2, "big")
                                          if n < 65536 else bytes([127]) + n.to_bytes(8, "big"))
        sock.sendall(head + data)


class LanServer:
    """Nur lesender Webserver: GET auf 4 feste Pfade, Schluessel, nur private Adressen."""

    def __init__(self):
        self.httpd = None
        self.key = ""
        self.allowed_hosts = set()
        self.snapshot = b"{}"
        self.bundle = b"{}"
        self.api = {}
        self.version = 0
        self.ws_count = 0
        self.cond = threading.Condition()
        self.url = ""

    def publish(self, snapshot, api):
        """Neuer Stand fuer Browser-Anzeige, API und WebSocket."""
        with self.cond:
            changed = snapshot != self.snapshot or api != self.api
            self.snapshot, self.api = snapshot, api
            if changed:
                self.bundle = b'{"display":' + snapshot + b"," + b",".join(
                    b'"' + k.encode() + b'":' + v for k, v in api.items()) + b"}"
                self.version += 1
                self.cond.notify_all()

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
            with self.cond:
                self.cond.notify_all()
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
# Ethernet: TAG Heuer Protokoll THCOM08 (CP 540 / CP 545)
# --------------------------------------------------------------------------- #
PC_IP = "192.168.1.55"
PC_MASK = "255.255.255.0"
CP_NET = "192.168.1."
CP_FIRST, CP_LAST = 50, 59
CP_SCAN_PORT = 7000       # bis 4 Verbindungen, fuer die Suche (#SN)
CP_DATA_PORT = 13500      # 1 Verbindung, Daten bleiben bei Abbruch gepuffert
CH_START, CH_FINISH = 1, 4  # Net Time: Start Eingang 1, Ziel Eingang 4
LOCK_POLL_S = 5.0  # CP 545: Sperrzustand der Eingaenge so oft abfragen
CMD_TIMEOUT = 1.6
HEARTBEAT_S = 15
HEARTBEAT_LOST_S = 30
SERIAL_SILENCE_S = 5        # RS232: so lange ohne Laufzeit waehrend eines Laufs = Abbruch

# Zeitfeld: HH:MM:SS.FFFFF, nach Synchronisation auf 00:00 auch M:SS.FFFFF oder S.FFFFF (ohne fuehrende Teile)
_RE_TIME = re.compile(r"^([TA][N\-\*\+=C]|TI)\s+(\d*)\s+(\d+)\s+(M?)(\d+)\s+"
                      r"(?:(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2}(?:\.\d+)?)|(?:(?P<m2>\d{1,2}):)?(?P<s2>\d{1,2}\.\d+))"
                      r"(?:\s+(?P<day>-?\d+))?(?=\s|$)")
_RE_NOTE = re.compile(r"^(IR|DR|VE)\s")
_RE_TC_NOSEQ = re.compile(r"^TC\s+M?\d{1,2}\s+\d{1,2}:\d{2}:\d{2}")  # TM550: gesperrter Kontakt ohne Zaehlnummer
NOTE_LABEL = {"IR": "Zwischenzeit", "DR": "Differenz Parallelstart", "VE": "Geschwindigkeit"}
_RE_DS = re.compile(r"^DS\s+(\d+)(?:\s+\d+\s+(.*))?")
_RE_DE = re.compile(r"^DE\s+(\d+)")
RAW_DIR = "rohdaten"
EPOCH_2000 = datetime.date(2000, 1, 1)
_RE_RR = re.compile(r"^(RR|GR)\s+(\d+)\s+(\d+)\s+([\d:.]+)(?:\s+-?\d+)?\s*$")  # skiFFS haengt einen Tag an
_RE_OP = re.compile(r"^OP\s+(\d+)(?:\s+T?\s*\d+(?=\s|$))?\s*(.*)$")  # CP: «OP 01  00  NET TIME», TM550: «OP 02 TIMING»
_RE_CL = re.compile(r"^CL\s+(\d+)")
_RE_AK = re.compile(r"^AK\s*([CFR])")
_RE_PAR = re.compile(r"^&P\s*(\d{3})\s*(.*)$")
_RE_SN = re.compile(r"^SN\s+(\d+)\s+(\S+)\s*(\S*)")
_RE_SYN = re.compile(r"^!T\s+(\d{1,2}):(\d{2}):(\d{2})")


def strip_frame(raw):
    """THCOM08-Rahmen: STX entfernen, CR/LF und eine angehaengte Pruefsumme (TAB + 4 Hex) abschneiden."""
    t = raw.replace("\x02", "").rstrip("\r\n")
    if "\t" in t:
        t = t.split("\t", 1)[0]
    return t.strip()


def parse_thcom(raw):
    """Eine Zeile des CP 545 (Ethernet) -> dict mit 'kind' oder None."""
    t = strip_frame(raw)
    if not t:
        return None
    m = _RE_TIME.match(t)
    if m:
        if m.group("h") is not None:
            h, mi, sec = int(m.group("h")), int(m.group("m")), float(m.group("s"))
        else:
            h, mi, sec = 0, int(m.group("m2") or 0), float(m.group("s2"))
        tod = h * 3600 + mi * 60 + sec
        day = int(m.group("day")) if m.group("day") else None
        if day is not None and day < 0:
            # Status statt Zeit (z.B. skiFFS: 00:00:00.00000 -0003 = DNF), kein Impuls
            return {"kind": "note", "label": f"Statuszeile (Code {day})", "text": t}
        if day is None:  # ohne Tagesangabe: heute
            day = (datetime.date.today() - EPOCH_2000).days
        return {"kind": "time", "type": m.group(1), "nr": int(m.group(2) or 0), "seq": int(m.group(3)),
                "manual": bool(m.group(4)), "ch": int(m.group(5)), "tod": tod, "day": day,
                "abs": day * 86400 + tod, "answer": m.group(1).startswith("A"), "text": t}
    m = _RE_DS.match(t)
    if m:
        return {"kind": "dlstart", "run": int(m.group(1)), "mode": (m.group(2) or "").strip()}
    m = _RE_DE.match(t)
    if m:
        return {"kind": "dlend", "run": int(m.group(1))}
    m = _RE_RR.match(t)
    if m:
        secs = parse_time(m.group(4))
        if secs is None:
            return None
        return {"kind": "result", "type": m.group(1), "rank": int(m.group(2)), "nr": int(m.group(3)), "secs": secs}
    m = _RE_AK.match(t)
    if m:
        return {"kind": "ack", "code": m.group(1)}
    if _RE_TC_NOSEQ.match(t):
        return {"kind": "note", "label": "gesperrter Kontakt ohne Zuordnung", "text": t}
    m = _RE_NOTE.match(t)
    if m:
        return {"kind": "note", "label": NOTE_LABEL[m.group(1)], "text": t}
    m = _RE_PAR.match(t)
    if m:
        return {"kind": "param", "id": m.group(1), "values": m.group(2).split()}
    m = _RE_OP.match(t)
    if m:
        return {"kind": "open", "run": int(m.group(1)), "mode": m.group(2).strip()}
    m = _RE_CL.match(t)
    if m:
        return {"kind": "close", "run": int(m.group(1))}
    m = _RE_SN.match(t)
    if m:
        return {"kind": "serial", "serial": m.group(1), "type": m.group(2), "version": m.group(3)}
    m = _RE_SYN.match(t)
    if m:
        return {"kind": "sync", "tod": int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))}
    return {"kind": "other", "text": t}


def parse_manual_startlist(text, max_range=500):
    """Von Hand eingegebene Startliste -> ([(nr, [Name 1, Name 2, Verein, Kategorie])], Warnungen).
    Zeilen mit Tab oder Semikolon: erste Zelle Nummer, dann Angaben. Sonst Nummern und Bereiche «a-b»."""
    items, warn, seen = [], [], set()

    def add(nr, fields=()):
        if nr <= 0 or nr > 9999:
            warn.append(f"Nr {nr} ungültig")
        elif nr in seen:
            warn.append(f"Nr {nr} doppelt")
        else:
            seen.add(nr)
            items.append((nr, [f.strip() for f in fields]))

    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line or ";" in line:
            cells = [c.strip() for c in re.split(r"[\t;]", line)]
            if cells and cells[0].isdigit():
                add(int(cells[0]), [c for c in cells[1:]])
                continue
            if cells and not any(c.isdigit() for c in cells[0]):
                continue  # Kopfzeile aus Excel
        line = re.sub(r"\s*[-–]\s*", "-", line)
        for tok in re.split(r"[,\s]+", line):
            if not tok:
                continue
            mm = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", tok)
            if mm:
                a, b = int(mm.group(1)), int(mm.group(2))
                if b < a or b - a + 1 > max_range:
                    warn.append(f"Bereich {tok} {'rückwärts' if b < a else 'zu gross'}")
                    continue
                for n in range(a, b + 1):
                    add(n)
            elif tok.isdigit():
                add(int(tok))
            else:
                warn.append(f"«{tok}» ist keine Nummer")
    return items, warn


def mode_label(mode):
    """TM550 meldet LAP als «CIRCUIT»."""
    m = " ".join((mode or "").split())
    return "LAP (CIRCUIT)" if m.upper() == "CIRCUIT" else m


def mode_numbers(device, mode):
    """Nimmt das Geraet in dieser Zeitmessart vorgeladene Startnummern an? 'yes' | 'no' | 'unknown' | 'maybe'
    (Zeitmessart noch nicht bekannt). CP 545 laut Handbuch: Nummern in allen Arten ausser PTB SEQ; getestet
    NET TIME (ja) und PTB SEQ (nein). TM550 1.48: TIMING ja; BASIC AK F; SPEED und LAP ohne Wirkung."""
    m = (mode or "").upper().replace(" ", "")
    if not m:
        return "maybe"
    if device == "tm550":
        if m == "TIMING":
            return "yes"
        if m in ("BASIC", "SPEED", "CIRCUIT", "LAP"):
            return "no"
        return "unknown"
    if "PTB" in m:
        return "no"
    if m.startswith("NETTIME") or m in ("START-FINISH", "START-INTER-FINISH", "TRAINING"):
        return "yes"
    return "unknown"


def trunc_secs(value, digits):
    """Wie der CP 545: auf die eingestellte Praezision abschneiden, nicht runden."""
    f = 10 ** max(0, digits)
    return int(value * f + 1e-6) / f


def local_tod():
    lt = time.localtime()
    return lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec + (time.time() % 1)


def day_from_pc(tod):
    """Tag fuer eine Uhrzeit des Geraets aus dem PC-Datum: liegt die Uhrzeit mehr als 12 h vor bzw. nach der
    PC-Uhrzeit, gehoert sie zum Vortag bzw. Folgetag (Mitternacht)."""
    now = local_abs()
    day, pc_tod = divmod(now, 86400)
    if tod - pc_tod > 43200:
        day -= 1
    elif pc_tod - tod > 43200:
        day += 1
    return int(day)


def local_abs():
    """Lokale Zeit in Sekunden ab 01.01.2000 wie die Zeiten des CP (laeuft ueber Mitternacht weiter)."""
    now = time.time()
    lt = time.localtime(now)
    day = (datetime.date(lt.tm_year, lt.tm_mon, lt.tm_mday) - EPOCH_2000).days
    return day * 86400 + lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec + (now % 1)


def apply_channels(timing):
    """Start- und Zieleingang aus den Einstellungen (Standard 1 und 4), Nachkommastellen der Resultate."""
    global CH_START, CH_FINISH, RESULT_DEC
    try:
        RESULT_DEC = max(0, min(3, int(timing.get("prec_digits", 1))))
    except (TypeError, ValueError):
        RESULT_DEC = 2
    try:
        a, b = int(timing.get("ch_start", 1)), int(timing.get("ch_finish", 4))
    except (TypeError, ValueError):
        return
    if a in (1, 2, 3, 4) and b in (1, 2, 3, 4) and a != b:
        CH_START, CH_FINISH = a, b


def cp_hosts():
    """Adressen fuer die CP-Suche. SWV_CP_HOSTS (z.B. '127.0.0.1') nur fuer Tests."""
    env = os.environ.get("SWV_CP_HOSTS", "").strip()
    if env:
        return [h.strip() for h in env.split(",") if h.strip()]
    # CP 545 ab .50, TM550 empfohlen .20 (Werkseinstellung ITS .101)
    return [f"{CP_NET}{i}" for i in list(range(CP_FIRST, CP_LAST + 1)) + [20, 101]]


def cp_ports():
    env = os.environ.get("SWV_CP_PORTS", "").strip()
    if env:
        a, b = env.split(",")
        return int(a), int(b)
    return CP_SCAN_PORT, CP_DATA_PORT


TM_ALT_PORT = 2101   # TM550: Werkseinstellung ITS (Port 2101), Stefans Geraet 7000


def split_hostport(text, port):
    """«192.168.1.51:2101» -> ('192.168.1.51', 2101); ohne Port der angegebene."""
    text = (text or "").strip()
    if text.count(":") == 1:
        h, p = text.split(":")
        if p.isdigit():
            return h, int(p)
    return text, port


def probe_cp(host, port, timeout=0.6):
    """Ein CP auf host? Antwort auf #SN als Text, sonst None. host darf «ip:port» sein."""
    host, port = split_hostport(host, port)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sk:
            sk.settimeout(0.5)
            sk.sendall(b"#SN\r\n")
            buf, end, cs_sent = b"", time.time() + 4.0, False
            while time.time() < end:
                if not cs_sent and time.time() > end - 3.0:
                    # TM550 beantwortet Befehle nur mit Pruefsumme
                    sk.sendall(b"#SN\t" + thcom_cs16(b"#SN").encode() + b"\r\n")
                    cs_sent = True
                try:
                    chunk = sk.recv(512)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                for line in buf.split(b"\n"):
                    info = parse_thcom(split_serial_frame(line.decode("latin-1", "replace"))[0])
                    if info and info["kind"] == "serial":
                        return f"{info['type']} Nr {info['serial']}" + (f" {info['version']}" if info["version"] else "")
            return "CP (ohne Kennung)" if buf else "CP"
    except OSError:
        return None


def scan_cps(hosts=None, port=None):
    """[(ip, kennung)] aller erreichbaren CPs, parallel abgefragt."""
    hosts = hosts or cp_hosts()
    port = port or cp_ports()[0]
    found, lock = [], threading.Lock()

    def one(h):
        info = probe_cp(h, port)
        DIAG.debug(f"Suche {h}:{port}: {info or 'keine Antwort'}")
        if not info and port != TM_ALT_PORT and not os.environ.get("SWV_CP_HOSTS"):
            info = probe_cp(h, TM_ALT_PORT)   # TM550 mit Werkseinstellung Port 2101
            if info:
                h = f"{h}:{TM_ALT_PORT}"
        if info:
            with lock:
                found.append((h, info))

    threads = [threading.Thread(target=one, args=(h,), daemon=True) for h in hosts]
    for t in threads:
        t.start()
    for t in threads:
        t.join(4)
    return sorted(found, key=lambda x: tuple(int(p) if p.isdigit() else 0
                                             for p in x[0].split(":")[0].split(".")))


class CPClient(threading.Thread):
    """TCP-Verbindung zum CP 545 (THCOM08). Liest Zeilen, sendet Befehle, verbindet bei Abbruch neu."""

    def __init__(self, host, port, out_queue):
        super().__init__(daemon=True)
        self.host, self.port, self.q = host, port, out_queue
        self.stop_event = threading.Event()
        self.reconnect_event = threading.Event()
        self.out = queue.Queue()
        self.connected = False
        self.link = "eth"

    def send(self, text):
        data = text.rstrip("\r\n").encode("latin-1", "replace")
        if getattr(self, "checksum", False):  # TM550: Befehle nur mit Pruefsumme
            data += b"\t" + thcom_cs16(data).encode("ascii")
        self.out.put(data + b"\r\n")

    def stop(self):
        self.stop_event.set()

    def force_reconnect(self):
        self.reconnect_event.set()

    def run(self):
        first = True
        while not self.stop_event.is_set():
            try:
                sk = socket.create_connection((self.host, self.port), timeout=3)
            except OSError as exc:
                self.q.put(("eth_open_error" if first else "eth_retry", exc, self))
                first = False
                if self.stop_event.wait(2):
                    break
                continue
            first = False
            try:
                sk.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError:
                pass
            sk.settimeout(0.15)
            while not self.out.empty():  # alte Befehle nicht nachsenden
                self.out.get_nowait()
            self.connected = True
            self.reconnect_event.clear()
            self.q.put(("eth_connected", self.host, self))
            buf = bytearray()
            err = None
            try:
                while not self.stop_event.is_set() and not self.reconnect_event.is_set():
                    while not self.out.empty():
                        sk.sendall(self.out.get_nowait())
                    try:
                        chunk = sk.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        err = ConnectionError("Verbindung vom CP geschlossen")
                        break
                    buf.extend(chunk)
                    while True:
                        idx = buf.find(b"\n")
                        if idx < 0:
                            break
                        line = bytes(buf[:idx]).decode("latin-1", errors="replace")
                        del buf[: idx + 1]
                        if line.strip():
                            self.q.put(("eth_line", line, self))
                    if len(buf) > 8192:
                        buf.clear()
            except OSError as exc:
                err = exc
            if self.reconnect_event.is_set() and err is None:
                err = TimeoutError("keine Antwort vom CP")
            self.connected = False
            try:
                if self.stop_event.is_set():
                    sk.shutdown(socket.SHUT_RDWR)  # sauber trennen: CP leert seinen Puffer
                sk.close()  # bei Abbruch nicht sauber trennen: CP behaelt ungelesene Daten
            except OSError:
                pass
            if self.stop_event.is_set():
                break
            self.q.put(("eth_lost", err, self))
            if self.stop_event.wait(2):
                break
        self.q.put(("eth_disconnected", self.host, self))


def thcom_cs16(data):
    """THCOM08 RS232: Summe aller Bytes der Daten ohne '#', 4 Hex-Ziffern."""
    return f"{sum(b for b in data if b != 0x23) & 0xFFFF:04X}"


def split_serial_frame(raw):
    """RS232/USB-Zeile: STX entfernen, [Daten] TAB CS16 pruefen. -> (daten, ok)."""
    raw = raw.rstrip("\r")
    stx = raw.rfind("\x02")
    if stx >= 0:
        raw = raw[stx + 1:]
    if "\t" not in raw:
        return raw, True
    data, cs = raw.rsplit("\t", 1)
    cs = cs.strip()
    if not cs:
        return data, True
    if not re.fullmatch(r"[0-9A-Fa-f]{4}", cs):
        return data, False
    return data, thcom_cs16(data.encode("latin-1", "replace")) == cs.upper()


class CPSerialClient(CPClient):
    """CP 545 direkt per USB (virtueller COM-Port) oder RS232: gleiche Befehle wie ueber Ethernet,
    Rahmen mit TAB und Pruefsumme. Findet den Port nach dem Ausstecken wieder (auch mit neuer COM-Nummer)."""

    def __init__(self, device, baud, out_queue, identity=None, ack=False):
        super().__init__(device, None, out_queue)
        self.baud, self.identity, self.ack = baud, identity, ack
        self.link = "usb"

    def send(self, text):
        data = text.rstrip("\r\n").encode("latin-1", "replace")
        self.out.put(data + b"\t" + thcom_cs16(data).encode("ascii") + b"\r\n")

    def run(self):
        first = True
        while not self.stop_event.is_set():
            dev = find_port(self.host, self.identity) or self.host
            try:
                ser = serial.serial_for_url(dev, baudrate=self.baud, bytesize=serial.EIGHTBITS,
                                            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                            timeout=0.1, write_timeout=1)
            except Exception as exc:
                self.q.put(("eth_open_error" if first else "eth_retry", exc, self))
                first = False
                if self.stop_event.wait(2):
                    break
                continue
            first = False
            try:
                ser.dtr = True   # TM550 (FTDI) sendet nur mit DTR/RTS
                ser.rts = True
            except Exception:
                pass
            self.host = dev
            if self.identity is None:
                self.identity = port_identity(dev)
            while not self.out.empty():
                self.out.get_nowait()
            self.connected = True
            self.reconnect_event.clear()
            self.q.put(("eth_connected", dev, self))
            buf = bytearray()
            err = None
            try:
                while not self.stop_event.is_set() and not self.reconnect_event.is_set():
                    while not self.out.empty():
                        ser.write(self.out.get_nowait())
                    chunk = ser.read(ser.in_waiting or 1)
                    if not chunk:
                        continue
                    buf.extend(chunk)
                    while True:
                        idx = buf.find(b"\n")
                        if idx < 0:
                            break
                        raw = bytes(buf[:idx]).decode("latin-1", errors="replace")
                        del buf[: idx + 1]
                        if self.ack:
                            ser.write(b"\x06")  # Flow Ctrl: CP sendet erst nach ACK weiter
                        line, ok = split_serial_frame(raw)
                        if not ok:
                            self.q.put(("eth_bad", raw, self))
                        elif line.strip():
                            self.q.put(("eth_line", line, self))
                    if len(buf) > 8192:
                        buf.clear()
            except Exception as exc:
                err = exc
            if self.reconnect_event.is_set() and err is None:
                err = TimeoutError("keine Antwort vom CP")
            self.connected = False
            try:
                ser.close()
            except Exception:
                pass
            if self.stop_event.is_set():
                break
            self.q.put(("eth_lost", err, self))
            if self.stop_event.wait(2):
                break
        self.q.put(("eth_disconnected", self.host, self))


# --------------------------------------------------------------------------- #
# Eingebauter Simulator eines CP 545 (THCOM08 ueber TCP auf 127.0.0.1)
# --------------------------------------------------------------------------- #
class SimCP:
    """Verhaelt sich wie der CP 545 in den Tests von Stefan: #WP 026 setzt die naechste Start- bzw.
    Zielnummer, #WC 013 wird mit AK R abgelehnt, #RT und #DL liefern gespeicherte Zeiten."""

    def __init__(self, port=0, rs232=False, device="cp545", timing=True, bounce=False, clock_offset=0.0, fw=None):
        # device «tm550»: Verhalten wie Stefans TM550 (FW 1.18): Befehle nur mit Pruefsumme, Zeilen immer mit
        # Pruefsumme, keine Nummern, #WP/#RP 026 -> AK F, #RT -> «T?» + AK C + AK C, #DL nur mit offenem Lauf
        # (timing=True), kein Puffer, gesperrte Zielkontakte als TC (bounce=True)
        self.device, self.timing, self.bounce = device, timing, bounce
        self.clock_offset = clock_offset  # Uhr des Geraets gegenueber dem PC (s), z.B. TM550 -281
        # Firmware: TM550 «1.18» (Standard der Tests) oder «1.48»; CP 545 «VB08»/«VB16» verhalten sich gleich.
        # TM550 1.48 (Test 23.11.2026): Zeitmessarten BASIC/TIMING/SPEED/CIRCUIT, #WP 026 in TIMING, Nummern
        # mit Nullen («0150»), IR-Zeile im Ziel, Doppelkontakt als eigene TN-Zeile, Tagesfeld stimmt.
        self.fw = fw or ("1.18" if device == "tm550" else "VB16")
        self.new_tm = device == "tm550" and self.fw >= "1.4"
        self.tm_mode = "TIMING" if timing else "BASIC"
        self.prec = 3            # Nachkommastellen in den Zeilen (CP 545: #RP 001 meldet diesen Wert)
        self.day_shift = -29 if device == "tm550" and not self.new_tm else 0  # TM550 1.18: Tagesfeld falsch
        self.offline = False      # Kabel gezogen
        self.eth_off = False      # CP neu gestartet: Ethernet am Geraet noch nicht eingeschaltet
        self.run_open = True
        self.mode = "NET TIME"    # CP: Zeitmessart; nur NET TIME mit Lauf nimmt Startnummern an
        self.startlist = []
        self.on_line = None       # jede gesendete Zeitzeile (Papierstreifen)
        self.on_event = None      # Rueckmeldung fuer das Trainingsfenster: on_event(text)
        self.blocked = []         # TM550: gesperrte Kontakte (Eingang, Seq, Zeit)
        self.rs232 = rs232 or device == "tm550"   # Rahmen [Daten] TAB CS16
        self.pending = []         # wie der CP: ohne Verbindung puffern, beim Verbinden zuerst senden
        self.lock = threading.RLock()
        self.clients = []
        self.next = {CH_START: 0 if self.new_tm else 1, CH_FINISH: None}
        self.seq = {CH_START: 0, CH_FINISH: 0}
        self.course = []          # [(nr, abs, seq)]
        self.recs = {}            # (ch, seq) -> [typ, nr, abs]
        self.results = []
        self.run = 1
        self.drop_next = False
        # Eingaenge (Gruppe P/Q, 25.11.2026). CP 545 Parameter 006: 1 offen, 0 gesperrt; in NET TIME E2/E3 0.
        # TM550 006/023: 0 offen (gruen, Pfeil nach oben), 1 senden (rot, Pfeil nach unten), 2 gesperrt (rot).
        self.inputs = {1: 0, 2: 2, 3: 2, 4: 0} if device == "tm550" else {1: 1, 2: 0, 3: 0, 4: 1}
        # Sperrzeit 004 wie im Gerätetest P: CP 1/100 s (E1 1.00, sonst 0.10), TM550 1/1000 s (0.100)
        self.block = {k: 100 for k in range(1, 5)} if device == "tm550" else {1: 100, 2: 10, 3: 10, 4: 10}
        self.cmds = []  # empfangene Befehle (Tests)
        self.manual = None        # Impuls von der Taste am Geraet (M1..M4) statt von der Buchse
        self.err_msgs = True      # CP: Einstellungen › Error Messages EIN druckt Socket-Fehler
        self.gps_sync = False     # TM550: WAIT GPS bis zur Synchronisation
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.alive = True
        threading.Thread(target=self._accept, daemon=True).start()

    def now_abs(self):
        return local_abs() + self.clock_offset

    def fmt(self, typ, nr, seq, ch, abs_t):
        day, tod = divmod(abs_t, 86400)
        h, r = divmod(tod, 3600)
        m, sec = divmod(r, 60)
        sec = trunc_secs(sec, self.prec)
        if self.device == "tm550":
            day += self.day_shift  # TM550 1.18: Tagesfeld weicht vom Datum ab
            nrs = f"{nr:04d}" if nr else "    "  # 1.48 mit Nummer: «TN 0150    2 01»
            chs = f"M{ch}" if self.manual else f"{ch:02d}"  # Taste am Geraet: M1 (Test 25.11.2026)
            return f"{typ} {nrs} {seq:4d} {chs} {int(h):2d}:{int(m):02d}:{sec:08.5f} {int(day):5d}"
        nrs = f"{nr:4d}" if nr else "    "  # CP ohne Nummer: Feld leer
        chs = f" {ch}" if self.manual is False else f"M{ch}"  # Buchse ohne M (Test 25.11.2026)
        return f"{typ} {nrs} {seq:4d} {chs} {int(h):02d}:{int(m):02d}:{sec:08.5f} {int(day):5d}"

    def _accept(self):
        while self.alive:
            try:
                c, _a = self.sock.accept()
            except OSError:
                return
            if self.offline or self.eth_off:  # Kabel gezogen / Ethernet am CP aus: keine Verbindung moeglich
                try:
                    c.close()
                except OSError:
                    pass
                continue
            with self.lock:
                pending, self.pending = self.pending, []
            for line in pending:
                self.send(line, c)
            self.clients.append(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def send(self, line, c=None):
        if c is None and getattr(self, "on_line", None):
            self.on_line(line)  # Papierstreifen im Trainingsfenster
        if c is None and self.drop_next and not line.startswith(("AK", "&P", "SN", "!T")):
            self.drop_next = False
            return  # simuliert eine verlorene Zeile
        if c is None and not self.clients:
            if self.device != "tm550":   # der TM550 puffert nicht
                with self.lock:
                    self.pending.append(line)
            return
        data = line.encode("latin-1")
        if self.rs232:
            data += b"\t" + thcom_cs16(data).encode("ascii")
        for cl in ([c] if c else list(self.clients)):
            try:
                cl.sendall(data + b"\r\n")
            except OSError:
                pass

    def _serve(self, c):
        buf = b""
        while self.alive:
            try:
                d = c.recv(1024)
            except OSError:
                break
            if not d:
                break
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("latin-1")
                if self.rs232:
                    if self.device == "tm550" and "\t" not in text:
                        continue  # TM550: Befehle ohne Pruefsumme bleiben unbeantwortet
                    text, ok = split_serial_frame(text)
                    if not ok:
                        self.send("AK F", c)
                        continue
                try:
                    self._cmd(text.strip(), c)
                except Exception:
                    self.send("AK F", c)
        if c in self.clients:
            self.clients.remove(c)

    def _cmd(self, t, c):
        p = t.split()
        if not p:
            return
        self.cmds = (self.cmds + [t])[-400:]
        if p[:2] in (["#RP", "004"], ["#WP", "004"]) and len(p) >= 3:
            k = int(p[2])
            if p[0] == "#WP" and len(p) >= 4:
                self.block[k] = max(0, min(9999, int(p[3])))
                self.send("AK C", c)
            else:
                self.send(f"&P 004 {k:02d} {self.block.get(k, 0):04d}", c)
                self.send("AK C", c)
            return
        if self.device == "tm550":
            return self._cmd_tm550(t, p, c)
        if t == "#SN":
            self.send("SN 00000 CP545 SIMULATOR", c)
        elif t == "#!T":
            tod = self.now_abs() % 86400
            self.send(f"!T {int(tod // 3600):02d}:{int(tod % 3600 // 60):02d}:{int(tod % 60):02d} "
                      f"{time.strftime('%d/%m/%y')}", c)
        elif p[:2] == ["#RP", "001"]:
            self.send(f"&P 001 {self.prec}", c)
        elif p[:2] == ["#WP", "001"] and len(p) >= 3:
            self.prec = max(1, min(5, int(p[2]) + 1))  # CP 545: n -> Zeiten n+1, Resultat n Stellen
        elif p[:2] == ["#RP", "003"]:
            self.send(f"&P 003 {self.run if self.run_open else 0:02d} {self.run + 1:02d}", c)
        elif t.startswith("#WC 001"):
            self.close_run()
        elif t.startswith("#WC 002"):
            if self.run_open or "PTB" not in self.mode:  # VB08/VB16: oeffnet nur in PTB SEQUENTIEL 1-4
                self.send("AK F", c)
                return
            self.open_run()
        elif t.startswith("#WC 012"):
            self.send("AK R", c)
            return
        elif p[0] == "#PL":
            self.note("Druck: " + t[3:].strip())
            if self.on_line:
                self.on_line("PL " + t[3:].strip())
        elif p[0] == "#SLR":
            self.startlist = []
        elif p[0] == "#SLA" and len(p) >= 2:
            self.startlist.append(int(p[1]))
        elif p[0] == "#SLC":
            self.open_run()  # CP 545 oeffnete dabei einen neuen Lauf (Test 22.11.2026)
        elif p[:2] == ["#RP", "026"]:
            ch = int(p[2])
            val = 0 if (self.run_open and "NET" not in self.mode) else (self.next.get(ch) or 0)
            self.send(f"&P 026 {ch:02d} {val:04d}", c)
        elif p[:2] == ["#WP", "026"] and len(p) >= 4:
            if not self.run_open:
                self.send("AK F", c)  # ohne Lauf abgelehnt
                return
            if int(p[2]) == CH_FINISH and int(p[3]) not in (999, 9999) and not any(x[0] == int(p[3]) for x in self.course):
                self.send("AK F", c)  # Annahme: Boot ist fuer den CP nicht auf der Strecke (noch nicht getestet)
                return
            if "NET" in self.mode:
                self.next[int(p[2])] = int(p[3])  # andere Zeitmessart: AK C, aber ohne Wirkung
        elif p[0] == "#RT" and len(p) >= 3:
            r = self.recs.get((int(p[2]), int(p[1])))
            if r:
                self.send(self.fmt("A" + r[0][1], r[1], int(p[1]), int(p[2]), r[2]), c)
        elif p[0] == "#DL":
            self.send(f"DS {self.run:02d}  00  {self.mode}", c)
            for (ch, seq), r in sorted(self.recs.items(), key=lambda x: x[1][2]):
                self.send(self.fmt("A" + r[0][1], r[1], seq, ch, r[2]), c)
            self.send(f"DE {self.run:02d}", c)
        elif t.startswith("#WC 013") or p[0] == "#EE":
            self.send("AK R", c)
            return
        elif p[:2] == ["#RP", "006"] and len(p) >= 3:
            k = int(p[2])
            self.send(f"&P 006 {k:02d} {self.inputs.get(k, 0)}", c)
        elif p[:2] == ["#WP", "006"] and len(p) >= 4:
            self.set_input(int(p[2]), 0 if int(p[3]) == 0 else 1)  # 2 gilt am CP als offen
        elif p[:2] == ["#RP", "023"]:
            self.send("&P 023 0 0 0 0", c)
        elif p[:2] == ["#WP", "023"]:
            self.send("AK F", c)
            return
        elif t.startswith("#"):
            pass
        else:
            return
        self.send("AK C", c)

    def _tm_inputs_cmd(self, p, c):
        """TM550: Eingaenge lesen/schreiben (006 pro Eingang, 023 alle vier), #EE abgelehnt. True = erledigt."""
        if p[0] == "#EE":
            self.send("AK F", c)
        elif p[:2] == ["#RP", "006"] and len(p) >= 3:
            k = int(p[2])
            self.send(f"&P 006 {k:02d} {self.inputs.get(k, 0)}", c)
            self.send("AK C", c)
        elif p[:2] == ["#WP", "006"] and len(p) >= 4:
            self.send("AK C", c)
            self.set_input(int(p[2]), max(0, min(2, int(p[3]))))
        elif p[:2] == ["#RP", "023"]:
            self.send(self.inputs_line(), c)
            self.send("AK C", c)
        elif p[:2] == ["#WP", "023"] and len(p) >= 6:
            self.send("AK C", c)
            for k in (1, 2, 3, 4):
                self.inputs[k] = max(0, min(2, int(p[1 + k])))
            self.send(self.inputs_line())
        else:
            return False
        return True

    def inputs_line(self):
        return "&P 023 " + " ".join(str(self.inputs[k]) for k in (1, 2, 3, 4))

    def input_locked(self, ch):
        if self.device == "tm550":
            return self.inputs.get(ch, 0) != 0  # gesperrt oder auf «senden»: auch die Taste loest nicht aus
        return self.inputs.get(ch, 1) == 0 and not self.manual  # CP: gruene Taste loest trotzdem aus

    def set_input(self, ch, value):
        self.inputs[ch] = value
        if self.device == "tm550":
            self.send(self.inputs_line())  # meldet jede Aenderung von selbst
            self.note(f"Eingang E{ch} " + ("offen", "senden", "gesperrt")[value])
        else:
            self.note(f"Eingang {ch} " + ("gesperrt" if value == 0 else "offen"))

    def cycle_input(self, ch):
        """Rote Sperrtaste am CP bzw. SHIFT + Ex am TM550."""
        if self.device == "tm550":
            self.set_input(ch, (self.inputs.get(ch, 0) + 1) % 3)
        else:
            self.set_input(ch, 1 if self.inputs.get(ch, 1) == 0 else 0)

    def _cmd_tm550(self, t, p, c):
        if self._tm_inputs_cmd(p, c):
            return
        if self.new_tm:
            return self._cmd_tm148(t, p, c)
        run = self.run if self.timing and self.run_open else 0
        if t == "#SN":
            self.send("SN 00059 TM550 1.18", c)
        elif t == "#ID":
            self.send("ID 00059", c)
        elif p[:2] == ["#RP", "003"]:
            self.send(f"&P 003 {run:02d} {self.run + 1:02d}", c)
        elif p[:2] in (["#RP", "026"], ["#WP", "026"], ["#RP", "001"]):
            self.send("AK F", c)
            return
        elif p[0] == "#RT":
            day = int(self.now_abs() // 86400)
            self.send(f"T?           00  0:00:00.00000 {day:5d}", c)
            self.send("AK C", c)
        elif t.startswith("#WC 001"):
            if self.run_open and self.timing:
                self.close_run()
        elif t.startswith("#WC 002"):
            if not self.timing:
                self.send("AK F", c)
                return
            if self.run_open:
                self.close_run()
            self.open_run(same=not self.recs)  # leerer Lauf behaelt seine Nummer (Test 22.11.2026)
        elif t.startswith("#WC 012"):
            self.send("DS 01", c)
            for (ch, seq), r in sorted(self.recs.items(), key=lambda x: x[1][2]):
                self.send(self.fmt("A" + r[0][1], 0, seq, ch, r[2]), c)
            self.send("DE 01", c)
            return  # ohne AK
        elif p[0] == "#PL":
            self.send("PL TO BE IMPLEMENTED", c)
            self.send("AK R", c)
            return
        elif p[0] in ("#SLR", "#SLA", "#SLC"):
            pass  # angenommen, ohne Wirkung bei NO IDENTIFICATION
        elif p[0] == "#!T":
            self.send("AK R", c)
            return
        elif p[0] == "#DL":
            self.send(f"DS {run:02d}", c)
            if run:
                rows = [(r[2], self.fmt("A" + r[0][1], 0, seq, ch, r[2])) for (ch, seq), r in self.recs.items()]
                rows += [(tb, self.fmt("AC", 0, seq, ch, tb)) for ch, seq, tb in self.blocked]
                for _t, line in sorted(rows):
                    self.send(line, c)
            self.send(f"DE {run:02d}", c)
        elif not t.startswith("#"):
            return
        self.send("AK C", c)

    def _cmd_tm148(self, t, p, c):
        """TM550 Firmware 1.48 nach dem Test vom 23.11.2026."""
        run = self.run if self.run_open else 0
        if t == "#SN":
            self.send(f"SN 00059 TM550 {self.fw}", c)
        elif t == "#ID":
            self.send("ID 00059", c)
        elif p[:2] == ["#RP", "003"]:
            self.send(f"&P 003 {run:02d} {self.run + 1:02d} 00:00:00     0", c)
        elif p[:2] == ["#RP", "001"]:
            self.send(f"&P 001 {self.prec}", c)
        elif p[:2] == ["#WP", "001"] and len(p) >= 3:
            self.prec = max(0, min(5, int(p[2])))
        elif p[:2] == ["#RP", "026"]:
            nxt = self.next.get(CH_START) or 0
            self.send(f"&P 026 01 {nxt:04d}" if nxt else "&P 026 00    0", c)
        elif p[:2] == ["#WP", "026"] and len(p) >= 4:
            if self.tm_mode == "BASIC":
                self.send("AK F", c)
                return
            self.next[CH_START] = int(p[3])  # SPEED/CIRCUIT: angenommen, ohne Wirkung
        elif p[0] == "#RT" and len(p) >= 3:
            r = self.recs.get((int(p[2]), int(p[1])))
            if r and self.tm_mode in ("BASIC", "TIMING"):
                self.send(self.fmt(r[0], r[1], int(p[1]), int(p[2]), r[2]), c)  # TM550 antwortet mit TN
        elif t.startswith("#WC 001"):
            if self.run_open:
                self.close_run()
        elif t.startswith("#WC 002"):
            if self.run_open:
                self.send("AK F", c)
                return
            self.open_run(same=not self.recs)
        elif t.startswith("#WC 012") or p[0] == "#DL":
            self.send(f"DS {max(run, 1):02d}", c)
            for (ch, seq), r in sorted(self.recs.items(), key=lambda x: x[1][2]):
                self.send(self.fmt("A" + r[0][1], r[1], seq, ch, r[2]), c)
            self.send(f"DE {max(run, 1):02d}", c)
            return  # ohne AK
        elif p[0] in ("#PL", "#!T"):
            self.send("AK F" if p[0] == "#PL" else "AK R", c)
            return
        elif p[0] in ("#SLR", "#SLA", "#SLC"):
            pass  # angenommen, ohne Wirkung
        elif p[:2] == ["#RP", "120"]:
            return  # keine Antwort
        elif not t.startswith("#"):
            return
        self.send("AK C", c)

    def _tm148_start(self):
        with self.lock:
            nr = (self.next.get(CH_START) or 0) if self.tm_mode == "TIMING" else 0
            self.next[CH_START] = 0  # verbraucht, der TM550 zaehlt nicht weiter
            self.seq[CH_START] += 1
            t = self.now_abs()
            self.recs[(CH_START, self.seq[CH_START])] = ["TN", nr, t]
            self.course.append((nr, t, self.seq[CH_START]))
            self.send(self.fmt("TN", nr, self.seq[CH_START], CH_START, t))
            return nr

    def _tm148_finish(self):
        with self.lock:
            t = self.now_abs()
            self.seq[CH_FINISH] += 1
            seq = self.seq[CH_FINISH]
            st = self.course.pop(0) if self.course else None
            nr = st[0] if st else 0
            self.recs[(CH_FINISH, seq)] = ["TN", nr, t]
            self.send(self.fmt("TN", nr, seq, CH_FINISH, t))
            if st:
                secs = trunc_secs(t - st[1], self.prec)
                h, r = divmod(secs, 3600)
                mi, sec = divmod(r, 60)
                self.send(f"IR 1    {nr:04d}    {int(h):02d}:{int(mi):02d}:{sec:08.5f}" if nr else
                          f"IR 1            {int(h):02d}:{int(mi):02d}:{sec:08.5f}")
            if self.bounce:  # 1.48: Doppelkontakt kommt als eigene Zeile ohne Nummer
                self.seq[CH_FINISH] += 1
                self.recs[(CH_FINISH, self.seq[CH_FINISH])] = ["TN", 0, t + 0.11]
                self.send(self.fmt("TN", 0, self.seq[CH_FINISH], CH_FINISH, t + 0.11))
            return nr or None

    def set_mode(self, mode):
        """Zeitmessart am Geraet umstellen (Trainingsfenster)."""
        if self.device == "tm550":
            self.tm_mode = mode
            self.timing = mode != "BASIC"
        else:
            self.mode = mode
        self.note(f"Zeitmessart {mode}")

    def false_start(self):
        """CP: E1 ohne Nummer = Nummer von der letzten Startzeit entfernen (Falschstart) -> TC."""
        with self.lock:
            if not self.course:
                self.note("Keine Startzeit auf der Strecke")
                return False
            nr, t, seq = self.course.pop()
            self.recs[(CH_START, seq)][0] = "TC"
            self.send(self.fmt("TC", nr, seq, CH_START, t))
            if nr and self.device == "cp545":
                self.next[CH_START] = nr  # die Nummer startet nochmals
        self.note(f"Falschstart: Startzeit Nr {nr} storniert")
        return True

    def numbered(self):
        """CP vergibt Startnummern nur in NET TIME mit offenem Lauf (Test 22.11.2026)."""
        return self.device == "cp545" and self.run_open and "NET" in self.mode

    def start(self):
        if self.new_tm:
            return self._tm148_start()
        if self.device == "tm550" or not self.numbered():
            with self.lock:
                self.seq[CH_START] += 1
                t = self.now_abs()
                self.recs[(CH_START, self.seq[CH_START])] = ["TN", 0, t]
                self.send(self.fmt("TN", 0, self.seq[CH_START], CH_START, t))
                return 0
        with self.lock:
            nr = self.next[CH_START]
            self.next[CH_START] = nr + 1
            self.seq[CH_START] += 1
            t = self.now_abs()
            self.recs[(CH_START, self.seq[CH_START])] = ["TN", nr, t]
            self.course.append((nr, t, self.seq[CH_START]))
            self.send(self.fmt("TN", nr, self.seq[CH_START], CH_START, t))
            return nr

    def finish(self):
        if self.new_tm:
            return self._tm148_finish()
        if self.device == "tm550" or not self.numbered():
            with self.lock:
                t = self.now_abs()
                self.seq[CH_FINISH] += 1
                seq = self.seq[CH_FINISH]
                self.recs[(CH_FINISH, seq)] = ["TN", 0, t]
                self.send(self.fmt("TN", 0, seq, CH_FINISH, t))
                if self.bounce and self.device == "tm550":  # zweiter Kontakt in der Sperrzeit
                    self.blocked.append((CH_FINISH, seq, t + 0.11))
                    self.send(self.fmt("TC", 0, seq, CH_FINISH, t + 0.11))
                return None
        with self.lock:
            t = self.now_abs()
            self.seq[CH_FINISH] += 1
            seq = self.seq[CH_FINISH]
            if not self.course:
                self.recs[(CH_FINISH, seq)] = ["TN", 0, t]
                self.send(self.fmt("TN", 0, seq, CH_FINISH, t))
                return None
            want = self.next[CH_FINISH]
            st = next((x for x in self.course if x[0] == want), self.course[0])
            self.next[CH_FINISH] = None
            self.course.remove(st)
            self.recs[(CH_FINISH, seq)] = ["TN", st[0], t]
            self.send(self.fmt("TN", st[0], seq, CH_FINISH, t))
            secs = trunc_secs(t - st[1], max(0, self.prec - 1))  # Resultat eine Stelle weniger als die Zeiten
            self.results.append((st[0], secs))
            rank = 1 + sum(1 for _n, s2 in self.results if s2 < secs)
            m, sec = divmod(secs, 60)
            self.send(f"RR {rank:4d} {st[0]:4d}        " + (f"{int(m)}:{sec:08.5f}" if m else f"{sec:.5f}"))
            return st[0]

    def replay_line(self, line):
        self.send(line)

    # ---------- Bedienung wie an der Tastatur (Trainingsfenster) ---------- #
    def note(self, text):
        if self.on_event:
            self.on_event(text)

    def impulse(self, ch, manual=None):
        """Impuls an Eingang ch. manual True: Taste am Geraet (CP gruen 1..4, TM550 E1..E4), False: Buchse."""
        prev, self.manual = self.manual, manual
        try:
            if self.input_locked(ch):
                self.note(f"Eingang {ch} gesperrt, kein Impuls")
                return
            self._impulse(ch)
        finally:
            self.manual = prev

    def _impulse(self, ch):
        if ch == CH_START:
            nr = self.start()
            self.note(f"Start Eingang {ch}" + (f" Nr {nr}" if nr else ""))
        elif ch == CH_FINISH:
            nr = self.finish()
            self.note(f"Ziel Eingang {ch}" + (f" Nr {nr}" if nr else ""))
        else:
            with self.lock:
                self.seq[ch] = self.seq.get(ch, 0) + 1
                t = self.now_abs()
                self.recs[(ch, self.seq[ch])] = ["TN", 0, t]
                self.send(self.fmt("TN", 0, self.seq[ch], ch, t))
            self.note(f"Impuls Eingang {ch}")

    def double_contact(self, ch, gap=0.12):
        """Prellen: zweiter Kontakt kurz nach dem ersten."""
        self.impulse(ch)
        if self.device == "tm550":
            with self.lock:
                seq = self.seq.get(ch, 0)
                t = self.now_abs() + gap
                self.blocked.append((ch, seq, t))
                self.send(self.fmt("TC", 0, seq, ch, t))
            self.note(f"Doppelkontakt Eingang {ch} (vom Gerät gesperrt)")
        else:
            threading.Timer(gap, lambda: self.impulse(ch)).start()

    def cancel(self, nr, dsq=False):
        """Nr R 0 (DNF) bzw. Nr R 0 . (DSQ): Startzeit stornieren."""
        with self.lock:
            st = next((x for x in self.course if x[0] == nr), None)
            if st is None:
                self.note(f"Nr {nr} ist nicht auf der Strecke")
                return False
            self.course.remove(st)
            self.recs[(CH_START, st[2])][0] = "TC"
            self.send(self.fmt("TC", nr, st[2], CH_START, st[1]))
        self.note(f"Nr {nr} {'disqualifiziert' if dsq else 'ausgeschieden'} (R 0{'.' if dsq else ''})")
        return True

    def renumber(self, old, new):
        """Alte Nr R E1 neue Nr Enter."""
        with self.lock:
            i = next((i for i, x in enumerate(self.course) if x[0] == old), None)
            if i is None:
                self.note(f"Nr {old} ist nicht auf der Strecke")
                return False
            nr, t, seq = self.course[i]
            self.course[i] = (new, t, seq)
            self.recs[(CH_START, seq)] = ["T*", new, t]
            self.send(self.fmt("T-", old, seq, CH_START, t))
            self.send(self.fmt("T*", new, seq, CH_START, t))
        self.note(f"Nr {old} umnummeriert auf {new}")
        return True

    def close_run(self):
        self.run_open = False
        self.send(f"CL {self.run:02d}")
        self.note(f"Lauf {self.run} geschlossen")

    def open_run(self, same=False):
        if not same:
            self.run += 1
        self.run_open = True
        with self.lock:
            self.seq = {CH_START: 0, CH_FINISH: 0}
            self.recs, self.course, self.results, self.blocked = {}, [], [], []
        tm_mode = self.tm_mode if self.new_tm else "TIMING"
        self.send(f"OP {self.run:02d} {tm_mode}" if self.device == "tm550" else f"OP {self.run:02d}  00  {self.mode}")
        self.note(f"Lauf {self.run} geöffnet")

    def restart(self):
        """CP aus und wieder ein: Verbindungen weg, Ethernet bleibt aus, bis es am Geraet eingeschaltet wird."""
        self.eth_off = self.device == "cp545"
        self.drop_clients()
        self.note("Gerät neu gestartet" + (", Ethernet aus" if self.eth_off else ""))

    def enable_ethernet(self):
        self.eth_off = False
        self.note("Ethernet eingeschaltet")

    def set_cable(self, connected):
        self.offline = not connected
        if not connected:
            self.drop_clients()
        self.note("Kabel eingesteckt" if connected else "Kabel gezogen")

    def drop_clients(self):
        if self.clients and self.device == "cp545" and self.err_msgs and self.on_line:
            self.on_line("PL Sock error RST 0")      # CP druckt das bei «Error Messages EIN»
            self.on_line("PL TCP Schliessen socket 0")
        for c in list(self.clients):
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        self.clients.clear()

    def close(self):
        self.alive = False
        self.drop_clients()
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# PDF ohne Zusatzmodule: A4, Helvetica, Tabellen mit Seitenumbruch
# --------------------------------------------------------------------------- #
_HELV_W = {c: 0.556 for c in "0123456789"}
_HELV_W.update({" ": 0.278, ".": 0.278, ",": 0.278, ":": 0.278, "-": 0.333, "(": 0.333, ")": 0.333, "+": 0.584,
                "/": 0.278, "'": 0.191})


def pdf_text_width(text, size, bold=False):
    w = 0.0
    for ch in text:
        if ch in _HELV_W:
            w += _HELV_W[ch]
        elif ch.isupper():
            w += 0.722 if bold else 0.667
        elif ch in "iljtf":
            w += 0.278
        elif ch in "mw":
            w += 0.833
        else:
            w += 0.611 if bold else 0.556
    return w * size


class PdfDoc:
    W, H, M = 595.28, 841.89, 42.0

    def __init__(self, title, subtitle=""):
        self.title, self.subtitle = title, subtitle
        self.pages = []
        self.ops = None
        self.y = 0
        self.new_page()

    @staticmethod
    def _esc(text):
        raw = str(text).encode("cp1252", "replace")
        return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")

    def text(self, x, y, text, size=9.5, bold=False, align="left", gray=0.0):
        if align == "right":
            x -= pdf_text_width(str(text), size, bold)
        self.ops.append(b"%.3f g BT /%s %.1f Tf %.2f %.2f Td (" % (gray, b"F2" if bold else b"F1", size, x, y)
                        + self._esc(text) + b") Tj ET")

    def line(self, x1, y1, x2, y2, gray=0.75, width=0.5):
        self.ops.append(b"%.3f G %.2f w %.2f %.2f m %.2f %.2f l S" % (gray, width, x1, y1, x2, y2))

    def new_page(self):
        self.ops = []
        self.pages.append(self.ops)
        self.text(self.M, self.H - self.M - 4, self.title, 15, True)
        if self.subtitle:
            self.text(self.M, self.H - self.M - 22, self.subtitle, 10, gray=0.35)
        self.line(self.M, self.H - self.M - 30, self.W - self.M, self.H - self.M - 30, 0.6, 0.8)
        self.y = self.H - self.M - 48

    def need(self, h):
        if self.y - h < self.M + 24:
            self.new_page()

    def heading(self, text):
        self.need(40)
        self.y -= 6
        self.text(self.M, self.y, text, 12, True)
        self.y -= 16

    def table(self, cols, rows, header=True):
        """cols: [(titel, breite_anteil, ausrichtung)]; rows: Listen von Texten."""
        width = self.W - 2 * self.M
        xs, x = [], self.M
        for _t, frac, _a in cols:
            xs.append(x)
            x += frac * width

        def draw(vals, bold, gray):
            for (t, frac, align), cx, v in zip(cols, xs, vals):
                v = str(v)
                limit = frac * width - 6
                while v and pdf_text_width(v, 9.5, bold) > limit:
                    v = v[:-2] + "…" if len(v) > 2 else ""
                self.text(cx + frac * width - 4 if align == "right" else cx, self.y, v, 9.5, bold, align, gray)
            self.y -= 14

        if header:
            self.need(30)
            draw([c[0] for c in cols], True, 0.35)
            self.line(self.M, self.y + 10, self.W - self.M, self.y + 10)
        for r in rows:
            if self.y - 14 < self.M + 24:
                self.new_page()
                if header:
                    draw([c[0] for c in cols], True, 0.35)
                    self.line(self.M, self.y + 10, self.W - self.M, self.y + 10)
            draw(r, False, 0.0)
        self.y -= 6

    def note(self, text, gray=0.35):
        self.need(16)
        self.text(self.M, self.y, text, 9, gray=gray)
        self.y -= 14

    def build(self, footer=""):
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
        kids = []
        n = len(self.pages)
        for i, ops in enumerate(self.pages, 1):
            foot = f"{footer}   Seite {i} von {n}".strip()
            stream = b"\n".join(ops + [b"0.4 g BT /F1 8 Tf %.2f %.2f Td (" % (self.M, self.M - 8)
                                       + self._esc(foot) + b") Tj ET"])
            objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            content_id = len(objs)
            objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 3 0 R "
                        b"/F2 4 0 R >> >> /Contents %d 0 R >>" % (self.W, self.H, content_id))
            kids.append(len(objs))
        objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % n
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, o in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
        return bytes(out)


# --------------------------------------------------------------------------- #
# Windows-Netzwerk: Netzwerkkarte fuer den CP auf feste Adresse und zurueck auf DHCP
# --------------------------------------------------------------------------- #
IS_WINDOWS = sys.platform.startswith("win")
_NO_WINDOW = 0x08000000


def list_adapters():
    """Kabelgebundene Netzwerkkarten: [{'name','desc','up','ips','dhcp'}]. Nur Windows."""
    if not IS_WINDOWS:
        return []
    script = (
        "$r=@(); foreach($a in Get-NetAdapter -Physical -ErrorAction SilentlyContinue){"
        "$ip=@(Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue"
        "|Select-Object -ExpandProperty IPAddress) -join ',';"
        "$d=(Get-NetIPInterface -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).Dhcp;"
        "$r+=[pscustomobject]@{Name=$a.Name;Desc=$a.InterfaceDescription;Status=[string]$a.Status;"
        "Media=[string]$a.PhysicalMediaType;Ip=$ip;Dhcp=[string]$d}}; ConvertTo-Json -InputObject $r -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=25, creationflags=_NO_WINDOW).stdout
        data = json.loads(out or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    if isinstance(data, dict):
        data = [data]
    res = []
    for a in data:
        media, desc, name = str(a.get("Media", "")), str(a.get("Desc", "")), str(a.get("Name", ""))
        low = (media + " " + desc + " " + name).lower()
        if "802.11" in low or "wireless" in low or "wi-fi" in low or "wlan" in low or "bluetooth" in low:
            continue
        res.append({"name": name, "desc": desc, "up": str(a.get("Status", "")).lower() == "up",
                    "ips": [x for x in str(a.get("Ip", "")).split(",") if x],
                    "dhcp": str(a.get("Dhcp", "")).lower() == "enabled"})
    res.sort(key=lambda a: (not a["up"], a["name"].casefold()))
    return res


def run_elevated(commands, timeout=90):
    """Befehle mit Administratorrechten ausfuehren (Windows fragt mit der Benutzerkontensteuerung).
    -> (ok, text)"""
    if not IS_WINDOWS:
        return False, "nur unter Windows"
    import ctypes
    from ctypes import wintypes
    line = " & ".join(commands)
    try:
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        admin = False
    if admin:
        try:
            r = subprocess.run(f"cmd.exe /c {line}", capture_output=True, text=True, timeout=timeout,
                               creationflags=_NO_WINDOW)
            return r.returncode == 0, (r.stdout + r.stderr).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)

    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    sei = SEI()
    sei.cbSize = ctypes.sizeof(SEI)
    sei.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb, sei.lpFile, sei.lpParameters, sei.nShow = "runas", "cmd.exe", f"/c {line}", 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = ctypes.GetLastError()
        return False, "Berechtigung abgelehnt" if err == 1223 else f"Windows-Fehler {err}"
    if not sei.hProcess:
        return True, ""
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, int(timeout * 1000))
    code = wintypes.DWORD(1)
    ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return code.value == 0, "" if code.value == 0 else f"netsh meldet Fehler {code.value}"


def set_static_ip(adapter):
    return run_elevated([f'netsh interface ipv4 set address name="{adapter}" static {PC_IP} {PC_MASK}'])


def set_dhcp(adapter):
    return run_elevated([f'netsh interface ipv4 set address name="{adapter}" source=dhcp',
                         f'netsh interface ipv4 set dnsservers name="{adapter}" source=dhcp'])


def address_ready(ip, timeout=12.0):
    """Wartet, bis Windows die Adresse wirklich vergeben hat."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
                sk.bind((ip, 0))
                return True
        except OSError:
            time.sleep(0.5)
    return False


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
        lines, next_lines = None, 0.0
        try:
            while not self.stop_event.is_set():
                if time.time() >= next_lines:  # Steuerleitungen (nur wenn das Kabel sie fuehrt)
                    next_lines = time.time() + 0.5
                    try:
                        now = {"CTS": bool(ser.cts), "DSR": bool(ser.dsr), "CD": bool(ser.cd)}
                    except Exception:
                        now = lines
                    if now is not None and now != lines:
                        lines = now
                        self.q.put(("lines", dict(now), self))
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
        migrated = migrate_data(self.data_path) if getattr(sys, "frozen", False) else None
        setup_diag(self.data_path)
        DIAG.info("=" * 70)
        DIAG.info(f"Start {APP_NAME} {APP_VERSION} | Python {sys.version.split()[0]} | {sys.platform} | "
                  f"Daten {self.data_path}" + (f" | übernommen aus {migrated}" if migrated else ""))
        self.install_error_hooks()

        self.settings = self.load_settings()
        apply_channels(self.settings["timing"])
        apply_palette(self.settings["theme"])
        messagebox.app = self
        self.dialog_hook = None   # Tests: Antworten fuer Meldungsfenster
        self._placed = []
        self.log_lines = []       # (zeile, tag, focus) fuer Neuaufbau der Oberflaeche
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
        # Ethernet (THCOM08)
        self.cp = None              # CPClient
        self.eth_job = None         # laufende Vorbereitung (Netzwerk, Suche)
        self.cp_found = []          # [(ip, kennung)]
        self.adapters = []
        self.cp_info = ""
        self.cp_run = 0
        self.cp_recs = {}           # (lauf, kanal, seq) -> {"nr", "tod", "status"}
        self.cp_prec = 2
        self.cp_next_start = None   # Nummer, die der CP als naechsten Start vergibt
        self.finish_override = None
        self.cp_finish_want = None  # Zielnummer, die im CP vorgeladen ist
        self.cp_cmds = []
        self.cp_inflight = None
        self.cp_hold_until = 0.0
        self.cp_readback = True
        self.cp_offsets = []        # (lokal, cp_minus_lokal)
        self.cp_last_rx = 0.0
        self.cp_last_hb = 0.0
        self.last_start_nr = None
        self.last_finish_key = None
        self.course = []            # [(start_tod, nr, key)] in erwarteter Zielreihenfolge
        self.status = {}            # nr -> "DNS" | "DNF" | "DSQ"
        self.cp_lastseq = {}        # (geraet, lauf, eingang) -> letzte Seq
        self.cp_download = None     # Zeiten waehrend #DL
        self.reset_caps("cp545")
        self.cp_b_device = None
        self.cp_b_fw, self.cp_b_mode, self.cp_b_nr_ok, self.cp_b_next = "", "", False, None
        self.backup_reset()
        self.cp_backlog = None      # alte Zeilen aus dem Puffer des CP direkt nach dem Verbinden
        self.cp_backlog_t = 0.0
        self.cp_backlog_again = False
        self.cp_session_seen = False   # in dieser Sitzung schon einmal mit einem CP verbunden
        self.cp_closed_runs = set()    # in dieser Sitzung am CP geschlossene Laeufe
        self.backup_seen = {}
        self.cp_b = None            # Reserve-CP
        self._quiet = False
        self.sim = None             # eingebauter Simulator
        self._eth_tick_job = None
        self._course_menu = None
        self._next_seen = False
        self._row_tpl = ("5. Nr. 888", "8:88.88s", "")

        self.online = OnlineClient(self.settings["online"])
        self.web = LanServer()

        self.setup_window()
        self.setup_fonts()
        self.setup_styles()
        self.build_ui()
        self.bind_ui_logging()
        self.refresh_ports()
        self.build_cards()
        self.apply_show_settings()
        self.load_autosave()
        self.update_live_info()
        self.update_ziel_info()
        self.update_window_title()
        self.report_missing_modules()
        if getattr(sys, "frozen", False):  # nur die gebaute App prueft beim Start (nicht Tests und Entwicklung)
            self.root.after(4000, lambda: self.check_updates(manual=False))
        self.root.after(6 * 3600 * 1000, self._periodic_update_check)
        if self.settings["conn"]["mode"] == "ethernet":
            self.refresh_adapters()
        elif self.settings["net_restore"].get("pending"):
            # letzte Sitzung endete ohne Rueckstellen (Absturz, Strom weg): jetzt nachholen
            self.root.after(1500, lambda: self.restore_network(background=True))

        self.root.after(POLL_INTERVAL_MS, self.poll_queue)
        self.root.after(BLINK_INTERVAL_MS, self.blink_tick)
        self.serial_base, self.serial_last_rx, self.serial_silent, self.serial_lines0 = None, 0.0, None, None
        self._conn_status = ("nicht verbunden", None)
        self.root.after(1000, self.serial_watch_tick)
        self.root.after(WEB_SNAPSHOT_MS, self.web_tick)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ================================================================== #
    # Fenster / Stil
    # ================================================================== #
    def setup_window(self):
        self.root.title(f"SWV Live-Ranking v{APP_VERSION}  |  TAG Heuer CP 545")
        self.root.configure(bg=BG)
        self.root.minsize(1000, 600)
        try:
            self.root.state("zoomed")
        except tk.TclError:
            try:
                self.root.attributes("-zoomed", True)
            except tk.TclError:
                self.root.geometry("1600x900")
        self.root.after(30, lambda: set_titlebar(self.root))
        self.icon_img = None
        ico = resource_file(ICON_ICO)
        if IS_WINDOWS and ico:
            try:
                self.root.iconbitmap(default=ico)  # Fenster, Taskleiste und alle Dialoge
            except tk.TclError:
                pass
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
        if not hasattr(self, "_tk_base_scaling"):
            try:
                self._tk_base_scaling = float(self.root.tk.call("tk", "scaling"))
                self._dpi = float(self.root.winfo_fpixels("1i"))
            except tk.TclError:
                self._tk_base_scaling, self._dpi = 96.0 / 72.0, 96.0
        dpi_scale = max(1.0, min(3.0, self._dpi / 96.0))
        f = self.size_factor(dpi_scale)
        self.ui_fit = f
        try:  # Schriften in Punkt (Seitenleiste, Dialoge) mitverkleinern
            self.root.tk.call("tk", "scaling", self._tk_base_scaling * f)
        except tk.TclError:
            pass
        self.ui_scale = max(0.7, min(3.0, dpi_scale * f))
        self.side_w = int(358 * self.ui_scale)
        self.wrap_w = self.side_w - int(70 * self.ui_scale)

        def px(n):  # Pixelschriften mit der Groesse der Oberflaeche
            return -max(8, int(round(n * f)))

        self.f_status = tkfont.Font(family=fam, size=px(28), weight="bold")
        self.f_status_name = tkfont.Font(family=fam, size=px(18), weight="bold")
        self.f_status_sub = tkfont.Font(family=fam, size=px(16))
        self.f_ticker = tkfont.Font(family=fam, size=px(20))
        self.f_ticker_bold = tkfont.Font(family=fam, size=px(20), weight="bold")
        self.f_ticker_time = tkfont.Font(family=fam, size=px(15))
        self._mf_bold = tkfont.Font(family=fam, size=px(30), weight="bold")
        self._mf_row = tkfont.Font(family=fam, size=px(30), weight="bold")
        self._mf_title = tkfont.Font(family=fam, size=px(20), weight="bold")
        self._mf_sub = tkfont.Font(family=fam, size=px(15))
        self._mf_pen = tkfont.Font(family=fam, size=px(16), weight="bold")
        self.f_title = tkfont.Font(family=fam, size=px(22), weight="bold")
        self.f_row = tkfont.Font(family=fam, size=px(28), weight="bold")
        self.f_first = tkfont.Font(family=fam, size=px(36), weight="bold")
        self.f_sub = tkfont.Font(family=fam, size=px(15))
        self.f_pen = tkfont.Font(family=fam, size=px(16), weight="bold")
        self.f_panel = tkfont.Font(family=fam, size=px(15))
        self.f_panel_bold = tkfont.Font(family=fam, size=px(15), weight="bold")
        self.f_panel_head = tkfont.Font(family=fam, size=px(16), weight="bold")
        self.f_side = tkfont.Font(family=fam, size=10)
        self.f_side_bold = tkfont.Font(family=fam, size=10, weight="bold")
        self.f_side_head = tkfont.Font(family=fam, size=11, weight="bold")
        self.f_log = tkfont.Font(family=mono, size=9)
        self.f_dialog = tkfont.Font(family=fam, size=px(40), weight="bold")

    def size_factor(self, dpi_scale):
        """Grösse der Oberflaeche: Auto passt auf die nutzbare Flaeche (Bezug 1600 x 900 Bildpunkte bei 100 %),
        z.B. 13''-Laptop mit Full HD und 150 % = 1280 x 720 -> 0.8. Sonst fester Faktor aus den Einstellungen."""
        pref = self.settings.get("ui_size", "auto")
        if pref != "auto":
            try:
                return max(0.7, min(1.3, float(pref)))
            except (TypeError, ValueError):
                pass
        try:
            sw = self.root.winfo_screenwidth() / dpi_scale
            sh = (self.root.winfo_screenheight() - 48 * dpi_scale) / dpi_scale  # Taskleiste
        except tk.TclError:
            return 1.0
        if os.environ.get("SWV_SCREEN"):  # Tests: «1280x720»
            sw, sh = (int(v) for v in os.environ["SWV_SCREEN"].lower().split("x"))
            sh -= 48
        return max(0.72, min(1.0, sw / 1600.0, sh / 852.0))

    def set_ui_size(self, value):
        if value == self.settings.get("ui_size", "auto"):
            return
        self.settings["ui_size"] = value
        self.save_settings()
        self.log("Grösse der Oberfläche: " + ("automatisch" if value == "auto" else f"{float(value) * 100:.0f} %"),
                 tag="ok")
        self.rebuild_ui(THEME)

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
                        arrowcolor=TEXT, padding=4, bordercolor=BORDER, lightcolor=INPUT_BG, darkcolor=INPUT_BG,
                        insertcolor=TEXT)
        style.map("Port.TCombobox",
                  fieldbackground=[("readonly", INPUT_BG), ("!disabled", INPUT_BG), ("disabled", INPUT_BG)],
                  background=[("readonly", BUTTON), ("active", BUTTON), ("!disabled", BUTTON)],
                  arrowcolor=[("disabled", MUTED), ("!disabled", TEXT)],
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
        return RoundButton(parent, text=text, command=cmd, bg=color, fg=BUTTON_FG if color == BUTTON else WHITE,
                           font=self.f_side_bold,
                           radius=int(9 * self.ui_scale), padx=int(12 * self.ui_scale), pady=int(6 * self.ui_scale))

    def _entry(self, parent, width=10, **kw):
        return tk.Entry(parent, width=width, bg=INPUT_BG, fg=INPUT_FG, insertbackground=INPUT_FG,
                        relief="flat", font=self.f_side, highlightthickness=1, selectbackground=BLUE,
                        highlightbackground=BORDER, highlightcolor=ACCENT, **kw)

    def _label(self, parent, text, bold=False, fg=None, bg=None, **kw):
        return tk.Label(parent, text=text, bg=bg or PANEL, fg=fg or TEXT,
                        font=self.f_side_bold if bold else self.f_side, anchor="w", **kw)

    # Auswahl als Umschaltknoepfe: aktiv = blau. Eindeutig auf jedem System, unabhaengig vom Theme.
    def _check(self, parent, text, var, bg=None):
        return tk.Checkbutton(parent, text=text, variable=var, indicatoron=False, bg=BUTTON, fg=BUTTON_FG,
                              selectcolor=CHECK_SEL, activebackground=CHECK_SEL, activeforeground=CHECK_SEL_FG,
                              font=self.f_side, relief="flat", offrelief="flat", overrelief="flat",
                              bd=0, padx=10, pady=4, highlightthickness=0, cursor="hand2")

    def _radio(self, parent, text, var, value, bg=None, command=None):
        return tk.Radiobutton(parent, text=text, variable=var, value=value, indicatoron=False, bg=BUTTON,
                              fg=BUTTON_FG, selectcolor=CHECK_SEL, activebackground=CHECK_SEL,
                              activeforeground=CHECK_SEL_FG,
                              font=self.f_side, relief="flat", offrelief="flat", overrelief="flat",
                              bd=0, padx=10, pady=4, highlightthickness=0, cursor="hand2", command=command)

    def _combo(self, parent, values=(), width=20, state="normal"):
        cb = ttk.Combobox(parent, style="Port.TCombobox", font=self.f_side, values=list(values),
                          width=width, state=state)
        return cb

    def _section(self, parent, title, key=None, status=False):
        box = RoundedPanel(parent, fill=PANEL, radius=int(12 * self.ui_scale), fit_height=True)
        box.pack(fill="x", padx=10, pady=(10, 0))
        if parent is getattr(self, "_side_frame", None):
            self.side_boxes.append((key, title, box))
        frm = box.inner
        headf = tk.Frame(frm, bg=PANEL, cursor="hand2" if key else "")
        headf.pack(fill="x", padx=12, pady=(10, 8))
        head = tk.Label(headf, bg=PANEL, fg=TEXT, font=self.f_side_head, anchor="w")
        head.pack(side="left")
        if key:
            self.section_heads = getattr(self, "section_heads", {})
            self.section_heads[key] = head
        stat = None
        if status:
            stat = tk.Label(headf, bg=PANEL, fg=MUTED, font=self.f_side_bold, anchor="w")
            stat.pack(side="left", padx=(8, 0))
        body = tk.Frame(frm, bg=PANEL)

        def render():
            collapsed = bool(key) and self.settings["collapsed"].get(key, False) \
                and not (self.settings.get("nav_layout") == "top" and getattr(self, "_drop_key", None) == key)
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
        if key:
            self._section_render[key] = render
        return (body, stat) if status else body

    def _toplevel(self, title, parent=None):
        DIAG.info(f"UI Fenster: {title}")
        dlg = tk.Toplevel(parent or self.root)
        dlg.title(title)
        dlg.configure(bg=PANEL, padx=18, pady=14)
        dlg.transient(self.root)
        if self.icon_img is not None:
            dlg.iconphoto(False, self.icon_img)
        set_titlebar(dlg)
        return dlg

    def _place(self, dlg, narrow=False, height=None):
        """Fenster links oben ueber die Seitenleiste legen, damit die Ranglisten frei bleiben.
        narrow: so breit wie die Seitenleiste (Fenster waehrend des Rennens)."""
        dlg.update_idletasks()
        m = int(10 * self.ui_scale)
        alive = [w for w in self._placed if w.winfo_exists() and w is not dlg and w.winfo_viewable()]
        self._placed = alive + [dlg]
        off = int(26 * self.ui_scale) * min(len(alive), 6)
        x, y = self.root.winfo_rootx() + m + off, self.root.winfo_rooty() + m + off
        max_h = max(200, min(self.root.winfo_height(), self.screen_height()) - 2 * m - off)
        max_w = max(300, self.root.winfo_screenwidth() - 2 * m)
        too_high = (height or dlg.winfo_reqheight()) > max_h
        if too_high:
            self._fit_height(dlg)  # Tabellen/Textfelder schrumpfen lassen, Knoepfe bleiben sichtbar
        if narrow:
            w = self.side_w - 2 * m
            h = min(max_h, height or dlg.winfo_reqheight())
            dlg.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        elif height or too_high:
            w = min(max_w, dlg.winfo_reqwidth())
            dlg.geometry(f"{w}x{min(max_h, height or dlg.winfo_reqheight())}+{max(0, x)}+{max(0, y)}")
        elif dlg.winfo_reqwidth() > max_w:
            dlg.geometry(f"{max_w}x{dlg.winfo_reqheight()}+{max(0, x)}+{max(0, y)}")
        else:
            dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        set_titlebar(dlg)

    def screen_height(self):
        """Nutzbare Bildschirmhoehe (ohne Taskleiste), in Tests per SWV_SCREEN."""
        if os.environ.get("SWV_SCREEN"):
            h = int(os.environ["SWV_SCREEN"].lower().split("x")[1])
            return int((h - 48) * max(1.0, getattr(self, "_dpi", 96.0) / 96.0))
        return self.root.winfo_screenheight() - int(48 * max(1.0, getattr(self, "_dpi", 96.0) / 96.0))

    def _fit_height(self, dlg):
        """Dialog hoeher als der Bildschirm: grosse Felder (Tabellen, Text, Listen) duerfen schrumpfen und
        bekommen die Resthoehe, Knopfzeilen am Ende werden zuerst platziert (bleiben sichtbar)."""
        big = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, (tk.Text, tk.Listbox, ttk.Treeview, tk.Canvas)):
                    big.append(c)
                else:
                    walk(c)
        walk(dlg)
        for w in big:
            try:
                if isinstance(w, (tk.Text, tk.Listbox, ttk.Treeview)):
                    w.configure(height=3)
                else:
                    w.configure(height=int(60 * self.ui_scale))
            except tk.TclError:
                pass
            node = w
            while node is not dlg and node is not None:
                mgr = node.winfo_manager()
                try:
                    if mgr == "grid":
                        node.master.rowconfigure(int(node.grid_info()["row"]), weight=1)
                        node.grid_configure(sticky="nsew")
                    elif mgr == "pack":
                        node.pack_configure(fill="both", expand=True)
                except tk.TclError:
                    pass
                node = node.master
        # pack: letzte Knopfzeile zuerst unten platzieren
        kids = [c for c in dlg.pack_slaves()]
        if kids:
            last = kids[-1]
            if last not in big:
                try:
                    last.pack_configure(side="bottom", before=kids[0])
                except tk.TclError:
                    pass
        dlg.update_idletasks()

    def _center(self, dlg):
        self._place(dlg)

    def narrow_wrap(self):
        """Umbruchbreite fuer Text in schmalen Fenstern."""
        return self.side_w - int(70 * self.ui_scale)

    # ================================================================== #
    # Updates: GitHub-Releases (nur ausgehend, nur auf Rueckfrage)
    # ================================================================== #
    def _periodic_update_check(self):
        """Alle 6 Stunden nach Updates sehen (nur ausgehend zu GitHub, wenn die Pruefung eingeschaltet ist)."""
        if self.settings["updates"].get("check", True):
            self.settings["updates"]["last_check"] = 0
            self.check_updates(manual=False)
        self.root.after(6 * 3600 * 1000, self._periodic_update_check)

    def _version_label(self, parent):
        lab = tk.Label(parent, text=f"v{APP_VERSION}", bg=BG, fg=MUTED, font=self.f_side_bold, cursor="hand2",
                       padx=6, pady=1)
        lab.bind("<Button-1>", lambda e: self.on_version_click())
        self.root.after(10, self.refresh_version_label)
        return lab

    def refresh_version_label(self):
        """Gruen = aktuell, Rot = neuere Version verfuegbar, Grau = nicht geprueft / keine Verbindung."""
        st = getattr(self, "update_state", None)
        if st is None:  # letztes Ergebnis der Pruefung (gespeichert), bis neu geprueft ist
            latest = self.settings["updates"].get("latest", "")
            st = "unknown"
            if latest and self.settings["updates"].get("check", True):
                st = "newer" if parse_version(latest) > parse_version(APP_VERSION) else "current"
                if st == "newer":
                    st = "unknown"  # ohne Release-Daten kein Download: neu pruefen
            self.update_state = st
        u = self.settings["updates"]
        if st != "ready" and self.update_ready_for(u.get("ready_tag")) \
                and parse_version(u.get("ready_tag")) > parse_version(APP_VERSION):
            st = self.update_state = "ready"
        color = {"current": GREEN, "newer": RED, "ready": ORANGE}.get(st, None)
        when = "beim Beenden" if u.get("install_on_exit") else "wenn du es auslöst"
        tip = {"current": "aktuell", "newer": f"{getattr(self, 'update_latest', '')} verfügbar, klicken zum "
                                                "Herunterladen",
               "ready": f"{u.get('ready_tag', '')} geladen, wird installiert {when}"}.get(
            st, "nicht geprüft, klicken zum Prüfen")
        for lab in (getattr(self, "lbl_version", None), getattr(self, "lbl_version_top", None)):
            if lab is None:
                continue
            try:
                if color:
                    lab.configure(bg=color, fg=WHITE)
                else:
                    lab.configure(bg=BG, fg=MUTED)
                lab._tip = tip
            except tk.TclError:
                pass
        if st == "newer" and not getattr(self, "_ver_glow", False):
            self._ver_glow = True
            self.root.after(700, self._version_glow)

    def _version_glow(self):
        """Neuere Version: Anzeige leuchtet (wechselt zwischen hell- und dunkelrot)."""
        if getattr(self, "update_state", "") != "newer":
            self._ver_glow = False
            return
        self._ver_phase = not getattr(self, "_ver_phase", False)
        for lab in (getattr(self, "lbl_version", None), getattr(self, "lbl_version_top", None)):
            try:
                if lab is not None:
                    lab.configure(bg=RED if self._ver_phase else DARK_RED)
            except tk.TclError:
                pass
        self.root.after(700, self._version_glow)

    def on_version_click(self):
        info = getattr(self, "update_info", None)
        if getattr(self, "update_state", "") == "ready":
            self.update_choice()
        elif getattr(self, "update_state", "") == "newer" and info:
            self.offer_update(info, from_click=True)
        else:
            self.check_updates(manual=True)

    def toggle_update_check(self):
        u = self.settings["updates"]
        u["check"] = not u["check"]
        self.sw_updates.set(u["check"])
        self.save_settings()

    def installed_build(self):
        """True, wenn die App aus dem Installer stammt (dann kann das Setup sie ersetzen)."""
        if not getattr(sys, "frozen", False):
            return False
        exe = os.path.normcase(os.path.abspath(sys.executable))
        roots = [os.environ.get(v, "") for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
        return any(r and exe.startswith(os.path.normcase(os.path.abspath(r)) + os.sep) for r in roots)

    def check_updates(self, manual=False):
        u = self.settings["updates"]
        if not manual and (not u["check"] or time.time() - u.get("last_check", 0) < 1800):
            return
        if getattr(self, "_update_busy", False):
            return
        self._update_busy = True
        if manual:
            self.log("Suche nach Updates ...", tag="ok")

        def work():
            try:
                info = fetch_latest_release()
                self.q.put(("update_info", (info, manual), None))
            except Exception as exc:
                self.q.put(("update_error", (str(exc), manual), None))

        threading.Thread(target=work, daemon=True, name="Update-Pruefung").start()

    def handle_update_event(self, kind, payload):
        if kind == "update_error":
            self._update_busy = False
            err, manual = payload
            DIAG.info(f"Update-Prüfung fehlgeschlagen: {err}")
            if getattr(self, "update_state", "unknown") != "newer":
                self.update_state = "unknown"
                self.refresh_version_label()
            if manual:
                page = "https://github.com/kuewi/swv-timing-live/releases"
                if "CERTIFICATE_VERIFY_FAILED" in err:
                    text = ("Das Zertifikat von GitHub lässt sich auf diesem PC nicht prüfen (Windows-Zertifikate "
                            "unvollständig oder ein Virenschutz prüft verschlüsselte Verbindungen). Aus Sicherheit "
                            "wird nichts geladen.")
                else:
                    text = f"Keine Verbindung zu GitHub ({err})."
                if messagebox.askyesno("Updates", f"{text}\n\nRelease-Seite im Browser öffnen und die neue Version "
                                                  "dort herunterladen?"):
                    import webbrowser
                    webbrowser.open(page)
            return
        if kind == "update_info":
            info, manual = payload
            self._update_busy = False
            u = self.settings["updates"]
            u["last_check"] = time.time()
            self.save_settings()
            DIAG.info(f"Update-Prüfung: neueste {info['tag']}, installiert v{APP_VERSION}")
            newer = bool(info["version"]) and info["version"] > parse_version(APP_VERSION)
            self.update_state = ("ready" if self.update_ready_for(info["tag"]) else "newer") if newer else "current"
            self.update_info = info if newer else None
            self.update_latest = info.get("tag", "")
            self.settings["updates"]["latest"] = self.update_latest
            self.save_settings()
            self.refresh_version_label()
            if not newer:
                if manual:
                    messagebox.showinfo("Updates", f"Version {APP_VERSION} ist aktuell.")
                return
            if not manual and u.get("declined") == info["tag"] and time.time() - u.get("declined_at", 0) < 12 * 3600:
                return
            self.offer_update(info)
            return
        if kind == "update_progress":
            done, total = payload
            step = done * 4 // total if total else 0
            if step > getattr(self, "_update_step", -1):
                self._update_step = step
                self.log(f"Update wird geladen: {done * 100 // total if total else 0} % "
                         f"({done // 1024 // 1024} MB)", tag="ok")
            return
        if kind == "update_ready":
            self._update_busy = False
            self.update_set_ready(payload)
            return
        if kind == "update_failed":
            self._update_busy = False
            self.log(f"Update nicht geladen: {payload}", tag="error")
            messagebox.showerror("Update", f"Das Update konnte nicht geladen werden:\n{payload}")

    def offer_update(self, info, from_click=False):
        notes = info["body"].strip()
        if len(notes) > 900:
            notes = notes[:900].rsplit("\n", 1)[0] + "\n..."
        installed = self.installed_build()
        if not installed or not info["setup_url"]:
            text = (f"Version {info['tag'].lstrip('v')} ist verfügbar (installiert: {APP_VERSION}).\n\n{notes}\n\n"
                    "Diese App wurde nicht mit dem Installer installiert und kann sich nicht selbst ersetzen. "
                    "Download-Seite öffnen?")
            if messagebox.askyesno("Neue Version", text):
                import webbrowser
                webbrowser.open(info["html_url"])
            else:
                self._decline_update(info)
            return
        if self.update_ready_for(info["tag"]):
            self.update_choice()
            return
        text = (f"Version {info['tag'].lstrip('v')} ist verfügbar (installiert: {APP_VERSION}).\n\n{notes}\n\n"
                "Jetzt im Hintergrund herunterladen? Die App läuft weiter. Wann installiert wird, wählst du danach: "
                "jetzt, in 8 Stunden oder beim Beenden der App.")
        if not messagebox.askyesno("Neue Version", text):
            if not from_click:
                self._decline_update(info)
            return
        self.download_update(info)

    def _decline_update(self, info):
        u = self.settings["updates"]
        u["declined"], u["declined_at"] = info["tag"], time.time()
        self.save_settings()
        DIAG.info(f"Update {info['tag']} abgelehnt")

    def download_update(self, info):
        self._update_busy = True
        self._update_step = -1
        folder = os.path.join(self.data_path, "updates")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, info["setup"])
        self.log(f"Lade {info['setup']} ...", tag="ok")

        def work():
            try:
                want = None
                if info["sums_url"]:
                    for line in fetch_text(info["sums_url"]).splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 2 and parts[-1].lstrip("*") == info["setup"]:
                            want = parts[0].lower()
                if not want:
                    raise ValueError("keine Prüfsumme zum Setup im Release (SHA256SUMS.txt)")
                last = [0.0]

                def prog(done, total):
                    if time.time() - last[0] > 0.3:
                        last[0] = time.time()
                        self.q.put(("update_progress", (done, total), None))

                got = download_file(info["setup_url"], path, prog)
                if got.lower() != want:
                    os.remove(path)
                    raise ValueError("Prüfsumme stimmt nicht, Datei verworfen")
                self.q.put(("update_ready", path, None))
            except Exception as exc:
                self.q.put(("update_failed", str(exc), None))

        threading.Thread(target=work, daemon=True, name="Update-Download").start()

    # ---- Update installieren: nie von selbst, nie waehrend des Wettkampfs ---- #
    def update_ready_for(self, tag):
        u = self.settings["updates"]
        return bool(u.get("ready_path")) and u.get("ready_tag") == tag and os.path.isfile(u["ready_path"])

    def update_set_ready(self, path):
        """Setup geladen und geprueft: Anzeige orange, Zeitpunkt waehlen lassen. Die App laeuft weiter."""
        info = getattr(self, "update_info", None) or {}
        u = self.settings["updates"]
        u["ready_path"], u["ready_tag"] = path, info.get("tag", u.get("ready_tag", ""))
        u["install_on_exit"] = False
        self.save_settings()
        self.update_state = "ready"
        self.refresh_version_label()
        self.log(f"Update {u['ready_tag']} geladen und geprüft. Installiert wird erst, wenn du es auslöst "
                 "(jetzt, in 8 Stunden oder beim Beenden).", tag="ok")
        self.update_choice()

    def update_busy_reason(self):
        """Grund, warum jetzt nicht installiert wird (Wettkampf laeuft), sonst ''."""
        parts = []
        if self.cp is not None and self.cp.connected:
            parts.append(f"{self.dev_name()} verbunden")
        elif self.reader is not None:
            parts.append("RS232 verbunden")
        if self.cp_b is not None and self.cp_b.connected:
            parts.append("Reserve verbunden")
        n = len(self.course)
        if n:
            parts.append(f"{n} {'Boot' if n == 1 else 'Boote'} auf der Strecke")
        return ", ".join(parts)

    def update_choice(self):
        """Fenster: jetzt installieren (nur ohne Verbindung und ohne Boote auf der Strecke), in 8 Stunden, beim
        Beenden. Blockiert nichts."""
        u = self.settings["updates"]
        if not self.update_ready_for(u.get("ready_tag")):
            return
        old = getattr(self, "_update_dlg", None)
        try:
            if old is not None and old.winfo_exists():
                old.destroy()
        except tk.TclError:
            pass
        try:
            dlg = self._toplevel("Update installieren")
        except tk.TclError:
            return
        self._update_dlg = dlg
        busy = self.update_busy_reason()
        tk.Label(dlg, text=f"Version {u['ready_tag'].lstrip('v')} ist geladen und geprüft.\nWann installieren? Die "
                           "App schliesst sich dafür nie von selbst.", bg=PANEL, fg=TEXT, font=self.f_side,
                 justify="left", wraplength=self.narrow_wrap()).pack(anchor="w", pady=(0, 8))
        b_now = self._button(dlg, "Jetzt installieren", lambda: pick("now"), GREEN if not busy else None)
        b_now.pack(fill="x", pady=(0, 4))
        if busy:
            b_now.configure(state="disabled")
            tk.Label(dlg, text=f"Gesperrt: {busy}. Erst nach dem Wettkampf (trennen, Strecke leer).", bg=PANEL,
                     fg=GOLD, font=self.f_side, justify="left", wraplength=self.narrow_wrap()).pack(
                anchor="w", pady=(0, 6))
        self._button(dlg, "In 8 Stunden", lambda: pick("later")).pack(fill="x", pady=(0, 4))
        self._button(dlg, "Beim Beenden der App", lambda: pick("exit")).pack(fill="x")
        dlg.protocol("WM_DELETE_WINDOW", lambda: pick("later"))
        self._place(dlg, narrow=True)

        def pick(choice):
            try:
                dlg.destroy()
            except tk.TclError:
                pass
            self.update_choose(choice)

    def update_choose(self, choice):
        u = self.settings["updates"]
        path = u.get("ready_path", "")
        if choice == "now":
            busy = self.update_busy_reason()
            if busy:
                messagebox.showinfo("Update", f"Jetzt nicht: {busy}. Das Update bleibt geladen.")
                return
            self.launch_setup(path)
            return
        if choice == "exit":
            u["install_on_exit"] = True
            self.save_settings()
            self.log(f"Update {u.get('ready_tag', '')} wird beim Beenden der App installiert.", tag="ok")
        else:
            self.log(f"Update {u.get('ready_tag', '')}: Erinnerung in 8 Stunden.", tag="ok")
            self._schedule_update_remind(8 * 3600)
        self.refresh_version_label()

    def _schedule_update_remind(self, sec):
        if getattr(self, "_upd_remind_job", None):
            try:
                self.root.after_cancel(self._upd_remind_job)
            except tk.TclError:
                pass
        self._upd_remind_job = self.root.after(int(sec * 1000), self._update_remind)

    def _update_remind(self):
        """Erinnerung: nur in einem ruhigen Moment fragen, sonst eine Stunde spaeter nochmals."""
        self._upd_remind_job = None
        if not self.update_ready_for(self.settings["updates"].get("ready_tag")):
            return
        if self.update_busy_reason():
            self._schedule_update_remind(3600)
            return
        self.update_choice()

    def start_setup(self, path):
        """Setup starten (Windows fragt nach Adminrechten). True, wenn gestartet."""
        DIAG.warning(f"Update: starte {path}")
        if IS_WINDOWS:
            try:
                import ctypes
                r = ctypes.windll.shell32.ShellExecuteW(None, "open", path, "/SILENT /SP- /NOCANCEL", None, 1)
                if r <= 32:
                    raise OSError(f"ShellExecute {r}")
            except Exception as exc:
                DIAG.error(f"Setup nicht gestartet: {exc}")
                return False
        u = self.settings["updates"]
        u["ready_path"], u["ready_tag"], u["install_on_exit"] = "", "", False
        self.save_settings()
        return True

    def launch_setup(self, path):
        """Auf ausdruecklichen Wunsch (Knopf «Jetzt installieren», ohne laufenden Wettkampf): Setup starten und die
        App schliessen."""
        self.log("Update: Setup startet, die App wird geschlossen.", tag="ok")
        if not self.start_setup(path):
            messagebox.showerror("Update", f"Setup nicht gestartet.\n{path}")
            return
        self._setup_started = True
        self.root.after(500, self.on_close)

    # ================================================================== #
    # Diagnose: Programmfehler, Bedienung, Fehlerberichte
    # ================================================================== #
    def install_error_hooks(self):
        import traceback
        self._pending_errors = []

        def report(where, exc_type, exc, tb):
            DIAG.error(f"Programmfehler ({where}): {exc_type.__name__}: {exc}", exc_info=(exc_type, exc, tb))
            traceback.print_exception(exc_type, exc, tb)
            self._pending_errors.append(f"{exc_type.__name__}: {exc}")

        sys.excepthook = lambda t, e, tb: report("Hauptprogramm", t, e, tb)
        threading.excepthook = lambda a: report(f"Thread {a.thread.name if a.thread else '?'}", a.exc_type,
                                                a.exc_value, a.exc_traceback)
        self.root.report_callback_exception = lambda t, e, tb: report("Oberfläche", t, e, tb)
        self._last_error_note = 0.0

    def show_pending_errors(self):
        if not self._pending_errors or time.time() - self._last_error_note < 10:
            return
        errs, self._pending_errors = self._pending_errors, []
        self._last_error_note = time.time()
        more = f" (und {len(errs) - 1} weitere)" if len(errs) > 1 else ""
        self.log(f"Programmfehler: {errs[0]}{more}. Details im Diagnose-Log. Bitte «Fehler melden» (F12).",
                 tag="error")

    def bind_ui_logging(self):
        def click(e):
            DIAG.debug(f"UI Klick {widget_desc(e.widget)}")

        def key(e):
            if e.keysym in ("Return", "Escape", "Delete", "Tab") or e.keysym.startswith("F"):
                DIAG.debug(f"UI Taste {e.keysym} in {widget_desc(e.widget)}")

        self.root.bind_all("<ButtonRelease-1>", click, add="+")
        self.root.bind_all("<ButtonRelease-3>", click, add="+")
        self.root.bind_all("<KeyPress>", key, add="+")
        self.root.bind_all("<F12>", lambda e: self.open_report_dialog(), add="+")

    def grab_screen(self):
        """Bildschirmfoto des App-Fensters als PNG-Bytes, falls Pillow vorhanden."""
        try:
            from PIL import ImageGrab
            self.root.update_idletasks()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            w, h = self.root.winfo_width(), self.root.winfo_height()
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return buf.getvalue()
        except Exception as exc:
            DIAG.info(f"Bildschirmfoto nicht möglich: {exc}")
            return None

    def report_dir(self):
        path = os.path.join(self.data_path, REPORT_DIR)
        os.makedirs(path, exist_ok=True)
        return path

    def open_report_dialog(self):
        if getattr(self, "_report_open", False):
            return
        marked = time.time()
        rid = time.strftime("%Y%m%d-%H%M%S", time.localtime(marked)) + "-" + secrets.token_hex(2)
        DIAG.warning(f"===== FEHLERMELDUNG {rid}: Zeitpunkt markiert =====")
        shot = self.grab_screen()
        self._report_open = True
        dlg = self._toplevel("Fehler melden")
        dlg.columnconfigure(0, weight=1)
        stamp = time.strftime("%H:%M:%S", time.localtime(marked))
        tk.Label(dlg, text=f"Zeitpunkt {stamp} ist markiert. Was ist passiert? Was hast du erwartet?",
                 bg=PANEL, fg=TEXT, font=self.f_side, justify="left", anchor="w",
                 wraplength=self.narrow_wrap()).grid(row=0, column=0, sticky="w")
        txt = tk.Text(dlg, height=8, width=48, bg=PANEL2, fg=TEXT, insertbackground=TEXT, font=self.f_side,
                      relief="flat", wrap="word", highlightthickness=1, highlightbackground=BORDER, padx=8, pady=6)
        txt.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        def close():
            self._report_open = False
            dlg.destroy()

        def ok(_e=None):
            desc = txt.get("1.0", "end").strip()
            path = self.make_report(rid, marked, desc, shot)
            close()
            if path:
                self.log(f"Fehlerbericht gespeichert: {path}", tag="ok")
                self.open_folder(path)
            return "break"

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self._button(btns, "Bericht speichern", ok, BLUE).pack(side="right")
        self._button(btns, "Abbrechen", close).pack(side="right", padx=(0, 8))
        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.bind("<Escape>", lambda e: close())
        dlg.bind("<Control-Return>", ok)
        self._place(dlg, narrow=True)
        dlg.focus_force()
        txt.focus_set()
        return dlg

    def session_dump(self):
        """Gesamter Zustand der Sitzung (ohne Geheimnisse) fuer Fehlerberichte."""
        data = self.autosave_data()
        data.update({
            "app": APP_NAME, "app_version": APP_VERSION, "erstellt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "settings": redact_settings(self.settings),
            "categories": self.categories,
            "course": [[t, nr, list(k)] for t, nr, k in self.course],
            "finish_override": self.finish_override,
            "cp_lastseq": [[list(k), v] for k, v in self.cp_lastseq.items()],
            "connected": bool(self.cp is not None and self.cp.connected),
            "conn_mode": self.settings["conn"]["mode"],
            "ticker": list(self.ticker)[:200],
            "log": [line.rstrip("\n") for line, _t, _f in self.log_lines[-3000:]],
        })
        return data

    def make_report(self, rid, marked, desc, shot=None):
        import zipfile
        folder = self.report_dir()
        path = os.path.join(folder, f"fehlerbericht_{rid}.zip")
        manifest = {
            "format": "swv-fehlerbericht/1", "id": rid, "app": APP_NAME, "version": APP_VERSION,
            "markiert": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(marked)),
            "erstellt": time.strftime("%Y-%m-%dT%H:%M:%S"), "beschreibung": desc,
            "system": {"platform": sys.platform, "python": sys.version.split()[0],
                       "frozen": bool(getattr(sys, "frozen", False))},
            "wettkampf": self.event_label() if hasattr(self, "event_label") else "",
            "hochgeladen": False,
        }
        DIAG.warning(f"===== FEHLERMELDUNG {rid}: {' '.join(desc.split())[:500]} =====")
        for h in DIAG.handlers:
            h.flush()
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                z.writestr("beschreibung.txt", f"Zeitpunkt: {manifest['markiert']}\nVersion: {APP_VERSION}\n\n{desc}\n")
                z.writestr("session.json", json.dumps(self.session_dump(), ensure_ascii=False, default=str))
                if shot:
                    z.writestr("bildschirm.png", shot)
                logdir = os.path.join(self.data_path, LOG_DIR)
                if os.path.isdir(logdir):
                    for name in sorted(os.listdir(logdir)):
                        fp = os.path.join(logdir, name)
                        if name.startswith("swv_live_ranking.log") and time.time() - os.path.getmtime(fp) < 12 * 3600:
                            z.write(fp, f"logs/{name}")
                rawdir = os.path.join(self.data_path, RAW_DIR)
                if os.path.isdir(rawdir):
                    for name in sorted(os.listdir(rawdir))[-2:]:
                        z.write(os.path.join(rawdir, name), f"rohdaten/{name}")
                ap = os.path.join(self.data_path, AUTOSAVE_FILE)
                if os.path.exists(ap):
                    z.write(ap, AUTOSAVE_FILE)
        except OSError as exc:
            self.log(f"Fehlerbericht nicht gespeichert: {exc}", tag="error")
            return None
        self.queue_report(rid, path)
        return path

    def queue_report(self, rid, path):
        """Liste der Berichte, die noch nicht ins Onlinetool hochgeladen sind (Upload folgt spaeter)."""
        qp = os.path.join(self.report_dir(), "offen.json")
        try:
            with open(qp, encoding="utf-8") as fh:
                items = json.load(fh)
        except (OSError, ValueError):
            items = []
        items.append({"id": rid, "datei": os.path.basename(path), "erstellt": time.strftime("%Y-%m-%dT%H:%M:%S")})
        try:
            with open(qp, "w", encoding="utf-8") as fh:
                json.dump(items, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def open_manual_menu(self, btn):
        menu = self._menu()
        menu.add_command(label="Benutzerhandbuch (PDF)", command=lambda: self.open_manual("Benutzerhandbuch"))
        menu.add_command(label="Training (PDF)", command=lambda: self.open_manual("Training"))
        menu.add_separator()
        menu.add_command(label="Übersicht im Browser", command=lambda: self.open_url(DOC_PAGE))
        try:
            menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
        finally:
            menu.grab_release()

    def open_url(self, url):
        import webbrowser
        DIAG.info(f"Browser: {url}")
        try:
            webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001
            self.log(f"Browser nicht geöffnet: {exc}", tag="warn")

    def open_manual(self, kind):
        """Aktuelle Fassung von GitHub laden und öffnen; ohne Internet die zuletzt geladene."""
        folder = os.path.join(self.data_path, "handbuch")
        os.makedirs(folder, exist_ok=True)
        self.log(f"{kind}: aktuelle Fassung wird geladen ...", tag="ok")

        def work():
            try:
                names = fetch_doc_list()
                name = pick_doc(names, kind)
                if not name:
                    raise ValueError("kein PDF gefunden")
                path = os.path.join(folder, name)
                if not os.path.exists(path):
                    url = names[name]
                    req = urllib.request.Request(url, headers={"User-Agent": f"SWV-Live-Ranking/{APP_VERSION}"})
                    with _urlopen(req, 30) as resp, open(path + ".part", "wb") as fh:
                        fh.write(resp.read())
                    os.replace(path + ".part", path)
                self.q.put(("manual_open", (path, ""), None))
            except Exception as exc:  # noqa: BLE001
                local = pick_doc(os.listdir(folder), kind)
                self.q.put(("manual_open", (os.path.join(folder, local) if local else "", str(exc)), None))
        threading.Thread(target=work, daemon=True).start()

    def manual_opened(self, payload):
        path, err = payload
        if err:
            self.log(f"Handbuch nicht von GitHub geladen ({err})" + (", zuletzt geladene Fassung geöffnet" if path
                                                                   else ", Übersicht im Browser"), tag="warn")
        if not path:
            return self.open_url(DOC_PAGE)
        self.log(f"Geöffnet: {os.path.basename(path)}", tag="ok")
        if IS_WINDOWS:
            try:
                subprocess.Popen(["explorer.exe", os.path.normpath(path)])
            except OSError as exc:
                self.log(f"PDF nicht geöffnet: {exc}", tag="warn")
        else:
            self.open_url("file://" + path)

    def open_folder(self, path=None):
        """Datenordner (oder den Ordner einer Datei, Datei markiert) im Explorer zeigen."""
        target = path or self.data_path
        DIAG.info(f"Ordner öffnen: {target}")
        if not IS_WINDOWS:
            return
        try:
            if path and os.path.isfile(path):
                subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
            else:
                subprocess.Popen(["explorer.exe", os.path.normpath(target)])
        except OSError as exc:
            self.log(f"Ordner nicht geöffnet: {exc}", tag="warn")

    def message_dialog(self, kind, title, message, parent=None, default=None, **kw):
        DIAG.info(f"UI Meldung ({kind}) {title}: {' '.join(str(message).split())}")
        result = self._message_dialog(kind, title, message, parent=parent, default=default, **kw)
        if kind == "ask":
            DIAG.info(f"UI Antwort {title}: {'Ja' if result else 'Nein'}")
        return result

    def _message_dialog(self, kind, title, message, parent=None, default=None, **_kw):
        """Meldung (info, warning, error) oder Ja/Nein-Frage. Enter waehlt die markierte Taste, Escape bricht ab."""
        if self.dialog_hook is not None:
            return self.dialog_hook(kind, title, message, default)
        dlg = self._toplevel(title, parent if parent is not None and parent.winfo_exists() else None)
        dlg.resizable(False, False)
        result = {"ok": False}
        icon, color = {"info": ("ⓘ", ACCENT), "warning": ("⚠", GOLD), "error": ("⚠", RED),
                       "ask": ("?", ACCENT)}[kind]
        row = tk.Frame(dlg, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text=icon, bg=PANEL, fg=color, font=self.f_dialog).pack(side="left", padx=(0, 12), anchor="n")
        tk.Label(row, text=message, bg=PANEL, fg=TEXT, font=self.f_side, justify="left", anchor="w",
                 wraplength=self.narrow_wrap() - int(40 * self.ui_scale)).pack(side="left", fill="x")
        btns = tk.Frame(dlg, bg=PANEL)
        btns.pack(fill="x", pady=(16, 0))

        def done(ok):
            result["ok"] = ok
            dlg.destroy()

        if kind == "ask":
            yes = self._button(btns, "Ja", lambda: done(True), BLUE if default == "yes" else None)
            no = self._button(btns, "Nein", lambda: done(False), None if default == "yes" else BLUE)
            no.pack(side="right")
            yes.pack(side="right", padx=(0, 8))
            first = yes if default == "yes" else no
            dlg.bind("<Return>", lambda e: done(default == "yes"))
        else:
            first = self._button(btns, "OK", lambda: done(True), BLUE)
            first.pack(side="right")
            dlg.bind("<Return>", lambda e: done(True))
        dlg.bind("<Escape>", lambda e: done(False))
        dlg.protocol("WM_DELETE_WINDOW", lambda: done(False))
        self._place(dlg, narrow=True)
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()
        first.focus_set()
        self.root.wait_window(dlg)
        return result["ok"]

    def confirm_danger(self, title, message, action_label):
        """Sichere Rückfrage: 'Abbrechen' ist vorausgewählt, Enter und Escape brechen ab."""
        if self.dialog_hook is not None:
            return self.dialog_hook("danger", title, message, "no")
        dlg = self._toplevel(title)
        dlg.resizable(False, False)
        result = {"ok": False}
        row = tk.Frame(dlg, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="⚠", bg=PANEL, fg=GOLD, font=self.f_dialog).pack(side="left", padx=(0, 12), anchor="n")
        tk.Label(row, text=message, bg=PANEL, fg=TEXT, font=self.f_side, justify="left", anchor="w",
                 wraplength=self.narrow_wrap() - int(40 * self.ui_scale)).pack(side="left", fill="x")
        btns = tk.Frame(dlg, bg=PANEL)
        btns.pack(fill="x", pady=(16, 0))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        def ok():
            result["ok"] = True
            dlg.destroy()

        cancel = self._button(btns, "Abbrechen", dlg.destroy, BLUE)
        cancel.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self._button(btns, action_label, ok, DARK_RED).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        cancel.bind("<Return>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        for w in (dlg, cancel):
            w.bind("<Escape>", lambda e: dlg.destroy())
        self._place(dlg, narrow=True)
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
        """Text-Widget nur neu befuellen, wenn sich der Inhalt geaendert hat. -> True bei Aenderung"""
        key = repr(segments)
        if self._text_cache.get(str(widget)) == key:
            return False
        self._text_cache[str(widget)] = key
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for text, tag in segments:
            tags = tag if isinstance(tag, tuple) else ((tag,) if tag else ())
            widget.insert("end", text, tags)
        widget.configure(state="disabled")
        return True

    def _set_fit(self, label, text, font=None, width=None, **kw):
        """Text setzen und bei Platzmangel sauber mit '…' kuerzen (Volltext bleibt gespeichert)."""
        self._full_text[str(label)] = text
        font = font or self._label_font(label)
        if width is None:
            width = label.winfo_width() - 6
        if isinstance(text, (list, tuple)):  # Varianten, laengste zuerst: die erste, die ganz passt
            text = next((t for t in text if fit_text(font, t, width) == t), text[-1])
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
        self.root.rowconfigure(1, weight=0)
        self.side_boxes, self._section_render = [], {}
        self._drop_key = None
        # «Empfangene Daten» immer sichtbar unten links: eigener Rahmen, je nach Layout unter der Seitenleiste
        # oder unter den Ranglisten
        self.log_frame = tk.Frame(self.root, bg=BG)

        # Seitenleiste (scrollbar), angepinnt oder versenkt (faehrt am linken Rand heraus)
        outer = tk.Frame(self.root, bg=BG, width=self.side_w)
        outer.grid(row=0, column=0, sticky="ns")
        outer.grid_propagate(False)
        self.side_outer = outer
        self.side_strip = tk.Frame(self.root, bg=PANEL2, width=int(12 * self.ui_scale), cursor="hand2")
        tk.Label(self.side_strip, text="›", bg=PANEL2, fg=MUTED, font=self.f_side_head).place(
            relx=0.5, rely=0.5, anchor="center")
        self.side_strip.bind("<Enter>", lambda e: self.side_show())
        self.side_strip.bind("<Button-1>", lambda e: self.side_show())
        self._side_out = False
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0,
                           yscrollincrement=int(40 * self.ui_scale))  # ein Mausrad-Schritt = 40 px
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
            try:
                w = self.root.winfo_containing(event.x_root, event.y_root)
            except KeyError:  # ueber einer offenen Combobox-Liste
                return
            if w is None:
                return
            if event.num == 4:
                step = -1
            elif event.num == 5:
                step = 1
            else:
                # Windows: delta 120 je Raste, Touchpads kleiner; mindestens 1 Schritt (yscrollincrement)
                step = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
            path = str(w)
            if path.startswith(str(outer)):
                if isinstance(w, (tk.Listbox, tk.Text)) or not sbar.winfo_ismapped():
                    return
                canvas.yview_scroll(step, "units")
            elif path.startswith(str(self.cards_canvas)) and self.cards_scrolling:
                self.cards_canvas.yview_scroll(step, "units")

        self.root.bind_all("<MouseWheel>", on_wheel, add="+")
        self.root.bind_all("<Button-4>", on_wheel, add="+")
        self.root.bind_all("<Button-5>", on_wheel, add="+")
        self.side_canvas = canvas

        # Hauptbereich
        main = tk.Frame(self.root, bg=BG)
        main.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(0, 10), pady=10)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(2, weight=1)
        self.main = main
        # Menueleiste oben (Layout «top»): je Abschnitt der Seitenleiste ein Knopf mit Ausklappfeld
        self.topbar = tk.Frame(main, bg=BG)
        self.topbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        status = tk.Frame(main, bg=BG)
        status.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        status.columnconfigure(0, weight=1, uniform="status")
        status.columnconfigure(1, weight=1, uniform="status")
        self.status_row = status
        # Spalte links (Menue oben, Fehlerbericht 26.11.2026): Ticker und Notiz rechts neben LAUFEND/ZIEL,
        # so hoch wie die beiden Felder
        self.top_side = tk.Frame(status, bg=BG, width=400, height=1)
        self.top_side.pack_propagate(False)
        self.banner_locks = {}
        self.live_labels = self._status_box(status, 0, BLUE, "LAUFEND: -", lock=("lock_start", "Start sperren"))
        self.ziel_labels = self._status_box(status, 1, GREEN, "ZIEL: -", lock=("lock_finish", "Ziel sperren"))
        self.lbl_live = self.live_labels[0]
        self.lbl_ziel = self.ziel_labels[0]

        content = tk.Frame(main, bg=BG)
        content.grid(row=2, column=0, columnspan=2, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.content = content
        self.cards_canvas = tk.Canvas(content, bg=BG, highlightthickness=0, bd=0,
                                      yscrollincrement=int(40 * self.ui_scale))
        self.cards_canvas.grid(row=0, column=0, sticky="nsew")
        self.cards_sb = tk.Scrollbar(content, orient="vertical", command=self.cards_canvas.yview)
        self.cards_canvas.configure(yscrollcommand=self.cards_sb.set)
        self.cards_area = tk.Frame(self.cards_canvas, bg=BG)
        self.cards_win = self.cards_canvas.create_window(0, 0, window=self.cards_area, anchor="nw")
        self.cards_canvas.bind("<Configure>", lambda e: self.schedule_font_scale())

        # Eltern main: die Spalte steht im Menue oben neben LAUFEND/ZIEL und Karten (ab der Menueleiste),
        # sonst im Kartenbereich (in_=content)
        self.right_panel = tk.Frame(main, bg=BG, width=400, height=240)
        self.right_panel.grid_propagate(False)
        self.right_panel.pack_propagate(False)
        self.panel_next, self.txt_next = self._panel(self.right_panel, "Als nächstes am Start", NEXT_COUNT * 2 + 3,
                                                     scroll=True, hint="Doppelklick: einfügen · Rechtsklick: DNS")
        self.txt_next.bind("<Double-Button-1>", self.on_next_double)
        self.txt_next.bind("<Button-3>", self.on_next_right)
        self.txt_next.tag_configure("warn", foreground=ORANGE)
        self.txt_next.tag_configure("ok_hand", foreground=GREEN_TEXT, font=self.f_panel_bold)
        self.txt_next.tag_configure("ok_online", foreground=BLUE, font=self.f_panel_bold)
        self.txt_next.bind("<Button-1>", self.on_next_click)
        self.next_sel, self._next_anchor = set(), None
        bar = tk.Frame(self.panel_next.inner, bg=PANEL)
        bar.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        self.lbl_next_count = tk.Label(bar, text="", bg=PANEL, fg=MUTED, font=self.f_ticker_time, anchor="w")
        self.lbl_next_count.pack(side="left")
        self._button(bar, "↓", self.next_scroll_to_next).pack(side="right", padx=(4, 0))
        self._button(bar, "✕", lambda: self.confirm_numbers(None, False)).pack(side="right", padx=(4, 0))
        self._button(bar, "✓", lambda: self.confirm_numbers(None, True), GREEN).pack(side="right")
        self.panel_course, self.txt_course = self._panel(self.right_panel, "Auf Fahrstrecke", 8, scroll=True,
                                                         hint="Klick auf ein Boot: Aktionen · ziehen: überholen")
        self.txt_course.bind("<Button-1>", self.on_course_press)
        self.txt_course.bind("<B1-Motion>", self.on_course_motion)
        self.txt_course.bind("<ButtonRelease-1>", self.on_course_release)
        self.txt_course.tag_configure("drop", background=mix(PANEL, BLUE, 0.45))
        self.txt_course.tag_configure("dragged", foreground=MUTED)
        self._crs_drag = None
        self.txt_course.tag_configure("next", foreground=GREEN_TEXT, font=self.f_panel_bold, spacing1=6)
        self.txt_course.tag_configure("warn", foreground=ORANGE)
        self.panel_note, self.txt_note = self._panel(main, "Notiz", 3)
        self.panel_note.set_outline(GOLD, 2)
        self.txt_note.configure(font=self.f_ticker, fg=TEXT)
        self.txt_note.tag_configure("nr", font=self.f_ticker_bold, foreground=GOLD, spacing1=0)
        self.txt_note.tag_configure("sub", font=self.f_ticker_time, foreground=MUTED)
        self._note_visible = False
        self.panel_ticker, self.txt_ticker = self._panel(main, "Ereignis-Ticker", 6, fit=False)
        self.panel_stats, self.txt_stats = self._panel(self.right_panel, "Statistik", 9)
        # Ticker: groessere, kontrastreichere Schrift (Punkt 9)
        self.txt_ticker.configure(font=self.f_ticker, fg=TEXT, spacing1=0, spacing3=0)
        self.txt_ticker.tag_configure("time", font=self.f_ticker_time, foreground=MUTED)
        self.txt_ticker.tag_configure("ziel", foreground=GREEN_TEXT)
        self.txt_ticker.tag_configure("warn", foreground=GOLD)
        self.txt_ticker.tag_configure("test", foreground=MUTED)
        self.txt_ticker.tag_configure("entry", spacing1=8)
        self.txt_ticker.tag_configure("newest", font=self.f_ticker_bold)

        # Seitenleiste erst jetzt, weil sie auf Kartenbereich und Panels verweist
        self._side_frame = side
        head = tk.Frame(side, bg=BG)
        head.pack(fill="x", padx=10, pady=(8, 0))
        want = int(30 * self.ui_scale)
        size = min(LOGO_SIZES, key=lambda h: abs(h - want))
        path = resource_file(os.path.join("assets", f"swv_logo_h{size}.png"))
        self.logo_img = None
        if path:
            try:
                self.logo_img = tk.PhotoImage(file=path)
            except tk.TclError:
                self.logo_img = None
        if self.logo_img is not None:
            # weisses Feld, damit Rot und Blau auch im dunklen Design gut lesbar sind
            tk.Label(head, image=self.logo_img, bg="#FFFFFF", bd=0, padx=int(8 * self.ui_scale),
                     pady=int(4 * self.ui_scale)).pack(side="left")
        self.btn_pin = self._button(head, "", self.toggle_sidebar_pin)
        self.btn_pin.pack(side="right")
        self.btn_theme = self._button(head, "☀" if THEME == "dark" else "☾", self.toggle_theme)
        self.btn_theme.pack(side="right", padx=(0, 4))
        head2 = tk.Frame(side, bg=BG)  # Versionsnummer und daneben «Fehler melden»
        head2.pack(fill="x", padx=10, pady=(8, 0))
        self.lbl_version = self._version_label(head2)
        self.lbl_version.pack(side="left")
        self._button(head2, "Fehler melden", self.open_report_dialog, RED).pack(
            side="left", padx=(8, 0), fill="x", expand=True)
        self.btn_manual_side = self._button(head2, "Handbuch ▾", lambda: self.open_manual_menu(self.btn_manual_side))
        self.btn_manual_side.pack(side="left", padx=(6, 0))
        self.side_heads = [head, head2]
        self.build_sidebar(side)
        self.build_topbar()
        self.apply_sidebar_mode()

    # ---------------- Seitenleiste versenken / Menue oben ---------------- #
    def build_topbar(self):
        bar = self.topbar
        for w in bar.winfo_children():
            w.destroy()
        self.top_buttons = {}
        bar.columnconfigure(1, weight=1)
        left = tk.Frame(bar, bg=BG)
        left.grid(row=0, column=0, sticky="nw")
        self.lbl_version_top = self._version_label(left)
        self.lbl_version_top.pack(side="left", padx=(4, 6))
        self._button(left, "Fehler melden", self.open_report_dialog, RED).pack(side="left", padx=(0, 6))
        self.btn_manual_top = self._button(left, "Handbuch ▾", lambda: self.open_manual_menu(self.btn_manual_top))
        self.btn_manual_top.pack(side="left", padx=(0, 8))
        right = tk.Frame(bar, bg=BG)
        right.grid(row=0, column=2, sticky="ne")
        self._button(right, "☀" if THEME == "dark" else "☾", self.toggle_theme).pack(side="left", padx=(6, 0))
        self._button(right, "⇥", self.toggle_sidebar_pin).pack(side="left", padx=(6, 0))
        mid = tk.Frame(bar, bg=BG)
        mid.grid(row=0, column=1, sticky="ew")
        for key, title, _box in self.side_boxes:
            short = title.split(" (")[0].replace("Kategorien & Nummern-Range", "Kategorien")
            b = self._button(mid, short + " ▾", lambda k=key: self.toggle_dropdown(k))
            self.top_buttons[key] = b
        self._top_mid = mid
        mid.bind("<Configure>", lambda e: self._flow_topbar())
        self.root.after(50, self._flow_topbar)
        self._conn_level = None
        self.refresh_conn_color()

    def _flow_topbar(self):
        """Abschnittsknoepfe in Zeilen umbrechen, statt Knoepfe aus dem Bild zu schieben."""
        mid = getattr(self, "_top_mid", None)
        if mid is None or not mid.winfo_exists():
            return
        width = max(1, mid.winfo_width())
        x = row = col = 0
        gap = int(4 * self.ui_scale)
        for b in self.top_buttons.values():
            w = b.winfo_reqwidth() + gap
            if x + w > width and col > 0:
                row, col, x = row + 1, 0, 0
            info = b.grid_info() if b.winfo_manager() == "grid" else {}
            if str(info.get("row")) != str(row) or str(info.get("column")) != str(col):
                b.grid(row=row, column=col, padx=(0, gap), pady=(0, gap if row or True else 0), sticky="w")
            x += w
            col += 1
        # Spalten hinter den letzten Knoepfen nicht dehnen
        for c in range(col + len(self.top_buttons)):
            mid.columnconfigure(c, weight=0)

    def connection_level(self):
        """2 = Haupt- und Reserve-Geraet verbunden, 1 = eines, 0 = keines."""
        main = (self.cp is not None and self.cp.connected) or \
               (self.reader is not None and getattr(self, "rs_rx_seen", True))
        return int(bool(main)) + int(bool(self.backup_connected()))

    def refresh_conn_color(self):
        lvl = self.connection_level()
        if lvl != getattr(self, "_conn_level", None):
            self._conn_level = lvl
            color = {2: GREEN, 1: ORANGE, 0: RED}[lvl]
            b = getattr(self, "top_buttons", {}).get("verbindung")
            if b is not None:
                try:
                    b.configure(bg=color, fg=WHITE)
                except tk.TclError:
                    pass
            head = getattr(self, "section_heads", {}).get("verbindung")
            if head is not None:
                try:
                    head.configure(fg={2: GREEN_TEXT, 1: ORANGE, 0: RED}[lvl])
                except tk.TclError:
                    pass
        if not getattr(self, "_conn_color_job", False):
            self._conn_color_job = True

            def again():
                self._conn_color_job = False
                self.refresh_conn_color()
            self.root.after(1000, again)

    def set_nav_layout(self, layout):
        if layout not in ("side", "top") or layout == self.settings.get("nav_layout", "side"):
            return
        self.settings["nav_layout"] = layout
        self.save_settings()
        self.log("Bedienung: " + ("Menü oben mit Ausklappfeldern" if layout == "top" else "Seitenleiste"), tag="ok")
        self.apply_sidebar_mode()

    def _pack_side(self, only=None):
        """Abschnitte der Seitenleiste in der urspruenglichen Reihenfolge packen; only: nur diesen Abschnitt."""
        for w in self.side_heads:
            w.pack_forget()
        for _k, _t, box in self.side_boxes:
            box.pack_forget()
        if only is None:
            for w in self.side_heads:
                w.pack(fill="x", padx=10, pady=(8, 0))
        for k, _t, box in self.side_boxes:
            if only is None or k == only:
                box.pack(fill="x", padx=10, pady=(10, 10 if only else 0))
        self.side_canvas.yview_moveto(0)

    def place_log(self, in_side):
        """«Empfangene Daten»: unter der angepinnten Seitenleiste, im Menue oben als erstes Feld im Kartenraster
        (oben links), damit die Ranglisten die volle Hoehe behalten."""
        lf = self.log_frame
        lf.grid_forget()
        lf.pack_forget()
        left = not in_side and hasattr(self, "right_panel") and self.left_column()
        self.log_in_cards = not in_side and not left
        for _b, txt in getattr(self, "log_tabs", {}).values():
            txt.configure(height=7 if in_side else 4)
        self.log_spacer.configure(width=self.side_w if in_side else 1)
        self.log_box.fit = in_side  # als Feld: Textbereich fuellt die Karte
        if in_side:
            self.log_box.pack_configure(fill="x", expand=False, padx=10, pady=(6, 10))
        else:
            self.log_box.pack_configure(fill="both", expand=True, padx=6, pady=6)
        self.log_box._redraw()
        lf.pack_propagate(not left)
        if in_side:
            lf.grid(row=1, column=0, sticky="ew")
            lf.lift()
        elif left:  # unten in der linken Spalte, feste Hoehe
            self.log_box.fit = False
            self.log_box.pack_configure(fill="both", expand=True, padx=0, pady=(6, 0))
            lf.configure(height=int(170 * self.ui_scale))
            lf.pack_propagate(False)
            first = [w for w in self.right_panel.pack_slaves() if w is not lf]
            # ganz unten: als erstes gepackt (side bottom stapelt in Packreihenfolge von unten nach oben)
            lf.pack(in_=self.right_panel, side="bottom", fill="x", **({"before": first[0]} if first else {}))
            lf.lift()
            self.log_box._redraw()
        if hasattr(self, "cards_area"):
            self.place_right_panel()
            self.layout_cards()

    def log_box_tag(self):
        return "Empfangene Daten"

    def apply_sidebar_mode(self):
        if not self.settings["sidebar_pinned"]:  # frueher: versenkt am linken Rand -> jetzt Menue oben
            self.settings["sidebar_pinned"] = True
            self.settings["nav_layout"] = "top"
        pinned = True
        top = self.settings.get("nav_layout", "side") == "top"
        self.btn_pin.configure(text="⇤" if pinned else "⇥")
        self._side_out = False
        self._drop_key = None
        self.side_outer.place_forget()
        if top:
            self.topbar.grid()
            self.side_strip.grid_remove()
            self.side_outer.grid_remove()
            self._pack_side(only="")
            self.place_log(False)
            if not getattr(self, "_drop_watching", False):
                self._drop_watching = True
                self.root.after(200, self._drop_watch)
            return
        self.topbar.grid_remove()
        self._pack_side()
        for k, rnd in self._section_render.items():
            rnd()
        if pinned:
            self.side_strip.grid_remove()
            self.side_outer.grid(row=0, column=0, sticky="ns")
            self.place_log(True)
        else:
            self.side_outer.grid_remove()
            self.side_strip.grid(row=0, column=0, rowspan=2, sticky="ns")
            self.place_log(False)
            if not getattr(self, "_side_watching", False):
                self._side_watching = True
                self.root.after(200, self._side_watch)

    def toggle_dropdown(self, key):
        """Menue oben: Abschnitt als Ausklappfeld unter seinem Knopf zeigen, nochmals klicken schliesst."""
        if self._drop_key == key:
            return self.close_dropdown()
        self._drop_key = key
        self._pack_side(only=key)
        rnd = self._section_render.get(key)
        if rnd:
            rnd()
        btn = self.top_buttons[key]
        self.root.update_idletasks()
        x = btn.winfo_rootx() - self.root.winfo_rootx()
        y = btn.winfo_rooty() - self.root.winfo_rooty() + btn.winfo_height() + 4
        x = max(0, min(x, self.root.winfo_width() - self.side_w - 4))
        h = max(120, self.root.winfo_height() - y - 10)
        self.side_outer.place(x=x, y=y, width=self.side_w, height=h)
        self.side_outer.lift()

    def close_dropdown(self):
        key, self._drop_key = self._drop_key, None
        self.side_outer.place_forget()
        rnd = self._section_render.get(key)
        if rnd:
            rnd()

    def _drop_watch(self):
        """Ausklappfeld schliessen, wenn die Maus es deutlich verlaesst (Auswahllisten und Dialoge halten es)."""
        if self.settings.get("nav_layout") != "top":
            self._drop_watching = False
            return
        try:
            if self._drop_key is not None:
                px, py = self.root.winfo_pointerxy()
                so = self.side_outer
                x0, y0 = so.winfo_rootx(), so.winfo_rooty()
                inside = x0 - 40 <= px <= x0 + so.winfo_width() + 40 and y0 - 60 <= py <= y0 + so.winfo_height()
                try:
                    w = self.root.winfo_containing(px, py)
                    foreign = w is not None and w.winfo_toplevel() is not self.root
                except KeyError:  # offene Auswahlliste einer Combobox (Tk-intern .popdown): haelt das Feld offen
                    foreign = True
                if not inside and not foreign and self.root.grab_current() is None:
                    self.close_dropdown()
        except tk.TclError:
            pass
        self.root.after(250, self._drop_watch)

    def toggle_sidebar_pin(self):
        """Pfeil: Seitenleiste versenken (Menue oben mit Ausklappfeldern) bzw. wieder anpinnen."""
        top = self.settings.get("nav_layout", "side") != "top"
        self.settings["nav_layout"] = "top" if top else "side"
        self.settings["sidebar_pinned"] = True
        self.save_settings()
        self.log("Seitenleiste " + ("versenkt: Menü oben mit Ausklappfeldern" if top else "angepinnt"), tag="ok")
        self.apply_sidebar_mode()

    def side_show(self):
        if self.settings["sidebar_pinned"] or self._side_out or self.settings.get("nav_layout") == "top":
            return
        self._side_out = True
        self.side_outer.place(x=0, y=0, relheight=1.0, width=self.side_w)
        self.side_outer.lift()

    def side_hide(self):
        if not self._side_out:
            return
        self._side_out = False
        self.side_outer.place_forget()

    def _side_watch(self):
        """Versenkte Seitenleiste: zeigen, wenn die Maus an den linken Rand kommt, verstecken, wenn sie
        die Leiste verlaesst. Offene Auswahllisten, Menues und Dialoge halten sie offen."""
        if self.settings["sidebar_pinned"] or self.settings.get("nav_layout") == "top":
            self._side_watching = False
            return
        try:
            px, py = self.root.winfo_pointerxy()
            x = px - self.root.winfo_rootx()
            y = py - self.root.winfo_rooty()
            inside_root = 0 <= y <= self.root.winfo_height() and x <= self.root.winfo_width()
            if not self._side_out:
                if inside_root and 0 <= x <= int(14 * self.ui_scale):
                    self.side_show()
            else:
                try:
                    w = self.root.winfo_containing(px, py)
                    foreign = w is not None and w.winfo_toplevel() is not self.root
                except KeyError:  # offene Combobox-Liste
                    foreign = True
                busy = self.root.grab_current() is not None or foreign
                if not busy and (x > self.side_w + int(24 * self.ui_scale) or not inside_root or x < -40):
                    self.side_hide()
        except tk.TclError:
            pass
        self.root.after(150, self._side_watch)

    def _status_box(self, parent, col, color, text, lock=None):
        panel = RoundedPanel(parent, fill=color, radius=int(16 * self.ui_scale), fit_height=True)
        panel.grid(row=0, column=col, sticky="nsew", padx=(6, 3) if col == 0 else (3, 6))
        box = panel.inner
        box.configure(padx=int(18 * self.ui_scale), pady=int(8 * self.ui_scale))
        top = tk.Frame(box, bg=color)
        top.pack(fill="x")
        if lock:
            key, label = lock
            ctl = tk.Frame(top, bg=color)
            sw = Switch(ctl, command=lambda k=key: self.toggle_lock(k), scale=self.ui_scale * 0.8,
                        on=self.settings["timing"][key], on_color=ORANGE)
            sw.pack(side="right")
            tk.Label(ctl, text=label, bg=color, fg=WHITE, font=self.f_status_sub).pack(side="right", padx=(0, 6))
            self.banner_locks[key] = (ctl, sw)
            if self.eth_mode():
                ctl.pack(side="right", padx=(8, 0))
        big = tk.Label(top, text=text, bg=color, fg=WHITE, font=self.f_status, anchor="w", width=1)
        big.pack(side="left", fill="x", expand=True)
        sub1 = tk.Label(box, text="", bg=color, fg=WHITE, font=self.f_status_name, anchor="w", width=1)
        sub1.pack(fill="x")
        sub2 = tk.Label(box, text="", bg=color, fg=WHITE, font=self.f_status_sub, anchor="w", width=1)
        sub2.pack(fill="x")
        return big, sub1, sub2

    def _panel(self, parent, title, height, fit=True, scroll=False, hint=""):
        box = RoundedPanel(parent, fill=PANEL, radius=int(16 * self.ui_scale), pad=2, fit_height=fit)
        if not fit:
            box.configure(width=1, height=1)
        frm = box.inner
        head = tk.Frame(frm, bg=PANEL)
        head.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(head, text=title, bg=PANEL, fg=MUTED, font=self.f_panel_head, anchor="w").pack(side="left")
        if hint:
            lh = tk.Label(frm, text=hint, bg=PANEL, fg=MUTED, font=self.f_ticker_time, anchor="w", justify="left")
            lh.pack(fill="x", padx=12)
            lh.bind("<Configure>", lambda e, w=lh: w.configure(wraplength=max(50, e.width - 4)))
            box.hint_label = lh
        holder = tk.Frame(frm, bg=PANEL)
        box.holder = holder
        holder.pack(fill="both", expand=True, pady=(0, 8))
        txt = tk.Text(holder, height=height, width=1, bg=PANEL, fg=TEXT, font=self.f_panel, relief="flat",
                      wrap="word", state="disabled", highlightthickness=0, padx=12, pady=4, cursor="arrow", bd=0)
        if scroll:
            sb = tk.Scrollbar(holder, orient="vertical", command=txt.yview, width=int(10 * self.ui_scale),
                              bg=PANEL2, troughcolor=PANEL, activebackground=BUTTON, relief="flat", bd=0,
                              highlightthickness=0, elementborderwidth=0)
            txt.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y", padx=(0, 6))
        txt.pack(side="left", fill="both", expand=True)
        txt.tag_configure("nr", font=self.f_panel_bold, foreground=TEXT, spacing1=6)
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

        # Verbindung: RS232 (nur auswerten), Ethernet oder USB (CP aktiv steuern)
        b, self.lbl_conn_head = self._section(side, "Verbindung", "verbindung", status=True)
        b.columnconfigure(0, weight=1)
        self.var_conn = tk.StringVar(value=self.settings["conn"]["mode"])
        self._label(b, "Hauptgerät", bold=True, fg=GOLD).grid(row=0, column=0, sticky="w")
        self.conn_seg = Segmented(b, (("rs232", "RS232"), ("ethernet", "Ethernet"), ("usb", "USB")),
                                  self.var_conn, command=self.on_conn_mode_change, font=self.f_side_bold,
                                  scale=self.ui_scale)
        self.conn_seg.grid(row=1, column=0, sticky="ew", pady=(2, 8))
        self.frm_conn_box = b
        net = self.frm_net = tk.Frame(b, bg=PANEL)
        net.columnconfigure(0, weight=1)
        self._label(net, "Netzwerkkarte am PC").grid(row=0, column=0, columnspan=2, sticky="w")
        self.cmb_adapter = self._combo(net, state="readonly")
        self.cmb_adapter.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self._button(net, "⟳", self.refresh_adapters).grid(row=1, column=1, sticky="e", padx=(6, 0), pady=(2, 6))
        rs = self.frm_rs = tk.Frame(b, bg=PANEL)
        rs.columnconfigure(0, weight=1)
        self._label(rs, "COM-Port").grid(row=0, column=0, columnspan=2, sticky="w")
        self.cmb_port = self._combo(rs)
        self.cmb_port.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self._button(rs, "⟳", self.refresh_ports).grid(row=1, column=1, sticky="e", padx=(6, 0), pady=(2, 6))
        self._label(rs, "Baudrate").grid(row=2, column=0, columnspan=2, sticky="w")
        self.e_baud = self._entry(rs, width=10)
        self.e_baud.insert(0, str(self.conn_target.get("baud") or DEFAULT_BAUD))
        self.e_baud.grid(row=3, column=0, sticky="w", pady=(2, 6))
        self._label(rs, "8N1", fg=MUTED).grid(row=3, column=1, sticky="e")
        self._label(rs, "Fahrzeiten nur auswerten. Ethernet und USB steuern den CP aktiv.", fg=MUTED, wraplength=wrap, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(0, 6))
        us = self.frm_usb = tk.Frame(b, bg=PANEL)
        us.columnconfigure(0, weight=1)
        self._label(us, "COM-Port (USB)").grid(row=0, column=0, columnspan=2, sticky="w")
        self.cmb_usb = self._combo(us)
        self.cmb_usb.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self._button(us, "⟳", self.refresh_ports).grid(row=1, column=1, sticky="e", padx=(6, 0), pady=(2, 6))
        self._label(us, "Baudrate").grid(row=2, column=0, columnspan=2, sticky="w")
        self.e_usb_baud = self._entry(us, width=10)
        self.e_usb_baud.insert(0, str(self.settings["conn"]["usb_baud"]))
        self.e_usb_baud.grid(row=3, column=0, sticky="w", pady=(2, 6))
        self._label(us, "8N1", fg=MUTED).grid(row=3, column=1, sticky="e")
        self._label(us, "ACK nach jeder Zeile (Flow Ctrl)").grid(row=4, column=0, sticky="w")
        self.sw_usb_ack = Switch(us, command=self.toggle_usb_ack, scale=self.ui_scale,
                                 on=self.settings["conn"]["usb_ack"])
        self.sw_usb_ack.grid(row=4, column=1, sticky="e")
        tools_u = tk.Frame(us, bg=PANEL)
        tools_u.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 6))
        tools_u.columnconfigure(0, weight=1)
        tools_u.columnconfigure(1, weight=1)
        self._button(tools_u, "Lauf vom CP laden", self.cp_download_run).grid(row=0, column=0, sticky="ew",
                                                                               padx=(0, 3))
        self._button(tools_u, "Simulator", self.open_simulator).grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self._button(tools_u, "Lauf öffnen (TM550)", self.cp_open_run).grid(row=1, column=0, columnspan=2,
                                                                          sticky="ew", pady=(4, 0))
        self._label(us, "CP 545 oder TM550 per USB-Kabel direkt am PC (TM550: «USB Serial Port»). Die App "
                        "steuert ihn wie über Ethernet und erkennt das Gerät selbst. Erscheint "
                        "beim Einstecken kein neuer COM-Port, erkennt Windows den CP nicht (Treiber prüfen). "
                        "«ACK» nur einschalten, wenn am CP «9600bds Flow Ctrl» gewählt ist.",
                    fg=MUTED, wraplength=wrap, justify="left").grid(row=6, column=0, columnspan=2, sticky="w",
                                                                   pady=(0, 6))
        eth = self.frm_eth = tk.Frame(b, bg=PANEL)
        eth.columnconfigure(0, weight=1)
        self._label(eth, "Gerät (CP 545 oder TM550)").grid(row=2, column=0, columnspan=2, sticky="w")
        self.cmb_cp = self._combo(eth, state="normal")
        self.cmb_cp.grid(row=3, column=0, sticky="ew", pady=(2, 6))
        self._button(eth, "Suchen", lambda: self.start_eth_job(connect=False)).grid(
            row=3, column=1, sticky="e", padx=(6, 0), pady=(2, 6))
        self.lbl_eth_hint = self._label(eth, f"PC erhält {PC_IP}, der CP hat ab {CP_NET}{CP_FIRST}. "
                                             "Ethernet am CP nach jedem Einschalten wieder einschalten "
                                             "(F › Einstellungen › Ethernet › Std Connexion). "
                                             "Ohne Adminrechte im Betrieb: in Windows bei der Netzwerkkarte "
                                             f"unter IPv4 › Alternative Konfiguration {PC_IP} / {PC_MASK} "
                                             "eintragen. TM550 (ITS/Vola): am Gerät IP 192.168.1.51 einstellen, "
                                             "Modus TIMING, Start E1, Ziel E4, MANUAL IDENTIFICATION, Lauf offen "
                                             "(Werkseinstellung Port 2101 findet die Suche auch). GPRS Interface "
                                             "(TAG Heuer Timing Online): «127.0.0.1:Port» eintippen, z.B. "
                                             "127.0.0.1:9000.",
                                        fg=MUTED, wraplength=wrap, justify="left")
        self.lbl_eth_hint.grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 6))
        tools = tk.Frame(eth, bg=PANEL)
        tools.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)
        self._button(tools, "Lauf vom CP laden", self.cp_download_run).grid(row=0, column=0, sticky="ew",
                                                                             padx=(0, 3))
        self._button(tools, "Simulator", self.open_simulator).grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self._button(tools, "Lauf öffnen (TM550)", self.cp_open_run).grid(row=1, column=0, columnspan=2,
                                                                        sticky="ew", pady=(4, 0))
        # Reserve-Geraet: eigene Verbindung, unabhaengig von der Art des Hauptgeraets
        bk = self.frm_bk = tk.Frame(b, bg=PANEL)
        bk.columnconfigure(0, weight=1)
        c = self.settings["conn"]
        if not c.get("backup_mode"):
            c["backup_mode"] = ("usb" if c["cp_ip_b"].startswith("usb:") else
                                "ethernet" if c["cp_ip_b"] else "none")
        self.var_bk = tk.StringVar(value=c["backup_mode"])
        self._label(bk, "Reserve-Gerät", bold=True, fg=GOLD).grid(row=0, column=0, sticky="w",
                                                                              pady=(6, 0))
        self.bk_seg = Segmented(bk, (("none", "Keines"), ("ethernet", "Ethernet"), ("usb", "USB")),
                                self.var_bk, command=self.on_backup_mode_change, font=self.f_side_bold,
                                scale=self.ui_scale)
        self.bk_seg.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        be = self.frm_bk_eth = tk.Frame(bk, bg=PANEL)
        be.columnconfigure(0, weight=1)
        self._label(be, "IP-Adresse (Liste oder eintippen)").grid(row=2, column=0, columnspan=2, sticky="w")
        self.cmb_cp_b = self._combo(be)
        self.cmb_cp_b.grid(row=3, column=0, sticky="ew", pady=(2, 6))
        self.cmb_cp_b.bind("<<ComboboxSelected>>", lambda e: self.on_backup_target_change())
        self.cmb_cp_b.bind("<Return>", lambda e: self.on_backup_target_change())
        self._button(be, "Suchen", lambda: self.start_eth_job(connect=False)).grid(
            row=3, column=1, sticky="e", padx=(6, 0), pady=(2, 6))
        bu = self.frm_bk_usb = tk.Frame(bk, bg=PANEL)
        bu.columnconfigure(0, weight=1)
        self._label(bu, "COM-Port (USB)").grid(row=0, column=0, columnspan=2, sticky="w")
        self.cmb_usb_b = self._combo(bu, state="readonly")
        self.cmb_usb_b.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self.cmb_usb_b.bind("<<ComboboxSelected>>", lambda e: self.on_backup_target_change())
        self._button(bu, "⟳", self.refresh_ports).grid(row=1, column=1, sticky="e", padx=(6, 0), pady=(2, 6))
        self.lbl_bk_hint = self._label(bk, "Läuft zur Kontrolle mit und übernimmt Zeiten, die dem Hauptgerät "
                                           "fehlen oder wenn es ausfällt. Beide Geräte an dieselben "
                                           "Start- und Zielgeber.", fg=MUTED, wraplength=wrap, justify="left")
        self.lbl_bk_hint.grid(row=3, column=0, sticky="w", pady=(0, 6))
        self.lbl_bk_state = self._label(bk, "nicht verbunden", fg=MUTED)
        self.lbl_bk_state.grid(row=4, column=0, sticky="w", pady=(0, 4))
        self.btn_bk = self._button(bk, "Reserve verbinden", self.toggle_backup, GREEN)
        self.btn_bk.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        bw = tk.Frame(bk, bg=PANEL)
        bw.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        bw.columnconfigure(0, weight=1)
        self._label(bw, "Wartezeit auf das Hauptgerät (s)").grid(row=0, column=0, sticky="w")
        self.e_bk_wait = self._entry(bw, width=5)
        self.e_bk_wait.insert(0, f"{self.backup_wait():g}")
        self.e_bk_wait.grid(row=0, column=1, sticky="e")
        self.e_bk_wait.bind("<FocusOut>", lambda e: self.save_backup_wait())
        self.e_bk_wait.bind("<Return>", lambda e: self.save_backup_wait())
        self.btn_connect = self._button(b, "Verbinden", self.toggle_connection, GREEN)
        self.btn_connect.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        self.show_conn_frames()
        self.fill_eth_combos()
        self.set_conn_status("nicht verbunden", MUTED)

        # Zeitmessung (Ethernet): Fehlimpulse, Sperren, Rohzeiten
        b = self._section(side, "Zeitmessung", "zeitmessung")
        b.columnconfigure(0, weight=1)
        ts = self.settings["timing"]
        self.timing_entries = {}
        rows = (("prell_start_ms", "Prellzeit Start (ms)"), ("prell_finish_ms", "Prellzeit Ziel (ms)"),
                ("min_run_s", "Mindestfahrzeit (s), 0 = aus"), ("ch_start", "Eingang Start (1-4)"),
                ("ch_finish", "Eingang Ziel (1-4)"), ("lock_nr", "Sperrnummer am Gerät"))
        for i, (key, label) in enumerate(rows):
            self._label(b, label).grid(row=i, column=0, sticky="w", pady=2)
            e = self._entry(b, width=7)
            e.insert(0, f"{ts[key]:g}")
            e.grid(row=i, column=1, sticky="e", pady=2)
            e.bind("<FocusOut>", lambda ev: self.save_timing())
            e.bind("<Return>", lambda ev: self.save_timing())
            self.timing_entries[key] = e
        self.timing_switches = {}
        for i, (key, label) in enumerate((("lock_start", "Start sperren"), ("lock_finish", "Ziel sperren")),
                                         start=len(rows)):
            self._label(b, label).grid(row=i, column=0, sticky="w", pady=(int(5 * self.ui_scale), 0))
            sw = Switch(b, command=lambda k=key: self.toggle_lock(k), scale=self.ui_scale, on=ts[key])
            sw.grid(row=i, column=1, sticky="e", pady=(int(5 * self.ui_scale), 0))
            self.timing_switches[key] = sw
        r = len(rows) + 2
        self._label(b, "Vereinswechsel auf CP drucken").grid(row=r, column=0, sticky="w",
                                                             pady=(int(5 * self.ui_scale), 0))
        self.sw_print_club = Switch(b, command=self.toggle_print_club, scale=self.ui_scale,
                                    on=ts.get("print_club", True))
        self.sw_print_club.grid(row=r, column=1, sticky="e", pady=(int(5 * self.ui_scale), 0))
        self._label(b, "Gilt bei Ethernet und USB. Gesperrte und ungültige Impulse erscheinen unter «Auf "
                       "Fahrstrecke» und lassen sich dort zuordnen. Vereinswechsel: der CP 545 druckt vor dem "
                       "ersten Boot eines neuen Vereins eine Zeile (TM550 hat keinen Drucker).", fg=MUTED,
                    wraplength=wrap, justify="left").grid(row=r + 1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._button(b, "Resultate aus Rohzeiten neu berechnen", self.ask_recompute).grid(
            row=r + 2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._label(b, "Präzision (abschneiden)").grid(row=r + 3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.var_prec = tk.StringVar(value=str(ts.get("prec_digits", 1)))
        Segmented(b, (("0", "1 s"), ("1", "1/10"), ("2", "1/100"), ("3", "1/1000")), self.var_prec,
                  command=self.set_prec_digits, font=self.f_side_bold, scale=self.ui_scale).grid(
            row=r + 4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._button(b, "Präzision am Gerät einstellen", self.cp_write_precision).grid(
            row=r + 5, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # Startliste
        b = self._section(side, "Startliste", "startliste")
        b.columnconfigure(0, weight=1)
        b.columnconfigure(1, weight=1)
        self.lbl_startlist = self._label(b, "Keine Startliste geladen", fg=MUTED, wraplength=wrap, justify="left")
        self.lbl_startlist.grid(row=0, column=0, columnspan=2, sticky="w")
        self.var_mode = tk.StringVar(value=self.settings["wettkampf"])
        self.mode_seg = Segmented(b, (("einzel", "Einzelwettfahren"), ("paar", "Paarwettfahren")), self.var_mode,
                                  command=self.on_mode_change, font=self.f_side_bold, scale=self.ui_scale)
        self.mode_seg.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._button(b, "Excel / CSV laden", self.import_startlist, BLUE).grid(
            row=2, column=0, sticky="ew", pady=(6, 0), padx=(0, 4))
        self._button(b, "Startliste eingeben", self.open_manual_startlist).grid(
            row=2, column=1, sticky="ew", pady=(6, 0), padx=(4, 0))
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
        b = self._section(side, "Manuelle Zeiterfassung", "manuell")
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
        tk.Frame(b, bg=BORDER, height=1).grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        auto = tk.Frame(b, bg=PANEL)
        auto.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(int(5 * self.ui_scale), 0))
        auto.columnconfigure(0, weight=1)
        self._label(auto, "Bereiche automatisch aus der Startliste (bis ..99, ab 900 bis 950)",
                    wraplength=wrap - int(60 * self.ui_scale), justify="left").grid(row=0, column=0, sticky="w")
        self.sw_cats_auto = Switch(auto, command=self.toggle_cats_auto, scale=self.ui_scale,
                                   on=self.settings["cats_auto"])
        self.sw_cats_auto.grid(row=0, column=1, sticky="e")
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
        self.btn_pdf = self._button(b, "PDF und Drucken ▾", self.open_pdf_menu, GREEN)
        self.btn_pdf.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._button(b, "Datenordner öffnen", lambda: self.open_folder()).grid(
            row=3, column=0, sticky="ew", pady=(6, 0))
        self._button(b, "Resultate zurücksetzen", self.reset_results, DARK_RED).grid(
            row=4, column=0, sticky="ew", pady=(6, 0))
        self.lbl_count = self._label(b, "0 Resultate erfasst", fg=MUTED)
        self.lbl_count.grid(row=5, column=0, sticky="w", pady=(4, 0))
        self._label(b, f"Daten, Logs und Fehlerberichte: {self.data_path}", fg=MUTED, wraplength=wrap,
                    justify="left").grid(row=6, column=0, sticky="w", pady=(4, 0))
        self._label(b, "Grösse der Oberfläche").grid(row=9, column=0, sticky="w", pady=(10, 0))
        self.var_size = tk.StringVar(value=str(self.settings.get("ui_size", "auto")))
        Segmented(b, (("auto", "Auto"), ("0.9", "90 %"), ("1.0", "100 %"), ("1.1", "110 %")), self.var_size,
                  command=lambda: self.set_ui_size(self.var_size.get()), font=self.f_side_bold,
                  scale=self.ui_scale).grid(row=10, column=0, sticky="ew", pady=(4, 0))
        upd = tk.Frame(b, bg=PANEL)
        upd.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        upd.columnconfigure(0, weight=1)
        self._label(upd, "Beim Start nach Updates suchen").grid(row=0, column=0, sticky="w")
        self.sw_updates = Switch(upd, command=self.toggle_update_check, scale=self.ui_scale,
                                 on=self.settings["updates"]["check"])
        self.sw_updates.grid(row=0, column=1, sticky="e")
        self._button(b, "Jetzt nach Updates suchen", lambda: self.check_updates(manual=True)).grid(
            row=8, column=0, sticky="ew", pady=(6, 0))

        # Log: eigener Rahmen unten links, immer sichtbar (place_log)
        self.log_spacer = tk.Frame(self.log_frame, bg=BG, width=self.side_w, height=0)
        self.log_spacer.pack()
        logbox = RoundedPanel(self.log_frame, fill=PANEL, radius=int(12 * self.ui_scale), fit_height=True)
        logbox.pack(fill="x", padx=10, pady=(6, 10))
        self.log_box = logbox
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
            txt = tk.Text(holder, height=7, width=1, bg=BG, fg=MUTED, font=self.f_log, relief="flat",
                          state="disabled", wrap="word" if key == "focus" else "none",
                          highlightthickness=0)
            txt.grid(row=0, column=0, sticky="nsew")
            txt.tag_configure("ziel", foreground=GREEN_TEXT)
            txt.tag_configure("warn", foreground=GOLD)
            txt.tag_configure("error", foreground=RED)
            txt.tag_configure("ok", foreground=ACCENT)
            txt.tag_configure("test", foreground=LOG_TEST)
            self.log_tabs[key] = (btn, txt)
        self.show_log_tab("focus")

    def show_log_tab(self, key):
        self.var_logtab.set(key)
        self.log_seg.redraw()
        txt = self.log_tabs[key][1]
        txt.tkraise()
        txt.see("end")

    def set_conn_status(self, text, color):
        self._conn_status = (text, color)
        self._set(self.lbl_conn_head, text=text, fg=color)

    # ---------------- Zeitmessung ---------------- #
    def toggle_print_club(self):
        ts = self.settings["timing"]
        ts["print_club"] = not ts.get("print_club", True)
        self.sw_print_club.set(ts["print_club"])
        self.save_settings()
        self.log("Vereinswechsel auf CP drucken: " + ("ein" if ts["print_club"] else "aus"), tag="ok")

    def save_timing(self):
        ts = self.settings["timing"]
        for key, e in self.timing_entries.items():
            try:
                val = float(e.get().replace(",", "."))
                if key.startswith("ch_"):
                    other = ts["ch_finish" if key == "ch_start" else "ch_start"]
                    if val not in (1, 2, 3, 4) or val == other:
                        raise ValueError
                    val = int(val)
                elif key == "lock_nr":
                    if not 1 <= val <= 9999 or val != int(val):
                        raise ValueError
                    val = int(val)
                    if val in self.participants:
                        messagebox.showwarning("Sperrnummer", f"Nr {val} steht in der Startliste. Als Sperrnummer "
                                                              "eine Nummer wählen, die nicht startet (z.B. 9999).")
                        raise ValueError
                elif val < 0 or val > (100000 if key.endswith("ms") else 3600):
                    raise ValueError
            except ValueError:
                e.delete(0, "end")
                e.insert(0, f"{ts[key]:g}")
                continue
            val = int(val) if key.endswith("ms") else val
            if val != ts[key]:
                ts[key] = val
                self.log(f"Zeitmessung: {key.replace('_', ' ')} = {val:g}", tag="ok")
                if key.startswith("prell_"):
                    self.device_blocking_write()
        apply_channels(ts)
        self.save_settings()

    @staticmethod
    def blocking_value(device, ms):
        """Sperrzeit des Eingangs (Parameter 004): CP 545 in 1/100 s, TM550 in 1/1000 s (Gruppe P, 25.11.2026)."""
        return max(0, min(9999, int(ms) // 10 if device == "cp545" else int(ms)))

    def _blocking_when_idle(self):
        self.device_blocking_write(("A",))

    def cp_when_idle(self, fn, tries=0):
        """fn ausfuehren, wenn das Hauptgeraet nichts zu tun hat und gerade kein Impuls kam (Befehle mit tiefer
        Prioritaet: das Vorladen der naechsten Startnummer geht vor)."""
        if not self.main_connected():
            return
        busy = self.cp_inflight is not None or self.cp_cmds or time.time() - getattr(self, "cp_last_imp", 0) < 3
        if busy and tries < 120:
            self.root.after(500, lambda: self.cp_when_idle(fn, tries + 1))
            return
        fn()

    def device_blocking_write(self, devs=("A", "B")):
        """Prellzeit Start/Ziel der App als Sperrzeit der Eingaenge an die Geraete (Fehlerbericht 26.11.2026:
        Bananenstecker an E4 prellt 0,1 s, der CP ordnete den Zweitimpuls dem naechsten Boot zu)."""
        ts = self.tset()
        for ch, key in ((CH_START, "prell_start_ms"), (CH_FINISH, "prell_finish_ms")):
            ms = ts.get(key, 300)
            if "A" in devs and self.main_connected() and self.cp_device in ("cp545", "tm550"):
                dev, name, val = self.cp_device, self.dev_name(), self.blocking_value(self.cp_device, ms)

                def check(info, ch=ch, val=val, name=name):
                    try:
                        got = int(info["values"][1])
                    except (IndexError, ValueError):
                        return
                    if got == val:
                        sec = got / (100.0 if dev == "cp545" else 1000.0)
                        DIAG.info(f"{name}: Sperrzeit Eingang E{ch} {sec:g} s gesetzt")
                    else:
                        self.log(f"{name}: Sperrzeit Eingang E{ch} meldet {got} statt {val}. Am Gerät unter "
                                 + ("Einstellungen › Sperre" if dev == "cp545" else "Input blocking time")
                                 + " prüfen.", tag="warn")

                def failed(r, ch=ch, name=name):
                    if getattr(self, "_block_fail_told", None) != name:  # einmal pro Geraet
                        self._block_fail_told = name
                        self.log(f"{name}: Sperrzeit Eingang E{ch} nicht gesetzt ({r}). Prellzeit wirkt nur in "
                                 "der App.", tag="warn")

                def read(ch=ch, check=check):
                    self.cp_query(f"#RP 004 {ch:02d}", ("param", "004", ch), on_ok=check)

                def write(ch=ch, val=val, read=read, failed=failed):
                    self.cp_query(f"#WP 004 {ch:02d} {val:04d}", "ack",
                                  on_ok=lambda _i: self.cp_when_idle(read), on_fail=failed)

                self.cp_when_idle(write)
            if "B" in devs and self.backup_connected() and self.cp_b_device in ("cp545", "tm550"):
                val = self.blocking_value(self.cp_b_device, ms)
                DIAG.debug(f"CP B> #WP 004 {ch:02d} {val:04d}")
                self.cp_b.send(f"#WP 004 {ch:02d} {val:04d}")

    def set_prec_digits(self):
        """Nachkommastellen der Resultate. Es wird abgeschnitten wie am Geraet, nicht gerundet."""
        ts = self.settings["timing"]
        try:
            d = max(0, min(3, int(self.var_prec.get())))
        except (AttributeError, ValueError):
            return
        if d == ts.get("prec_digits", 1):
            return
        ts["prec_digits"] = d
        apply_channels(ts)
        self.save_settings()
        self.log(f"Präzision: {PREC_LABEL[d]} (abgeschnitten). Gilt für neue Zeiten; bestehende mit «Resultate aus "
                 "Rohzeiten neu berechnen».", tag="ok")
        self._rank_cache = None
        self.on_data_changed(save=False)
        if self.cp is not None and self.cp.connected:  # verbundenes Geraet sofort mitstellen
            self.cp_write_precision(auto=True)

    def prec_write_value(self, digits, device=None):
        """Wert fuer #WP 001 und erwarteter Rueckgabewert. CP 545 (VB08/VB16, Test 24.11.2026): geschrieben n
        ergibt n Stellen im Resultat (RR, Papier) und n+1 Stellen in den Zeitzeilen, zurueckgelesen n+1.
        TM550 (1.18/1.48): geschrieben = Nachkommastellen = zurueckgelesen."""
        if (device or self.cp_device) == "tm550":
            return digits, digits
        return digits, digits + 1

    def cp_write_precision(self, auto=False):
        """Praezision an Haupt- und Reserve-Geraet schicken (Knopf, und beim Verbinden automatisch)."""
        digits = self.settings["timing"].get("prec_digits", 1)
        if self.cp is None or not self.cp.connected or self.cp_device not in ("cp545", "tm550"):
            if not auto:
                messagebox.showinfo("Präzision", "Zuerst über Ethernet oder USB mit dem Gerät verbinden.")
            return
        w, want = self.prec_write_value(digits)
        name = self.dev_name()
        note = " (Resultat auf dem Papier, Zeitzeilen eine Stelle genauer)" if self.cp_device == "cp545" else ""
        self.backup_write_precision()

        def read_ok(info):
            try:
                got = int(info["values"][0])
            except (IndexError, ValueError):
                got = None
            if got is not None:
                self.cp_prec = got
            if got == want:
                self.log(f"{name}: Präzision {PREC_LABEL.get(digits, digits)} eingestellt{note}.", tag="ok")
            else:
                self.log(f"{name}: Präzision geschrieben, das Gerät meldet {got} statt {want}. Am Gerät prüfen.",
                         tag="warn")

        self.cp_query(f"#WP 001 {w}", "ack",
                      on_ok=lambda _i: self.cp_query("#RP 001", ("param", "001"), on_ok=read_ok),
                      on_fail=lambda r: self.log(f"{name}: Präzision nicht gesetzt ({r})", tag="error"))

    def backup_write_precision(self):
        if self.cp_b is None or not self.cp_b.connected or self.cp_b_device not in ("cp545", "tm550"):
            return
        w, _want = self.prec_write_value(self.settings["timing"].get("prec_digits", 1), self.cp_b_device)
        DIAG.debug(f"CP B> #WP 001 {w}")
        self.cp_b.send(f"#WP 001 {w}")

    def toggle_lock(self, key):
        ts = self.settings["timing"]
        if not ts[key] and self.eth_mode() and self.course:
            boats = ", ".join(str(n) for _t, n, _k in self.course[:6])
            what = "Ziel" if key == "lock_finish" else "Start"
            text = (f"Auf der Strecke: Nr {boats}.\n\n{what} trotzdem sperren? " +
                    ("Zielimpulse werden dann ignoriert, die Boote bekommen keine Zeit, bis das Ziel wieder "
                     "freigegeben ist." if key == "lock_finish" else
                     "Die Boote auf der Strecke bleiben, neue Startimpulse werden ignoriert."))
            if not messagebox.askyesno(f"{what} sperren", text):
                return
        self.set_lock(key, not ts[key])

    def set_lock(self, key, on, from_device=""):
        """Start/Ziel sperren oder freigeben. from_device: Name des Geraets, an dem gesperrt wurde (dann nichts
        zurueck ans Geraet schreiben, nur Sperrnummer nachfuehren)."""
        ts = self.settings["timing"]
        ts[key] = bool(on)
        self.save_settings()
        self.cp_lock_preload(key, ts[key])
        # am Hauptgeraet gesperrt: Reserve nachfuehren; in der App gesperrt: beide Geraete
        self.device_lock_write(key, ts[key], devs=("B",) if from_device else ("A", "B"))
        for sw in (self.timing_switches.get(key), (getattr(self, "banner_locks", {}).get(key) or (None, None))[1]):
            if sw is not None:
                sw.set(ts[key])
        what = "Start" if key == "lock_start" else "Ziel"
        src = f" (am {from_device})" if from_device else ""
        self.log(f"{what}{src} {'gesperrt: Impulse werden ignoriert und unter «Auf Fahrstrecke» als gesperrt aufgeführt' if ts[key] else 'freigegeben'}",
                 tag="warn" if ts[key] else "ok")
        self.add_ticker(f"{what}{src} {'gesperrt' if ts[key] else 'freigegeben'}", "warn" if ts[key] else None)
        self.update_panels()

    # Eingang am Geraet sperren (Gruppe P/Q, 25.11.2026): Parameter 006 pro Eingang.
    # CP 545: 0 gesperrt (schwarzer Balken), 1 offen; die gruene Taste loest trotzdem aus.
    # TM550 1.48: 0 offen, 1 senden, 2 gesperrt; aendert es sich am Geraet, meldet er «&P 023 a b c d».
    @staticmethod
    def lock_value(device, on):
        if device == "tm550":
            return 2 if on else 0
        return 0 if on else 1

    @staticmethod
    def value_locked(device, value):
        return value != 0 if device == "tm550" else value == 0

    def device_lock_write(self, key, on, devs=("A", "B")):
        ch = CH_START if key == "lock_start" else CH_FINISH
        exp = self.__dict__.setdefault("_dev_lock_expect", {})
        if ("A" in devs and self.eth_mode() and self.cp is not None and self.cp.connected
                and self.cp_device in ("cp545", "tm550")):
            dev, name = self.cp_device, self.dev_name()
            exp[("A", ch)] = bool(on)

            def check(info):
                try:
                    locked = self.value_locked(dev, int(info["values"][1]))
                except (IndexError, ValueError):
                    return
                self.device_lock_seen("A", ch, locked)
                if locked != bool(on):
                    self.log(f"{name}: Eingang E{ch} ist am Gerät nicht {'gesperrt' if on else 'offen'}. "
                             "Die App ignoriert die Impulse trotzdem" if on else
                             f"{name}: Eingang E{ch} ist am Gerät noch gesperrt, bitte am Gerät öffnen.", tag="warn")

            self.cp_query(f"#WP 006 {ch:02d} {self.lock_value(dev, on)}", "ack",
                          on_ok=lambda _i: self.cp_query(f"#RP 006 {ch:02d}", ("param", "006", ch), on_ok=check),
                          on_fail=lambda r: self.log(f"{name}: Eingang E{ch} am Gerät nicht "
                                                     f"{'gesperrt' if on else 'geöffnet'} ({r})", tag="warn"))
        if "B" in devs and self.backup_connected() and self.cp_b_device in ("cp545", "tm550"):
            exp[("B", ch)] = bool(on)
            self.cp_b.send(f"#WP 006 {ch:02d} {self.lock_value(self.cp_b_device, on)}")
            self.root.after(800, lambda: self.cp_b.send(f"#RP 006 {ch:02d}") if self.backup_connected() else None)

    def device_lock_read(self, dev="A", silent=False):
        """Zustand von Start- und Zieleingang lesen (CP 545 meldet Aenderungen nicht von selbst)."""
        for ch in (CH_START, CH_FINISH):
            if dev == "A":
                self.cp_query(f"#RP 006 {ch:02d}", ("param", "006", ch), silent=silent)
            elif self.backup_connected():
                if silent:
                    self._rx_silent_b = time.time() + 1.5
                self.cp_b.send(f"#RP 006 {ch:02d}")

    def device_param_event(self, info, dev):
        """&P 002 / 006 / 023 vom Geraet (Antwort oder von selbst)."""
        device = self.cp_device if dev == "A" else self.cp_b_device
        vals, pid = info.get("values") or [], info.get("id")
        try:
            if pid == "006" and len(vals) >= 2:
                self.device_lock_seen(dev, int(vals[0]), self.value_locked(device, int(vals[1])))
            elif pid == "023" and device == "tm550" and len(vals) >= 4:
                for ch in (CH_START, CH_FINISH):
                    self.device_lock_seen(dev, ch, self.value_locked(device, int(vals[ch - 1])))
            elif pid == "002" and device == "tm550" and len(vals) >= 4:
                self.check_tm_channels(dev, vals)
        except ValueError:
            pass

    def device_lock_seen(self, dev, ch, locked):
        key = "lock_start" if ch == CH_START else ("lock_finish" if ch == CH_FINISH else None)
        if key is None:
            return
        seen = self.__dict__.setdefault("_dev_lock", {})
        exp = self.__dict__.setdefault("_dev_lock_expect", {})
        prev = seen.get((dev, ch))
        seen[(dev, ch)] = locked
        if exp.get((dev, ch)) is not None:
            if exp[(dev, ch)] == locked:
                exp.pop((dev, ch))  # eigener Befehl ist angekommen
            return
        what = "Start" if key == "lock_start" else "Ziel"
        name = self.dev_name() if dev == "A" else ("Reserve " + self.DEVICE_LABEL.get(self.cp_b_device or "cp545",
                                                                                       "Gerät"))
        app_on = bool(self.tset().get(key))
        if prev is None:
            # erster Wert nach dem Verbinden (Fehlerbericht 26.11.2026): ist in der App gesperrt, schreibt die App
            # die Sperre ans Geraet (siehe on_cp_connected). Sonst gilt der Zustand des Hauptgeraets, die Reserve
            # bekommt den Zustand der App.
            if locked != app_on:
                if dev == "A" and locked:
                    self.set_lock(key, True, from_device=f"{name} beim Verbinden")
                else:
                    self.log(f"{name}: Eingang E{ch} ({what}) ist am Gerät {'gesperrt' if locked else 'offen'}, "
                             f"in der App {'gesperrt' if app_on else 'offen'}: Gerät wird angepasst.", tag="warn")
                    self.device_lock_write(key, app_on, devs=(dev,))
            return
        if prev == locked:
            return
        if dev == "A" and locked != app_on:
            self.set_lock(key, locked, from_device=name)
        else:
            self.log(f"{name}: Eingang E{ch} ({what}) am Gerät {'gesperrt' if locked else 'geöffnet'}", tag="warn")
            self.add_ticker(f"{name}: {what} am Gerät {'gesperrt' if locked else 'offen'}", "warn")

    def check_tm_channels(self, dev, vals):
        """TM550 &P 002: Zeitmessart, dann Timing 1 (an, Start-, Zieleingang). Einmal pro Verbindung warnen,
        wenn die Eingaenge nicht zu Start/Ziel in der App passen."""
        told = self.__dict__.setdefault("_tm_ch_told", set())
        if dev in told or vals[1] not in ("01", "1"):
            return
        st, fi = int(vals[2]), int(vals[3])
        if (st, fi) == (CH_START, CH_FINISH):
            return
        told.add(dev)
        name = self.dev_name() if dev == "A" else "Reserve TM550"
        self.log(f"{name} misst Start E{st}, Ziel E{fi}, die App erwartet Start E{CH_START}, Ziel E{CH_FINISH}. "
                 "Am TM550 unter Timing modes › Timing › Timing 1 oder in der App unter Zeitmessung › Eingang "
                 "anpassen.", tag="warn")
        self.add_ticker(f"{name}: Eingänge Start/Ziel anders als in der App", "warn")

    def lock_number(self):
        try:
            return max(1, min(9999, int(self.settings["timing"].get("lock_nr", 9999))))
        except (TypeError, ValueError):
            return 9999

    def cp_lock_preload(self, key, on):
        """Sperre am Geraet nachfuehren: CP 545 (und TM550 in TIMING) bekommen die Sperrnummer vorgeladen,
        damit ein Impuls in der Pause keine echte Startnummer verbraucht. Freigeben: wieder abgleichen."""
        ch = CH_START if key == "lock_start" else CH_FINISH
        if not self.eth_mode() or self.cp is None or not self.cp.connected:
            return
        nr = self.lock_number()
        if on:
            if self.cp_caps.get("preload") and (ch == CH_START or self.cp_device != "tm550"):
                if ch == CH_FINISH:
                    self._cp_finish_dirty = True  # nach dem Freigeben echte Zielnummer neu schreiben
                self.cp_write_param("026", ch, nr, "Sperrnummer")
            if self.backup_preload_ok() and (ch == CH_START or self.cp_b_device != "tm550"):
                self.cp_b.send(f"#WP 026 {ch:02d} {nr:04d}")
                if ch == CH_START:
                    self.cp_b_next = nr
            return
        if ch == CH_START:
            self.cp_next_start = None
            self._cp_next_pending = None
            self.cp_sync_next("Start freigegeben")
        else:
            self.cp_finish_want = None
            self._cp_finish_pending = None
            # am CP steht noch die Sperrnummer als naechstes Ziel: echte Nummer in jedem Fall neu schreiben
            self.cp_sync_finish(force=True)

    def ask_recompute(self):
        if not any(k[2] == CH_FINISH for k in self.cp_recs):
            messagebox.showinfo("Neu berechnen", "Es gibt noch keine Rohzeiten vom CP (Ethernet oder USB).")
            return
        if messagebox.askyesno("Neu berechnen", "Alle Fahrzeiten vom CP aus den gespeicherten Rohzeiten neu "
                                                "berechnen?\nVon Hand erfasste Zeiten bleiben."):
            changed, removed = self.recompute_from_raw()
            messagebox.showinfo("Neu berechnen", f"{changed} Zeiten geändert oder ergänzt, {removed} entfernt.")

    # ---------------- Helles / dunkles Design ---------------- #
    def toggle_theme(self):
        new = "dark" if THEME == "light" else "light"
        self.settings["theme"] = new
        self.save_settings()
        self.rebuild_ui(new)
        self.log(f"Design: {'hell' if new == 'light' else 'dunkel'}")

    def rebuild_ui(self, theme):
        """Farbsatz wechseln und Oberflaeche neu aufbauen. Daten und Verbindungen laufen weiter."""
        conn_text, conn_color = getattr(self, "_conn_status", ("nicht verbunden", None))
        conn_key = {MUTED: "muted", GOLD: "gold", RED: "red", GREEN_TEXT: "green"}.get(conn_color, "muted")
        port_sel = self.cmb_port.get() if hasattr(self, "cmb_port") else ""
        apply_palette(theme)
        for w in list(self.root.winfo_children()):
            w.destroy()
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.unbind_all(seq)
        self._text_cache, self._full_text = {}, {}
        self.cards, self.participant_dialogs, self._placed = [], {}, []
        self.upload_win = self.note_win = None
        self._note_visible = False
        self._next_seen = False
        self.prev_top = {}
        self.root.configure(bg=BG)
        set_titlebar(self.root)
        self.setup_fonts()
        self.setup_styles()
        self.build_ui()
        self.refresh_ports()
        if port_sel:
            self.cmb_port.set(port_sel)
        self.build_cards()
        self.apply_show_settings()
        for line, tag, focus in self.log_lines[-LOG_MAX_LINES:]:
            self._log_insert(line, tag, focus)
        color = {"muted": MUTED, "gold": GOLD, "red": RED, "green": GREEN_TEXT}[conn_key]
        self.restore_conn_ui(conn_text, color)
        if self.web.running:
            self.btn_web.configure(text="Browser-Anzeige stoppen", bg=DARK_RED)
            self.set_web_url(f"Läuft: {self.web.url.split('?')[0]}\nSchlüssel im Link verborgen, mit «Link kopieren» "
                             "oder «QR-Code» weitergeben.", GREEN_TEXT)
        self.update_startlist_label()
        self.update_live_info()
        self.update_ziel_info()
        self.update_panels()
        self.update_window_title()

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
        base = f"SWV Live-Ranking v{APP_VERSION}  |  TAG Heuer CP 545"
        self.root.title(f"{base}  |  {label}" if label else base)
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
        return any(show.get(k) for k in ("naechste", "ticker", "statistik")) or self._note_visible \
            or self.eth_mode()

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
            if self.left_column():
                opts["pady"] = (0, 4)
            if ticker_packed:
                opts["before"] = self.panel_ticker
            else:
                opts["in_"] = self.top_side if self.left_column() else self.right_panel
            self.panel_note.pack(**opts)
            self.panel_note.tk.call("raise", self.panel_note._w)
        self.place_right_panel()
        self.root.after_idle(self.fit_top_side)

    def fit_top_side(self):
        """Ticker/Notiz neben LAUFEND/ZIEL: mit Notiz so hoch, dass darunter noch zwei Ticker-Eintraege Platz
        haben (die Reihe mit LAUFEND/ZIEL waechst dann mit)."""
        try:
            h = 1
            if self.left_column() and self._note_visible:
                h = self.panel_note.inner.winfo_reqheight() + 2 * self.panel_note.pad + int(96 * self.ui_scale)
            if int(self.top_side.cget("height")) != h:
                self.top_side.configure(height=h)
        except (AttributeError, tk.TclError):
            pass

    def apply_show_settings(self):
        show = self.settings["show"]
        for frame in (self.panel_next, self.panel_course, self.panel_note, self.panel_ticker, self.panel_stats):
            frame.pack_forget()
        self._note_visible = False
        self.txt_stats.configure(height=len(self.categories) + 3)
        # Spalte links (Menue oben): «Als naechstes» und «Auf Fahrstrecke» kuerzer (beide scrollen), damit der
        # Ereignis-Ticker ueber «Empfangene Daten» Platz fuer etwa 6 Eintraege hat
        left = self.left_column()
        self.txt_next.configure(height=4 if left else NEXT_COUNT * 2 + 3)
        # Spalte links: «Als naechstes» fuellt die freie Hoehe
        self.panel_next.fit = not left
        if left:
            self.panel_next.configure(height=1)
        else:
            self.panel_next._fit()
        self.panel_next._redraw()
        self.txt_course.configure(height=4 if left else 8)
        for box in (self.panel_next, self.panel_course):  # Bedienhinweise in der schmalen Spalte weglassen
            lh = getattr(box, "hint_label", None)
            if lh is not None:
                if left:
                    lh.pack_forget()
                elif not lh.winfo_manager():
                    lh.pack(fill="x", padx=12, before=box.holder)
        vis = dict(show)
        vis["course"] = self.eth_mode()
        rp = self.right_panel
        if left:
            # Spalte links ab der Menueleiste: Als naechstes (fuellt), Auf Fahrstrecke, Statistik; Ticker oben
            # rechts neben LAUFEND/ZIEL
            layout = ((self.panel_course, "course", "bottom", False, rp), (self.panel_stats, "statistik", "bottom",
                                                                          False, rp),
                      (self.panel_next, "naechste", "top", True, rp), (self.panel_ticker, "ticker", "top", True,
                                                                        self.top_side))
            for frame, key, side, expand, host in layout:
                if vis.get(key):
                    frame.pack(in_=host, side=side, fill="both" if expand else "x", expand=expand,
                               pady=(6, 0) if side == "bottom" else (0, 0 if host is self.top_side else 6))
                    frame.tk.call("raise", frame._w)
        elif self.panel_orient == "right":
            layout = ((self.panel_next, "naechste", "top", False), (self.panel_course, "course", "top", False),
                      (self.panel_stats, "statistik", "bottom", False), (self.panel_ticker, "ticker", "top", True))
            for frame, key, side, expand in layout:
                if vis.get(key):
                    frame.pack(in_=rp, side=side, fill="both" if expand else "x", expand=expand,
                               pady=(6, 0) if side == "bottom" else (0, 6))
                    frame.tk.call("raise", frame._w)
        else:
            for frame, key in ((self.panel_next, "naechste"), (self.panel_course, "course"),
                               (self.panel_ticker, "ticker"), (self.panel_stats, "statistik")):
                if vis.get(key):
                    frame.pack(in_=rp, side="left", fill="both", expand=True, padx=(0, 6))
                    frame.tk.call("raise", frame._w)
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

    def left_column(self):
        """Menue oben: Als naechstes am Start, Auf Fahrstrecke, Ticker und ganz unten «Empfangene Daten» in einer
        Spalte links, die Ranglisten rechts daneben."""
        return self.settings.get("nav_layout", "side") == "top" and self.panel_orient == "right"

    def place_right_panel(self):
        left = self.left_column()
        self.cards_canvas.grid_configure(column=1 if left else 0)
        self.content.columnconfigure(1, weight=1 if left else 0)
        self.content.columnconfigure(0, weight=0 if left else 1)
        if self.cards_sb.winfo_manager():
            self.cards_sb.grid_configure(column=2 if left else 1)
        # Menue oben: Spalte links ab der Menueleiste, LAUFEND/ZIEL/Ticker und Karten rechts daneben
        self.status_row.grid_configure(column=1 if left else 0, columnspan=1 if left else 2)
        self.content.grid_configure(column=1 if left else 0, columnspan=1 if left else 2)
        if left:
            self.top_side.configure(width=int(self.right_panel.cget("width")))
            self.top_side.grid(row=0, column=2, sticky="nsew", padx=(3, 6))
        else:
            self.top_side.grid_remove()
        if not self.any_panel() and not left:
            self.right_panel.grid_remove()
            return
        if left:
            self.right_panel.grid(in_=self.main, row=1, column=0, rowspan=2, columnspan=1, sticky="ns",
                                  padx=(0, 6), pady=(0, 6))
        elif self.panel_orient == "right":
            self.right_panel.grid(in_=self.content, row=0, column=2, rowspan=1, columnspan=1, sticky="ns",
                                  padx=(6, 6), pady=6)
        else:
            self.right_panel.grid(in_=self.content, row=1, column=0, rowspan=1, columnspan=3, sticky="ew",
                                  padx=6, pady=(6, 6))
        self.right_panel.lift()
        for pnl in (self.panel_ticker, self.panel_note):  # Kinder von main: ueber der Spalte halten
            pnl.tk.call("raise", pnl._w)

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
                l_txt = tk.Label(f, text="", font=font, bg=PANEL, fg=TEXT, anchor="w")
                l_arr = tk.Label(f, text="", font=font, bg=PANEL, fg=TEXT)
                l_time = tk.Label(f, text="", font=font, bg=PANEL, fg=TEXT, anchor="w")
                l_pen = tk.Label(f, text="", font=self.f_pen, bg=PANEL, fg=ORANGE, anchor="w")
                l_sub = tk.Label(f, text="", font=self.f_sub, bg=PANEL, fg=MUTED, anchor="w")
                l_txt.grid(row=r_main, column=0, sticky="sw", padx=(14, 4))
                l_arr.grid(row=r_main, column=1, sticky="s", padx=6)
                l_time.grid(row=r_main, column=2, sticky="sw", padx=(4, 4))
                l_pen.grid(row=r_main, column=3, sticky="sw", padx=(0, 14), pady=(0, 4))
                l_sub.grid(row=r_sub, column=0, columnspan=4, sticky="nw", padx=(14, 14))
                f.rowconfigure(r_main, weight=1)
                f.rowconfigure(r_sub, weight=0)
                row_d = {"txt": l_txt, "arrow": l_arr, "time": l_time, "pen": l_pen, "sub": l_sub,
                         "nr": None, "rank": None, "color": TEXT, "sub_full": ""}
                for wdg in (l_txt, l_arr, l_time, l_sub):
                    wdg.bind("<Button-3>", lambda e, r=row_d: self.card_row_menu(r, e))
                rows_w.append(row_d)
            card = {"cat": cat, "frame": f, "box": box, "title": title, "rows": rows_w}
            title.bind("<ButtonPress-1>", lambda e, c=card: self.drag_start(c))
            title.bind("<B1-Motion>", self.drag_motion)
            title.bind("<ButtonRelease-1>", self.drag_end)
            self.cards.append(card)

        self.layout_cards()
        # Bisherige Top-Listen behalten: ein Neuaufbau (z.B. Kategorien nachgefuehrt) darf das Blinken
        # eines gerade eingetroffenen Resultats nicht verschlucken
        old = dict(self.prev_top)
        self.prev_top = old
        self.update_rankings(initial=not old)
        if hasattr(self, "lbl_count"):
            self.apply_show_settings()
        self.schedule_font_scale()

    def card_row_menu(self, row, event):
        nr = row.get("nr")
        if nr is None:
            return
        menu = self._menu()
        menu.add_command(label=self.order_label(nr), state="disabled")
        menu.add_separator()
        menu.add_command(label="Disqualifiziert (DSQ)", command=lambda: self.set_status(nr, "DSQ"))
        menu.add_command(label="Teilnehmer bearbeiten ...", command=lambda: self.open_participant_dialog(nr))
        self._popup(menu, event)

    def layout_cards(self):
        nc = max(1, self.card_cols)
        off = 1 if getattr(self, "log_in_cards", False) else 0  # Feld «Empfangene Daten» oben links
        rows = max(1, -(-(len(self.cards) + off) // nc))
        for r in range(40):
            self.cards_area.rowconfigure(r, weight=1 if r < rows else 0, uniform="row" if r < rows else "")
        for c in range(3):
            self.cards_area.columnconfigure(c, weight=1 if c < nc else 0, uniform="col" if c < nc else "")
        if off:
            self.log_frame.grid(in_=self.cards_area, row=0, column=0, sticky="nsew", padx=0, pady=0)
            self.log_frame.tk.call("raise", frame._w)
        for i, card in enumerate(self.cards):
            j = i + off
            card["box"].grid(row=j // nc, column=j % nc, sticky="nsew", padx=6, pady=6)

    def card_title(self, cat):
        title = f"{cat['name']}   {cat['min']}-{cat['max']}"
        if cat.get("rekord"):
            title += f"   Rekord {cat['rekord']}s"
        nk = [f"{nr} {code}" for nr, code in sorted(self.status.items())
              if (self.category_of(nr) or {}).get("name") == cat["name"]]
        if nk:
            title += "   nicht klassiert: " + ", ".join(nk[:4]) + (" ..." if len(nk) > 4 else "")
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
        try:
            target = self.card_from_widget(self.root.winfo_containing(event.x_root, event.y_root))
        except KeyError:
            target = None
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
        boxw = (mw - (2 * int(self.right_panel.cget("width")) if self.left_column() else 0)) / 2
        sp = max(int(14 * s), min(int(52 * s), int(min(boxw / 23, mh / 22))))
        self.f_status.configure(size=-sp)
        self.f_status_name.configure(size=-max(int(12 * s), int(sp * 0.62)))
        self.f_status_sub.configure(size=-max(int(11 * s), int(sp * 0.55)))
        pp = max(int(12 * s), min(int(17 * s), int(mh / 62)))
        self.f_panel.configure(size=-pp)
        self.f_panel_bold.configure(size=-pp)
        self.f_panel_head.configure(size=-pp)
        tp = int(pp * (1.0 if self.left_column() else 1.33))  # schmale Spalte links: Ticker wie die Listen
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
            if int(self.top_side.cget("width")) != panel_w:
                self.top_side.configure(width=panel_w)
        else:
            panel_h = int(max(200 * s, min(320 * s, mh * 0.3)))
            if int(self.right_panel.cget("height")) != panel_h:
                self.right_panel.configure(height=panel_h)
        if changed:
            self.apply_show_settings()
            if self.settings.get("nav_layout", "side") == "top":
                self.place_log(False)
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
            self.cards_sb.grid(row=0, column=2 if self.left_column() else 1, sticky="ns")
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
                if self.status.get(nr) in ("DNF", "DSQ", "DNS"):
                    continue  # nicht klassiert
                cat = self.category_of(nr)
                if cat:
                    groups[cat["name"]].append(nr)
            out = {}
            for name, nrs in groups.items():
                # gleiche angezeigte Zeit = gleicher Rang; bei Gleichstand hoehere Startnummer zuerst (wie SkiPro)
                entries = sorted(((round(self.total_secs(nr) + 1e-9, 2), -nr, nr) for nr in nrs))
                ranked, prev, rank = [], None, 0
                for i, (t, _neg, nr) in enumerate(entries):
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
            if hasattr(self, "card_inner_w"):
                self._set_fit(card["title"], self.card_title(cat), self.f_title, self.card_inner_w)
            prev = self.prev_top.get(cat["name"])
            if not initial and prev is not None:
                for nr in top - prev:
                    self.blink[nr] = now + BLINK_SECONDS
            self.prev_top[cat["name"]] = top

            for k, row in enumerate(card["rows"]):
                pen_txt, sub_txt = "", ""
                if k < len(ranked):
                    rank, nr, _ = ranked[k]
                    color = GOLD if rank == 1 else TEXT
                    font = self.f_first if rank == 1 else self.f_row
                    txt, arrow, tstr = f"{rank}. Nr. {nr}", "➔", f"{self.disp_time(nr)}s"
                    pen = self.penalty(nr)
                    pen_txt = f"+{pen}" if pen else ""
                    sub_txt = self.who_text(nr)
                else:
                    rank = nr = None
                    color, font = TEXT, self.f_row
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
        ts = self.settings["timing"]
        for key in ("lock_start", "lock_finish"):
            for sw in (getattr(self, "timing_switches", {}).get(key),
                       (getattr(self, "banner_locks", {}).get(key) or (None, None))[1]):
                if sw is not None:
                    try:
                        if ts[key]:
                            sw.blink(self.blink_phase)
                        elif getattr(sw, "_blink", None) is not None:
                            sw._blink = None
                            sw._draw()
                    except tk.TclError:
                        pass
        now = time.time()
        for nr in [n for n, until in self.blink.items() if until <= now]:
            del self.blink[nr]
        for card in self.cards:
            for row in card["rows"]:
                if row["nr"] is not None:
                    self._set(row["arrow"], fg=self._arrow_color(row, now))
        self.root.after(BLINK_INTERVAL_MS, self.blink_tick)

    def on_data_changed(self, save=True):
        self.sync_categories()
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
        if self.eth_mode():
            self.root.after(50, lambda: self.print_next_club(nr, event="finish"))

    def ticker_for_final(self, nr, cat, before, prev):
        who = self.who_text(nr)
        who_txt = f" {who}" if who else ""
        disp = f"{self.disp_time(nr)}s"
        if self.status.get(nr) in ("DSQ", "DNF"):
            self.add_ticker(f"Nr {nr}{who_txt} im Ziel: {disp} (disqualifiziert, nicht klassiert)", "warn")
            return
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
        if self._quiet:
            return
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
        # schmales Feld: Kategorie weglassen (steht in der Zeile darunter), damit die Zeit sichtbar bleibt
        self._set_fit(big, (f"ZIEL: Nr {nr} ({cat_name}) ➔ {res['str']}s{pen_txt}",
                            f"ZIEL: Nr {nr} ➔ {res['str']}s{pen_txt}"))
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
        idx = self.order_index.get(self.order_anchor(), -1)
        on_course = {n for _t, n, _k in self.course} if self.eth_mode() else set()
        out = []
        for nr in self.start_order[idx + 1:]:
            if nr not in self.results and nr not in on_course and nr not in self.status:
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
                nxt = self.next_starters(count=len(self.start_order))  # alle noch nicht gestarteten
                if not nxt:
                    seg.append(("Keine weiteren Starts in der Startliste", "sub"))
                # naechste Nummer zuunterst, darueber die folgenden
                used = any(self.confirm_state(n) for n in self.start_order)
                for i, nr in reversed(list(enumerate(nxt))):
                    p = self.participants.get(nr, {})
                    cat = self.category_of(nr)
                    row = f"row{nr}"
                    first = i == 0
                    st = self.confirm_state(nr)
                    seg.append(("✓ " if st else "   ", (("ok_hand" if st == "hand" else "ok_online") if st
                                                         else "nr", row)))
                    head = f"Nr {nr}  {display_name(p, mode) or '-'}"
                    if first and self.eth_mode() and self.cp is not None and self.cp_next_start == nr:
                        head += "   ✓ im CP"
                    extra = ("warn",) if first and used and not st else ()
                    seg.append((head + "\n", ("nr", row) + (("next",) if first else ()) + extra))
                    info = "  ·  ".join(x for x in (p.get("verein", ""), cat["name"] if cat else
                                                    ("Test" if self.is_test(nr) else "")) if x)
                    seg.append((f"{info}\n", ("sub", row)))
                    notes = "  ·  ".join(x for x in (p.get("notiz", ""), p.get("bemerkung", "")) if x)
                    if notes and show.get("notizen"):
                        seg.append((f"{notes}\n", ("note", row)))
            at_bottom = self.txt_next.yview()[1] >= 0.98
            top = self.txt_next.yview()[0]
            if self._set_text(self.txt_next, seg):
                if at_bottom or not self._next_seen:
                    self.txt_next.see("end")
                else:
                    self.txt_next.yview_moveto(top)
                self._next_seen = True
            self.paint_next_selection()
            done = sum(1 for n in nxt if self.confirm_state(n)) if self.start_order else 0
            self.lbl_next_count.configure(text=f"{done} von {len(nxt)} bestätigt" if self.start_order else "")
        if self.eth_mode():
            self.update_course_panel()
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

    # ---------------- Als naechstes: Nummer einfuegen ---------------- #
    @staticmethod
    def _tag_nr(widget, event, prefix):
        idx = widget.index(f"@{event.x},{event.y}")
        for tag in widget.tag_names(idx):
            if tag.startswith(prefix) and tag[len(prefix):].isdigit():
                return int(tag[len(prefix):])
        return None

    def confirm_state(self, nr):
        """'hand' (gruen, von Hand) geht vor 'online' (blau, vom Onlinetool), sonst None."""
        p = self.participants.get(nr) or {}
        return "hand" if p.get("best_hand") else ("online" if p.get("best_online") else None)

    def on_next_click(self, event):
        nr = self._tag_nr(self.txt_next, event, "row")
        if nr is None:
            return "break"
        order = self.next_starters(count=len(self.start_order))
        if event.state & 0x0001 and self._next_anchor in order and nr in order:  # Shift: Bereich
            a, b = sorted((order.index(self._next_anchor), order.index(nr)))
            self.next_sel |= set(order[a:b + 1])
        elif event.state & 0x0004:  # Ctrl: einzeln dazu oder weg
            self.next_sel ^= {nr}
            self._next_anchor = nr
        else:
            self.next_sel = set() if self.next_sel == {nr} else {nr}
            self._next_anchor = nr
        self.paint_next_selection()
        return "break"

    def paint_next_selection(self):
        txt = self.txt_next
        for tag in txt.tag_names():
            if tag.startswith("row") and tag[3:].isdigit():
                txt.tag_configure(tag, background=mix(PANEL, BLUE, 0.35) if int(tag[3:]) in self.next_sel else "")

    def confirm_numbers(self, nrs, on):
        """Gewaehlte (oder angegebene) Nummern von Hand bestaetigen bzw. die Bestaetigung aufheben."""
        nrs = sorted(nrs if nrs is not None else self.next_sel)
        if not nrs:
            self.log("Als nächstes am Start: zuerst Nummern anklicken (Ctrl/Shift für mehrere)", tag="warn")
            return
        for nr in nrs:
            p = self.participants.get(nr)
            if p is not None:
                if on:
                    p["best_hand"] = True
                else:
                    p.pop("best_hand", None)
        self.log(f"{'Bestätigt' if on else 'Bestätigung aufgehoben'}: Nr " + ", ".join(map(str, nrs)), tag="ok")
        self.next_sel = set()
        self.save_autosave()
        self.update_panels()

    def reset_confirmations(self):
        if not self.message_dialog("ask", "Bestätigungen zurücksetzen",
                                   "Alle Bestätigungen von Hand (grüne Haken) entfernen? Die blauen Haken vom "
                                   "Onlinetool bleiben."):
            return
        for p in self.participants.values():
            p.pop("best_hand", None)
        self.save_autosave()
        self.update_panels()

    def next_scroll_to_next(self):
        self.txt_next.see("end")

    def on_next_double(self, event):
        nr = self._tag_nr(self.txt_next, event, "row")
        if nr is not None:
            self.open_insert_dialog(nr)
        return "break"

    def open_insert_dialog(self, before):
        """Neue Nummer unterhalb von 'before' einfuegen: sie startet direkt vor 'before'."""
        dlg = self._toplevel("Nummer einfügen")
        dlg.columnconfigure(0, weight=1)
        tk.Label(dlg, text=f"Neue Nummer unterhalb von {self.order_label(before)} einfügen. Sie startet direkt "
                           f"vor Nr {before}.", bg=PANEL, fg=TEXT, font=self.f_side, justify="left", anchor="w",
                 wraplength=self.narrow_wrap()).grid(row=0, column=0, sticky="w")
        self._label(dlg, "Startnummer").grid(row=1, column=0, sticky="w", pady=(10, 0))
        e = self._entry(dlg, width=8)
        e.grid(row=2, column=0, sticky="ew", pady=(2, 0))
        msg = tk.Label(dlg, text="", bg=PANEL, fg=RED, font=self.f_side, justify="left", anchor="w",
                       wraplength=self.narrow_wrap())
        msg.grid(row=3, column=0, sticky="w", pady=(4, 0))

        def ok(_e=None):
            err = self.insert_number(e.get().strip(), before)
            if err:
                msg.configure(text=err)
                e.focus_set()
                return "break"
            dlg.destroy()
            return "break"

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self._button(btns, "Einfügen", ok, BLUE).pack(side="right")
        self._button(btns, "Abbrechen", dlg.destroy).pack(side="right", padx=(0, 8))
        dlg.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda ev: dlg.destroy())
        self._place(dlg, narrow=True)
        dlg.focus_force()
        e.focus_set()
        return dlg

    def insert_number(self, text, before):
        """-> Fehlertext oder None. Bekannte Nummern werden verschoben, unbekannte neu angelegt."""
        try:
            nr = int(text)
            if nr <= 0:
                raise ValueError
        except ValueError:
            return "Gültige Startnummer eingeben"
        if nr == before:
            return "Nicht dieselbe Nummer"
        if before not in self.order_index:
            return f"Nr {before} ist nicht mehr in der Startliste"
        known = nr in self.participants
        test = not known and self.range_category(nr) is None
        if not known and not test:
            cat = self.range_category(nr)
            self.participants[nr] = {
                "nr": nr, "p1": "", "p2": "", "kategorie": cat["name"], "verein": "", "vnr": "", "staver": "",
                "fg": "", "bemerkung": "", "notiz": "", "strafpunkte": 0, "unknown": True}
        was_dns = self.status.get(nr) == "DNS"
        if was_dns:
            self.status.pop(nr, None)
            self._rank_cache = None
            self.log(f"Nr {nr}: Status DNS aufgehoben, wieder in der Startreihenfolge", tag="ok")
            self.add_ticker(f"Nr {nr}{(' ' + self.who_text(nr)) if self.who_text(nr) else ''} startet doch", None)
            self.save_autosave()
        order = [n for n in self.start_order if n != nr]
        order.insert(order.index(before), nr)
        moved = nr in self.order_index
        self.start_order = order
        self.rebuild_order_index()
        what = "verschoben" if moved else "eingefügt"
        self.log(f"{'Testnummer' if test else 'Nr'} {nr} vor Nr {before} {what}", tag="test" if test else "ok")
        self.update_startlist_label()
        self.on_data_changed()
        self.cp_sync_next("Startliste")
        if not known and not test:
            self.add_ticker(f"Nr {nr} vor Nr {before} eingefügt", None)
            self.open_participant_dialog(nr, unknown=True)
        return None

    # ---------------- Auf Fahrstrecke ---------------- #
    def update_course_panel(self):
        """Wie ein Fluss von oben nach unten: oben das zuletzt gestartete Boot, unten das Boot,
        das als naechstes ins Ziel kommt, darunter der letzte Zieleinlauf und Impulse ohne Zuordnung."""
        if not hasattr(self, "txt_course"):
            return
        if self._crs_drag and self._crs_drag.get("active"):
            return  # waehrend dem Ziehen nicht neu zeichnen
        mode = self.settings["wettkampf"]
        ts = self.settings["timing"]
        seg = []
        locks = [w for w, k in (("Start", "lock_start"), ("Ziel", "lock_finish")) if ts[k]]
        if locks:
            seg.append((f"{' und '.join(locks)} gesperrt\n", "warn"))
        online = self.cp is not None and self.cp.connected
        if not online and not self.course:
            seg.append(("Keine Verbindung zum CP (Ethernet oder USB)\n", "sub"))
        elif not self.course:
            seg.append(("Kein Boot auf der Strecke\n", "sub"))
        n = len(self.course)
        # eine Zeile pro Boot, nur Nr und Name (Fehlerbericht 26.11.2026: mindestens 3 Boote ohne Scrollen)
        for i, (tod, nr, _key) in reversed(list(enumerate(self.course))):
            p = self.participants.get(nr, {})
            tag = f"crs{nr}"
            nxt = i == 0 and n > 1
            moved = nxt and (self.finish_override == nr or "order" in self.cp_recs[_key])
            seg.append((f"{'▸ ' if nxt else ''}Nr {nr}   {display_name(p, mode) or '-'}"
                        f"{'  (überholt)' if moved else ''}\n", ("next" if nxt else "nr", tag)))
            if self.status.get(nr) == "DSQ":
                seg.append(("DSQ, fährt noch ins Ziel (nicht klassiert)\n", ("warn", tag)))
            crec = self.cp_recs.get(_key)
            if crec and crec.get("cp_nr") and crec["cp_nr"] != nr and self.eth_mode():
                seg.append((f"CP führt noch Nr {crec['cp_nr']}: am CP {crec['cp_nr']} R E1 {nr} Enter\n",
                            ("warn", tag)))
        rec = self.cp_recs.get(self.last_finish_key) if self.last_finish_key else None
        if rec and rec["status"] == "ok" and rec["nr"] in self.results:
            seg.append((f"Zuletzt im Ziel: Nr {rec['nr']}  {self.results[rec['nr']]['str']}s\n", ("time", "lastfin")))
        pend = self.pending_impulses()
        self._pending_keys = pend
        if pend:
            seg.append(("\nImpulse ohne Zuordnung\n", "sub"))
            why = {"locked": "gesperrt", "nobody": "ohne Boot", "reserve": "nur Reserve", "fehl": "Fehlimpuls", "prell": "Prellzeit",
                   "unassigned": "Nummer am CP entfernt"}
            for j, k in enumerate(pend):
                r = self.cp_recs[k]
                where = "Start" if k[2] == CH_START else "Ziel"
                seg.append((f"{where} {fmt_tod(r['abs'] % 86400)}  ({why.get(r['status'], r['status'])})\n",
                            ("warn", f"imp{j}")))
        if self.left_column():
            lines = sum(t.count("\n") for t, _tag in seg)
            h = max(4, min(9, lines + 1))  # +1: Zeilenabstand (spacing1) der Bootzeilen
            if int(self.txt_course.cget("height")) != h:
                self.txt_course.configure(height=h)
        shape = (tuple(c[1] for c in self.course), self.last_finish_key, tuple(pend))
        at_bottom = self.txt_course.yview()[1] >= 0.98
        top = self.txt_course.yview()[0]
        if self._set_text(self.txt_course, seg):
            if at_bottom or shape != getattr(self, "_course_shape", None):
                self.txt_course.see("end")  # unten bleiben; von Hand hochgescrollt bleibt es oben
            else:
                self.txt_course.yview_moveto(top)
            self._course_shape = shape

    def _menu(self):
        if self._course_menu is not None:
            try:
                self._course_menu.destroy()
            except tk.TclError:
                pass
        self._course_menu = LoggedMenu(self.root, tearoff=0, bg=PANEL2, fg=TEXT, activebackground=BLUE,
                                    activeforeground=WHITE, font=self.f_side, bd=0, relief="flat")
        return self._course_menu

    @staticmethod
    def _popup(menu, event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ---------------- Ueberholen per Ziehen ---------------- #
    def on_course_press(self, event):
        nr = self._tag_nr(self.txt_course, event, "crs")
        self._crs_drag = {"nr": nr, "x": event.x, "y": event.y, "event": event, "active": False, "target": None}
        return "break"

    def _course_target(self, y):
        """Boot unter der Maus; ober- oder unterhalb aller Boote: erstes bzw. letztes."""
        boxes = []
        for _t, nr, _k in self.course:
            rng = self.txt_course.tag_ranges(f"crs{nr}")
            if not rng:
                continue
            b1, b2 = self.txt_course.bbox(rng[0]), self.txt_course.dlineinfo(f"{rng[-1]} -1c")
            if b1 is None or b2 is None:
                continue
            boxes.append((b1[1], b2[1] + b2[3], nr))
        if not boxes:
            return None
        for top, bottom, nr in boxes:
            if top <= y < bottom:
                return nr
        top_nr = min(boxes)[2]
        bottom_nr = max(boxes, key=lambda b: b[1])[2]
        if y < min(b[0] for b in boxes):
            return top_nr
        if y >= max(b[1] for b in boxes):
            return bottom_nr
        return None

    def on_course_motion(self, event):
        d = self._crs_drag
        if not d or d["nr"] is None or self.course_key(d["nr"]) is None or len(self.course) < 2:
            return "break"
        if not d["active"]:
            if abs(event.y - d["y"]) < 8 * self.ui_scale and abs(event.x - d["x"]) < 8 * self.ui_scale:
                return "break"
            d["active"] = True
            self.txt_course.configure(cursor="fleur")
            rng = self.txt_course.tag_ranges(f"crs{d['nr']}")
            if rng:
                self.txt_course.tag_add("dragged", rng[0], rng[-1])
        # am Rand automatisch scrollen
        h = self.txt_course.winfo_height()
        if event.y < 10:
            self.txt_course.yview_scroll(-1, "units")
        elif event.y > h - 10:
            self.txt_course.yview_scroll(1, "units")
        target = self._course_target(event.y)
        if target != d["target"]:
            self.txt_course.tag_remove("drop", "1.0", "end")
            d["target"] = target
            if target is not None and target != d["nr"]:
                rng = self.txt_course.tag_ranges(f"crs{target}")
                if rng:
                    self.txt_course.tag_add("drop", rng[0], rng[-1])
        return "break"

    def on_course_release(self, event):
        d, self._crs_drag = self._crs_drag, None
        if not d:
            return "break"
        if not d["active"]:
            return self.on_course_click(d["event"])
        self.txt_course.configure(cursor="")
        self.txt_course.tag_remove("drop", "1.0", "end")
        self.txt_course.tag_remove("dragged", "1.0", "end")
        target = d["target"]
        if target is not None and target != d["nr"]:
            self.move_on_course(d["nr"], target)
        else:
            self.update_course_panel()
        return "break"

    def move_on_course(self, nr, target):
        """nr nimmt den Platz von target in der erwarteten Zielreihenfolge ein."""
        order = [k for _t, _n, k in self.course]
        src, dst = self.course_key(nr), self.course_key(target)
        if src is None or dst is None or src == dst:
            return
        to = order.index(dst)
        order.remove(src)
        order.insert(to, src)
        self.set_course_order(order)
        pos = order.index(src)
        if pos == 0:
            text = f"Nr {nr} hat überholt und kommt als nächstes ins Ziel"
        else:
            ahead = self.cp_recs[order[pos - 1]]["nr"]
            text = f"Reihenfolge auf der Strecke: Nr {nr} jetzt hinter Nr {ahead}"
        self.log(text, tag="ok")
        self.add_ticker(text, None)

    def set_course_order(self, keys):
        """Erwartete Zielreihenfolge festlegen: die Startzeiten der Boote werden in der neuen Reihenfolge
        als Sortierschluessel verteilt. Spaeter gestartete Boote kommen so weiterhin hinten dazu."""
        stamps = sorted(self.cp_recs[k]["abs"] for k in keys)
        for k, a in zip(keys, stamps):
            r = self.cp_recs[k]
            if r["abs"] == a:
                r.pop("order", None)
            else:
                r["order"] = a
        self.finish_override = None
        self.save_autosave()
        self.course_changed()

    def on_course_click(self, event):
        idx = self.txt_course.index(f"@{event.x},{event.y}")
        tags = self.txt_course.tag_names(idx)
        imp = next((int(t[3:]) for t in tags if t.startswith("imp") and t[3:].isdigit()), None)
        if imp is not None and imp < len(getattr(self, "_pending_keys", [])):
            self.pending_menu(self._pending_keys[imp], event)
            return "break"
        if "lastfin" in tags and self.last_finish_key:
            menu = self._menu()
            fk = self.last_finish_key
            menu.add_command(label="Zielzeit ungültig (Fehlimpuls), Boot wieder auf die Strecke",
                             command=lambda: self.invalidate_finish(fk))
            self._popup(menu, event)
            return "break"
        nr = self._tag_nr(self.txt_course, event, "crs")
        if nr is None or self.course_key(nr) is None:
            return "break"
        menu = self._menu()
        menu.add_command(label=f"{self.order_label(nr)}", state="disabled")
        menu.add_separator()
        first = self.course[0][1] if self.course else None
        if nr != first:
            menu.add_command(label="Kommt als nächstes ins Ziel (überholt)", command=lambda: self.cp_set_next_finish(nr))
        lf = self.cp_recs.get(self.last_finish_key) if self.last_finish_key else None
        if lf and lf["status"] == "ok" and lf["nr"] != nr and lf["nr"] > 0:
            menu.add_command(label=f"Letzte Zielzeit gehört Nr {nr} (statt Nr {lf['nr']})",
                             command=lambda: self.reassign_last_finish(nr))
        menu.add_command(label="Nummer ändern ...", command=lambda: self.open_renumber_dialog(nr))
        menu.add_command(label="Ausgeschieden (DNF)", command=lambda: self.cp_cancel_start(nr, "DNF"))
        if self.status.get(nr) == "DSQ":
            menu.add_command(label="DSQ aufheben", command=lambda: self.set_status(nr, None))
            menu.add_command(label="DSQ, Boot ist schon draussen", command=lambda: self.cp_cancel_start(nr, "DSQ"))
        else:
            menu.add_command(label="Disqualifiziert, fährt weiter ins Ziel (DSQ)",
                             command=lambda: self.cp_cancel_start(nr, "DSQ", running=True))
            menu.add_command(label="Disqualifiziert, ist schon draussen (DSQ)",
                             command=lambda: self.cp_cancel_start(nr, "DSQ"))
        self._popup(menu, event)
        return "break"

    def pending_menu(self, key, event):
        rec = self.cp_recs.get(key)
        if rec is None:
            return
        menu = self._menu()
        where = "Start" if key[2] == CH_START else "Ziel"
        menu.add_command(label=f"{where}impuls {fmt_tod(rec['abs'] % 86400)}", state="disabled")
        menu.add_separator()
        if key[2] == CH_FINISH:
            for _t, nr, skey in self.course:
                st = self.cp_recs[skey]
                menu.add_command(label=f"Nr {nr} zuordnen (Fahrzeit {fmt_secs(rec['abs'] - st['abs'], 2)}s)",
                                 command=lambda n=nr: self.assign_pending(key, n))
            if not self.course:
                menu.add_command(label="Kein Boot auf der Strecke", state="disabled")
        else:
            menu.add_command(label="Startnummer zuordnen ...", command=lambda: self.open_start_assign(key))
        menu.add_command(label="Ungültig lassen (ausblenden)", command=lambda: self.dismiss_impulse(key))
        self._popup(menu, event)

    def dismiss_impulse(self, key):
        rec = self.cp_recs.get(key)
        if rec:
            rec["status"] = "invalid"
            self.log(f"Impuls {fmt_tod(rec['abs'] % 86400)} ungültig gelassen", tag="warn")
            self.save_autosave()
            self.course_changed()

    def open_start_assign(self, key):
        rec = self.cp_recs.get(key)
        if rec is None:
            return None
        dlg = self._toplevel("Startnummer zuordnen")
        dlg.columnconfigure(0, weight=1)
        nxt = self.next_starters(1)
        tk.Label(dlg, text=f"Startimpuls {fmt_tod(rec['abs'] % 86400)}: welche Nummer ist gestartet?", bg=PANEL,
                 fg=TEXT, font=self.f_side, justify="left", anchor="w", wraplength=self.narrow_wrap()).grid(
            row=0, column=0, sticky="w")
        e = self._entry(dlg, width=8)
        if nxt:
            e.insert(0, str(nxt[0]))
        e.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        def ok(_e=None):
            try:
                nr = int(e.get().strip())
                if not 0 < nr <= 9999:
                    raise ValueError
            except ValueError:
                return "break"
            dlg.destroy()
            self.assign_pending(key, nr)
            return "break"

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self._button(btns, "Zuordnen", ok, BLUE).pack(side="right")
        self._button(btns, "Abbrechen", dlg.destroy).pack(side="right", padx=(0, 8))
        dlg.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda ev: dlg.destroy())
        self._place(dlg, narrow=True)
        dlg.focus_force()
        e.focus_set()
        e.select_range(0, "end")
        return dlg

    def on_next_right(self, event):
        nr = self._tag_nr(self.txt_next, event, "row")
        if nr is None:
            return "break"
        menu = self._menu()
        menu.add_command(label=self.order_label(nr), state="disabled")
        menu.add_separator()
        sel = sorted(self.next_sel | {nr})
        lab = f"Nr {nr}" if len(sel) == 1 else f"{len(sel)} Nummern"
        menu.add_command(label=f"{lab} bestätigen", command=lambda: self.confirm_numbers(sel, True))
        menu.add_command(label=f"Bestätigung {lab} aufheben", command=lambda: self.confirm_numbers(sel, False))
        menu.add_command(label="Alle Bestätigungen zurücksetzen ...", command=self.reset_confirmations)
        menu.add_separator()
        menu.add_command(label="Nummer darunter einfügen ...", command=lambda: self.open_insert_dialog(nr))
        menu.add_command(label="Nicht gestartet (DNS)", command=lambda: self.set_status(nr, "DNS"))
        absent = [n for n in self.start_order if self.status.get(n) == "DNS"]
        if absent:
            sub = LoggedMenu(menu, tearoff=0, bg=PANEL2, fg=TEXT, activebackground=BLUE, activeforeground=WHITE,
                          font=self.f_side, bd=0, relief="flat")
            for n in absent:
                sub.add_command(label=self.order_label(n), command=lambda n=n: self.insert_number(str(n), nr))
            menu.add_separator()
            menu.add_cascade(label="Abwesende (DNS) darunter wieder einfügen", menu=sub)
        self._popup(menu, event)
        return "break"

    def open_renumber_dialog(self, nr):
        key = self.course_key(nr)
        if key is None:
            return None
        dlg = self._toplevel("Nummer ändern")
        dlg.columnconfigure(0, weight=1)
        tk.Label(dlg, text=f"{self.order_label(nr)} ist auf der Fahrstrecke. Richtige Startnummer:", bg=PANEL,
                 fg=TEXT, font=self.f_side, justify="left", anchor="w", wraplength=self.narrow_wrap()).grid(
            row=0, column=0, sticky="w")
        e = self._entry(dlg, width=8)
        e.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        msg = tk.Label(dlg, text="", bg=PANEL, fg=RED, font=self.f_side, justify="left", anchor="w",
                       wraplength=self.narrow_wrap())
        msg.grid(row=2, column=0, sticky="w", pady=(4, 0))

        def ok(_e=None):
            try:
                new = int(e.get().strip())
                if not 0 < new <= 9999:
                    raise ValueError
            except ValueError:
                msg.configure(text="Gültige Startnummer eingeben")
                return "break"
            if new == nr:
                dlg.destroy()
                return "break"
            if any(n == new for _t, n, _k in self.course):
                msg.configure(text=f"Nr {new} ist bereits auf der Fahrstrecke")
                return "break"
            dlg.destroy()
            self.cp_change_number(key, nr, new)
            return "break"

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self._button(btns, "Ändern", ok, BLUE).pack(side="right")
        self._button(btns, "Abbrechen", dlg.destroy).pack(side="right", padx=(0, 8))
        dlg.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda ev: dlg.destroy())
        self._place(dlg, narrow=True)
        dlg.focus_force()
        e.focus_set()
        return dlg

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
        if self._pending_errors:
            self.show_pending_errors()
        try:
            while True:
                kind, payload, reader = self.q.get_nowait()
                if kind.startswith("update_"):
                    self.handle_update_event(kind, payload)
                    continue
                if kind == "manual_open":
                    self.manual_opened(payload)
                    continue
                if kind.startswith(("eth_", "net_")):
                    self.handle_eth_event(kind, payload, reader)
                    continue
                if reader is not self.reader:
                    continue  # Nachzuegler einer frueheren Verbindung
                if kind == "line":
                    self.serial_rx()
                    self.handle_line(payload)
                elif kind == "lines":
                    self.on_serial_lines(payload)
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
        self.print_next_club(nr)
        self.update_panels()

    def print_next_club(self, nr, event="start"):
        """Vereinswechsel auf dem Papier des CP 545 (#PL, am CP getestet). Gedruckt wird beim ersten der beiden
        Ereignisse: der letzte Fahrer des alten Vereins kommt ins Ziel (event «finish», Zeile vor dem Start des
        neuen Vereins), oder der erste Fahrer des neuen Vereins startet (event «start», Zeile direkt nach dessen
        Startzeile; der CP druckt die Startzeile beim Impuls selbst). event «connect»: ersten Verein ankuendigen.
        Gruende fuer «nicht gedruckt» stehen im Log unter «Alle»."""
        def skip(why):
            self.log(f"Vereinsdruck: nichts gedruckt ({why})", tag="test", focus=False)  # nur unter «Alle»

        if not self.settings["timing"].get("print_club", True):
            return skip("Schalter «Vereinswechsel drucken» aus")
        if not self.eth_mode():
            return skip("Verbindungsart RS232, Drucken nur über Ethernet oder USB")
        if not ((self.cp is not None and self.cp.connected and self.cp_device == "cp545")
                or (self.cp_b is not None and self.cp_b.connected and self.cp_b_device == "cp545")):
            return skip("kein CP 545 verbunden (TM550 druckt nicht)")
        done = self.__dict__.setdefault("_club_printed", set())

        def club_of(p):
            return (p.get("vnr") or p.get("verein") or "") if p else ""

        announced = getattr(self, "_print_prev_club", None)  # zuletzt angekuendigter Verein
        target = None
        if event == "start":
            cur = self.participants.get(nr)
            if not cur or not cur.get("verein"):
                return skip(f"Nr {nr} ohne Verein")
            if club_of(cur) == announced:
                return skip(f"Verein von Nr {nr} schon angekündigt")
            target = (nr, cur)
        else:
            nxt = self.next_starters(1)
            if not nxt:
                return skip("kein weiteres Boot in der Startliste")
            new = self.participants.get(nxt[0])
            if not new or not new.get("verein"):
                return skip(f"Nr {nxt[0]} ohne Verein")
            if club_of(new) == announced:
                return skip(f"kein Vereinswechsel: nächstes Boot Nr {nxt[0]} im selben Verein")
            if event == "finish":
                fin = self.participants.get(nr)
                left = [n for _t, n, _k in self.compute_course()
                        if club_of(self.participants.get(n)) == club_of(fin)]
                if left:
                    return skip(f"Verein von Nr {nr} noch auf der Strecke (Nr {', '.join(map(str, left[:4]))})")
            target = (nxt[0], new)
        tnr, new = target
        club = new.get("vnr") or new["verein"]
        if (tnr, club) in done:
            return skip(f"Verein von Nr {tnr} schon gedruckt")
        done.add((tnr, club))
        self._print_prev_club = club
        count = sum(1 for p in self.participants.values() if p.get("verein") == new["verein"])
        text = cp_print_text(new["verein"], count)
        sent = False
        if self.cp is not None and self.cp.connected and self.cp_device == "cp545":
            self.cp_query(f"#PL {text}", "ack")
            sent = True
        if self.cp_b is not None and self.cp_b.connected and self.cp_b_device == "cp545":
            self.cp_b.send(f"#PL {text}")
            sent = True
        if sent:
            self.log(f"CP druckt: {text}", tag="ok")

    # ================================================================== #
    # Verbindungsart RS232 / Ethernet
    # ================================================================== #
    def eth_mode(self):
        """CP wird aktiv gesteuert (THCOM08), ueber Ethernet oder USB."""
        return self.settings["conn"]["mode"] in ("ethernet", "usb")

    def usb_mode(self):
        return self.settings["conn"]["mode"] == "usb"

    def update_banner_locks(self):
        for key, (ctl, sw) in getattr(self, "banner_locks", {}).items():
            sw.set(self.settings["timing"][key])
            if self.eth_mode():
                if not ctl.winfo_manager():
                    ctl.pack(side="right", padx=(8, 0))
            else:
                ctl.pack_forget()

    def show_conn_frames(self):
        self.update_banner_locks()
        mode = self.settings["conn"]["mode"]
        want = {"ethernet": self.frm_eth, "usb": self.frm_usb}.get(mode, self.frm_rs)
        for f in (self.frm_rs, self.frm_eth, self.frm_usb):
            if f is not want:
                f.grid_remove()
        want.grid(row=3, column=0, sticky="ew")
        bk = self.settings["conn"].get("backup_mode", "none")
        if mode == "rs232":
            self.frm_bk.grid_remove()
        else:
            self.frm_bk.grid(row=5, column=0, sticky="ew")
        for f, key in ((self.frm_bk_eth, "ethernet"), (self.frm_bk_usb, "usb")):
            if key == bk:
                f.grid(row=2, column=0, sticky="ew")
            else:
                f.grid_remove()
        # Netzwerkkarte nur bei Ethernet: beim Hauptgeraet, sonst (Haupt USB, Reserve Ethernet) bei der Reserve
        if mode == "ethernet":
            self.frm_net.grid(in_=self.frm_conn_box, row=2, column=0, columnspan=2, sticky="ew")
        elif mode == "usb" and bk == "ethernet":
            self.frm_net.grid(in_=self.frm_bk_eth, row=0, column=0, columnspan=2, sticky="ew")
        else:
            self.frm_net.grid_remove()

    def toggle_usb_ack(self):
        c = self.settings["conn"]
        c["usb_ack"] = not c["usb_ack"]
        self.save_settings()
        if self.cp is not None and self.cp.link == "usb":
            self.cp.ack = c["usb_ack"]

    def connect_usb(self):
        if serial is None:
            messagebox.showerror("pyserial fehlt", "Modul 'pyserial' ist nicht installiert:\npip install pyserial")
            return
        sel = self.cmb_usb.get().strip()
        port = self.port_map.get(sel, sel.split(" - ")[0].strip())
        if not port:
            messagebox.showwarning("Verbindung", "Kein COM-Port ausgewählt.")
            return
        try:
            baud = int(self.e_usb_baud.get().strip())
        except ValueError:
            messagebox.showwarning("Verbindung", "Baudrate ist ungültig.")
            return
        c = self.settings["conn"]
        c["usb_port"], c["usb_baud"] = port, baud
        self.save_settings()
        self.cp_reconnected = False
        self.cp = CPSerialClient(port, baud, self.q, identity=port_identity(port), ack=c["usb_ack"])
        self.cp.start()
        self.set_conn_status(f"verbinde mit CP an {port} ...", GOLD)
        self.btn_connect.configure(text="Trennen", bg=DARK_RED)

    def fill_eth_combos(self):
        labels = [f"{a['name']}" + ("" if a["up"] else " (kein Kabel)") for a in self.adapters]
        self.cmb_adapter["values"] = labels
        want = self.settings["conn"]["adapter"]
        idx = next((i for i, a in enumerate(self.adapters) if a["name"] == want), 0 if self.adapters else None)
        if idx is not None:
            self.cmb_adapter.current(idx)
        elif not IS_WINDOWS:
            self.cmb_adapter.set("(nur unter Windows)")
        else:
            self.cmb_adapter.set("")
        cps = [f"{ip}  {info}" for ip, info in self.cp_found]
        self.cmb_cp["values"] = cps
        want = self.settings["conn"]["cp_ip"]
        idx = next((i for i, (ip, _i) in enumerate(self.cp_found) if ip == want), 0 if self.cp_found else None)
        if idx is not None:
            self.cmb_cp.current(idx)
        else:
            self.cmb_cp.set(f"{want}  (zuletzt verwendet)" if want else "noch nicht gesucht")
        self.fill_backup_combos()

    def backup_options(self, kind):
        """[(ziel, anzeige)] fuer das Reserve-Geraet: kind 'ethernet' -> IP, 'usb' -> 'usb:COMx'."""
        c = self.settings["conn"]
        if kind == "ethernet":
            main_ip = c["cp_ip"] if c["mode"] == "ethernet" else ""
            opts = [(ip, f"{ip}  {info}") for ip, info in self.cp_found if ip != main_ip]
        else:
            main_usb = c["usb_port"] if c["mode"] == "usb" else ""
            opts = [(f"usb:{dev}", label) for label, dev in getattr(self, "port_map", {}).items()
                    if dev != main_usb]
        want = c["cp_ip_b"]
        main = c["cp_ip"] if c["mode"] == "ethernet" else ("usb:" + c["usb_port"] if c["mode"] == "usb" else "")
        if want and want != main and want.startswith("usb:") == (kind == "usb") and want not in [o[0] for o in opts]:
            opts.append((want, f"{want.replace('usb:', '')}  (zuletzt verwendet)"))
        return opts

    def fill_backup_combos(self):
        want = self.settings["conn"]["cp_ip_b"]
        for name, kind in (("cmb_cp_b", "ethernet"), ("cmb_usb_b", "usb")):
            cmb = getattr(self, name, None)
            if cmb is None:
                continue
            opts = self.backup_options(kind)
            cmb["values"] = [label for _t, label in opts]
            idx = next((i for i, (t, _l) in enumerate(opts) if t == want), None)
            if idx is not None:
                cmb.current(idx)
            elif kind == "ethernet":
                cur = cmb.get().split()[0] if cmb.get().split() else ""
                if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", cur):
                    cmb.set(opts[0][1] if opts else f"{CP_NET}20")
            elif opts:
                cmb.current(0)
            else:
                cmb.set("")

    def on_backup_mode_change(self):
        self.settings["conn"]["backup_mode"] = self.var_bk.get()
        self.save_settings()
        self.show_conn_frames()
        if self.var_bk.get() == "ethernet" and not self.adapters:
            self.refresh_adapters()
        if self.var_bk.get() == "usb":
            self.refresh_ports()
        self.fill_backup_combos()
        self.on_backup_target_change()

    def on_backup_target_change(self):
        """Reserve-Auswahl merken. Verbunden wird nur mit dem Knopf «Reserve verbinden»."""
        target = self.selected_backup()
        if self.cp_b is None and getattr(self, "_bk_job", None) is None:
            self.settings["conn"]["cp_ip_b"] = target
            self.save_settings()

    def toggle_backup(self):
        """Eigener Knopf fuer das Reserve-Geraet, unabhaengig vom Hauptgeraet."""
        if self.cp_b is not None or getattr(self, "_bk_job", None) is not None:
            self._bk_job = None
            self.stop_backup()
            self.backup_reset()
            self.backup_state = ""
            self.log("Reserve-Gerät getrennt", tag="warn")
            self.refresh_conn_head()
            return
        if not self.selected_backup():
            messagebox.showinfo("Reserve-Gerät", "Zuerst Ethernet oder USB wählen und die IP-Adresse bzw. den "
                                                 "COM-Port des Reserve-Geräts angeben.")
            return
        self.connect_backup()
        self.start_eth_tick()
        self.refresh_conn_head()

    def refresh_bk_button(self):
        btn = getattr(self, "btn_bk", None)
        if btn is None:
            return
        busy = self.cp_b is not None or getattr(self, "_bk_job", None) is not None
        btn.configure(text="Reserve trennen" if busy else "Reserve verbinden", bg=DARK_RED if busy else GREEN)
        state = getattr(self, "backup_state", "") if busy else "nicht verbunden"
        name = self.DEVICE_LABEL.get(self.cp_b_device or "", "") if busy else ""
        off = getattr(self, "b_offset", None) if busy else None
        self.lbl_bk_state.configure(
            text=" ".join(x for x in (name, state) if x) + (f", Versatz {off:+.2f} s" if off is not None else ""),
            fg=GREEN_TEXT if state == "verbunden" else (MUTED if not busy else GOLD))

    def selected_adapter(self):
        i = self.cmb_adapter.current()
        return self.adapters[i]["name"] if 0 <= i < len(self.adapters) else ""

    def selected_cp(self):
        i = self.cmb_cp.current()
        if 0 <= i < len(self.cp_found):
            return self.cp_found[i][0]
        return self.settings["conn"]["cp_ip"]

    def refresh_adapters(self):
        if not IS_WINDOWS:
            self.fill_eth_combos()
            return
        self.set_conn_status("Netzwerkkarten werden gelesen ...", GOLD)
        token = object()
        self._adapter_token = token
        threading.Thread(target=lambda: self.q.put(("net_adapters", list_adapters(), token)), daemon=True).start()

    def is_connected(self):
        if self.eth_mode():
            return self.cp is not None and self.cp.connected
        return self.reader is not None and self.reader.is_alive()

    def restore_conn_ui(self, text, color):
        """Nach dem Neuaufbau der Oberflaeche: Knopf und Status wieder wie vorher."""
        busy = (self.cp is not None or self.eth_job is not None) if self.eth_mode() else \
            (self.reader is not None and self.reader.is_alive())
        if self.reconnecting:
            self.btn_connect.configure(text="Warten abbrechen", bg=DARK_RED)
        elif busy:
            self.btn_connect.configure(text="Trennen" if self.cp is not None or self.reader else "Abbrechen",
                                       bg=DARK_RED)
        self.set_conn_status(text, color)

    def on_conn_mode_change(self):
        mode = self.var_conn.get()
        if mode == self.settings["conn"]["mode"]:
            return
        self.disconnect_all()
        self.settings["conn"]["mode"] = mode
        self.save_settings()
        self.show_conn_frames()
        self.set_connected(False, "nicht verbunden")
        if mode == "ethernet":
            self.log("Verbindungsart Ethernet: CP 545 wird aktiv gesteuert (THCOM08)", tag="ok")
            if not self.adapters:
                self.refresh_adapters()
        elif mode == "usb":
            self.log("Verbindungsart USB: Gerät wird aktiv gesteuert (THCOM08 über COM-Port)", tag="ok")
            self.refresh_ports()
            if self.settings["conn"].get("backup_mode") == "ethernet":
                if not self.adapters:
                    self.refresh_adapters()
            else:
                self.restore_network(background=True)
        else:
            self.log("Verbindungsart RS232: Fahrzeiten nur auswerten", tag="ok")
            self.restore_network(background=True)
        self.apply_show_settings()

    def disconnect_all(self):
        self.stop_reconnect()
        if self.reader is not None:
            self.reader.stop()
            self.reader = None
        self.eth_job = None
        if self.cp is not None:
            self.cp.stop()
            self.cp = None
        self.stop_backup()
        self.cp_cmds, self.cp_inflight = [], None
        self.stop_eth_tick()

    # ---------------- Netzwerkkarte ---------------- #
    def restore_network(self, background=True, blocking=False):
        """Netzwerkkarte wieder auf automatische Adresse (DHCP), falls die App sie umgestellt hat."""
        nr = self.settings["net_restore"]
        if not nr.get("pending") or not nr.get("adapter") or not IS_WINDOWS:
            return True
        adapter = nr["adapter"]
        if blocking:
            ok, msg = set_dhcp(adapter)
            self.on_network_restored(ok, msg, adapter)
            return ok
        self.log(f"Netzwerkkarte «{adapter}» wird auf automatische Adresse zurückgestellt ...")
        token = object()
        threading.Thread(target=lambda: self.q.put(("net_restored", (*set_dhcp(adapter), adapter), token)),
                         daemon=True).start()
        return True

    def on_network_restored(self, ok, msg, adapter):
        if ok:
            self.settings["net_restore"] = {"pending": False, "adapter": ""}
            self.save_settings()
            self.log(f"Netzwerkkarte «{adapter}» bezieht die Adresse wieder automatisch (DHCP)", tag="ok")
        else:
            self.log(f"Netzwerkkarte «{adapter}» nicht zurückgestellt: {msg}. Wird beim nächsten Start "
                     "erneut versucht.", tag="warn")

    # ---------------- Vorbereitung im Hintergrund ---------------- #
    def start_eth_job(self, connect=True):
        if self.eth_job is not None:
            return
        adapter = self.selected_adapter()
        if adapter:
            self.settings["conn"]["adapter"] = adapter
            self.save_settings()
        token = object()
        self.eth_job, self.eth_job_connect = token, connect
        want = self.selected_cp()
        avoid = self.selected_backup()
        info = next((a for a in self.adapters if a["name"] == adapter), None)
        if connect:
            self.btn_connect.configure(text="Abbrechen", bg=DARK_RED)
        threading.Thread(target=self._eth_job_run, args=(token, adapter, info, want, connect, avoid),
                         daemon=True).start()

    def _eth_job_run(self, token, adapter, info, want, connect, avoid=""):
        put = lambda kind, payload: self.q.put((kind, payload, token))  # noqa: E731
        hosts = cp_hosts()
        DIAG.info(f"CP-Suche: Karte {adapter!r}, Adressen {hosts[0]}..{hosts[-1]}, verbinden={connect}")
        if IS_WINDOWS and adapter:
            fresh_list = list_adapters()
            put("net_adapters_job", fresh_list)  # Liste aktualisieren (z.B. «kein Kabel» weg)
            fresh = next((a for a in fresh_list if a["name"] == adapter), None)
            DIAG.info(f"CP-Suche: Karte jetzt {fresh}")
            if fresh is not None:
                info = fresh
        put("eth_status", ("CP suchen ...", "gold"))
        found = scan_cps(hosts)  # zuerst ohne Umstellung: braucht keine Adminrechte
        if not found and IS_WINDOWS and adapter and info is not None and not info.get("up", True):
            put("eth_fail", f"Netzwerkkarte «{adapter}» hat keine Verbindung (Windows: kein Kabel). Prüfen: "
                            "Kabel an PC und CP eingesteckt (Lämpchen an der Buchse?), CP eingeschaltet, Ethernet "
                            "am CP eingeschaltet (F › Einstellungen › Ethernet › Std Connexion), richtige Netzwerkkarte gewählt. "
                            "Danach ⟳ und nochmals versuchen.")
            return
        if not found and IS_WINDOWS and adapter and not os.environ.get("SWV_CP_HOSTS"):
            fresh = next((a for a in list_adapters() if a["name"] == adapter), None)
            ips = (fresh or info or {}).get("ips", [])
            changed = False
            if any(ip.startswith(CP_NET) for ip in ips):
                put("eth_log", (f"Netzwerkkarte «{adapter}» hat bereits {', '.join(ips)}", "ok"))
            else:
                changed = True
                put("eth_status", (f"Netzwerkkarte «{adapter}» auf {PC_IP} stellen, Windows fragt nach "
                                   "Berechtigung ...", "gold"))
                put("net_pending", adapter)
                ok, msg = set_static_ip(adapter)
                if not ok:
                    put("eth_fail", f"Netzwerkkarte nicht umgestellt: {msg}")
                    return
                put("eth_status", ("Warte auf Netzwerkadresse ...", "gold"))
                if not address_ready(PC_IP):
                    put("eth_fail", f"{PC_IP} ist nach 12 s noch nicht aktiv. Kabel zum CP prüfen.")
                    return
                put("eth_log", (f"Netzwerkkarte «{adapter}» hat {PC_IP} / {PC_MASK}", "ok"))
            if changed:  # nur nach dem Umstellen nochmals suchen (sonst war die erste Suche schon gueltig)
                put("eth_status", (f"CP suchen ({hosts[0]} bis {hosts[-1]}) ..." if len(hosts) > 1
                                   else "CP suchen ...", "gold"))
                found = scan_cps(hosts)
                if not found:
                    # zweiter Versuch: Windows braucht nach der Umstellung manchmal einige Sekunden
                    time.sleep(2)
                    found = scan_cps(hosts)
        put("eth_found", found)
        hint = (f"Kein Gerät gefunden ({hosts[0]} bis {hosts[-1]}). CP 545: Ethernet nach jedem Einschalten "
                "wieder einschalten (F › Einstellungen › Ethernet › Std Connexion), Adresse unter «User "
                "Connexion» prüfen. Kabel eingesteckt? TM550: IP und Port unter Communication › Ethernet prüfen.")
        if not connect:
            if not found:
                put("eth_log", (hint, "warn"))
            return
        if not found:
            put("eth_fail", hint)
            return
        others = [f[0] for f in found if f[0] != avoid] or [found[0][0]]
        ip = want if want != avoid and any(f[0] == want for f in found) else others[0]
        put("eth_go", ip)

    def handle_eth_event(self, kind, payload, token):
        """Meldungen aus Hintergrund-Threads (Netzwerk, Suche, CP-Verbindung)."""
        if kind == "net_adapters":
            if token is getattr(self, "_adapter_token", None):
                self.adapters = payload
                self.fill_eth_combos()
                if not self.is_connected() and self.eth_job is None:
                    self.set_conn_status("nicht verbunden" if payload else "keine Netzwerkkarte gefunden",
                                         MUTED if payload else GOLD)
            return
        if kind == "net_restored":
            self.on_network_restored(*payload)
            return
        if kind in ("net_bk_pending", "eth_bk_fail", "eth_bk_log", "eth_bk_go"):
            if token is not getattr(self, "_bk_job", None):
                return
            if kind == "net_bk_pending":
                self.settings["net_restore"] = {"pending": True, "adapter": payload}
                self.save_settings()
            elif kind == "eth_bk_log":
                self.log(payload, tag="ok")
            elif kind == "eth_bk_fail":
                self._bk_job = None
                self.backup_state = "Fehler"
                self.log(f"Reserve-Gerät: {payload}", tag="error")
                self.refresh_conn_head()
            elif kind == "eth_bk_go":
                self._bk_job = None
                ip, info = payload
                if info and not any(h == ip for h, _i in self.cp_found):
                    self.cp_found = sorted(self.cp_found + [(ip, info)])
                    self.fill_backup_combos()
                if not info:
                    self.log(f"Reserve-Gerät {ip} antwortet nicht, versuche weiter zu verbinden", tag="warn")
                self.start_backup(ip)
            return
        if kind == "net_adapters_job":
            if payload:
                sel = self.selected_adapter()
                self.adapters = payload
                self.fill_eth_combos()
                if sel:
                    match = next((lbl for lbl in self.cmb_adapter["values"] if lbl.split(" (")[0] == sel), None)
                    if match:
                        self.cmb_adapter.set(match)
            return
        if kind.startswith("eth_") and kind in ("eth_status", "eth_fail", "eth_found", "eth_go", "eth_log") \
                or kind == "net_pending":
            if token is not self.eth_job:
                return
            if kind == "net_pending":
                self.settings["net_restore"] = {"pending": True, "adapter": payload}
                self.save_settings()
            elif kind == "eth_status":
                text, color = payload
                self.set_conn_status(text, {"gold": GOLD, "red": RED}.get(color, MUTED))
            elif kind == "eth_log":
                self.log(payload[0], tag=payload[1])
            elif kind == "eth_found":
                self.cp_found = payload
                self.fill_eth_combos()
                if payload:
                    self.log("CP gefunden: " + ", ".join(f"{ip} ({info})" for ip, info in payload), tag="ok")
                if not self.eth_job_connect:
                    self.eth_job = None
                    if self.cp is None:
                        self.set_conn_status(f"{len(payload)} Gerät(e) gefunden" if payload else
                                             "kein Gerät gefunden: Ethernet am CP nach Einschalten wieder aktivieren",
                                             MUTED if payload else GOLD)
            elif kind == "eth_fail":
                self.eth_job = None
                self.set_connected(False, "Fehler beim Verbinden", RED)
                self.log(payload, tag="error")
                messagebox.showerror("Ethernet", payload)
            elif kind == "eth_go":
                self.eth_job = None
                self.connect_cp(payload)
            return
        # Nachrichten der CP-Verbindungen
        if token is not None and token is self.cp_b:
            self.handle_backup_event(kind, payload)
            return
        if token is not self.cp:
            return
        if kind == "eth_line":
            self.handle_eth_line(payload)
        elif kind == "eth_bad":
            self.cp_last_rx = time.time()
            self.log(f"CP: Zeile mit falscher Prüfsumme verworfen: {payload.strip()}",
                     tag="test" if self.cp_backlog is not None else "warn")
        elif kind == "eth_connected":
            self.on_cp_connected(payload)
        elif kind == "eth_open_error":
            self.log(f"CP {self.cp.host}: {payload}", tag="error")
            if self.cp.link != "usb" and not getattr(self, "_eth_on_told", False):
                self._eth_on_told = True
                self.log("Wurde der CP aus- und eingeschaltet? Dann Ethernet am CP wieder einschalten "
                         "(F › Einstellungen › Ethernet › Std Connexion).", tag="warn")
            self.set_conn_status(f"CP {self.cp.host} nicht erreichbar, neuer Versuch ...", RED)
        elif kind == "eth_retry":
            self.set_conn_status(f"CP {self.cp.host} getrennt, verbinde neu ...", RED)
        elif kind == "eth_lost":
            now = time.time()
            DIAG.warning(f"Verbindung verloren: {payload!r} | zuletzt gesendet {getattr(self, '_diag_tx', None)!r} "
                         f"| zuletzt empfangen vor {now - self.cp_last_rx:.1f} s: {getattr(self, '_diag_rx', None)!r}")
            self.cp_inflight, self.cp_cmds = None, []
            if re.search(r"PermissionError|Zugriff verweigert|ClearCommError|device reports readiness|"
                         r"FileNotFoundError|nicht gefunden", str(payload)) and str(self.cp.host).upper().startswith("COM"):
                self.log(f"USB-Verbindung zum {self.dev_name()} {self.cp.host} weg (Kabel gezogen oder Gerät "
                         "ausgeschaltet). Die App verbindet neu, sobald der COM-Port wieder da ist.", tag="error")
                DIAG.info(f"USB weg: {payload}")
            else:
                self.log(f"Verbindung zum {self.dev_name()} {self.cp.host} unterbrochen: {payload}", tag="error")
            if self.cp.link != "usb":
                self.log("Kommt die Verbindung nicht zurück: CP neu gestartet? Ethernet am CP wieder einschalten "
                         "(F › Einstellungen › Ethernet › Std Connexion).", tag="warn")
            self.add_ticker("Verbindung zum CP 545 unterbrochen, verbinde neu", "warn")
            self.set_conn_status(f"CP {self.cp.host} getrennt, verbinde neu ...", RED)
        elif kind == "eth_disconnected":
            self.cp = None
            self.stop_eth_tick()
            self.set_connected(False, "nicht verbunden")
            self.log(f"Verbindung zum CP {payload} getrennt", tag="warn")
            if self.cp_b is not None:
                self.log("Reserve-Gerät bleibt verbunden und liefert jetzt alle Zeiten", tag="warn")
                self.start_eth_tick()
                self.refresh_conn_head()
            self.apply_show_settings()

    def handle_backup_event(self, kind, payload):
        b = self.cp_b
        if kind == "eth_line":
            self.handle_eth_line(payload, dev="B")
        elif kind == "eth_connected":
            self.log(f"Reserve-Gerät {b.host} verbunden", tag="ok")
            self.backup_state = "verbunden"
            b.send("#SN")
            self.refresh_conn_head()
        elif kind in ("eth_lost", "eth_retry", "eth_open_error"):
            if getattr(self, "backup_state", "") != "getrennt":
                self.log(f"Reserve-Gerät {b.host} nicht erreichbar: {payload}", tag="warn")
            self.backup_state = "getrennt"
            self.refresh_conn_head()
        elif kind == "eth_disconnected":
            self.cp_b = None
            self.backup_state = ""
            self.refresh_conn_head()

    def refresh_conn_head(self):
        extra = ""
        if self.cp_b is not None or getattr(self, "_bk_job", None) is not None:
            off = getattr(self, "b_offset", None)
            extra = f"Reserve {getattr(self, 'backup_state', '')}" + (f", Versatz {off:+.2f} s"
                                                                       if off is not None else "")
        if self.cp is not None and self.cp.connected:
            self.set_conn_status(f"{self.dev_name()} {self.cp.host} verbunden" + (f" · {extra}" if extra else ""),
                                 GREEN_TEXT)
        elif self.cp is None and extra:
            self.set_conn_status(f"Hauptgerät getrennt · {extra}", GOLD)
        self.refresh_bk_button()

    def selected_backup(self):
        """Ziel des Reserve-Geraets: '' (keines), IP oder 'usb:COMx'."""
        kind = self.settings["conn"].get("backup_mode", "none")
        if kind not in ("ethernet", "usb") or self.settings["conn"]["mode"] == "rs232":
            return ""
        cmb = getattr(self, "cmb_cp_b" if kind == "ethernet" else "cmb_usb_b", None)
        if cmb is None:
            return ""
        opts = self.backup_options(kind)
        i = cmb.current()
        if 0 <= i < len(opts) and cmb.get() == opts[i][1]:
            return opts[i][0]
        text = cmb.get().split()[0] if cmb.get().split() else ""
        if kind == "ethernet" and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", text):
            return text
        return ""

    def connect_backup(self):
        """Reserve nach der Auswahl verbinden. Ethernet: Netzwerkkarte vorbereiten (falls das Hauptgeraet nicht
        schon ueber Ethernet laeuft) und Geraet abfragen (CP 545 oder TM550), dann verbinden."""
        c = self.settings["conn"]
        target = self.selected_backup()
        c["cp_ip_b"] = target
        self.save_settings()
        if not target:
            if self.cp_b is not None:
                self.log("Reserve-Gerät getrennt")
            self.stop_backup()
            self.backup_reset()
            self.refresh_conn_head()
            return
        main_ip = c["cp_ip"] if c["mode"] == "ethernet" else ""
        if target == main_ip:
            self.log(f"Reserve-Gerät {target} ist das Hauptgerät, bitte ein anderes wählen", tag="warn")
            return
        if target.startswith("usb:"):
            self.start_backup(target)
            return
        if c["mode"] == "ethernet" and any(h == target for h, _i in self.cp_found):
            self.start_backup(target)
            return
        token = self._bk_job = object()
        adapter = self.selected_adapter() if c["mode"] != "ethernet" else ""
        if adapter:
            c["adapter"] = adapter
            self.save_settings()
        self.stop_backup()
        self.backup_state = "suche"
        self.refresh_conn_head()
        threading.Thread(target=self._backup_job_run, args=(token, target, adapter), daemon=True).start()

    def _backup_job_run(self, token, target, adapter):
        put = lambda kind, payload: self.q.put((kind, payload, token))  # noqa: E731
        if IS_WINDOWS and adapter and not os.environ.get("SWV_CP_HOSTS"):
            fresh = next((a for a in list_adapters() if a["name"] == adapter), None)
            ips = (fresh or {}).get("ips", [])
            if not any(ip.startswith(CP_NET) for ip in ips):
                put("net_bk_pending", adapter)
                ok, msg = set_static_ip(adapter)
                if not ok or not address_ready(PC_IP):
                    put("eth_bk_fail", f"Netzwerkkarte «{adapter}» nicht auf {PC_IP} gestellt: {msg or 'Zeitüberschreitung'}")
                    return
                put("eth_bk_log", f"Netzwerkkarte «{adapter}» hat {PC_IP} / {PC_MASK}")
        info = probe_cp(target, cp_ports()[0])
        put("eth_bk_go", (target, info))

    def start_backup(self, target, port=None):
        """Reserve-Geraet: Ethernet (IP) oder USB ('usb:COMx'). Zeiten laufen zur Kontrolle mit; fehlt ein
        Impuls beim Hauptgeraet oder ist es getrennt, uebernimmt die App die Zeit der Reserve (Uhr abgeglichen)."""
        self.stop_backup()
        self.backup_reset()
        self.cp_b_fw, self.cp_b_mode, self.cp_b_nr_ok, self.cp_b_next = "", "", False, None
        if not target:
            return
        if target.startswith("usb:"):
            dev = target[4:]
            self.cp_b = CPSerialClient(dev, self.settings["conn"].get("usb_baud", 9600), self.q,
                                       identity=port_identity(dev))
            self.cp_b_device = None
        else:
            info = next((i for h, i in self.cp_found if h == target), "")
            self.cp_b_device = "tm550" if "TM550" in (info or "") else ("cp545" if info else None)
            self.cp_b_fw = (info or "").split()[-1] if info else ""
            self.cp_b_nr_ok = self.cp_b_device == "cp545" or self.cp_b_fw >= "1.4"
            tm = self.cp_b_device == "tm550"
            self.cp_b = CPClient(target, port or (cp_ports()[0] if tm else cp_ports()[1]), self.q)
            self.cp_b.checksum = tm
        self.backup_state = "verbinde"
        self.cp_b.start()
        self.log(f"Reserve-Gerät {target.replace('usb:', 'USB ')}: Zeiten laufen zur Kontrolle mit und werden "
                 "übernommen, wenn das Hauptgerät eine Zeit nicht liefert oder getrennt ist")

    # ---------------- Reserve: Uhrabgleich und Uebernahme ---------------- #
    def backup_reset_extra(self):
        self.b_rx_offsets, self.b_seq_base, self.b_seq_last, self._b_asked = [], 0, {}, set()
        self.a_hist, self.b_hist = [], []  # letzte Impulse je Geraet (Eingang, Zeit): Doppelkontakte erkennen

    def backup_reset(self):
        self.b_pend = []            # Reserve-Impulse ohne Gegenstueck: [rx, info]
        self.a_pend = []            # Haupt-Impulse ohne Gegenstueck (nur wenn Reserve verbunden): [rx, info]
        self.b_offsets = []         # Uhrversatz Reserve - Haupt aus Impulspaaren
        self.b_offset = None
        self.b_taken = 0
        self._b_warn_t = 0.0
        self.backup_reset_extra()

    def backup_connected(self):
        return self.cp_b is not None and self.cp_b.connected

    def main_connected(self):
        return self.cp is not None and self.cp.connected

    def backup_renumber(self, info):
        """Zaehlnummern der Reserve eindeutig machen: neuer Lauf (OP) oder rueckwaerts springende Zaehlnummer
        ergibt einen neuen Bereich (+10000 je Lauf), damit alte und neue Zeiten nicht verwechselt werden."""
        if info.get("kind") != "time" or "seq" not in info:
            return info
        base = getattr(self, "b_seq_base", 0)
        last = getattr(self, "b_seq_last", {})
        ch, seq = info["ch"], info["seq"]
        if info["type"] == "TN" and ch in last and seq < last[ch] - 0 and seq <= 2 and not info.get("answer"):
            base += 10000
            last = {}
            self.b_seq_base = base
            DIAG.info(f"Reserve: Zählnummer {seq} nach {self.b_seq_last} -> neuer Bereich {base}")
        if info["type"] == "TN":
            last[ch] = max(last.get(ch, 0), seq)
        self.b_seq_last = last
        if base:
            info = dict(info, seq=seq + base)
        return info

    def backup_clock_estimate(self):
        """Versatz Reserve - Hauptgeraet aus den Eingangszeiten am PC, solange kein Impuls-Paar den genauen Wert
        liefert (z.B. nur an der Reserve ausgeloest). Genauigkeit etwa die Uebertragungszeit (±0,3 s)."""
        samples = [o for t, o in getattr(self, "b_rx_offsets", []) if time.time() - t < 600]
        if not samples:
            return None
        return max(samples) - (self.cp_offset() or 0.0)

    def backup_offset(self):
        if self.b_offset is not None:
            return self.b_offset
        est = self.backup_clock_estimate()
        return est if est is not None else 0.0

    def backup_corrected(self, info):
        off = self.backup_offset()
        out = dict(info)
        out["abs"] = info["abs"] - off
        out["tod"] = out["abs"] % 86400
        return out

    def backup_time(self, info):
        """Zeile vom Reserve-Geraet."""
        if info["type"] == "TN" and not info.get("answer"):
            self.b_rx_offsets = (getattr(self, "b_rx_offsets", []) + [(time.time(), info["abs"] - local_abs())])[-30:]
        info = self.backup_renumber(info)
        if info["type"] not in ("TN", "T+", "T="):
            if not self.main_connected():
                self.on_cp_time(self.backup_corrected(info), "B")
            return
        now = time.time()
        if not self.main_connected():
            if self.b_taken == 0:
                self.log("Hauptgerät getrennt: Zeiten des Reserve-Geräts werden übernommen"
                         + ("" if self.b_offset is not None else " (Uhrversatz noch unbekannt, 0 angenommen)"),
                         tag="warn")
                self.add_ticker("Reserve-Gerät übernimmt die Zeitmessung", "warn")
            self.b_taken += 1
            self.on_cp_time(self.backup_corrected(info), "B")
            return
        # Gegenstueck beim Hauptgeraet? Gleicher Eingang; bei bekanntem Uhrversatz nach Geraetezeit, sonst
        # nach Eingang am PC (2.5 s). Bei mehreren (Doppelkontakt) das naechstgelegene.
        self.b_hist = [h for h in getattr(self, "b_hist", []) if now - h[2] < 30] + [(info["ch"], info["abs"], now)]
        i = self.backup_best(self.a_pend, info, now, main_side=False)
        if i is not None:
            a = self.a_pend.pop(i)[1]
            self.backup_pair(a, info)
            return
        self.b_pend.append([now, info])

    def backup_ask(self, key):
        """Abweichung Haupt/Reserve: fragen, welches Geraet gilt. Blockiert nichts, bis zur Antwort gilt die Zeit
        der Reserve vorlaeufig. Fenster zu = Reserve bleibt."""
        rec = self.cp_recs.get(key)
        if rec is None:
            return
        asked = self.__dict__.setdefault("_b_asked", set())
        if key in asked:
            return  # zu diesem Impuls ist schon eine Rueckfrage offen bzw. beantwortet
        asked.add(key)
        ch = "Start" if key[2] == CH_START else ("Ziel" if key[2] == CH_FINISH else f"Eingang {key[2]}")
        who = f"Nr {rec['nr']}" if rec.get("nr") else "kein Boot"
        if self.b_offset is None:
            who += " (Uhr der Reserve geschätzt, ±0,3 s)"
        try:
            dlg = self._toplevel("Abweichung Haupt- und Reserve-Gerät")
        except tk.TclError:
            return
        self._b_dialogs = getattr(self, "_b_dialogs", []) + [dlg]
        tk.Label(dlg, text=f"{ch} {fmt_tod(rec['abs'] % 86400)}: nur das Reserve-Gerät hat diesen Impuls, das "
                           f"Hauptgerät nicht.\nVorläufig übernommen: {who}.\n\nWelches Gerät gilt?",
                 bg=PANEL, fg=TEXT, font=self.f_side, justify="left", wraplength=self.narrow_wrap()).pack(
            anchor="w", pady=(0, 8))
        remember = tk.BooleanVar(value=False)
        self._check(dlg, "Für diese Sitzung immer so", remember).pack(anchor="w", pady=(0, 8))

        def pick(choice):
            try:
                dlg.destroy()
            except tk.TclError:
                pass
            self.backup_decide(key, choice, remember.get())

        self._button(dlg, "Reserve übernehmen", lambda: pick("reserve"), GREEN).pack(fill="x", pady=(0, 4))
        self._button(dlg, "Hauptgerät gilt (Impuls verwerfen)", lambda: pick("main"), DARK_RED).pack(fill="x")
        dlg.protocol("WM_DELETE_WINDOW", lambda: pick("reserve"))
        self._place(dlg, narrow=True)

    def backup_decide(self, key, choice, remember=False):
        if remember:
            self._b_rule = choice
            self.log("Abweichung Haupt/Reserve für diese Sitzung: " + ("Reserve übernehmen" if choice == "reserve"
                                                                        else "Hauptgerät gilt"), tag="ok")
            for d in getattr(self, "_b_dialogs", []):
                try:
                    d.destroy()
                except tk.TclError:
                    pass
            self._b_dialogs = []
        rec = self.cp_recs.get(key)
        if rec is None or choice != "main":
            if rec is not None:
                self.log(f"Abweichung {fmt_tod(rec['abs'] % 86400)}: Zeit der Reserve gilt", tag="ok")
            return
        nr = rec.get("nr", 0)
        if key[2] == CH_FINISH and rec["status"] == "ok":
            self.undo_finish(key)
            self.log(f"Abweichung: Zielzeit {fmt_tod(rec['abs'] % 86400)} der Reserve verworfen, Nr {nr} wieder "
                     "auf der Strecke", tag="warn")
        elif key[2] == CH_START and rec["status"] == "ok" and nr > 0:
            self.unstart(nr)
            self.log(f"Abweichung: Startzeit {fmt_tod(rec['abs'] % 86400)} der Reserve verworfen, Nr {nr} wieder "
                     "als nächstes am Start", tag="warn")
        rec.update(status="reserve", nr=0, start=None)
        self.save_autosave()
        self.on_data_changed()
        self.course_changed()
        self.update_panels()
        self.cp_sync_next("Abweichung")

    def unstart(self, nr):
        """Nr wieder als naechstes an den Start (Startzeit verworfen)."""
        if self.last_start_nr == nr and nr in self.order_index:
            i = self.order_index[nr]
            self.last_start_nr = self.start_order[i - 1] if i > 0 else None

    def backup_preload_ok(self):
        """Nimmt das Reserve-Geraet vorgeladene Startnummern an? CP 545 ja; TM550 ab 1.48 in TIMING (bzw. solange
        die Zeitmessart unbekannt ist und keine Startzeit ohne Nummer kam)."""
        if self.cp_b is None or not self.cp_b.connected:
            return False
        if self.cp_b_device == "cp545":
            return True
        if self.cp_b_device == "tm550":
            mode = (getattr(self, "cp_b_mode", "") or "").upper()
            return bool(getattr(self, "cp_b_nr_ok", False)) and mode in ("", "TIMING")
        return False

    def backup_preload(self, nr):
        """Naechste Startnummer in die Reserve laden (ohne Zuruecklesen; der TM550 verbraucht sie beim Start)."""
        if not self.backup_preload_ok() or getattr(self, "cp_b_next", None) == nr:
            return
        self.cp_b_next = nr
        DIAG.debug(f"CP B> #WP 026 {CH_START:02d} {nr:04d}")
        self.cp_b.send(f"#WP 026 {CH_START:02d} {nr:04d}")

    def backup_match(self, a, b, rx_gap):
        if self.b_offset is not None:
            return abs(b["abs"] - self.b_offset - a["abs"]) <= self.backup_tol()
        return abs(rx_gap) <= 2.5

    @staticmethod
    def line_res(device, digits):
        """Aufloesung der Zeitzeilen: CP 545 eine Stelle mehr als das Resultat, TM550 wie eingestellt."""
        return 10 ** -(digits + 1 if device == "cp545" else digits)

    def backup_tol(self):
        """Toleranz Haupt/Reserve (Fehlerbericht 26.11.2026): 0,05 s plus die Aufloesung des groeberen Geraets
        (TM550 auf 1/10 schneidet Zehntel ab, der Versatz kann bei 1/100 bestimmt sein)."""
        d = self.settings["timing"].get("prec_digits", 1)
        res = max(self.line_res(self.cp_device or "cp545", d), self.line_res(self.cp_b_device or "cp545", d))
        return 0.05 + min(res, 0.1)

    def backup_best(self, pend, info, now, main_side):
        """Index des passenden Impulses in pend (gleicher Eingang, kleinste Zeitdifferenz) oder None."""
        best, best_d = None, None
        for i, (rx, other) in enumerate(pend):
            if other["ch"] != info["ch"]:
                continue
            a, b = (info, other) if main_side else (other, info)
            if not self.backup_match(a, b, now - rx):
                continue
            d = abs(b["abs"] - (self.b_offset or 0.0) - a["abs"]) if self.b_offset is not None else abs(now - rx)
            if best_d is None or d < best_d:
                best, best_d = i, d
        return best

    def backup_prell_twin(self, ch, abs_main, hist_a, hist_b):
        """Zweitimpuls eines Doppelkontakts? Innerhalb der Prellzeit nach einem Impuls am selben Eingang (an
        einem der beiden Geraete, Zeiten auf die Uhr des Hauptgeraets umgerechnet)."""
        ms = self.tset()["prell_start_ms" if ch == CH_START else "prell_finish_ms"]
        win = ms / 1000.0 + self.backup_tol()
        off = self.b_offset or 0.0
        times = [t for c, t, _rx in hist_a if c == ch] + [t - off for c, t, _rx in hist_b if c == ch]
        return any(0.001 < abs_main - t <= win for t in times)

    def save_backup_wait(self):
        try:
            v = float(self.e_bk_wait.get().replace(",", "."))
            if not 1 <= v <= 30:
                raise ValueError
        except ValueError:
            self.e_bk_wait.delete(0, "end")
            self.e_bk_wait.insert(0, f"{self.backup_wait():g}")
            return
        if v != self.settings["conn"].get("backup_wait_s"):
            self.settings["conn"]["backup_wait_s"] = v
            self.save_settings()
            self.log(f"Reserve: Wartezeit auf das Hauptgerät {v:g} s", tag="ok")

    def backup_wait(self):
        """So lange wartet die App auf die Zeile des Hauptgeraets, bevor sie die Zeit der Reserve nimmt."""
        try:
            return max(1.0, min(30.0, float(self.settings["conn"].get("backup_wait_s", 3.0))))
        except (TypeError, ValueError):
            return 3.0

    def backup_note_main(self, info):
        """Live-Impuls vom Hauptgeraet: mit Reserve-Impuls paaren oder auf ihn warten."""
        if not self.backup_connected() or info["type"] not in ("TN", "T+", "T="):
            return
        now = time.time()
        self.a_hist = [h for h in getattr(self, "a_hist", []) if now - h[2] < 30] + [(info["ch"], info["abs"], now)]
        i = self.backup_best(self.b_pend, info, now, main_side=True)
        if i is not None:
            b = self.b_pend.pop(i)[1]
            self.backup_pair(info, b)
            return
        rec = self.cp_recs.get(("A", self.cp_run, info["ch"], info["seq"]))
        if rec is not None and rec.get("status") == "dup" and str(rec.get("twin", ("",))[0]) == "B":
            # Zeile des Hauptgeraets kam erst nach Ablauf der Wartezeit: Reserve-Zeit gilt schon, keine Warnung
            self.log(f"Hauptgerät: Zeile {fmt_tod(info['abs'] % 86400)} Eingang {info['ch']} kam verspätet, "
                     "die Zeit der Reserve gilt bereits (kein Doppel)", tag="test")
            return
        self.a_pend.append([now, info])

    def backup_pair(self, a, b):
        if a.get("nr") and b.get("nr") and a["nr"] != b["nr"] and self.backup_preload_ok():
            self.log(f"Haupt- und Reserve-Gerät: verschiedene Nummern für denselben Impuls "
                     f"({fmt_tod(a['abs'] % 86400)}, Eingang {a['ch']}): Haupt Nr {a['nr']}, Reserve Nr {b['nr']}. "
                     "Es gilt die Nummer des Hauptgeräts", tag="warn")
        off = b["abs"] - a["abs"]
        if self.b_offset is not None and abs(off - self.b_offset) > 0.5:
            self.log(f"Reserve-Gerät: Uhrversatz springt von {self.b_offset:+.3f} s auf {off:+.3f} s "
                     "(Uhr verstellt?)", tag="warn")
            self.b_offsets = []
        self.b_offsets = (self.b_offsets + [off])[-15:]
        vals = sorted(self.b_offsets)
        first = self.b_offset is None
        self.b_offset = vals[len(vals) // 2]
        if first:
            self.log(f"Reserve-Gerät: Uhrversatz {self.b_offset:+.3f} s gegenüber dem Hauptgerät", tag="ok")
        DIAG.debug(f"Paar Eingang {a['ch']}: Versatz {off:+.4f} s, Median {self.b_offset:+.4f} s")
        self.refresh_conn_head()

    def backup_tick(self):
        """Unpaarige Impulse auswerten (aus dem Ethernet-Takt aufgerufen)."""
        now = time.time()
        wait = self.backup_wait()
        for rx, b in [x for x in self.b_pend if now - x[0] > wait]:
            self.b_pend.remove([rx, b])
            key = ("B", self.cp_run, b["ch"], b["seq"])
            if self.main_connected() and self.backup_prell_twin(
                    b["ch"], self.backup_corrected(b)["abs"], getattr(self, "a_hist", []),
                    [h for h in getattr(self, "b_hist", []) if abs(h[1] - b["abs"]) > 0.001]):
                DIAG.info(f"Reserve: Impuls {fmt_tod(self.backup_corrected(b)['abs'] % 86400)} Eingang {b['ch']} "
                          "innerhalb der Prellzeit (Doppelkontakt), verworfen")
                continue
            if self.main_connected():
                tod = fmt_tod(self.backup_corrected(b)["abs"] % 86400)
                rule = getattr(self, "_b_rule", None)
                if rule == "main":
                    c = self.backup_corrected(b)
                    self.cp_recs[key] = {"nr": 0, "cp_nr": b["nr"], "abs": c["abs"], "status": "reserve"}
                    self.log(f"Impuls {tod} auf Eingang {b['ch']} nur beim Reserve-Gerät: verworfen (Hauptgerät "
                             "gilt für diese Sitzung), unter «Auf Fahrstrecke» als «nur Reserve»", tag="warn")
                    self.save_autosave()
                    self.course_changed()
                    continue
                self.log(f"Abweichung: Impuls {tod} auf Eingang {b['ch']} nur beim Reserve-Gerät, das Hauptgerät "
                         "hat ihn nicht. Zeit der Reserve vorläufig übernommen", tag="warn")
                self.add_ticker(f"Abweichung: Zeit {tod} nur beim Reserve-Gerät", "warn")
                self.b_taken += 1
                self.on_cp_time(self.backup_corrected(b), "B")
                if rule is None:
                    self.backup_ask(key)
                continue
            self.b_taken += 1
            self.on_cp_time(self.backup_corrected(b), "B")
        for rx, a in [x for x in self.a_pend if now - x[0] > wait]:
            self.a_pend.remove([rx, a])
            if a.get("manual"):  # Handtaste am Hauptgeraet: die Reserve kann den Impuls nicht haben
                DIAG.info(f"Hauptgerät: Handimpuls {fmt_tod(a['abs'] % 86400)} Eingang {a['ch']} ohne Reserve")
                continue
            if self.backup_prell_twin(a["ch"], a["abs"], [h for h in getattr(self, "a_hist", [])
                                                         if abs(h[1] - a["abs"]) > 0.001], getattr(self, "b_hist", [])):
                DIAG.info(f"Hauptgerät: Impuls {fmt_tod(a['abs'] % 86400)} Eingang {a['ch']} innerhalb der "
                          "Prellzeit, ohne Gegenstück bei der Reserve: in Ordnung")
                continue
            if self.backup_connected() and now - self._b_warn_t > 60:
                self._b_warn_t = now
                self.log(f"Reserve-Gerät hat den Impuls {fmt_tod(a['abs'] % 86400)} auf Eingang {a['ch']} nicht "
                         "erhalten. Kabel und Eingänge der Reserve prüfen.", tag="warn")

    def stop_backup(self):
        if self.cp_b is not None:
            self.cp_b.stop()
            self.cp_b = None

    # ---------------- Geraete: CP 545 oder TM550 ---------------- #
    DEVICE_LABEL = {"cp545": "CP 545", "tm550": "TM550", "gprs": "GPRS Interface"}

    def reset_caps(self, device):
        """Faehigkeiten des Geraets. TM550 (ITS/Vola): FW 1.18 ohne vorgeladene Startnummer; FW 1.48 nimmt sie
        in TIMING an (#WP 026), in BASIC/SPEED/LAP nicht. #RT nur in BASIC/TIMING, Download (#DL) bei offenem
        Lauf, Befehle nur mit Pruefsumme, Antworten bis 3 s, puffert nicht bei Unterbruch. Ohne Vorladen
        vergibt die App die Nummern (ignore_nr)."""
        tm = device == "tm550"
        self.cp_device = device
        self.cp_mode = ""
        self.cp_caps = {"preload": not tm, "rt": not tm, "dl": True, "ignore_nr": tm, "buffer": not tm,
                        "timeout": 4.0 if tm else CMD_TIMEOUT}
        if device == "gprs":  # nur Empfang ueber das GPRS Interface auf 127.0.0.1
            self.cp_caps.update(preload=False, rt=False, dl=False, ignore_nr=False, buffer=False)
        try:
            self.root.title(f"SWV Live-Ranking v{APP_VERSION}  |  "
                            + {"tm550": "ITS TM550", "gprs": "GPRS Interface"}.get(device, "TAG Heuer CP 545"))
        except (AttributeError, tk.TclError):
            pass

    def dev_name(self):
        return self.DEVICE_LABEL.get(self.cp_device, "CP")

    def device_for_ip(self, ip):
        info = next((i for h, i in getattr(self, "cp_found", []) if h == ip), "")
        if "TM550" in (info or ""):
            return "tm550"
        if info:
            return "cp545"
        return self.settings["conn"].get("device") if self.settings["conn"].get("cp_ip") == ip else None

    def set_device(self, device, why=""):
        if device == self.cp_device:
            return
        self.reset_caps(device)
        self.settings["conn"]["device"] = device
        self.save_settings()
        if device == "tm550":
            self.log("Gerät: TM550 erkannt. In TIMING (ab Firmware 1.48) lädt die App die nächste Startnummer vor, "
                     "sonst vergibt sie die Nummern selbst. Verlorene Zeiten holt sie per Download des Laufs (mit "
                     "offenem Lauf). Empfohlen am TM550: TIMING, Start E1, Ziel E4, MANUAL IDENTIFICATION ohne "
                     "Smartphone-App." + (f" ({why})" if why else ""), tag="ok")
        DIAG.info(f"Gerät {device}: {self.cp_caps}")

    def connect_cp(self, ip, port=None):
        self.settings["conn"]["cp_ip"] = ip
        self.save_settings()
        self.fill_eth_combos()
        self.cp_reconnected = False
        device = self.device_for_ip(ip) if port is None else None
        if device:
            self.reset_caps(device)
        host, own_port = split_hostport(ip, None)
        if own_port:  # «ip:port», z.B. TM550 mit Werkseinstellung 2101
            port = own_port
            if own_port == TM_ALT_PORT:
                device = "tm550"
                self.reset_caps("tm550")
        if port is None and device == "tm550":
            port = cp_ports()[0]  # TM550: Befehle und Zeiten ueber dieselbe Verbindung auf Port 7000
        self.cp = CPClient(host, port or cp_ports()[1], self.q)
        self.cp.checksum = device == "tm550"
        self.cp.start()
        self.set_conn_status(f"verbinde mit CP {ip} ...", GOLD)
        self.btn_connect.configure(text="Trennen", bg=DARK_RED)

    def connect_gprs(self, target):
        """TAG Heuer «GPRS Interface» (Timing Online): liefert die Zeilen der Geraete im Pool auf 127.0.0.1 am
        Software-Port des Events (z.B. 9000), wie Elite V3 mit Protokoll «TAG HEUER CP540/HL440». Nur lesen:
        keine Befehle, Nummern wie geliefert, sonst aus der Startreihenfolge."""
        host, port = split_hostport(target.replace("localhost", "127.0.0.1"), None)
        if not port:
            return
        self.reset_caps("gprs")
        self.settings["conn"]["cp_ip"] = target
        self.save_settings()
        self.cp_reconnected = False
        self.cp = CPClient(host, port, self.q)
        self.cp.checksum = False
        self.cp.start()
        self.set_conn_status(f"verbinde mit GPRS Interface {target} ...", GOLD)
        self.btn_connect.configure(text="Trennen", bg=DARK_RED)
        self.log(f"GPRS Interface {target}: nur Empfang, die App sendet keine Befehle. Das GPRS Interface muss "
                 "laufen (Software-Port wie im Event auf TAG Heuer Timing Online). Es ist ein fremdes Programm "
                 "und verbindet selbst ins Internet; die App verbindet nur lokal zu 127.0.0.1.", tag="warn")

    def on_cp_connected(self, ip):
        again = self.cp_reconnected
        self.cp_reconnected = True
        # Wechsel Ethernet <-> USB oder neues Verbinden in derselben Sitzung: verpasste Zeilen nachtragen
        take_buffer = again or self.cp_session_seen
        self.cp_session_seen = True
        self.cp_last_rx = self.cp_last_hb = time.time()
        self.cp_rx_lines = 0  # Zeilen seit dem Verbinden: fuer den Hinweis bei stummer USB-Verbindung
        self._usb_silent_told = False
        self._cp_finish_dirty = True  # naechste Zielnummer am Geraet unbekannt: beim ersten Abgleich schreiben
        self.set_connected(True, f"CP {ip} verbunden")
        self.refresh_conn_head()
        if again:
            self.log(f"CP {ip} wieder verbunden", tag="ok")
            self.add_ticker("Verbindung zum CP 545 wieder hergestellt", "ziel")
        else:
            how = f"USB, {self.cp.baud} Bd" if self.cp.link == "usb" else f"Ethernet, Port {self.cp.port}"
            self.log(f"Verbunden mit CP {ip} ({how})", tag="ok")
        self.cp_cmds, self.cp_inflight = [], None
        if self.cp_device == "gprs":
            self.cp_backlog = None
            self.start_eth_tick()
            self.apply_show_settings()
            return
        self._eth_on_told = False
        self.cp_noanswer = 0
        self._noanswer_told = False
        self._clock_told = {}
        self._clock_prev = {}
        # Der CP schickt zuerst alles, was er seit dem letzten Abholen gepuffert hat, erst dann die Antwort
        # auf #SN. Diese Zeilen werden gesammelt und nicht als neue Impulse behandelt.
        self.cp_backlog, self.cp_backlog_t, self.cp_backlog_again = [], time.time(), take_buffer
        self.cp_query("#SN", "serial", on_fail=self._sn_retry)
        self.cp_query("#RP 003", ("param", "003"), on_ok=self._on_run)
        self.cp_query(f"#RP 026 {CH_START:02d}", ("param", "026", CH_START), on_ok=self._on_next_read,
                      on_fail=self._on_next_unread)
        self.cp_query("#RP 001", ("param", "001"), on_ok=self._on_prec)
        self.cp_query("#!T", "sync")
        self.__dict__.setdefault("_dev_lock", {}).pop(("A", CH_START), None)
        self.__dict__["_dev_lock"].pop(("A", CH_FINISH), None)
        self.__dict__.setdefault("_dev_lock_expect", {}).clear()
        self.__dict__.setdefault("_tm_ch_told", set()).discard("A")
        for k in ("lock_start", "lock_finish"):
            if self.tset().get(k):
                self.root.after(4000, lambda k=k: (self.cp_lock_preload(k, True), self.device_lock_write(k, True)))
        self.root.after(4500, lambda: self.device_lock_read("A") if self.main_connected() else None)
        self.root.after(3000, lambda: self.cp_write_precision(auto=True))  # eingestellte Praezision ans Geraet
        self.root.after(5500, self._blocking_when_idle)
        if not self.cp_recs and self.last_start_nr is None:  # noch kein Start: Ueberschrift fuer den ersten Verein
            self.root.after(2500, lambda: self.print_next_club(None, event="connect"))
        self.start_eth_tick()
        self.apply_show_settings()

    def cp_note_mode(self, mode):
        """Zeitmessart aus OP- bzw. DS-Zeile. Vorladen nur in Zeitmessarten mit Startnummern (siehe
        mode_numbers); lehnt das Geraet trotzdem ab (AK F, Zuruecklesen 0), schaltet cp_set_preload aus."""
        mode = (mode or "").strip()
        if not mode or self.cp_device not in ("cp545", "tm550"):
            return
        changed = mode != self.cp_mode
        self.cp_mode = mode
        verdict = mode_numbers(self.cp_device, mode)
        label = mode_label(mode)
        if verdict == "unknown" and changed:
            self.log(f"{self.dev_name()}: Zeitmessart {label} ist mit der App nicht getestet. Die App vergibt die "
                     "Startnummern selbst. Empfohlen: " + ("TIMING." if self.cp_device == "tm550" else "NET TIME."),
                     tag="warn")
        self.cp_set_preload(verdict == "yes", f"Zeitmessart {label}")

    def cp_set_preload(self, on, why):
        """Startnummern im CP vorladen ein/aus. Aus: die App nummeriert die Starts aus der Startreihenfolge
        (wie beim TM550). Meldung nur beim Wechsel."""
        if self.cp_device not in ("cp545", "tm550") or bool(self.cp_caps.get("preload")) == bool(on):
            return
        tm = self.cp_device == "tm550"
        self.cp_caps["preload"] = bool(on)
        if tm:
            self.cp_caps["ignore_nr"] = not on  # ohne Vorladen sind die Nummern des TM550 nur Zaehler
        self.cp_next_start = None
        self._cp_next_pending = None
        name = self.dev_name()
        if on:
            self.log(f"{name} nimmt Startnummern an ({why}): nächste Nummer wird vorgeladen", tag="ok")
            self.root.after(50, lambda: self.cp_sync_next("Zeitmessart"))
        else:
            need = "TIMING und Lauf offen" if tm else "NET TIME und Lauf offen"
            self.log(f"{name} vergibt keine Startnummern ({why}). Die App nummeriert die Starts aus der "
                     f"Startreihenfolge. Für Nummern vom Gerät: Zeitmessart {need}.", tag="warn")
            self.add_ticker(f"Startnummern vergibt die App ({name} ohne {need.split(' und')[0]} / Lauf)", "warn")
        self.update_panels()

    def usb_silent_hint(self):
        """USB ohne eine einzige Zeile vom Geraet: meist Baudrate oder Flow control am TM550 (bzw. CP)."""
        if (self.settings["conn"]["mode"] != "usb" or getattr(self, "cp_rx_lines", 0)
                or getattr(self, "_usb_silent_told", False) or getattr(self, "cp_noanswer", 0) < 2):
            return
        self._usb_silent_told = True
        baud = self.settings["conn"].get("usb_baud", 9600)
        self.log(f"USB: vom Gerät kommt nichts an. TM550: am Gerät Communication › USB › {baud} Bds wählen, nicht "
                 f"«9600 Bds Flow control», dieselbe Baudrate wie in der App ({baud}). CP 545: USB-Ausgabe auf "
                 f"{baud} Baud prüfen. Sonst anderen COM-Port wählen.", tag="error")
        self.add_ticker("USB: keine Antwort vom Gerät (Baudrate/Flow control prüfen)", "warn")

    def _sn_retry(self, reason):
        """Keine Antwort auf #SN ohne Pruefsumme: TM550 versteht Befehle nur mit Pruefsumme."""
        if self.cp is None or getattr(self.cp, "checksum", True) or reason != "keine Antwort":
            return
        self.cp.checksum = True
        DIAG.info("#SN ohne Antwort: Befehle ab jetzt mit Prüfsumme")
        self.cp_cmds.insert(0, {"text": "#SN", "expect": "serial", "on_ok": None,
                                "on_fail": lambda r: setattr(self.cp, "checksum", False) if self.cp else None,
                                "label": "#SN", "tries": 1})

    def _on_prec(self, info):
        try:
            self.cp_prec = max(0, min(5, int(info["values"][0])))
        except (IndexError, ValueError):
            pass

    def _on_run(self, info):
        try:
            run = int(info["values"][0])
        except (IndexError, ValueError):
            return
        self.cp_run_open = bool(run)
        if run:
            self._cp_norun_told = False
        if run and run != self.cp_run:
            self.cp_run = run
            self._club_printed = set()  # neuer Lauf: Vereinswechsel wieder drucken
            self.log(f"CP: Lauf {run} offen")
        if run and not self.cp_caps["preload"] \
                and mode_numbers(self.cp_device, getattr(self, "cp_mode", "") or "") in ("yes", "maybe"):
            self.cp_set_preload(True, f"Lauf {run} offen")
        elif not run:
            self.cp_run = 0
            if self.cp_device == "tm550":
                if self.cp_caps.get("preload"):
                    self.cp_set_preload(False, "kein Lauf offen")
                if not getattr(self, "_tm_norun_told", False):
                    self._tm_norun_told = True
                    self.log("TM550: kein Lauf offen. Zeiten kommen trotzdem, verlorene Zeiten lassen sich aber nur "
                             "mit offenem Lauf nachladen. Knopf «Lauf öffnen» öffnet einen.", tag="warn")
            else:
                if not getattr(self, "_cp_norun_told", False):  # nur einmal, bis wieder ein Lauf offen ist
                    self._cp_norun_told = True
                    self.log("CP: kein Lauf offen. Am CP einen Lauf öffnen (NET TIME).", tag="warn")
                self.cp_set_preload(False, "kein Lauf offen")

    def _on_next_unread(self, reason):
        if reason == "keine Antwort" and self.cp_readback:
            self.cp_readback = False
            self.log("CP: Zurücklesen wird nicht beantwortet, nur Bestätigung (AK) wird geprüft", tag="warn")
        self.cp_next_start = None
        self.cp_sync_next("Verbindung")

    def _on_next_read(self, info):
        try:
            self.cp_next_start = int(info["values"][-1])
        except (IndexError, ValueError):
            return
        self.cp_sync_next("Verbindung")

    # ---------------- Befehle mit Bestaetigung ---------------- #
    def cp_query(self, text, expect="ack", on_ok=None, on_fail=None, label=None, tries=1, silent=False):
        """Befehl einreihen. expect: 'ack' | 'serial' | 'sync' | ('param', id[, eingang]).
        silent: Abfrage im Takt (Sperren, Lauf): Befehl und Antwort nur ins Diagnose-Log."""
        if self.cp is None or self.cp_device == "gprs":
            if on_fail:
                on_fail("keine Verbindung" if self.cp is None else "nicht unterstützt")
            return
        self.cp_cmds.append({"text": text, "expect": expect, "on_ok": on_ok, "on_fail": on_fail,
                             "label": label or text, "tries": tries, "silent": silent})
        self.cp_pump()

    def cp_pump(self):
        if self.cp_inflight is not None or not self.cp_cmds or self.cp is None or not self.cp.connected:
            return
        if time.time() < self.cp_hold_until:
            self.root.after(int((self.cp_hold_until - time.time()) * 1000) + 5, self.cp_pump)
            return
        cmd = self.cp_cmds.pop(0)
        wait = self.cp_caps["timeout"]
        if cmd["expect"] == "serial":
            wait = max(wait, 8.0)  # erste Antwort nach dem Verbinden: TM550 braucht bis 6 s
        cmd["deadline"] = time.time() + wait
        self.cp_inflight = cmd
        DIAG.debug(f"CP A> {cmd['text']}")
        self._diag_tx = (time.strftime("%H:%M:%S"), cmd["text"])
        self.cp.send(cmd["text"])
        self._rx_silent = bool(cmd.get("silent"))
        if not self._rx_silent:
            self.log(f"→ CP {cmd['text']}", focus=False, tag="ok")

    def cp_resolve(self, ok, info=None, reason=""):
        cmd, self.cp_inflight = self.cp_inflight, None
        if ok or info is not None:
            self.cp_noanswer = 0
        elif reason == "keine Antwort":
            self.cp_noanswer = getattr(self, "cp_noanswer", 0) + 1
            self.usb_silent_hint()
            if (self.cp_noanswer >= 3 and time.time() - self.cp_last_rx < 120
                    and not getattr(self, "_noanswer_told", False)):
                self._noanswer_told = True
                msg = (f"{self.dev_name()} beantwortet keine Befehle mehr, Zeiten kommen aber weiter und werden "
                       "übernommen. Nummern vorladen und Nachholen gehen nicht. Abhilfe in einer Pause: Gerät aus- "
                       "und einschalten" + (", danach Ethernet am CP wieder einschalten." if self.cp_device == "cp545"
                                             else "."))
                self.log(msg, tag="error")
                self.add_ticker(f"{self.dev_name()} antwortet nicht auf Befehle", "warn")
                DIAG.warning(f"Befehle ohne Antwort: {cmd['text']!r}")
        if cmd["expect"] != "ack" or self.cp_device == "tm550":
            # nachfolgendes AK der Abfrage abwarten; TM550 quittiert manche Befehle doppelt (AK F + AK C)
            self.cp_hold_until = time.time() + (0.6 if self.cp_device == "tm550" else 0.3)
        if ok and cmd["on_ok"]:
            cmd["on_ok"](info)
        elif not ok and cmd["on_fail"]:
            cmd["on_fail"](reason)
        self.cp_pump()

    def cp_check_reply(self, info):
        cmd = self.cp_inflight
        if cmd is None:
            return
        exp = cmd["expect"]
        if info["kind"] == "ack":
            if exp == "ack":
                self.cp_resolve(info["code"] == "C", info, {"F": "vom CP abgelehnt",
                                                            "R": "vom CP nicht unterstützt"}.get(info["code"], ""))
            elif info["code"] in "FR":
                self.cp_resolve(False, info, "vom CP abgelehnt" if info["code"] == "F" else "nicht unterstützt")
            return
        if exp == "serial" and info["kind"] == "serial":
            self.cp_info = f"{info['type']} Nr {info['serial']} {info['version']}".strip()
            self.log(f"CP: {self.cp_info}", tag="ok")
            self.set_device("tm550" if "TM550" in info["type"].upper() else "cp545", self.cp_info)
            if self.cp_device == "tm550" and self.cp is not None:
                self.cp.checksum = True
            self.cp_resolve(True, info)
        elif exp == "sync" and info["kind"] == "sync":
            self.add_cp_offset((datetime.date.today() - EPOCH_2000).days * 86400 + info["tod"])
            self.cp_resolve(True, info)
        elif isinstance(exp, tuple) and info["kind"] == "param" and info["id"] == exp[1]:
            if len(exp) > 2:
                try:
                    if int(info["values"][0]) not in (exp[2], 0):  # TM550: «&P 026 00 0» = nichts vorgeladen
                        return
                except (IndexError, ValueError):
                    return
            self.cp_resolve(True, info)

    def cp_timeout_check(self):
        cmd = self.cp_inflight
        if cmd is None or time.time() < cmd["deadline"]:
            return
        self.cp_resolve(False, None, "keine Antwort")

    def cp_write_param(self, param, inp, nr, label, on_done=None, attempt=1):
        """#WP schreiben, mit #RP zuruecklesen, bis 3 Versuche. on_done(ok)."""
        text = f"#WP {param} {inp:02d} {nr:04d}"

        def failed(reason):
            if reason in ("vom CP abgelehnt", "CP meldet 0"):
                # CP nimmt keine Nummer an (kein Lauf offen bzw. Zeitmessart ohne Nummern): nicht wiederholen
                DIAG.info(f"#WP {param} {nr}: {reason}")
                if on_done:
                    on_done(False, reason)
                return
            if param == "026" and inp == CH_START and reason.startswith("CP meldet") and on_done:
                # inzwischen gestartet (CP zaehlt weiter): nicht dieselbe Nummer erzwingen, neu abgleichen
                DIAG.info(f"#WP 026 {nr}: {reason}, neu abgleichen")
                on_done(False, reason)
                return
            if attempt < 3:
                self.log(f"CP: {label} Nr {nr} nicht bestätigt ({reason}), neuer Versuch", tag="warn")
                self.root.after(300, lambda: self.cp_write_param(param, inp, nr, label, on_done, attempt + 1))
            else:
                self.log(f"CP: {label} Nr {nr} nach 3 Versuchen nicht gesetzt ({reason})", tag="error")
                self.add_ticker(f"CP: {label} Nr {nr} nicht gesetzt, am CP prüfen", "warn")
                if on_done:
                    on_done(False, reason)

        def read_ok(info):
            try:
                got = int(info["values"][-1])
            except (IndexError, ValueError):
                got = None
            if got == nr:
                self.log(f"CP: {label} Nr {nr} gesetzt und zurückgelesen", tag="ok")
                if on_done:
                    on_done(True)
            elif got == 0 and self.cp_device == "tm550":
                # TM550 1.48: vorgeladene Nummer schon von einem Start verbraucht, liest dann 0 zurueck
                self.log(f"TM550: {label} Nr {nr} bestätigt (inzwischen verbraucht)", tag="ok")
                if on_done:
                    on_done(True)
            else:
                failed(f"CP meldet {got}")

        def read_fail(reason):
            if reason == "keine Antwort" and self.cp_readback:
                self.cp_readback = False
                self.log("CP: Zurücklesen wird nicht beantwortet, nur Bestätigung (AK) wird geprüft", tag="warn")
            self.log(f"CP: {label} Nr {nr} gesetzt (bestätigt)", tag="ok")
            if on_done:
                on_done(True)

        def ak_ok(_info):
            if self.cp_readback:
                self.cp_query(f"#RP {param} {inp:02d}", ("param", param, inp), on_ok=read_ok, on_fail=read_fail)
            else:
                read_fail("")

        self.cp_query(text, "ack", on_ok=ak_ok, on_fail=failed)

    # ---------------- Startnummern vorladen / Steuerung ---------------- #
    def order_anchor(self):
        return self.last_start_nr if self.eth_mode() else self.current_nr

    def cp_sync_next(self, reason=""):
        """Naechste Startnummer aus der Startliste im CP vorladen, wenn sie von seiner Folge abweicht."""
        if not self.eth_mode() or self.cp is None or not self.cp.connected or not self.cp_caps["preload"]:
            if self.eth_mode() and not self.tset().get("lock_start"):
                nxt = self.next_starters(1)
                if nxt:
                    self.backup_preload(nxt[0])  # Reserve auch, wenn das Hauptgeraet nicht vorlaedt
            return
        if self.tset().get("lock_start"):
            return  # Sperrnummer bleibt vorgeladen
        nxt = self.next_starters(1)
        if not nxt:
            return
        want = nxt[0]
        self.backup_preload(want)
        if want == self.cp_next_start or getattr(self, "_cp_next_pending", None) == want:
            return
        self._cp_next_pending = want

        def done(ok, why=""):
            self._cp_next_pending = None
            if not ok and why in ("vom CP abgelehnt", "CP meldet 0"):
                self.cp_set_preload(False, "Startnummer vorladen abgelehnt" if why == "vom CP abgelehnt"
                                    else "Startnummer vom CP nicht übernommen")
                return
            if ok:
                self.cp_next_start = want
                self.update_panels()
            # Startliste hat sich inzwischen geaendert: nochmals abgleichen
            self.root.after(50, self.cp_sync_next)

        self.cp_write_param("026", CH_START, want, "nächster Start", done)

    # ================================================================== #
    # Zeitmessung Ethernet: die App ordnet die Impulse selbst zu
    #   Start: Nummer vom CP (vorgeladen aus der Startliste)
    #   Ziel:  das Boot, das in der App als naechstes erwartet wird
    # Jede Startzeit fuehrt 'cp_nr' (wie der CP sie kennt) und 'nr' (richtige Nummer).
    # Schluessel einer Zeit: (geraet, lauf, eingang, seq), Zeiten absolut ab 01.01.2000 (ueber Mitternacht).
    # ================================================================== #
    def tset(self):
        return self.settings["timing"]

    def run_recs(self, ch=None):
        return [(k, r) for k, r in self.cp_recs.items()
                if k[1] == self.cp_run and (ch is None or k[2] == ch)]

    def cp_set_next_finish(self, nr):
        """Ueberholen: nr kommt als naechstes ins Ziel."""
        self.finish_override = nr
        self.log(f"Überholen: Nr {nr} kommt als nächstes ins Ziel", tag="ok")
        self.add_ticker(f"Nr {nr} hat überholt und kommt als nächstes ins Ziel", None)
        self.course_changed()

    def cp_alive(self):
        """Startzeiten, die der CP noch auf der Strecke sieht (fuer seinen Papierstreifen)."""
        keys = [k for k, r in self.run_recs(CH_START) if k[0] == "A" and r["status"] == "ok"
                and r["cp_nr"] > 0 and not r.get("cp_done")]
        return sorted(keys, key=lambda k: self.cp_recs[k]["abs"])

    def cp_sync_finish(self, force=False):
        """Den CP auf dasselbe naechste Boot einstellen wie die App (#WP 026 04), damit sein
        Papierstreifen und seine Rangliste stimmen. Die Zuordnung in der App haengt nicht davon ab.
        force: auch schreiben, wenn der CP nach der eigenen Folge schon richtig laege (nach Ziel freigeben)."""
        force = force or getattr(self, "_cp_finish_dirty", False)
        if (not self.eth_mode() or self.cp is None or not self.cp.connected or not self.course
                or not self.cp_caps["preload"] or self.tset().get("lock_finish") or self.cp_device == "tm550"):
            return  # TM550: keine vorgeladene Zielnummer (nur Start in TIMING)
        want = self.cp_recs[self.course[0][2]]
        if want.get("cp_done") or want["cp_nr"] <= 0:
            return
        alive = self.cp_alive()
        if not alive:
            return
        cp_next = next((k for k in alive if self.cp_recs[k]["cp_nr"] == self.cp_finish_want), alive[0])
        target = want["cp_nr"]
        if getattr(self, "_cp_finish_pending", None) == target:
            return
        if self.cp_recs[cp_next]["cp_nr"] == target and not force:
            return
        self._cp_finish_pending = target

        def done(ok, why=""):
            self._cp_finish_pending = None
            if ok:
                self.cp_finish_want = target
                self._cp_finish_dirty = False
                self.root.after(50, self.cp_sync_finish)
            elif why in ("vom CP abgelehnt", "CP meldet 0") and target not in getattr(self, "_restore_told", set()):
                self._restore_told = getattr(self, "_restore_told", set()) | {target}
                self.log(f"CP nimmt Nr {target} für das Ziel nicht an (für den CP ist es schon im Ziel). Der nächste "
                         f"Zielimpuls kommt am CP ohne Nummer, die App ordnet ihn Nr {target} zu. Am CP vor dem "
                         f"Zielimpuls «{target} E4» eingeben, dann stimmen Papierstreifen und CP überein.",
                         tag="warn")

        self.cp_write_param("026", CH_FINISH, target, "nächstes Ziel", done)

    # ---------------- Status DNS / DNF / DSQ ---------------- #
    def set_status(self, nr, code, reason="", keep_on_course=False):
        """code: 'DNS', 'DNF', 'DSQ' oder None (aufheben). keep_on_course: DSQ-Boot faehrt weiter ins Ziel
        und nimmt dort seinen Zielimpuls, wird aber nicht klassiert."""
        old = self.status.get(nr)
        key = self.course_key(nr)
        if code == old and not (key and code == "DSQ"):
            return
        if code:
            self.status[nr] = code
        else:
            self.status.pop(nr, None)
        if code in ("DNF", "DSQ"):
            if key:
                if code == "DSQ" and keep_on_course:
                    self.cp_recs[key]["dsq_run"] = True
                else:
                    self.cp_recs[key]["dnf"] = True
                    self.cp_recs[key].pop("dsq_run", None)
        elif code is None:
            for _k, r in self.run_recs(CH_START):
                if r["nr"] == nr:
                    r["dnf"] = False
                    r.pop("dsq_run", None)
        if self.finish_override == nr and code and not keep_on_course:
            self.finish_override = None
        who = self.who_text(nr)
        label = {"DNS": "nicht gestartet", "DNF": "ausgeschieden", "DSQ": "disqualifiziert"}
        if code:
            if keep_on_course:
                reason = (reason + " " if reason else "") + "(fährt weiter, Zielimpuls gehört diesem Boot)"
            self.log(f"Nr {nr} {label[code]} ({code}){(' ' + reason) if reason else ''}", tag="warn")
            self.add_ticker(f"Nr {nr}{(' ' + who) if who else ''} {label[code]}", "warn")
        else:
            self.log(f"Nr {nr}: Status {old} aufgehoben", tag="ok")
        self.save_autosave()
        self._rank_cache = None
        self.on_data_changed()
        self.course_changed()
        self.cp_sync_next("Status")

    def cp_cancel_start(self, nr, code="DNF", running=False):
        if self.course_key(nr) is None:
            return
        what = "ausgeschieden" if code == "DNF" else "disqualifiziert"
        if running:
            text = (f"{self.order_label(nr)} als disqualifiziert markieren?\nDas Boot fährt weiter: der nächste "
                    "Zielimpuls gehört ihm, die Zeit wird nicht klassiert.")
        else:
            text = (f"{self.order_label(nr)} als {what} markieren?\nDas Boot verlässt die Fahrstrecke sofort. "
                    "Am CP läuft die Zeit weiter: dort mit Nr + R + 0" + ("." if code == "DSQ" else "")
                    + " abbrechen.")
        if not messagebox.askyesno(what.capitalize(), text):
            return
        self.set_status(nr, code, "(nur in der App)" if not running else "", keep_on_course=running)

    def mark_dnf(self, nr, key, local=False):
        self.set_status(nr, "DNF", "(nur in der App)" if local else "(Startzeit am CP storniert)")

    def cp_change_number(self, key, old, new):
        """Nummer auf der Strecke aendern (nur in der App, der CP kennt #WC 013 nicht)."""
        rec = self.cp_recs.get(key) if key else None
        if rec is None or rec["nr"] != old:
            return
        rec["nr"] = new
        self.status.pop(new, None)
        if self.finish_override == old:
            self.finish_override = new
        self.log(f"Nummer auf der Strecke: Nr {new} statt Nr {old} (nur in der App, der CP führt weiter "
                 f"Nr {rec['cp_nr']})", tag="warn")
        if rec["cp_nr"] != new and self.eth_mode():
            messagebox.showinfo("Nummer am CP nachführen",
                                f"Die App führt das Boot jetzt als Nr {new}. Der CP kann nicht ferngesteuert "
                                f"umnummerieren und zeigt weiter Nr {rec['cp_nr']}.\n\nAm CP eingeben:\n"
                                f"{rec['cp_nr']}  R  E1  {new}  Enter\n\nDanach stimmen Anzeigetafel, "
                                f"Papierstreifen und App überein.")
        self.add_ticker(f"Nummer korrigiert: Nr {new} statt Nr {old} auf der Fahrstrecke", None)
        if self.start_order and new not in self.participants and not self.is_test(new):
            self.ensure_participant(new, after=old if old in self.order_index else None, prompt=True)
        self.save_autosave()
        self.on_data_changed()
        self.course_changed()
        self.cp_sync_next("Nummer geändert")

    # ---------------- Daten vom CP ---------------- #
    def add_cp_offset(self, cp_abs):
        now = time.time()
        self.cp_offsets.append((now, cp_abs - local_abs()))
        self.cp_offsets = [(t, o) for t, o in self.cp_offsets if now - t < 600][-50:]

    def cp_offset(self):
        return max(o for _t, o in self.cp_offsets) if self.cp_offsets else None

    def raw_log(self, dev, raw):
        """Jede Zeile des CP sofort in die Rohdaten-Datei des Tages (Grundlage fuer Neuberechnung und Simulator)."""
        try:
            folder = os.path.join(self.data_path, RAW_DIR)
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, time.strftime("%Y-%m-%d") + ".jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": round(time.time(), 3), "dev": dev, "line": strip_frame(raw)},
                                    ensure_ascii=False) + "\n")
        except OSError:
            pass

    def handle_eth_line(self, raw, dev="A"):
        if dev == "A":
            self.cp_last_rx = time.time()
            self.cp_rx_lines = getattr(self, "cp_rx_lines", 0) + 1
        text = strip_frame(raw)
        info = parse_thcom(raw)
        DIAG.debug(f"CP {dev}< {raw.strip()}")
        if dev == "A":
            self._diag_rx = raw.strip()
            if self.cp_inflight is not None and self.cp_download is not None:
                self.cp_inflight["deadline"] = max(self.cp_inflight["deadline"], time.time() + self.cp_caps["timeout"])
        if info is None:
            return
        if info["kind"] == "time" and (self.cp_device if dev == "A" else self.cp_b_device) == "tm550":
            # TM550: FW 1.18 lieferte ein falsches Tagesfeld (9793 statt 9822), FW 1.48 ein richtiges. Weicht es
            # mehr als einen Tag vom PC ab, gilt der Tag vom PC.
            pc_day = day_from_pc(info["tod"])
            if abs(info["day"] - pc_day) > 1:
                info["day_raw"] = info["day"]
                info["day"] = pc_day
                info["abs"] = info["day"] * 86400 + info["tod"]
        self.raw_log(dev, raw)
        if dev == "B" and info["kind"] in ("open", "close"):
            self.cp_b_mode = info.get("mode", "") if info["kind"] == "open" else ""
            self.cp_b_open = info["kind"] == "open"
            if info["kind"] == "open":
                self.cp_b_next = None
                if getattr(self, "b_seq_last", {}):  # neuer Lauf der Reserve: Zaehlnummern neu
                    self.b_seq_base = getattr(self, "b_seq_base", 0) + 10000
                    self.b_seq_last = {}
                self.root.after(100, lambda: self.cp_sync_next("Reserve: Lauf offen"))
        if dev == "B" and info["kind"] == "serial":
            self.cp_b_device = "tm550" if "TM550" in info["type"].upper() else "cp545"
            self.cp_b_fw = info.get("version", "")
            self.cp_b_nr_ok = self.cp_b_device == "cp545" or self.cp_b_fw >= "1.4"
            self.cp_b_next = None
            if self.cp_b is not None and self.cp_b_device == "tm550":
                self.cp_b.checksum = True
            self.root.after(100, lambda: self.cp_sync_next("Reserve verbunden"))
            self.root.after(600, self.backup_write_precision)
            self.__dict__.setdefault("_dev_lock", {}).pop(("B", CH_START), None)
            self.__dict__["_dev_lock"].pop(("B", CH_FINISH), None)
            self.root.after(1200, lambda: self.device_lock_read("B"))
            self.root.after(2000, lambda: self.device_blocking_write(("B",)))
            self.log(f"Reserve-Gerät: {info['type']} Nr {info['serial']} {info['version']}".strip(), tag="ok")
            return
        if dev == "A" and self.cp_backlog is not None:
            if info["kind"] == "serial":
                self.finish_backlog()
            elif info["kind"] in ("time", "result", "open", "close") and not info.get("answer"):
                now = time.time()
                self.cp_backlog.append(info)
                self.cp_backlog_t = now
                if self.cp_inflight is not None:  # CP ist noch am Senden: Befehl nicht als verloren werten
                    self.cp_inflight["deadline"] = max(self.cp_inflight["deadline"], now + CMD_TIMEOUT)
                return
        if info["kind"] == "time" and not info.get("answer") and info["type"] in ("TN", "T+", "T="):
            self.check_device_clock(info, dev)
            if dev == "A":
                self.cp_last_imp = time.time()
        quiet = info["kind"] in ("ack", "param", "serial", "sync")
        if info["kind"] == "note":
            text = f"{text}  ({info['label']}, wird nicht ausgewertet)"
        if quiet and dev == "A" and getattr(self, "_rx_silent", False):
            DIAG.debug(f"CP A< {text}")
        elif quiet and dev == "B" and getattr(self, "_rx_silent_b", 0) > time.time():
            DIAG.debug(f"CP B< {text}")
        else:
            self.log(("CP " if dev == "A" else "CP Reserve ") + text, focus=False, tag=None if not quiet else "test")
        if info["kind"] == "param" and info.get("id") in ("002", "006", "023"):
            self.device_param_event(info, dev)
        if quiet:
            if dev == "A":
                self.cp_check_reply(info)
            return
        if info["kind"] == "dlstart":
            if dev == "A" and info.get("mode") and info["run"] == self.cp_run:
                self.cp_note_mode(info["mode"])
            if dev == "A":
                self.cp_download = []
                DIAG.debug(f"Download Lauf {info['run']} beginnt")
            return
        if info["kind"] == "dlend":
            if dev == "A" and self.cp_download is not None:
                items, self.cp_download = self.cp_download, None
                if items:
                    self.process_download(items)
                else:
                    DIAG.debug(f"DS/DE {info['run']} ohne Zeiten")  # TM550 meldet sich von selbst so
            return
        if info["kind"] == "time":
            if info["answer"]:
                if self.cp_download is not None and dev == "A":
                    self.cp_download.append(info)
                else:
                    k = (dev, self.cp_run, info["ch"])
                    if info["seq"] > self.cp_lastseq.get(k, 0):
                        self.cp_lastseq[k] = info["seq"]
                    self.on_cp_time(info, dev, recalled=True)
                return
            if dev == "B":
                self.backup_time(info)
                return
            self.check_seq_gap(info, dev)
            self.on_cp_time(info, dev)
            self.backup_note_main(info)
        elif info["kind"] == "result" and info["type"] == "RR" and dev == "A":
            self.on_cp_result(info)
        elif info["kind"] == "open" and dev == "A":
            if info["run"] in self.cp_closed_runs:
                # Lauf mit derselben Nummer neu geoeffnet: der CP zaehlt wieder ab 1
                self.archive_run(info["run"], "am CP geschlossen und wieder geöffnet")
                self.cp_closed_runs.discard(info["run"])
            self.cp_run = info["run"]
            self.cp_run_open = True
            self.finish_override = self.cp_finish_want = None
            self.log(f"CP: Lauf {info['run']} geöffnet ({info['mode'] or '?'})", tag="ok")
            self.cp_note_mode(info["mode"])
            self.course_changed()
        elif info["kind"] == "close" and dev == "A":
            self.cp_closed_runs.add(info["run"])
            if info["run"] == self.cp_run:
                self.cp_run_open = False
            self.finish_override = None
            self.log(f"CP: Lauf {info['run']} geschlossen", tag="warn")
            if info["run"] == self.cp_run:
                self.cp_set_preload(False, "kein Lauf offen")
            self.course_changed()

    def archive_run(self, run, why):
        """Bisherige Zeiten eines Laufs als abgeschlossene Runde ablegen (Laufnummer run + 1000 * n),
        damit der neu begonnene Lauf mit derselben Nummer wieder ab Seq 1 zaehlen kann. Resultate bleiben."""
        mapping = {k: k for k in self.cp_recs if k[1] == run}
        if not mapping:
            return None
        n = 1 + max((k[1] // 1000 for k in self.cp_recs if k[1] >= 1000 and k[1] % 1000 == run), default=0)
        new_run = run + 1000 * n
        mapping = {k: (k[0], new_run, k[2], k[3]) for k in mapping}

        def remap(v):
            if isinstance(v, (tuple, list)) and len(v) == 4 and tuple(v) in mapping:
                return mapping[tuple(v)]
            return v

        self.cp_recs = {mapping.get(k, k): r for k, r in self.cp_recs.items()}
        for r in self.cp_recs.values():
            for f in ("start", "done", "twin", "cp_start"):
                if f in r:
                    r[f] = remap(r[f])
        for res in self.results.values():
            if res.get("cp"):
                res["cp"] = list(remap(res["cp"]))
        self.last_finish_key = remap(self.last_finish_key) if self.last_finish_key else None
        if getattr(self, "cp_last_finish_rx", None):
            self.cp_last_finish_rx = remap(self.cp_last_finish_rx)
        for k in [k for k in self.cp_lastseq if k[1] == run]:
            del self.cp_lastseq[k]
        self.finish_override = self.cp_finish_want = None
        self.log(f"CP: Lauf {run} neu begonnen ({why}). {len(mapping)} bisherige Zeiten als Runde {new_run} "
                 "abgelegt, Resultate bleiben.", tag="warn")
        DIAG.info(f"Lauf {run} archiviert als {new_run}: {sorted(mapping)}")
        self.save_autosave()
        self.course_changed()
        return new_run

    def finish_backlog(self):
        """Gepufferte Zeilen des CP nach dem Verbinden auswerten. Nach einem Unterbruch in dieser Sitzung
        werden die fehlenden Zeiten uebernommen, beim ersten Verbinden nur der Lauf und die Sequenzen."""
        items, self.cp_backlog = self.cp_backlog, None
        if not items:
            return
        run = self.cp_run
        timed = []
        closed = set()
        for info in items:
            if info["kind"] == "close":
                closed.add(info["run"])
            elif info["kind"] == "open":
                if info["run"] in closed or info["run"] in self.cp_closed_runs:
                    # im Puffer: Lauf geschlossen und neu geoeffnet. Zeilen davor gehoeren zur alten Runde
                    timed = [(-1, i) for _r, i in timed]
                    if self.cp_backlog_again:
                        self.archive_run(info["run"], "während der Unterbrechung am CP neu geöffnet")
                    closed.discard(info["run"])
                    self.cp_closed_runs.discard(info["run"])
                run = info["run"]
            elif info["kind"] == "time":
                timed.append((run, info))
        if run and run != self.cp_run:
            self.cp_run = run
            self.log(f"CP: Lauf {run} offen")
        take, old = [], 0
        for r, info in timed:
            if r != run:
                old += 1
                continue
            k = ("A", run, info["ch"])
            if info["seq"] > self.cp_lastseq.get(k, 0):
                self.cp_lastseq[k] = info["seq"]  # sonst holt #RT die alten Zeiten wieder
            if self.cp_backlog_again:
                take.append(info)
            elif ("A", run, info["ch"], info["seq"]) not in self.cp_recs:
                old += 1
        if old:
            self.log(f"CP: {old} ältere Zeiten aus dem Speicher des CP nicht übernommen (vor dem Verbinden). "
                     f"Falls sie zum laufenden Wettkampf gehören: «Lauf vom CP laden».", tag="warn")
        if take:
            self.log(f"CP: {len(take)} Zeilen aus der Zeit ohne Verbindung werden ausgewertet", tag="ok")
            self.process_download(take)

    def check_seq_gap(self, t, dev):
        """Fehlende Sequenznummern mit #RT beim CP nachholen (verlorene Zeilen)."""
        if t["type"] not in ("TN", "T+", "T=") or t["seq"] <= 0 or dev != "A":
            return
        k = (dev, self.cp_run, t["ch"])
        last = self.cp_lastseq.get(k)
        if last is not None and t["seq"] > last + 1:
            missing = list(range(last + 1, min(t["seq"], last + 51)))
            if not self.cp_caps["rt"]:
                if self.cp_caps["dl"] and self.cp_run:
                    self.log(f"{self.dev_name()}: Zeiten Seq {missing[0]}-{missing[-1]} auf Eingang {t['ch']} "
                             "fehlen, Lauf wird nachgeladen", tag="warn")
                    if not getattr(self, "_gap_dl_pending", False):
                        self._gap_dl_pending = True
                        self.root.after(1500, self._gap_download)
                else:
                    self.log(f"{self.dev_name()}: Zeiten Seq {missing[0]}-{missing[-1]} auf Eingang {t['ch']} "
                             "fehlen und lassen sich ohne offenen Lauf nicht nachholen. Am Gerät ablesen und von "
                             "Hand nachtragen.", tag="error")
                missing = []
            for s in missing:
                if (dev, self.cp_run, t["ch"], s) not in self.cp_recs:
                    self.cp_query(f"#RT {s:04d} {t['ch']:02d}", "ack")
        if last is None or t["seq"] > last:
            self.cp_lastseq[k] = t["seq"]

    def _gap_download(self):
        self._gap_dl_pending = False
        if self.cp is not None and self.cp.connected and self.cp_run:
            DIAG.info(f"Lücke: lade Lauf {self.cp_run} (#DL)")
            self.cp_query(f"#DL {self.cp_run:02d}", "ack")

    def cp_probe(self):
        """Nach der letzten bekannten Zeit je Eingang fragen: findet auch eine verlorene letzte Zeile,
        auf die keine weitere Zeit folgt (Sequenzluecke sonst erst beim naechsten Impuls sichtbar)."""
        if not self.cp_caps["rt"]:
            return
        cnt = self.__dict__.setdefault("_probe_cnt", {})
        for ch in (CH_START, CH_FINISH):
            last = self.cp_lastseq.get(("A", self.cp_run, ch))
            if last is not None:
                k = (self.cp_run, ch, last + 1)
                cnt[k] = cnt.get(k, 0) + 1
                if cnt[k] > 3:
                    continue  # dreimal AK F: keine solche Zeit, erst nach dem naechsten Impuls wieder fragen
                if cnt[k] == 3:
                    DIAG.info(f"Nachfrage Seq {last + 1} Eingang {ch}: keine weitere Zeit, Nachfragen pausiert")
                self.cp_query(f"#RT {last + 1:04d} {ch:02d}", "ack", silent=True)

    def cp_download_run(self):
        if self.cp is None or not self.cp.connected:
            messagebox.showinfo("Lauf vom CP laden", "Zuerst über Ethernet mit dem CP verbinden.")
            return
        if not self.cp_run:
            if self.cp_device == "tm550":
                if messagebox.askyesno("Lauf vom Gerät laden", "Am TM550 ist kein Lauf offen. Laden geht nur mit "
                                                              "offenem Lauf (Modus TIMING).\n\nJetzt am TM550 einen "
                                                              "Lauf öffnen?"):
                    self.cp_open_run(ask=False)
            else:
                messagebox.showinfo("Lauf vom CP laden", "Am CP ist kein Lauf offen. Am CP einen Lauf öffnen "
                                                         "(NET TIME), dann erneut laden.")
            return
        run = self.cp_run
        self.log(f"Lauf {run} wird vom {self.dev_name()} geladen (#DL)", tag="ok")
        self.cp_query(f"#DL {run:02d}", "ack",
                      on_fail=lambda r: messagebox.showerror("Lauf vom CP laden", f"Der CP hat den Download nicht "
                                                                                 f"bestätigt ({r})."))

    def check_device_clock(self, info, dev):
        """Uhr des Geraets gegen den PC: zwei Zeilen hintereinander mit gleicher Abweichung ueber 60 s -> Warnung,
        einmal pro Verbindung. Gepufferte Zeilen beim Verbinden laufen nicht hierher.
        TM550 1.18 hat ein falsches Tagesfeld (Firmware): dort zaehlt nur die Uhrzeit, ab 1.4 auch das Datum."""
        tm = (self.cp_device if dev == "A" else self.cp_b_device) == "tm550"
        fw = ((getattr(self, "cp_info", "") or "").split() or [""])[-1] if dev == "A" else (self.cp_b_fw or "")
        day = info["day"] if tm and fw and fw < "1.4" else info.get("day_raw", info["day"])
        diff = day * 86400 + info["tod"] - local_abs()
        if not hasattr(self, "_clock_prev"):
            self._clock_prev, self._clock_told = {}, {}
        prev = self._clock_prev.get(dev)
        self._clock_prev[dev] = diff
        if abs(diff) <= 60 or prev is None or abs(prev - diff) > 5 or self._clock_told.get(dev):
            return
        self._clock_told[dev] = True
        name = self.dev_name() if dev == "A" else ("Reserve " + self.DEVICE_LABEL.get(self.cp_b_device or "cp545",
                                                                                       "Gerät"))
        a = abs(diff)
        if a >= 86400:
            amount = f"{a / 86400:.0f} Tage"
        elif a >= 3600:
            amount = f"{int(a // 3600)} h {int(a % 3600 // 60)} min"
        else:
            amount = f"{int(a // 60)} min {int(a % 60)} s"
        try:
            date = (EPOCH_2000 + datetime.timedelta(days=int(day))).strftime("%d.%m.%Y")
        except (OverflowError, ValueError, KeyError):
            date = "?"
        tod = int(info["tod"])
        where = "Synchronisation › Manual oder GPS" if tm else "F › Synchronisation"
        msg = (f"Uhr {name} geht {amount} {'vor' if diff > 0 else 'nach'} (Gerät {date} {tod // 3600:02d}:"
               f"{tod // 60 % 60:02d}, PC {time.strftime('%d.%m.%Y %H:%M')}). Laufzeiten stimmen, Startzeiten und "
               f"Uhrzeit im Ranking nicht. In einer Pause, vor dem Öffnen des Laufs, am Gerät unter {where} stellen.")
        self.log(msg, tag="warn")
        self.add_ticker(f"Uhr {name} falsch gestellt", "warn")

    def cp_open_run(self, ask=True):
        """Lauf aus der App oeffnen (#WC 002). TM550: in allen Zeitmessarten. CP 545 (VB08/VB16): nur in
        PTB SEQUENTIEL 1-4, in NET TIME und START-FINISH AK F (am CP oeffnen)."""
        name = self.dev_name()
        if self.cp is None or not self.cp.connected:
            messagebox.showinfo("Lauf öffnen", "Zuerst mit dem Gerät verbinden.")
            return
        if self.cp_device != "tm550" and "PTB" not in (self.cp_mode or "").upper():
            messagebox.showinfo("Lauf öffnen", "Der CP 545 öffnet einen Lauf auf Befehl nur in PTB SEQUENTIEL 1-4. "
                                               "In NET TIME am CP einen Lauf öffnen.")
            return
        if self.cp_run and getattr(self, "cp_run_open", True):
            messagebox.showinfo("Lauf öffnen", f"Am {name} ist Lauf {self.cp_run} bereits offen.")
            return
        if ask and not messagebox.askyesno("Lauf öffnen", f"Am {name} einen neuen Lauf öffnen?"):
            return
        self.log(f"{name}: Lauf wird geöffnet (#WC 002)", tag="ok")

        def done(_info):
            self.cp_query("#RP 003", ("param", "003"), on_ok=self._on_run)

        self.cp_query("#WC 002", "ack", on_ok=done,
                      on_fail=lambda r: self.log(f"{name}: Lauf nicht geöffnet ({r})", tag="error"))

    def process_download(self, items):
        """Alle Zeiten eines Laufs aus dem Speicher des CP: nur Neues uebernehmen, in Zeitfolge."""
        before = len(self.cp_recs)
        self._quiet = True
        try:
            for t in sorted(items, key=lambda x: (x["abs"], x["ch"] != CH_START)):
                self.on_cp_time(t, "A", recalled=True)
        finally:
            self._quiet = False
        added = len(self.cp_recs) - before
        self.log(f"Download vom CP: {len(items)} Zeiten, davon {added} neu übernommen", tag="ok")
        if added:
            self.add_ticker(f"{added} Zeiten vom CP nachgeladen", None)
        self.save_autosave()
        self.on_data_changed()
        self.course_changed()

    def find_twin(self, dev, ch, abs_t):
        """Dieselbe Zeit schon vom anderen CP erfasst? (Reserve-CP, Toleranz 0.1 s)"""
        for k, r in self.run_recs(ch):
            if k[0] != dev and abs(r["abs"] - abs_t) <= 0.1:
                return k
        return None

    def on_cp_time(self, t, dev="A", recalled=False):
        typ = t["type"]
        if typ.startswith("A"):
            typ = "T" + typ[1:]  # Antwort auf #RT / #DL wie eine normale Zeit behandeln
        ch, seq, cpn = t["ch"], t["seq"], t["nr"]
        if dev == "B" and self.cp_b_device == "tm550" and self.backup_preload_ok() and cpn <= 0 \
                and t["ch"] == CH_START and t["type"] == "TN":
            self.cp_b_nr_ok = False  # TM550 als Reserve liefert keine Nummern (Zeitmessart ohne Nummern)
            self.log("Reserve TM550: Startzeit ohne Nummer, die App vergibt die Nummern der Reserve selbst",
                     tag="warn")
        if (dev == "A" and self.cp_caps["ignore_nr"]) or (dev == "B" and self.cp_b_device == "tm550"
                                                          and not self.backup_preload_ok()):
            cpn = 0  # TM550 ohne Vorladen: Nummern vom Geraet sind nur Zaehler, die App vergibt die Nummern
        key = (dev, self.cp_run, ch, seq)
        rec = self.cp_recs.get(key)
        if typ == "TC" and rec is not None and abs(rec["abs"] - t["abs"]) > 0.01:
            # TM550: weiterer Kontakt innerhalb der Sperrzeit, mit Seq der gueltigen Zeit. Kein Storno.
            self.log(f"{self.dev_name()}: Kontakt {fmt_tod(t['abs'] % 86400)} auf Eingang {ch} in der Sperrzeit "
                     f"verworfen (gültig bleibt {fmt_tod(rec['abs'] % 86400)})", tag="test")
            DIAG.info(f"gesperrter Kontakt {key} {t['abs']}")
            return
        if typ in ("TN", "T+", "T=", "TI"):
            if rec is not None and abs(rec["abs"] - t["abs"]) > 0.5 and dev == "A":
                # gleiche Laufnummer und Zaehlnummer, andere Zeit: der CP hat den Lauf neu begonnen
                self.archive_run(self.cp_run, f"Seq {seq} kam mit neuer Zeit")
                key = (dev, self.cp_run, ch, seq)
                rec = self.cp_recs.get(key)
            if rec is not None:
                return  # bereits bekannt
            twin = self.find_twin(dev, ch, t["abs"])
            if twin is not None:
                self.cp_recs[key] = {"nr": self.cp_recs[twin]["nr"], "cp_nr": cpn, "abs": t["abs"],
                                     "status": "dup", "twin": twin}
                return
            if typ == "TN" and not recalled and (dev == "A" or not self.main_connected()):
                self.add_cp_offset(t["abs"])  # Uhr des Hauptgeraets (Reserve-Zeiten sind schon umgerechnet)
            if recalled:
                self.log(f"CP: Zeit Seq {seq} Eingang {ch} nachgeholt", tag="ok")
            if ch == CH_START:
                self.on_start_impulse(key, cpn, t["abs"])
            elif ch == CH_FINISH:
                self.on_finish_impulse(key, cpn, t["abs"])
            else:
                self.cp_recs[key] = {"nr": cpn, "cp_nr": cpn, "abs": t["abs"], "status": "ok"}
        elif typ in ("T-", "TC"):
            # Korrektur an der Tastatur des CP: Zeit ohne Nummer bzw. storniert
            if rec is None:
                rec = self.cp_recs[key] = {"nr": cpn, "cp_nr": cpn, "abs": t["abs"], "status": "ok"}
            # Nur wenn genau diese Startzeit die aktuelle des Boots ist, verlaesst es die Strecke. Eine
            # stornierte alte Startzeit (z.B. nachgeholt nach einem Unterbruch) trifft einen Neustart nicht.
            mine = [(t_, k) for t_, n, k in self.compute_course() if n == rec["nr"]]
            active = bool(mine) and max(mine)[1] == key  # bei Neustart gilt die juengste Startzeit
            if ch == CH_FINISH:
                self.undo_finish(key)
            rec["status"] = "cancelled" if typ == "TC" else "unassigned"
            if typ == "T-" and rec["nr"] > 0 and not recalled:
                # CP 545 (Handbuch): startet eine Nummer neu, verlieren ihre alten Zeiten die Nummer; ebenso
                # beim Umnummerieren (danach T* mit der neuen Nummer) und bei «Nr R E1» an der Tastatur
                self.log(f"CP: Zeit {fmt_tod(t['abs'] % 86400)} (Eingang {ch}, Seq {seq}) gehört nicht mehr Nr "
                         f"{rec['nr']}: am CP umnummeriert oder Nr {rec['nr']} neu gestartet (der CP nimmt alten "
                         "Zeiten einer neu gestarteten Nummer die Nummer weg)", tag="warn")
            if ch == CH_START and typ == "TC" and rec["nr"] > 0:
                if active and self.status.get(rec["nr"]) is None:
                    self.false_start(rec["nr"], key)
                    return
                if not active:
                    self.log(f"CP: ältere Startzeit von Nr {rec['nr']} (Seq {seq}, {fmt_tod(t['abs'] % 86400)}) "
                             "storniert, das Boot bleibt wie es ist", tag="warn")
        elif typ == "T*":
            if ch == CH_FINISH:
                if dev == "A":
                    self.cp_last_finish_rx = key
                if rec is not None:
                    self.undo_finish(key)
                skey = self.course_key(cpn)
                self.cp_recs[key] = {"nr": 0, "cp_nr": cpn, "abs": t["abs"], "status": "nobody"}
                if skey:
                    self.assign_finish(key, skey)
            elif ch == CH_START:
                old = rec["nr"] if rec else None
                if rec is None:
                    rec = self.cp_recs[key] = {"nr": cpn, "cp_nr": cpn, "abs": t["abs"], "status": "ok"}
                if not recalled or rec["nr"] in (rec["cp_nr"], 0):
                    rec["nr"] = cpn  # Korrektur an der Tastatur des CP gilt, auch nach einer Aenderung in der App
                rec["cp_nr"], rec["status"] = cpn, "ok"
                if old is not None and old != rec["nr"]:
                    self.log(f"CP: Startzeit (Seq {seq}) von Nr {old} zu Nr {rec['nr']}", tag="warn")
                    self.add_ticker(f"Nummer korrigiert: Nr {rec['nr']} statt Nr {old} auf der Fahrstrecke", None)
                    if self.start_order and rec["nr"] not in self.participants and not self.is_test(rec["nr"]):
                        self.ensure_participant(rec["nr"], after=old if old in self.order_index else None,
                                                prompt=True)
            else:
                self.cp_recs[key] = {"nr": cpn, "cp_nr": cpn, "abs": t["abs"], "status": "ok"}
        self.save_autosave()
        self.course_changed()

    def false_start(self, nr, key):
        """Startzeit am Geraet storniert (CP: E1 bzw. * E1, TM550: Zeit in der Smartphone-App geloescht):
        das Boot verlaesst die Strecke und ist wieder als naechstes am Start."""
        dev = "CP" if self.cp_device != "tm550" else "TM550"
        self.log(f"{dev}: Startzeit von Nr {nr} ({fmt_tod(self.cp_recs[key]['abs'] % 86400)}) storniert "
                 "(Falschstart). Nr {0} ist wieder als nächstes am Start.".format(nr), tag="warn")
        self.add_ticker(f"Falschstart: Nr {nr} startet nochmals", "warn")
        self.unstart(nr)
        self.save_autosave()
        self.course_changed()
        self.update_panels()
        self.cp_sync_next("Falschstart")

    def bounce(self, ch, abs_t, key):
        """Prellimpuls: zweiter Impuls am selben Messpunkt innerhalb der eingestellten Zeit."""
        ms = self.tset()["prell_start_ms" if ch == CH_START else "prell_finish_ms"]
        if ms <= 0:
            return False
        return any(k != key and r["status"] in ("ok", "fehl") and abs(abs_t - r["abs"]) * 1000 < ms
                   for k, r in self.run_recs(ch))

    def bounce_tag(self, ch, abs_t):
        """Doppelkontakt unter 0.2 s nur leise protokollieren (prellender Kontakt, z.B. Kabel mit Bananensteckern
        statt Taster). Haeufen sie sich auf einem Eingang (3 in 10 min), einmal darauf hinweisen."""
        near = min((abs(abs_t - r["abs"]) for _k, r in self.run_recs(ch) if r["status"] == "ok"), default=1.0)
        now = time.time()
        hist = self._bounce_hist = getattr(self, "_bounce_hist", {})
        hist[ch] = [t for t in hist.get(ch, []) if now - t < 600] + [now]
        told = self._bounce_told = getattr(self, "_bounce_told", set())
        if len(hist[ch]) >= 3 and ch not in told:
            told.add(ch)
            self.log(f"Eingang {ch} prellt ({len(hist[ch])} Doppelkontakte in 10 min). Kontakt bzw. Kabel prüfen. Die "
                     "Zweitimpulse werden verworfen.", tag="warn")
            self.add_ticker(f"Eingang {ch} prellt, Kontakt prüfen", "warn")
        return "test" if near < 0.2 else "warn"

    def on_start_impulse(self, key, cpn, abs_t):
        rec = self.cp_recs[key] = {"nr": cpn, "cp_nr": cpn, "abs": abs_t, "status": "ok"}
        if self.tset()["lock_start"]:
            rec.update(nr=0, status="locked")
            self.log(f"Startimpuls {fmt_tod(abs_t % 86400)} bei gesperrtem Start ignoriert"
                     + (f" (Gerät: Nr {cpn})" if cpn else ""), tag="warn")
            self.add_ticker(f"Startimpuls bei gesperrtem Start ({fmt_tod(abs_t % 86400)})", "warn")
            if key[0] == "A" and cpn > 0:
                self.root.after(100, lambda: self.cp_lock_preload("lock_start", True))  # CP zaehlt weiter
            return
        if self.bounce(CH_START, abs_t, key):
            rec.update(nr=0, status="prell")
            self.log(f"Startimpuls {fmt_tod(abs_t % 86400)} ungültig (Prellzeit)", tag=self.bounce_tag(CH_START, abs_t))
            return
        if cpn <= 0 and key[0] == "A" and self.cp_device == "tm550" and self.cp_caps["preload"]:
            self.cp_set_preload(False, "Startzeit ohne Nummer")
        if cpn <= 0:
            nxt = self.next_starters(1) if (not self.cp_caps["preload"] or key[0] == "B") else []
            if nxt:
                # TM550: Nummer aus der Startreihenfolge der App. Kommt eine verlorene, fruehere Startzeit
                # nachtraeglich (Download), werden die Nummern der spaeteren, noch fahrenden Starts nachgeschoben.
                later = sorted((r["abs"], k) for k, r in self.run_recs(CH_START)
                               if k != key and r.get("auto_nr") and r["status"] == "ok" and not r.get("done")
                               and not r.get("dnf") and r["abs"] > abs_t)
                if later:
                    nums = [self.cp_recs[k]["nr"] for _a, k in later] + [nxt[0]]
                    rec.update(nr=nums[0], status="ok", auto_nr=True)
                    for (_a, k), n in zip(later, nums[1:]):
                        self.cp_recs[k]["nr"] = n
                    self.last_start_nr = nums[-1]
                    self.log(f"START Nr {nums[0]} ({fmt_tod(abs_t % 86400)}) nachgeholt, spätere Starts "
                             f"neu nummeriert: {', '.join(str(n) for n in nums[1:])}", tag="warn")
                    self.save_autosave()
                    self.course_changed()
                    self.update_panels()
                    return
                self.start_number(key, nxt[0])
                rec["auto_nr"] = True
                return
            rec["status"] = "nobody"
            self.log(f"Startimpuls {fmt_tod(abs_t % 86400)} ohne Nummer", tag="warn")
            return
        self.start_number(key, cpn)

    def start_number(self, key, nr):
        rec = self.cp_recs[key]
        rec.update(nr=nr, status="ok")
        prev = self.last_start_nr
        self.last_start_nr = nr
        if self.status.get(nr) == "DNS":
            self.status.pop(nr, None)
            self.log(f"Nr {nr} startet doch: Status DNS aufgehoben", tag="warn")
        if key[0] == "A" and rec["cp_nr"] > 0:
            # CP 545 zaehlt selbst weiter, der TM550 (1.48) verbraucht die vorgeladene Nummer. Ein Start nur bei
            # der Reserve aendert am Hauptgeraet nichts: dort bleibt die alte Nummer vorgeladen.
            self.cp_next_start = rec["cp_nr"] + 1 if self.cp_device != "tm550" else 0
        elif key[0] == "B":
            self.cp_b_next = None  # Reserve hat die Nummer verbraucht
        self.log(f"START Nr {nr} ({fmt_tod(rec['abs'] % 86400)})", tag="test" if self.is_test(nr) else "ok")
        self.on_new_starter(prev, nr)
        self.cp_sync_next("Start")

    def on_finish_impulse(self, key, cpn, abs_t):
        if key[0] == "A":
            self.cp_last_finish_rx = key
        DIAG.info(f"Zielimpuls {key} CP-Nr {cpn} {fmt_tod(abs_t % 86400)} | erwartet: "
                  f"{[c[1] for c in self.course]} | Vorrang {self.finish_override} | "
                  f"Sperre {self.settings['timing']['lock_finish']}")
        rec = self.cp_recs[key] = {"nr": 0, "cp_nr": cpn, "abs": abs_t, "status": "nobody"}
        # Sicht des CP nachfuehren (Papierstreifen): seine offene Startzeit mit dieser Nummer ist fertig
        cp_start = next((k for k in self.cp_alive() if self.cp_recs[k]["cp_nr"] == cpn
                         and self.cp_recs[k]["abs"] <= abs_t), None)
        if cp_start:
            self.cp_recs[cp_start]["cp_done"] = True
        self.cp_finish_want = None
        rec["cp_start"] = cp_start
        tod = fmt_tod(abs_t % 86400)
        if self.tset()["lock_finish"]:
            rec["status"] = "locked"
            self.log(f"Zielimpuls {tod} bei gesperrtem Ziel ignoriert", tag="warn")
            self.add_ticker(f"Zielimpuls bei gesperrtem Ziel ({tod})", "warn")
            return
        if self.bounce(CH_FINISH, abs_t, key):
            rec["status"] = "prell"
            self.log(f"Zielimpuls {tod} ungültig (Prellzeit, Doppelkontakt)", tag=self.bounce_tag(CH_FINISH, abs_t))
            return
        if not self.course:
            self.log(f"Zielimpuls {tod}: kein Boot auf der Strecke", tag="warn")
            return
        skey = self.course[0][2]
        st = self.cp_recs[skey]
        min_s = self.tset()["min_run_s"]
        if min_s > 0 and abs_t - st["abs"] < min_s:
            rec["status"] = "fehl"
            self.log(f"Zielimpuls {tod} ungültig: Fahrzeit {fmt_secs(abs_t - st['abs'], 2)}s unter der "
                     f"Mindestzeit {min_s:g}s (Fehlimpuls)", tag="warn")
            self.add_ticker(f"Fehlimpuls im Ziel ({tod}) nicht gewertet", "warn")
            return
        self.assign_finish(key, skey)

    def assign_finish(self, fkey, skey):
        fin, st = self.cp_recs[fkey], self.cp_recs[skey]
        nr = st["nr"]
        fin.update(nr=nr, status="ok", start=skey,
                   rr_ok=fin.get("cp_start") == skey and fin["cp_nr"] == st["cp_nr"] == nr)
        st["done"] = fkey
        self.last_finish_key = fkey
        if self.finish_override == nr:
            self.finish_override = None
        if fin["cp_nr"] != nr:
            self.log(f"ZIEL Nr {nr} (der CP führt diese Zeit unter Nr {fin['cp_nr']})", tag="warn")
        self.store_cp_result(nr, trunc_secs(fin["abs"] - st["abs"], min(self.cp_prec, RESULT_DEC)), fkey)

    def assign_pending(self, fkey, nr):
        """Impuls ohne Zuordnung von Hand zuordnen (Ziel: Boot auf der Strecke, Start: Nummer)."""
        rec = self.cp_recs.get(fkey)
        if rec is None:
            return
        if fkey[2] == CH_FINISH:
            skey = self.course_key(nr)
            if skey is None:
                return
            self.assign_finish(fkey, skey)
            self.log(f"Zielimpuls {fmt_tod(rec['abs'] % 86400)} von Hand Nr {nr} zugeordnet", tag="ok")
        else:
            self.start_number(fkey, nr)
            self.log(f"Startimpuls {fmt_tod(rec['abs'] % 86400)} von Hand Nr {nr} zugeordnet", tag="ok")
        self.save_autosave()
        self.on_data_changed()
        self.course_changed()

    def invalidate_finish(self, fkey):
        """Zielzeit ungueltig schalten (Fehlimpuls): Resultat weg, Boot wieder auf der Strecke."""
        rec = self.cp_recs.get(fkey)
        if not rec or rec["status"] != "ok":
            return
        nr = rec["nr"]
        skey = rec.get("start")
        self.undo_finish(fkey)
        rec.update(status="fehl", nr=0, start=None)
        self.log(f"Zielzeit {fmt_tod(rec['abs'] % 86400)} ungültig geschaltet, Nr {nr} wieder auf der Strecke",
                 tag="warn")
        self.device_restore_finish(nr, skey, fkey)
        self.add_ticker(f"Zielzeit von Nr {nr} ungültig (Fehlimpuls), Nr {nr} wieder auf der Strecke", "warn")
        self.save_autosave()
        self.on_data_changed()
        self.course_changed()

    def device_restore_finish(self, nr, skey, fkey):
        """Zielzeit in der App zurueckgenommen: das Geraet fuehrt das Boot weiter als fertig. CP 545: «am CP fertig»
        aufheben und die Nummer auf den Zieleingang vorladen, sobald das Boot als naechstes erwartet wird.
        TM550 laesst sich dafuer nicht fernsteuern."""
        st = self.cp_recs.get(skey) if skey else None
        if fkey[0] == "A" and self.cp_device == "tm550" or fkey[0] == "B" and self.cp_b_device == "tm550":
            self.log(f"TM550 führt Nr {nr} weiter als im Ziel. Der nächste Zielimpuls kommt dort ohne Nummer, die "
                     f"App ordnet ihn Nr {nr} zu. Am TM550 lässt sich das in der Smartphone-App korrigieren.",
                     tag="warn")
            return
        if st is None or not self.eth_mode():
            return
        st["cp_done"] = False
        self._restore_told = set(getattr(self, "_restore_told", set())) - {nr}
        self.cp_finish_want = None
        self._cp_finish_pending = None
        if self.cp is not None and self.cp.connected and self.cp_caps.get("preload") and fkey[0] == "A":
            target = st["cp_nr"] or nr
            course = self.compute_course()
            if course and course[0][1] == nr:
                def done(ok, why=""):
                    if ok:
                        self.cp_finish_want = target
                        self.log(f"CP: nächster Zielimpuls am CP bekommt wieder Nr {target}", tag="ok")
                    else:
                        self.log(f"CP nimmt Nr {target} für das Ziel nicht an (für den CP ist es schon im Ziel). "
                                 f"Der nächste Zielimpuls kommt am CP ohne Nummer, die App ordnet ihn Nr {nr} zu. Am "
                                 f"CP vor dem Zielimpuls «{target} E4» eingeben, dann stimmen Papierstreifen und CP "
                                 "überein.", tag="warn")
                        self._restore_told = getattr(self, "_restore_told", set()) | {target}
                self.cp_write_param("026", CH_FINISH, target, "nächstes Ziel", done)
            else:
                self.log(f"CP: Nr {nr} wird für das Ziel am CP vorgeladen, sobald es als nächstes erwartet wird",
                         tag="ok")
        course = self.compute_course()
        if self.cp_b is not None and self.cp_b.connected and self.cp_b_device == "cp545" and course \
                and course[0][1] == nr:
            self.cp_b.send(f"#WP 026 {CH_FINISH:02d} {st['cp_nr'] or nr:04d}")

    def pending_impulses(self):
        """Impulse ohne Zuordnung im laufenden Lauf, neueste zuletzt."""
        items = [(r["abs"], k) for k, r in self.run_recs()
                 if k[2] in (CH_START, CH_FINISH) and r["status"] in ("locked", "nobody", "fehl", "prell",
                                                                         "unassigned", "reserve")]
        return [k for _a, k in sorted(items)][-8:]

    def on_cp_result(self, info):
        """RR vom CP bestaetigt die Fahrzeit, wenn der CP dieselbe Start- und Zielzeit verwendet hat."""
        cpn = info["nr"]
        # RR folgt direkt auf die Zielzeit, zu der es gehoert. Gehoert diese Zielzeit keinem Boot oder einem
        # anderen als dem, das der CP meint, gilt das RR nicht.
        key = getattr(self, "cp_last_finish_rx", None)
        rec = self.cp_recs.get(key) if key else None
        if rec is None or rec["cp_nr"] != cpn or rec["status"] != "ok" or not rec.get("rr_ok"):
            if rec is not None and rec["cp_nr"] == cpn:
                DIAG.info(f"RR Nr {cpn} {info['secs']} ignoriert: Zielzeit {key} Status {rec['status']}, "
                          f"Boot {rec['nr']}")
            return
        rec = self.cp_recs[key]
        # CP 545: Resultat (RR, Papier) mit einer Stelle weniger als die Zeitzeilen (#WP 001 n: Zeiten n+1,
        # Resultat n Stellen). Nur bei echter Abweichung auf der Genauigkeit des RR gilt der Wert des CP.
        rr_dec = max(0, self.cp_prec - 1) if self.cp_device == "cp545" else self.cp_prec
        res = self.results.get(rec["nr"])
        if res and res.get("cp") == list(key):
            dec = min(rr_dec, RESULT_DEC)  # verglichen wird auf der groeberen der beiden Praezisionen
            app_t = trunc_secs(res["secs"], dec)
            if abs(app_t - trunc_secs(info["secs"], dec)) > 0.6 * 10 ** -dec:
                secs = trunc_secs(info["secs"], dec)
                self.log(f"CP meldet für Nr {rec['nr']} {fmt_secs(secs)}s, App rechnete "
                         f"{res['str']}s: Wert des CP übernommen", tag="warn")
                res["secs"], res["str"] = secs, fmt_secs(secs)
                self.on_data_changed()

    def store_cp_result(self, nr, secs, key):
        res = self.results.get(nr)
        if res and key is not None and res.get("cp") == list(key):
            return  # schon erfasst
        self.register_final(nr, secs, fmt_secs(secs), source="CP 545 LAN")  # Stellen nach Praezision der App
        if nr in self.results:
            self.results[nr]["cp"] = list(key) if key else None
            self.save_autosave()
        self.ziel_nr = nr

    def undo_finish(self, key):
        rec = self.cp_recs.get(key)
        if rec and rec.get("start") in self.cp_recs:
            st = self.cp_recs[rec["start"]]
            if st.get("done") == key:
                st["done"] = None
        self.revert_cp_result(key)

    def reassign_last_finish(self, nr):
        """Letzte Zielzeit gehoert in Wirklichkeit Nr nr (unbemerkt ueberholt)."""
        fkey = self.last_finish_key
        frec = self.cp_recs.get(fkey) if fkey else None
        new_key = self.course_key(nr)
        if not frec or frec["status"] != "ok" or new_key is None:
            return
        old = frec["nr"]
        self.undo_finish(fkey)
        self.assign_finish(fkey, new_key)
        self.cp_recs[fkey]["rr_ok"] = False
        self.log(f"Zielzeit umgebucht: Nr {nr} statt Nr {old}", tag="warn")
        self.add_ticker(f"Zielzeit korrigiert: Nr {nr} war im Ziel, Nr {old} wieder auf der Strecke", "warn")
        self.save_autosave()
        self.on_data_changed()
        self.course_changed()

    def revert_cp_result(self, key):
        for nr, r in list(self.results.items()):
            if r.get("cp") == list(key):
                prev = r.get("prev")
                if prev:
                    self.results[nr] = {"secs": prev["secs"], "str": prev["str"], "ts": r["ts"],
                                        "source": r.get("source", ""), "run": max(1, r.get("run", 2) - 1),
                                        "prev": None, "status": r.get("status", ST_OPEN)}
                else:
                    del self.results[nr]
                if self.ziel_nr == nr and nr not in self.results:
                    self.ziel_nr = None
                self.log(f"Zielzeit Nr {nr} ({r['str']}s) zurückgenommen", tag="warn")
                self.on_data_changed()
                return nr
        return None

    def recompute_from_raw(self):
        """Resultate aus den Rohzeiten neu berechnen. Von Hand erfasste Zeiten bleiben."""
        changed, removed = 0, 0
        linked = {}
        for k, r in self.cp_recs.items():
            if k[2] == CH_FINISH and r["status"] == "ok" and r.get("start") in self.cp_recs:
                st = self.cp_recs[r["start"]]
                linked[list(k).__repr__()] = (r["nr"], trunc_secs(r["abs"] - st["abs"], min(self.cp_prec, RESULT_DEC)), k)
        for nr, res in list(self.results.items()):
            if res.get("source") != "CP 545 LAN" or not res.get("cp"):
                continue
            item = linked.get(repr(res["cp"]))
            if item is None or item[0] != nr:
                del self.results[nr]
                removed += 1
            elif abs(item[1] - res["secs"]) > 0.001 or res["str"] != fmt_secs(item[1]):
                res["secs"], res["str"] = item[1], fmt_secs(item[1])
                changed += 1
        for nr, secs, k in linked.values():
            if nr not in self.results and self.status.get(nr) not in ("DNF",):
                self.results[nr] = {"secs": secs, "str": fmt_secs(secs), "ts": time.time(),
                                    "source": "CP 545 LAN", "run": 1, "prev": None, "status": ST_OPEN,
                                    "cp": list(k)}
                changed += 1
        self._rank_cache = None
        self.log(f"Aus Rohzeiten neu berechnet: {changed} geändert oder ergänzt, {removed} entfernt", tag="ok")
        self.save_autosave()
        self.on_data_changed()
        self.course_changed()
        return changed, removed

    # ---------------- Fahrstrecke ---------------- #
    def compute_course(self):
        """Boote auf der Strecke in erwarteter Zielreihenfolge: [(startzeit, nr, key)]."""
        course = sorted(((r["abs"], r["nr"], k) for k, r in self.run_recs(CH_START)
                         if r["status"] == "ok" and r["nr"] > 0 and not r.get("dnf") and not r.get("done")),
                        key=lambda c: (self.cp_recs[c[2]].get("order", c[0]), c[0]))
        if self.finish_override is not None:
            first = [c for c in course if c[1] == self.finish_override]
            if first:
                course = first + [c for c in course if c[1] != self.finish_override]
            else:
                self.finish_override = None
        return course

    def course_key(self, nr):
        return next((key for _t, n, key in self.course if n == nr), None)

    def course_changed(self):
        self.course = self.compute_course()
        self.update_eth_live()
        self.update_panels()
        self.cp_sync_finish()

    def update_eth_live(self):
        if not self.eth_mode():
            return
        if self.course:
            tod, nr, _key = self.course[0]
            off = self.cp_offset()
            secs = max(0.0, local_abs() + off - tod) if off is not None else None
            txt = None if secs is None else (f"{int(secs // 60)}:{int(secs % 60):02d}" if secs >= 60 else
                                             f"{int(secs)}")
            if nr != self.current_nr:
                self.current_nr = nr
            self.live_time, self.live_secs, self.live_final = txt, secs, False
        elif self.ziel_nr is not None and self.ziel_nr in self.results:
            self.current_nr = self.ziel_nr
            self.live_time, self.live_secs, self.live_final = self.results[self.ziel_nr]["str"], None, True
        self.update_live_info()

    def running_text(self, tod):
        off = self.cp_offset()
        if off is None:
            return ""
        secs = max(0.0, local_abs() + off - tod)
        return f"{int(secs // 60)}:{int(secs % 60):02d}"

    def start_eth_tick(self):
        if self._eth_tick_job is None:
            self._eth_tick_job = self.root.after(250, self.eth_tick)

    def stop_eth_tick(self):
        if self._eth_tick_job is not None:
            self.root.after_cancel(self._eth_tick_job)
            self._eth_tick_job = None

    def eth_tick(self):
        self._eth_tick_job = None
        if self.cp is None:
            if self.cp_b is not None:  # nur Reserve verbunden
                self.backup_tick()
                if self.course:
                    self.update_eth_live()
                    self.update_course_panel()
                self._eth_tick_job = self.root.after(250, self.eth_tick)
            return
        self.cp_timeout_check()
        now = time.time()
        if self.cp_backlog is not None and now - self.cp_backlog_t > 3:
            self.finish_backlog()
        self.backup_tick()
        if self.cp.connected:
            if now - self.cp_last_hb > HEARTBEAT_S and self.cp_inflight is None and not self.cp_cmds:
                self.cp_last_hb = now
                self.cp_query("#RP 003", ("param", "003"), on_ok=self._on_run, silent=True)
                self.cp_probe()
            elif (self.cp_device == "cp545" and now - getattr(self, "_lock_poll_t", 0) > LOCK_POLL_S
                  and self.cp_inflight is None and not self.cp_cmds and self.cp_backlog is None):
                self._lock_poll_t = now  # CP 545 meldet die rote Sperrtaste nicht von selbst
                self.device_lock_read("A", silent=True)
            if now - self.cp_last_rx > HEARTBEAT_LOST_S:
                self.cp_last_rx = now
                self.log("CP antwortet nicht mehr, Verbindung wird neu aufgebaut", tag="warn")
                self.cp.force_reconnect()
        if self.course:
            self.update_eth_live()
            self.update_course_panel()
        self._eth_tick_job = self.root.after(250, self.eth_tick)

    # ================================================================== #
    # Simulator in der App
    # ================================================================== #
    def open_simulator(self):
        if getattr(self, "sim_win", None) is not None and self.sim_win.winfo_exists():
            self.sim_win.lift()
            return self.sim_win
        if self.sim is None:
            self.sim = SimCP()
            self.log(f"Simulator gestartet (127.0.0.1:{self.sim.port})", tag="ok")
        if self.settings["conn"]["mode"] != "ethernet":
            self.var_conn.set("ethernet")
            self.on_conn_mode_change()
            self.conn_seg.redraw()
        if self.cp is None or self.cp.host != "127.0.0.1" or self.cp.port != self.sim.port:
            self.disconnect_all()
            self.connect_cp("127.0.0.1", self.sim.port)
        win = self.sim_win = self._toplevel("Simulator CP 545")
        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=1)
        tk.Label(win, text="Impulse wie am CP auslösen. Die App reagiert wie im Rennen.", bg=PANEL, fg=MUTED,
                 font=self.f_side, wraplength=self.narrow_wrap(), justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w")
        self._button(win, "Start", lambda: self.sim_do("start"), GREEN).grid(row=1, column=0, sticky="ew",
                                                                             padx=(0, 3), pady=(8, 0))
        self._button(win, "Ziel", lambda: self.sim_do("finish"), BLUE).grid(row=1, column=1, sticky="ew",
                                                                            padx=(3, 0), pady=(8, 0))
        self._button(win, "Nächste Zeile verlieren", lambda: self.sim_do("drop")).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        row = tk.Frame(win, bg=PANEL)
        row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        row.columnconfigure(0, weight=1)
        tk.Label(row, text="Automatisch (Start alle 15 s)", bg=PANEL, fg=TEXT, font=self.f_side).grid(
            row=0, column=0, sticky="w")
        self.sw_sim_auto = Switch(row, command=self.sim_toggle_auto, scale=self.ui_scale, on=False)
        self.sw_sim_auto.grid(row=0, column=1, sticky="e")
        self._button(win, "Log abspielen ...", self.sim_replay_dialog).grid(row=4, column=0, columnspan=2,
                                                                         sticky="ew", pady=(8, 0))
        self._button(win, "Üben: CP 545 mit Tastatur", lambda: self.open_trainer("cp545")).grid(
            row=8, column=0, sticky="ew", padx=(0, 3), pady=(10, 0))
        self._button(win, "Üben: TM550", lambda: self.open_trainer("tm550")).grid(
            row=8, column=1, sticky="ew", padx=(3, 0), pady=(10, 0))
        self.var_sim_speed = tk.StringVar(value="5")
        Segmented(win, (("1", "1×"), ("5", "5×"), ("20", "20×")), self.var_sim_speed, font=self.f_side_bold,
                  scale=self.ui_scale).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.lbl_sim = tk.Label(win, text="", bg=PANEL, fg=MUTED, font=self.f_side, wraplength=self.narrow_wrap(),
                                justify="left", anchor="w")
        self.lbl_sim.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._button(win, "Simulator beenden", self.close_simulator, DARK_RED).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._place(win, narrow=True)
        return win

    # ================================================================== #
    # Trainingsfenster: Geraet mit Display, Tastatur und Bananenbuchsen (nach den Handbuechern nachgebaut,
    # keine Original-Firmware). Die App ist mit dem Simulator wie mit einem echten Geraet verbunden.
    # ================================================================== #
    def open_trainer(self, device="cp545"):
        import collections
        if getattr(self, "trainer", None) is not None and self.trainer.winfo_exists():
            self.trainer.destroy()
        if self.sim is None or self.sim.device != device:
            if self.sim is not None:
                self.sim.close()
            self.sim = SimCP(device=device, fw="1.48" if device == "tm550" else "VB16")
            self.log(f"Simulator {self.DEVICE_LABEL[device]} ({self.sim.fw}) gestartet (127.0.0.1:{self.sim.port})",
                     tag="ok")
        if self.settings["conn"]["mode"] != "ethernet":
            self.var_conn.set("ethernet")
            self.on_conn_mode_change()
            self.conn_seg.redraw()
        if self.cp is None or self.cp.host != "127.0.0.1" or self.cp.port != self.sim.port:
            self.disconnect_all()
            self.reset_caps(device)
            self.connect_cp("127.0.0.1", self.sim.port)
            self.cp.checksum = device == "tm550"
        sim = self.sim
        tq = self._trainer_q = collections.deque()
        sim.on_event = lambda text: tq.append(("note", text))
        sim.on_line = lambda line: tq.append(("line", line))
        self.tr = {"buf": "", "state": "", "nr": None, "new": "", "device": device, "log": [], "flash": {},
                   "rows": [], "menu": [], "runs": [], "vals": {}}
        name = self.DEVICE_LABEL[device]
        win = self.trainer = self._toplevel(f"Üben: {name} (nachgebaut)")
        front = tk.Frame(win, bg=PANEL)
        front.grid(row=0, column=0, rowspan=2, sticky="n")
        right = tk.Frame(win, bg=PANEL, padx=12)
        right.grid(row=0, column=1, sticky="nsew")
        win.columnconfigure(1, weight=1)
        self.tr_paper = None
        if device == "cp545":
            self._trainer_front_cp(front)
        else:
            self._trainer_front_tm(front)
        tk.Label(right, text="Rückseite  (Buchse: Klick = Impuls, Rechtsklick = Doppelkontakt; "
                             "Ethernet: Klick = Kabel ab/an)", bg=PANEL, fg=MUTED, font=self.f_side,
                 anchor="w").pack(anchor="w")
        self._trainer_rear(right, device)
        if device == "tm550":
            tk.Label(right, text="Meldungen", bg=PANEL, fg=TEXT, font=self.f_side_bold).pack(anchor="w",
                                                                                             pady=(8, 0))
            self.tr_paper = tk.Text(right, width=44, height=7, bg=PANEL2, fg=TEXT, relief="flat",
                                    font=("Consolas", int(10 * self.ui_scale)), padx=6, pady=4)
            self.tr_paper.pack(fill="x", pady=(4, 0))
        tk.Label(right, text="Übungsfälle", bg=PANEL, fg=TEXT, font=self.f_side_bold).pack(anchor="w",
                                                                                          pady=(10, 0))
        sc = tk.Frame(right, bg=PANEL)
        sc.pack(fill="x")
        sc.columnconfigure(0, weight=1)
        sc.columnconfigure(1, weight=1)
        cases = (("Fehlstart", self.trainer_case_falsestart), ("Kabel 10 s ab", self.trainer_case_cable),
                 ("Lauf neu öffnen", self.trainer_case_reopen), ("Falsche Nummer", self.trainer_case_wrongnr),
                 ("Doppelkontakt Ziel", lambda: self.trainer_do(lambda: sim.double_contact(CH_FINISH),
                                                                "Doppelkontakt Ziel")),
                 ("Gerät neu gestartet", self.trainer_case_restart),
                 ("Protokoll speichern", self.trainer_save))
        for i, (lab, cmd) in enumerate(cases):
            self._button(sc, lab, cmd).grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
        hint = ("CP 545 (nach Handbuch 03/2015): grüne Tasten 1 bis 4 = Handimpuls auf dem Eingang. "
                "Nr E1 = nächste Startnummer, E1 allein = Falschstart (Nummer von der letzten Startzeit "
                "entfernen), Nr R 0 = ausgeschieden, Nr R 0 * = disqualifiziert, alte Nr R E1 neue Nr ↵ = "
                "umnummerieren, * = Eingabe löschen. Rote Tasten unter den grünen = Eingang sperren/öffnen (Balken im "
                "Display, die grüne Taste löst trotzdem aus). F = Menü wie am Gerät (▲ ▼, ↵ wählen, * = JA, F "
                "zurück). Ethernet nach dem Einschalten: F › Einstellungen › Ethernet › Std Connexion. ON = Aus."
                if device == "cp545" else
                "TM550 (Firmware 1.48): E1 bis E4 = Handimpuls. ◀ öffnet das Menü Run, nochmals ◀ das Hauptmenü "
                "(▲ ▼, OK oder ▶ wählen, ◀ zurück). In TIMING lädt die App die nächste Startnummer vor. SHIFT + "
                "E1..E4 schaltet den Eingang weiter: offen (grün ↑), senden (rot ↓), gesperrt (rot).")
        tk.Label(right, text=hint, bg=PANEL, fg=MUTED, font=self.f_side, wraplength=int(360 * self.ui_scale),
                 justify="left").pack(anchor="w", pady=(8, 0))
        win.protocol("WM_DELETE_WINDOW", self.trainer_close)
        self._place(win)
        self.trainer_poll()
        self.trainer_log(f"Übung {name} begonnen")
        return win

    def _tr_key(self, parent, label, cmd=None, w=3, bg="#F4F4F2", fg="#222", font=None, oval=False):
        b = tk.Button(parent, text=label, width=w, font=font or self.f_side_bold, bg=bg, fg=fg,
                      activebackground="#BFD3F2", activeforeground=fg, relief="raised", bd=2,
                      cursor="hand2", command=cmd or (lambda: self.trainer_key(label)))
        return b

    def _trainer_front_cp(self, parent):
        """CP 545 hochkant: Drucker, Display, Tastenfeld wie am Geraet (Tasten nach Foto angeordnet)."""
        red, grey, dark = "#D9392F", "#8E9196", "#55585D"
        shell = tk.Frame(parent, bg=red, padx=10, pady=10)
        shell.pack()
        body = tk.Frame(shell, bg=grey, padx=12, pady=10)
        body.pack()
        tk.Label(body, text="TAG HEUER   CHRONOPRINTER 545", bg=grey, fg="white",
                 font=self.f_side_bold).pack(anchor="w")
        pr = tk.Frame(body, bg="#3A3C40", padx=6, pady=6)
        pr.pack(fill="x", pady=(6, 6))
        self.tr_paper = tk.Text(pr, width=34, height=7, bg="#FBFAF4", fg="#222", relief="flat",
                                font=("Consolas", int(9 * self.ui_scale)), padx=4, pady=2)
        self.tr_paper.pack(fill="x")
        lcd = tk.Frame(body, bg=red, padx=3, pady=3)
        lcd.pack(fill="x", pady=(0, 8))
        # Display 8 Zeilen zu 21 Zeichen wie am CP 545 (Handbuch 03/2015)
        self.tr_disp = tk.Label(lcd, text="", bg="#A9B79A", fg="#1E2618",
                                font=("Consolas", int(11 * self.ui_scale), "bold"), justify="left", anchor="nw",
                                width=21, height=8, padx=8, pady=6)
        self.tr_disp.pack(fill="x")
        kp = tk.Frame(body, bg=grey)
        kp.pack()
        small = dict(bg=dark, fg="white", w=3)
        for i, lab in enumerate(("E1", "E2", "", "E3", "E4")):
            if lab:
                self._tr_key(kp, lab, **small).grid(row=0, column=i, padx=3, pady=(0, 6))
            else:
                tk.Label(kp, text="TAG\nHEUER", bg="#1B7F4B", fg="white", font=self.f_side_bold, padx=4).grid(
                    row=0, column=i, pady=(0, 6))
        for r, lab in enumerate(("⇧", "F", "ON")):
            self._tr_key(kp, lab, **small).grid(row=1 + r, column=0, padx=3, pady=3)
        for r, (lab, key) in enumerate((("▲", "▲"), ("↵", "Enter"), ("▼", "▼"))):
            self._tr_key(kp, lab, cmd=lambda k=key: self.trainer_key(k), **small).grid(
                row=1 + r, column=4, padx=3, pady=3)
        for r, row in enumerate((("7", "8", "9"), ("4", "5", "6"), ("1", "2", "3"), ("*", "0", "R"))):
            for c, lab in enumerate(row):
                key = "." if lab == "*" else lab
                self._tr_key(kp, lab, cmd=lambda k=key: self.trainer_key(k)).grid(
                    row=1 + r, column=1 + c, padx=3, pady=3)
        ch = tk.Frame(body, bg=grey)
        ch.pack(pady=(10, 0))
        self.tr_leds = {}
        for i in (1, 2, 3, 4):
            f = tk.Frame(ch, bg=grey)
            f.grid(row=0, column=i, padx=8)
            self._tr_key(f, str(i), cmd=lambda c=i: self.trainer_key(f"K{c}"), bg="#2E9E4F", fg="white").pack()
            led = tk.Canvas(f, width=18, height=18, bg=grey, highlightthickness=0, cursor="hand2")
            led.create_oval(2, 2, 16, 16, fill="#B8322A", outline="#5A1A16", tags="led")
            led.pack(pady=(3, 0))
            led.bind("<Button-1>", lambda e, c=i: self.trainer_key(f"L{c}"))  # rote Sperrtaste
            self.tr_leds[i] = led

    def _trainer_front_tm(self, parent):
        """TM550: Schild-Form, Tasten E1-E4 oben, Farbdisplay, ON/SHIFT, Pfeilkreuz mit OK."""
        s = self.ui_scale
        W, H = int(340 * s), int(470 * s)
        cv = tk.Canvas(parent, width=W, height=H, bg=PANEL, highlightthickness=0)
        cv.pack()
        def poly(pts, **kw):
            return cv.create_polygon([v * s for v in pts], **kw)
        poly((40, 4, 300, 4, 336, 60, 336, 330, 250, 466, 90, 466, 4, 330, 4, 60), fill="#1C1C1E", outline="")
        poly((48, 14, 292, 14, 324, 64, 324, 326, 244, 454, 96, 454, 16, 326, 16, 64), fill="#E6E7EA",
             outline="#C8102E", width=2)
        cv.create_text(170 * s, 32 * s, text="TIME MASTER 550", fill="#C8102E", font=self.f_side_bold)
        for i in range(4):
            x = (92 + i * 52) * s
            b = tk.Button(cv, text=f"E{i + 1}", font=self.f_side_bold, bg="#C8102E", fg="white", bd=2,
                          activebackground="#E2384F", relief="raised", cursor="hand2", width=2,
                          command=lambda k=f"E{i + 1}": self.trainer_key(k))
            cv.create_window(x, 62 * s, window=b)
        self.tr_disp = tk.Canvas(cv, width=int(230 * s), height=int(160 * s), bg="#0A0A0A",
                                 highlightthickness=2, highlightbackground="#333")
        cv.create_window(170 * s, 172 * s, window=self.tr_disp)
        for lab, x in (("ON", 86), ("SHIFT", 254)):
            b = tk.Button(cv, text=lab, font=self.f_side_bold, bg="white", fg="#333", bd=2, width=5,
                          cursor="hand2", command=lambda k=lab: self.trainer_key(k))
            cv.create_window(x * s, 282 * s, window=b)
        for lab, (x, y) in (("▲", (170, 318)), ("◀", (118, 360)), ("OK", (170, 360)), ("▶", (222, 360)),
                            ("▼", (170, 402))):
            b = tk.Button(cv, text=lab, font=self.f_side_bold, width=3,
                          bg="white" if lab == "OK" else "#4A4C50", fg="#C8102E" if lab == "OK" else "white",
                          bd=2, cursor="hand2", command=lambda k=lab: self.trainer_key(k))
            cv.create_window(x * s, y * s, window=b)
        cv.create_text(170 * s, 440 * s, text="⧗", fill="#C8102E", font=self.f_side_bold)
        self.tr_leds = {}

    def _trainer_rear(self, parent, device):
        """Rueckseite: Bananenbuchsen (gruen = Signal, schwarz = Masse) und Anschluesse."""
        s = self.ui_scale
        cp = device == "cp545"
        W, H = int(420 * s), int((215 if cp else 190) * s)
        cv = tk.Canvas(parent, width=W, height=H, bg=PANEL, highlightthickness=0)
        cv.pack(anchor="w", pady=(4, 0))
        body = "#8E9196" if cp else "#1C1C1E"
        if cp:
            cv.create_rectangle(0, 10 * s, 18 * s, H - 10 * s, fill="#D9392F", outline="")
            cv.create_rectangle(402 * s, 10 * s, 420 * s, H - 10 * s, fill="#D9392F", outline="")
        cv.create_rectangle(18 * s, 6 * s, 402 * s, H - 6 * s, fill=body, outline="#555")
        order = (4, 3, 2, 1) if cp else (1, 2, 3, 4)
        xs = (70, 140, 260, 330) if cp else (150, 200, 270, 320)
        for ch, x in zip(order, xs):
            x *= s
            tag = f"jack{ch}"
            cv.create_oval(x - 17 * s, 22 * s, x + 17 * s, 56 * s, fill="#2EA84E", outline="#1E6B33", width=2,
                           tags=tag)
            cv.create_oval(x - 7 * s, 32 * s, x + 7 * s, 46 * s, fill="#111", outline="", tags=tag)
            cv.create_oval(x - 17 * s, 66 * s, x + 17 * s, 100 * s, fill="#222", outline="#555", width=2)
            cv.create_oval(x - 7 * s, 76 * s, x + 7 * s, 90 * s, fill="#000", outline="")
            cv.create_text(x, 110 * s, text=str(ch), fill="white", font=self.f_side_bold)
            cv.tag_bind(tag, "<Button-1>", lambda e, c=ch: self.trainer_do(lambda: self.sim.impulse(c, manual=False),
                                                                          f"Buchse {c}"))
            cv.tag_bind(tag, "<Button-3>", lambda e, c=ch: self.trainer_do(lambda: self.sim.double_contact(c),
                                                                          f"Buchse {c} Doppelkontakt"))
            cv.tag_bind(tag, "<Enter>", lambda e: cv.configure(cursor="hand2"))
            cv.tag_bind(tag, "<Leave>", lambda e: cv.configure(cursor=""))
        if cp:
            cv.create_text(200 * s, 70 * s, text="TAG\nHEUER", fill="white", font=self.f_side_bold,
                           justify="center")
            ports = (("POWER", 80, 34, 20), ("USB", 160, 22, 10), ("RS 232", 240, 34, 30), ("ETHERNET", 330, 44, 34))
            y0 = 172
        else:
            ports = (("RS 232", 60, 30, 24), ("ETHERNET", 60, 40, 34), ("USB-C", 378, 18, 8), ("DC", 378, 12, 12))
            y0 = 0
        for i, (lab, x, w, h) in enumerate(ports):
            x *= s
            y = (y0 if cp else (40, 110, 60, 110)[i]) * s
            fill = "#E8E8E8" if lab == "ETHERNET" else "#2A2A2A"
            tag = "eth" if lab == "ETHERNET" else ""
            cv.create_rectangle(x - w * s / 2, y - h * s / 2, x + w * s / 2, y + h * s / 2, fill=fill,
                                outline="#444", width=2, tags=tag)
            if lab == "ETHERNET":
                cv.create_rectangle(x - w * s / 2 + 5 * s, y - h * s / 2 + 5 * s, x + w * s / 2 - 5 * s,
                                    y + h * s / 2 - 5 * s, fill="#1A1A1A", outline="", tags="eth")
                cv.create_rectangle(x - w * s / 2 + 4 * s, y - h * s / 2 + 2 * s, x - w * s / 2 + 10 * s,
                                    y - h * s / 2 + 6 * s, fill="#3DDC5A", outline="", tags=("eth", "ethled"))
            cv.create_text(x, y - (h * s / 2) - 9 * s if cp else y + (h * s / 2) + 9 * s, text=lab, fill="white",
                           font=self.f_side)
        cv.tag_bind("eth", "<Button-1>", lambda e: self.trainer_cable())
        cv.tag_bind("eth", "<Enter>", lambda e: cv.configure(cursor="hand2"))
        cv.tag_bind("eth", "<Leave>", lambda e: cv.configure(cursor=""))
        self.tr_rear = cv
        self.tr_cable = _CableToggle(cv)

    def trainer_log(self, text):
        line = f"{time.strftime('%H:%M:%S')}  {text}"
        self.tr["log"].append(line)
        DIAG.info(f"Übung: {text}")

    def trainer_paper(self, text):
        if getattr(self, "tr_paper", None) is not None and self.tr_paper.winfo_exists():
            self.tr_paper.insert("end", text + "\n")
            self.tr_paper.see("end")

    def trainer_do(self, fn, label):
        self.trainer_log(label)
        fn()

    def trainer_poll(self):
        win = getattr(self, "trainer", None)
        if win is None or not win.winfo_exists():
            return
        now = time.time()
        while self._trainer_q:
            kind, text = self._trainer_q.popleft()
            if kind == "line":
                info = parse_thcom(text)
                if info and info["kind"] == "time":
                    nr = f"{info['nr']:>4}" if info["nr"] else "    "
                    self.trainer_paper(f"{info['type']} {nr} {info['seq']:>3} {info['ch']} "
                                       f"{fmt_tod(info['abs'] % 86400)}")
                    if info["type"] in ("TN", "T+", "T="):
                        self.tr["flash"][info["ch"]] = now + 0.4
                        runs = self.tr["runs"]
                        if info["ch"] == CH_START:
                            runs.append({"nr": info["nr"], "st": info["abs"], "fi": None})
                        elif info["ch"] == CH_FINISH:
                            r = next((x for x in runs if x["fi"] is None and info["nr"] and x["nr"] == info["nr"]),
                                     next((x for x in runs if x["fi"] is None), None))
                            if r is not None:
                                r["fi"] = info["abs"]
                        self.tr["runs"] = runs[-8:]
                    self.tr["rows"] = (self.tr["rows"] + [(info["type"], info["ch"], info["seq"],
                                                            info["abs"] % 86400)])[-5:]
                elif info and info["kind"] in ("open", "close"):
                    self.trainer_paper(("OPEN " if info["kind"] == "open" else "CLOSE ") + f"RUN {info['run']:02d}")
                elif text.startswith(("RR", "PL ")):
                    self.trainer_paper(text[3:] if text.startswith("PL ") else text)
            else:
                self.trainer_log(text)
                self.tr["last"] = text
        sim = self.sim
        if sim is not None:
            tod = (sim.now_abs()) % 86400
            if sim.device == "cp545":
                lines = self._lcd_cp_lines() if self.tr["menu"] else self._cp_home_lines(tod)
                lines = (lines + [""] * 8)[:8]
                self.tr_disp.configure(text="\n".join(l[:21] for l in lines))
                for ch, led in self.tr_leds.items():
                    led.itemconfigure("led", fill="#FF6B5F" if sim.inputs.get(ch) == 0 else "#B8322A")
            else:
                self._trainer_draw_tm(sim, tod, now)
        win.after(150, self.trainer_poll)

    def _trainer_draw_tm(self, sim, tod, now):
        """Farbdisplay TM550 nach Fotos (25.11.2026): Kaestchen ueber E1-E4 (gruen ↑ offen, rot ↓ senden, rot
        gesperrt), Uhrzeit, Eingangsnamen (gruen benutzt, blau nicht benutzt), WAIT/SYNC GPS, Zeilen pro Boot
        (Messung, Nr, Start, Ziel gelb, Laufzeit) oder Menue, Statusleiste."""
        cv, s = self.tr_disp, self.ui_scale
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        mono = ("Consolas", int(8 * s), "bold")
        xs = [22, 62, 168, 208]
        mode = sim.tm_mode if sim.new_tm else ("TIMING" if sim.timing else "BASIC")
        used = {1, 2, 3, 4} if mode == "BASIC" else {1, 4}
        for i in range(4):
            x, ch = xs[i] * s, i + 1
            st = sim.inputs.get(ch, 0)
            col = "#3DDC5A" if st == 0 else "#E5352B"
            cv.create_rectangle(x - 9 * s, 4 * s, x + 9 * s, 20 * s, outline=col, width=2)
            if st == 0:
                cv.create_text(x, 12 * s, text="↑", fill="#5BB8FF", font=mono)
            elif st == 1:
                cv.create_text(x, 12 * s, text="↓", fill="#5BB8FF", font=mono)
            lit = self.tr["flash"].get(ch, 0) > now
            name_col = ("#3DDC5A" if ch in used else "#5BB8FF")
            cv.create_rectangle(x - 12 * s, 26 * s, x + 12 * s, 38 * s, outline=name_col, width=2,
                                fill=name_col if lit else "")
            cv.create_text(x, 32 * s, text=f"E{ch}", fill="#04220A" if lit else name_col, font=mono)
        cv.create_text(W / 2, 12 * s, text=fmt_tod(tod)[:8], fill="white",
                       font=("Consolas", int(10 * s), "bold"))
        cv.create_line(4 * s, 32 * s, W - 4 * s, 32 * s, fill="#3A8DDE", width=1)
        gps = getattr(sim, "gps_sync", False)
        lab, col = (("SYNC GPS", "#2FA84F") if gps == "gps" else ("SYNC MAN", "#2F6FD8") if gps == "manual"
                    else ("WAIT GPS", "#E5532B"))
        cv.create_rectangle(W / 2 - 34 * s, 26 * s, W / 2 + 20 * s, 38 * s, fill=col, outline="")
        cv.create_text(W / 2 - 7 * s, 32 * s, text=lab, fill="white", font=mono)
        y = 46 * s
        if self.tr["menu"]:
            node = self.tr["menu"][-1]
            if node["kind"] == "confirm":
                cv.create_text(W / 2, 80 * s, text=node["text"], fill="white", font=mono)
                cv.create_text(W / 2, 110 * s, text="OK = Ja   ◀ = Nein", fill="#9AF59A", font=mono)
            elif node["kind"] == "info":
                for line in node["lines"][node["top"]:node["top"] + 6]:
                    cv.create_text(8 * s, y + 8 * s, anchor="w", fill="white", font=mono, text=line)
                    y += 15 * s
                if node["top"] + 6 < len(node["lines"]):
                    cv.create_text(W - 8 * s, H - 30 * s, text="↓", fill="#5BB8FF", font=mono)
            else:
                items, cur = node["items"], node["cur"]
                top = max(0, min(cur - 3, len(items) - 6))
                for i in range(top, min(len(items), top + 6)):
                    if i == cur:
                        cv.create_rectangle(4 * s, y, W - 4 * s, y + 14 * s, fill="#E6E7EA", outline="")
                    cv.create_text(8 * s, y + 7 * s, anchor="w", font=mono, text=items[i][0][:30],
                                   fill="#111" if i == cur else "white")
                    y += 15 * s
        else:
            for r in self.tr["runs"][-4:]:
                cv.create_rectangle(4 * s, y, W - 4 * s, y + 18 * s, fill="#C8102E", outline="")
                st = fmt_tod(r["st"] % 86400)[:12]
                fi = fmt_tod(r["fi"] % 86400)[:12] if r["fi"] else ""
                el = (r["fi"] if r["fi"] else sim.now_abs()) - r["st"]
                cv.create_text(6 * s, y + 9 * s, anchor="w", fill="white", font=("Consolas", int(7 * s), "bold"),
                               text=f"T1 {r['nr'] or '':>3} {st}")
                cv.create_text(W * 0.62, y + 9 * s, anchor="w", fill="#FFE14D", font=("Consolas", int(7 * s), "bold"),
                               text=fi[3:] if fi else "")
                cv.create_text(W - 6 * s, y + 9 * s, anchor="e", fill="white", font=("Consolas", int(7 * s), "bold"),
                               text=f"{el:.3f}" if r["fi"] else f"{el:.1f}")
                y += 22 * s
        cv.create_rectangle(0, H - 18 * s, W, H, fill="#111", outline="")
        icons = "▮100%  ⌖ " + ("Ton✕" if self._lcd_val("sound", "Off") == "Off" else "Ton") + \
                ("  ETH" if sim.clients else "  ETH✕") + "  BT✕"
        cv.create_text(6 * s, H - 9 * s, anchor="w", fill="#9AF59A", font=mono, text=icons)
        cv.create_rectangle(W - 70 * s, H - 16 * s, W - 2 * s, H - 2 * s, fill="#7FB8F0", outline="")
        cv.create_text(W - 36 * s, H - 9 * s, fill="#0A2A4A", font=mono,
                       text={"CIRCUIT": "Lap"}.get(mode, mode.capitalize()))

    def trainer_key(self, k):
        sim, t = self.sim, self.tr
        if sim is None:
            return
        self.trainer_log(f"Taste {k}")
        if k.startswith("K") and k[1:].isdigit():
            sim.impulse(int(k[1:]), manual=True)  # gruene Taste
            return
        if k.startswith("L") and k[1:].isdigit():
            sim.cycle_input(int(k[1:]))  # rote Sperrtaste
            return
        if k == "SHIFT":
            t["shift"] = not t.get("shift")
            return
        if k == "ON":
            if sim.device == "cp545":
                t["menu"] = [self._lcd_confirm("Gerät ausschalten?", self._lcd_power_off)]
            return
        if k == "⇧":
            return
        if k in ("E1", "E2", "E3", "E4") and sim.device == "tm550":
            if t.get("shift"):  # SHIFT + Ex: offen -> senden -> gesperrt -> offen
                t["shift"] = False
                sim.cycle_input(int(k[1]))
                return
            sim.impulse(int(k[1]), manual=True)
            return
        if t["menu"] or k in ("◀", "F") or (sim.device == "tm550" and k in ("▲", "▼", "▶", "OK")):
            return self.lcd_menu_key(k)
        if k == "." and not (t["state"] == "R" and t["buf"] == "0"):
            t.update(buf="", state="", nr=None, new="")  # * = Eingabe loeschen
            return
        if t["state"] == "RE1":
            if k.isdigit():
                t["new"] += k
            elif k == "Enter" and t["new"]:
                sim.renumber(t["nr"], int(t["new"]))
                t.update(buf="", state="", nr=None, new="")
            return
        if t["state"] == "R":
            if k == "E1":
                t["state"] = "RE1"
            elif k == "0":
                t["buf"] = "0"
                nr = t["nr"]
                self.root.after(1200, lambda: self._trainer_r0(nr))
            elif k == "." and t["buf"] == "0":
                sim.cancel(t["nr"], dsq=True)
                t.update(buf="", state="", nr=None)
            return
        if k.isdigit():
            t["buf"] = (t["buf"] + k)[-4:]
        elif k == "R" and t["buf"]:
            t.update(state="R", nr=int(t["buf"]), buf="")
        elif k in ("Enter", "E1") and t["buf"] and sim.device == "cp545":
            sim.next[CH_START] = int(t["buf"])  # Nr E1 = naechste Startnummer
            sim.note(f"Nächste Startnummer {t['buf']}")
            t["buf"] = ""
        elif k == "E1" and sim.device == "cp545":
            sim.false_start()

    def _trainer_r0(self, nr):
        t = self.tr
        if t["state"] == "R" and t["nr"] == nr and t["buf"] == "0":
            self.sim.cancel(nr)
            t.update(buf="", state="", nr=None)

    # ---------- Menues im Display (Fotos vom Geraet, 25.11.2026) ---------- #
    CP_MODES = ("PTB SEQUENTIEL 1-4", "PTB SEQUENTIEL 5-8", "NET TIME", "NET TIME + 2 INTER", "PARALLELE SEQ",
                "PARALLELE DIFF", "START - FINISH", "START INTER FINISH", "TRAINING", "SPLIT 1-4", "SPLIT 5-8",
                "SPLIT/LAP", "JUMPING", "JUMPING 2 PHASE", "JUMPING SNG PHASE")
    CP_MODE_ABBR = {"NET TIME": "NT", "NET TIME + 2 INTER": "NT", "PTB SEQUENTIEL 1-4": "PT",
                    "PTB SEQUENTIEL 5-8": "PT", "PARALLELE SEQ": "PS", "PARALLELE DIFF": "PD",
                    "START - FINISH": "SF", "START INTER FINISH": "SI", "TRAINING": "TR"}

    def _lcd_menu(self, title, items, cur=0):
        return {"kind": "menu", "title": title, "items": items, "cur": cur}

    def _lcd_confirm(self, text, yes):
        return {"kind": "confirm", "text": text, "yes": yes}

    def _lcd_info(self, title, lines):
        return {"kind": "info", "title": title, "lines": list(lines), "top": 0}

    def _lcd_choice(self, title, options, get, put):
        """Auswahlliste; der Cursor steht beim Oeffnen auf dem eingestellten Wert."""
        def make():
            cur = get()
            items = [(o, (lambda o=o: (put(o), "back")[1])) for o in options]
            return self._lcd_menu(title, items, options.index(cur) if cur in options else 0)
        return make

    def _lcd_val(self, key, default):
        return self.tr["vals"].get(key, default)

    def _lcd_set(self, key):
        def put(v):
            self.tr["vals"][key] = v
            self.trainer_log(f"Gerät: {key} = {v}")
        return put

    def _lcd_power_off(self):
        sim = self.sim
        sim.restart()
        self.trainer_paper("→ Gerät aus und wieder ein" + (": Ethernet ist aus (F › Einstellungen › Ethernet › "
                                                          "Std Connexion)" if sim.device == "cp545" else ""))

    def _cp_menu_main(self):
        sim = self.sim
        v, st = self._lcd_val, self._lcd_set

        def runs_list():
            return self._lcd_info("Liste der Läufe", [f"{sim.run:02d}+{sim.run - 1:02d}" if sim.run > 1 else ""] +
                                  [f"{r:02d}" for r in range(sim.run, 0, -1)])

        def ranking():
            rows = sorted(sim.results, key=lambda x: x[1])
            return self._lcd_info("Rangliste", [f"{i + 1:>2}. {n:>4} {secs:>8.1f}" for i, (n, secs) in
                                                enumerate(rows)] or ["keine Zeiten"])

        def still_running():
            now = sim.now_abs()
            return self._lcd_info("Noch im Rennen", [f"{n:>4} {now - t:>9.1f}" for n, t, _s in sim.course] or
                                  ["kein Boot"])

        def settings():
            def prec_get():
                return ("1", "1/10", "1/100", "1/1000", "1/10'000")[max(0, min(4, sim.prec - 1))]

            def prec_put(o):
                i = ("1", "1/10", "1/100", "1/1000", "1/10'000").index(o)
                sim.prec = max(1, min(5, i + 1))  # wie #WP 001 i: Resultat i, Zeiten i+1 Stellen
                sim.note(f"Präzision {o}")

            def lock_times():
                return self._lcd_menu("Sperre", [(f"Eingang {k}", (lambda k=k: self._lcd_info(
                    f"Eingang {k}", ["", f"   {'1.00' if k == 1 else '0.10'} Sek.", "", "Use Up & Dn Arrow"])))
                    for k in (1, 2, 3, 4)])

            def status_inputs():
                return self._lcd_info("Status Eingänge", [" ↑   ↑        ↑   ↑", "", "  Status Eingänge",
                                                          "     E1 bis E4", "", "", "           OK -> ↵"])

            def ethernet():
                def std():
                    sim.enable_ethernet()
                    return "back"
                return self._lcd_menu("Ethernet", [("Std Connexion", std), ("User Connexion", lambda: self._lcd_info(
                    "IP eingeben", ["", "  192.168.001.050", "", "", "Löschen -> *  OK -> ↵"]))])

            def print_params():
                for k in (1, 2, 3, 4):
                    self.trainer_paper(f"EINGANG {k} SPERRE {'1.00' if k == 1 else '0.10'}s")
                self.trainer_paper(f"{sim.mode}  PRÄZISION {prec_get()}")
                return None

            def slider(title, val):
                return lambda: self._lcd_info(title, ["", f"     {val}", "  |=====|----------|", "",
                                                      "Use Up & Dn Arrow"])

            items = [("Präzision", self._lcd_choice("Präzision [Sek]", ("1", "1/10", "1/100", "1/1000",
                                                                        "1/10'000"), prec_get, prec_put)),
                     ("Sperre", lock_times),
                     ("Numerierung", lambda: self._lcd_info("Numerierung", ["Eingang 1: Automatisch",
                                                                            "Eingang 4: Automatisch"])),
                     ("Status Eingänge", status_inputs),
                     ("RFID Auto Inkrem.", self._lcd_choice("RFID Auto Inkrem.", ("AUS", "0.5 sek", "1 sek"),
                                                            lambda: v("rfid", "AUS"), st("rfid"))),
                     ("LCD Kontrast", slider("LCD Kontrast", "40 %")),
                     ("Hintergrdlicht (Batt)", slider("Hintergrdlicht (Batt)", "30 %")),
                     ("HGbeleuchtung", slider("HGbeleuchtung", "60 Sek.")),
                     ("LCD Dauer", slider("LCD Dauer", "5 Sek.")),
                     ("Piep", self._lcd_choice("Piep", ("AUS", "EIN"), lambda: v("piep", "AUS"), st("piep"))),
                     ("RS232", self._lcd_choice("RS232", ("Zum PC", "TAGHeuer HL960/HL990", "TAGHeuer HL970/HL980",
                                                          "ALGE Display", "zu Ext. Drucker"),
                                                lambda: v("rs232", "TAGHeuer HL970/HL980"), st("rs232"))),
                     ("Ethernet", ethernet),
                     ("Sprache", self._lcd_choice("Sprache", ("English", "Francais", "Deutsch", "Italiano",
                                                              "Espanol"), lambda: v("sprache", "Deutsch"),
                                                  st("sprache"))),
                     ("Battery Type", self._lcd_choice("Battery Type", ("Non-Rechargeable", "NIMH charge enabled",
                                                                        "NIMH charge disabled"),
                                                       lambda: v("bat", "Non-Rechargeable"), st("bat"))),
                     ("Error Messages", self._lcd_choice("Error Messages", ("AUS", "EIN"),
                                                         lambda: "EIN" if sim.err_msgs else "AUS",
                                                         lambda o: setattr(sim, "err_msgs", o == "EIN"))),
                     ("Parameter drucken", print_params)]
            return self._lcd_menu("Einstellungen", items)

        def modes():
            items = [(md, (lambda md=md: (sim.set_mode(md), "back")[1])) for md in self.CP_MODES]
            return self._lcd_menu("Zeitmessart", items)  # Cursor oben wie am Geraet

        common = [("Geschwindigkeit", self._lcd_choice("Geschw.-Einheit", ("m/s", "Km/h", "Mph", "Knoten"),
                                                       lambda: v("speed", "Km/h"), st("speed"))),
                  ("Einstellungen", settings),
                  ("Drucker", self._lcd_choice("Drucker", ("AUS", "EIN"), lambda: v("drucker", "AUS"),
                                               st("drucker")))]
        if sim.run_open:
            items = [("Lauf schliessen", lambda: (sim.close_run(), "close")[1]),
                     ("Rangliste", ranking), ("Rangliste Lauf", runs_list), ("Noch im Rennen", still_running),
                     ("Kopieren", lambda: self._lcd_info("Kopieren", ["nicht nachgebaut"])),
                     ("Zeit einfügen", lambda: self._lcd_info("Zeit einfügen", ["nicht nachgebaut"]))] + common + [
                     ("Lauf einfügen", lambda: self._lcd_info("Lauf einfügen", ["nicht nachgebaut"]))]
            return self._lcd_menu("Hauptmenü", items, 1)
        items = [("CP545 Ausschalten", lambda: self._lcd_confirm("Gerät ausschalten?", self._lcd_power_off)),
                 ("Neuen Lauf öffnen", lambda: self._lcd_confirm(f"NEUER LAUF NR. {sim.run + 1}\nLauf hinzufügen?",
                                                                 lambda: sim.open_run())),
                 ("Synchronisation", lambda: self._lcd_menu("Synchroart", [("Manuell oder extern", None),
                                                                          ("Master/Slave RS232", None)])),
                 ("Speicher löschen", lambda: self._lcd_confirm("Speicher löschen", lambda: sim.note(
                     "Speicher gelöscht"))),
                 ("Rangliste Lauf", runs_list),
                 ("Rally Einstellungen", lambda: self._lcd_menu("Rally Einstellungen",
                                                                [("Rally Drucker Einstellungen", None)])),
                 ("Zeitmessart", modes)] + common + [
                 ("Herunterladen", lambda: self._lcd_menu("Herunterladen", [("Zum Drucker", None), ("Zum USB", None),
                                                                           ("Zum RS232 AUX", None),
                                                                           ("Zu Chrono RS232", None)]))]
        return self._lcd_menu("Hauptmenü", items, 1)

    def _tm_menu_run(self):
        sim = self.sim
        first = ((f"Current run n°{sim.run}", None) if sim.run_open else
                 ("Open a run", lambda: (sim.open_run(), "close")[1]))
        return self._lcd_menu("Run", [first, ("Close a run", lambda: (sim.close_run(), "close")[1]),
                                      ("Download run", None),
                                      ("Erase all runs", lambda: self._lcd_confirm("Erase all runs?",
                                                                                   lambda: sim.note("Läufe gelöscht")))])

    def _tm_menu_main(self):
        sim = self.sim
        v, st = self._lcd_val, self._lcd_set
        precs = ("1 second", "1/10 second", "1/100 second", "1/1000 second", "1/10000 second", "1/100000 second")

        def prec_put(o):
            sim.prec = precs.index(o)
            sim.note(f"Precision {o}")

        def status():
            day = int(sim.now_abs() // 86400)
            d = EPOCH_2000 + datetime.timedelta(days=day)
            return self._lcd_info("Status", [f"S/N : 59   V{sim.fw}", f"Date : {d:%Y/%m/%d}", "Free memory : 99 %",
                                             f"Precision : {precs[max(0, min(5, sim.prec))]}",
                                             "E1 : 0.10 s", "E2 : 0.10 s", "E3 : 0.10 s", "E4 : 0.10 s",
                                             "USB : 9600 Bds", "IP : 192.168.1.51", "Port : 7000",
                                             f"RS232 : {v('rs232', 'Scoreboard')}", "RS232 : 9600 Bds",
                                             "Battery temperature : 29°C"])

        def sync():
            def manual():
                sim.gps_sync = "manual"
                sim.note("Uhr von Hand gestellt (gilt ab dem nächsten Impuls)")
                return "back"

            def gps():
                sim.note("Suche GPS ...")
                self.root.after(5000, lambda: (setattr(sim, "gps_sync", "gps"), sim.note("SYNC GPS")))
                return "back"
            return self._lcd_menu("Synchronisation", [("Manual", manual), ("GPS", gps)])

        def mode_menu(name, val, extra):
            def activate():
                sim.set_mode(val)
                return "back"
            on = (sim.tm_mode == val)
            return lambda: self._lcd_menu(name, [(f"Activate          {'On' if on else 'Off'}", activate)] + extra)

        def timing_modes():
            tim = [(f"Timing {i}" + ("      E1  E4" if i == 1 else ""), None) for i in (1, 2, 3, 4)]
            spd = [(f"Speed {i}", None) for i in (1, 2, 3, 4)]
            return self._lcd_menu("Timing modes", [
                ("Basic", mode_menu("Basic", "BASIC", [])), ("Speed", mode_menu("Speed", "SPEED", spd)),
                ("Timing", mode_menu("Timing", "TIMING", tim)),
                ("Lap", mode_menu("Lap", "CIRCUIT", [("Configuration", None)])),
                ("Identification mode", self._lcd_choice("Identification mode", (
                    "Manual identification", "Identification at start", "Automatic identification"),
                    lambda: v("ident", "Automatic identification"), st("ident")))])

        def onoff(key, title, default="Off"):
            return self._lcd_choice(title, ("On", "Off"), lambda: v(key, default), st(key))

        items = [("Status", status), ("Synchronisation", sync), ("Run", self._tm_menu_run),
                 ("Timing modes", timing_modes),
                 ("Precision", self._lcd_choice("Precision", precs, lambda: precs[max(0, min(5, sim.prec))], prec_put)),
                 ("Input blocking time", lambda: self._lcd_info("Input blocking time",
                                                                [f"E{k} : 0.10 s" for k in (1, 2, 3, 4)])),
                 ("Options", lambda: self._lcd_menu("Options", [
                     ("Screen", None), ("Sound", onoff("sound", "Sound")),
                     ("Languages", self._lcd_choice("Languages", ("English", "Français"),
                                                    lambda: v("lang", "English"), st("lang"))),
                     ("Factory settings", lambda: self._lcd_confirm("Factory settings?", lambda: sim.note(
                         "Werkseinstellungen (Port wieder 2101)")))])),
                 ("Communication", lambda: self._lcd_menu("Communication", [
                     ("Ethernet", lambda: self._lcd_info("Ethernet", ["IP : 192.168.1.51", "Port : 7000"])),
                     ("Bluetooth", onoff("bt", "Bluetooth")),
                     ("RS232", self._lcd_choice("RS232", ("To PC", "Scoreboard"), lambda: v("rs232", "Scoreboard"),
                                                st("rs232"))),
                     ("USB", self._lcd_choice("USB", ("2400 Bds", "9600 Bds", "9600 Bds Flow control", "19200 Bds",
                                                      "38400 Bds"), lambda: v("usb", "9600 Bds"), st("usb"))),
                     ("Printer BLE", onoff("ble", "Printer BLE", "On")),
                     ("Protocol dock", self._lcd_choice("Protocol dock", ("DOCK", "PRINTER"),
                                                        lambda: v("dock", "DOCK"), st("dock")))])),
                 ("Scoreboard", lambda: self._lcd_menu("Scoreboard", [
                     ("Display protocol", self._lcd_choice("Display protocol", ("TAG HEUER THDIS08", "ITS"),
                                                           lambda: v("disp", "TAG HEUER THDIS08"), st("disp"))),
                     ("Display parameters", lambda: self._lcd_menu("Display parameters", [
                         ("Line", lambda: self._lcd_info("Line", [f"Line 0{i} : -" for i in (1, 2, 3, 4)])),
                         ("Freeze time", lambda: self._lcd_info("Freeze time", ["10 s"]))])),
                     ("ID competitor", onoff("idc", "ID competitor", "On"))])),
                 ("Update", lambda: self._lcd_info("Update", ["über ITS Updater"])),
                 ("Turn off", lambda: self._lcd_confirm("Turn off?", self._lcd_power_off))]
        return self._lcd_menu("Menu", items)

    def lcd_menu_key(self, k):
        """Tasten im Menue: CP F (auf/zurueck), ▲ ▼, ↵, * = JA; TM550 ◀ (auf/zurueck), ▲ ▼, OK/▶."""
        sim, stack = self.sim, self.tr["menu"]
        cp = sim.device == "cp545"
        if not stack:
            if cp and k == "F":
                stack.append(self._cp_menu_main())
            elif not cp and k == "◀":
                stack.append(self._tm_menu_run())
            return
        node = stack[-1]
        back = (k == "F") if cp else (k == "◀")
        if node["kind"] == "confirm":
            if k == ".":
                stack.pop()
                node["yes"]()
                stack.clear()
            elif k in ("Enter",) or back or (not cp and k == "◀"):
                stack.pop()
            elif not cp and k == "OK":
                stack.pop()
                node["yes"]()
                stack.clear()
            return
        if back:
            if not cp and node.get("title") == "Run" and len(stack) == 1:
                stack[-1] = self._tm_menu_main()  # ◀ aus Run fuehrt ins Hauptmenue
                return
            stack.pop()
            return
        if node["kind"] == "info":
            if k == "▼":
                node["top"] = min(max(0, len(node["lines"]) - 5), node["top"] + 1)
            elif k == "▲":
                node["top"] = max(0, node["top"] - 1)
            elif k in ("Enter", "OK", "▶"):
                stack.pop()
            return
        n = len(node["items"])
        if k == "▼":
            node["cur"] = min(n - 1, node["cur"] + 1)
        elif k == "▲":
            node["cur"] = max(0, node["cur"] - 1)
        elif k in ("Enter", "OK", "▶"):
            _lab, act = node["items"][node["cur"]]
            if act is None:
                return
            res = act()
            if res == "back":
                stack.pop()
            elif res == "close":
                stack.clear()
            elif isinstance(res, dict):
                stack.append(res)

    def _lcd_cp_lines(self):
        """Menue im CP-Display: Titel, Strich, 5 Eintraege mit ▶, △/▽ am Rand."""
        node = self.tr["menu"][-1]
        if node["kind"] == "confirm":
            body = node["text"].split("\n")
            return [""] + [f"{b:^21}" for b in body] + [""] * (6 - len(body)) + ["JA -> *     NEIN -> ↵"]
        title = node["title"]
        lines = [f"{title:^21}", "─" * 21]
        if node["kind"] == "info":
            return lines + node["lines"][node["top"]:node["top"] + 6]
        items, cur = node["items"], node["cur"]
        top = max(0, min(cur - 2, len(items) - 5))
        for i in range(top, min(len(items), top + 5)):
            mark = "▶" if i == cur else " "
            end = "△" if i == top and top > 0 else ("▽" if i == top + 4 and top + 5 < len(items) else "")
            lines.append(f"{mark}{items[i][0][:19]:<19}{end}")
        return lines

    def _cp_home_lines(self, tod):
        """Grundanzeige CP 545 (Fotos 25.11.2026): Laufnummer, Balken der gesperrten Eingaenge, Uhrzeit,
        Zeitmessart; darunter naechste Start- und Zielnummer, unten das Boot auf der Strecke."""
        sim, bar = self.sim, "▬▬"
        on = sim.run_open
        c1 = f"{sim.run:02d}" if on and sim.inputs.get(1) else bar
        c2 = "  " if sim.inputs.get(2) else bar
        c3 = "  " if sim.inputs.get(3) else bar
        c4 = self.CP_MODE_ABBR.get(sim.mode, sim.mode[:2]) if on and sim.inputs.get(4) else bar
        l1 = f"{c1} {c2} {fmt_tod(tod)[:8]} {c3} {c4}"
        nxt = sim.next.get(CH_START) if sim.numbered() or not on else None
        left = f"{nxt:>4} ◁" if nxt else "      "
        fin = f"{sim.course[0][0]}" if sim.course and sim.course[0][0] else "____"
        l2 = f"{left}{'▷ ' + fin:>15}"
        l3 = "▯" + ("  ETHERNET AUS" if sim.eth_off else ("  KABEL AB" if sim.offline else ""))
        entry = self.tr["buf"]
        if self.tr["state"] == "R":
            entry = f"{self.tr['nr']} R {self.tr['buf']}"
        elif self.tr["state"] == "RE1":
            entry = f"{self.tr['nr']} R E1 {self.tr['new']}"
        if sim.course:
            nr, t0, _s = sim.course[0]
            el = sim.now_abs() - t0
            bottom = f"{(str(nr) if nr else '') + '▷':<8}{el:>13.1f}"
        elif sim.results:
            nr, secs = sim.results[-1]
            bottom = f"{nr} <  {nr}>{secs:>13.1f}"[:21]
        else:
            bottom = ""
        return [l1, l2, l3, (self.tr.get("last") or "")[:21], "", f"> {entry}" if entry else "", "", bottom]

    def trainer_menu(self):
        sim = self.sim
        menu = self._menu()
        menu.add_command(label="Lauf schliessen", command=lambda: self.trainer_do(sim.close_run, "Lauf schliessen"))
        menu.add_command(label="Neuen Lauf öffnen", command=lambda: self.trainer_do(sim.open_run, "Lauf öffnen"))
        menu.add_command(label="Lauf mit gleicher Nummer neu öffnen",
                         command=lambda: self.trainer_do(lambda: sim.open_run(same=True), "Lauf neu öffnen"))
        menu.add_separator()
        modes = (("NET TIME", "PTB SEQUENTIEL 1-4", "START - FINISH") if sim.device == "cp545" else
                 (("BASIC", "BASIC"), ("TIMING", "TIMING"), ("SPEED", "SPEED"), ("LAP", "CIRCUIT")))
        for md in modes:
            lab, val = (md, md) if isinstance(md, str) else md
            cur = sim.mode if sim.device == "cp545" else sim.tm_mode
            menu.add_command(label=("● " if cur == val else "   ") + f"Zeitmessart {lab}",
                             command=lambda v=val: self.trainer_do(lambda: sim.set_mode(v), f"Zeitmessart {v}"))
        if sim.device == "cp545":
            menu.add_separator()
            menu.add_command(label=("Einstellungen › Ethernet einschalten" if sim.eth_off else
                                    "Einstellungen › Ethernet (ist eingeschaltet)"),
                             command=lambda: self.trainer_do(sim.enable_ethernet, "Ethernet am CP eingeschaltet"))
        x, y = self.trainer.winfo_pointerxy()
        menu.tk_popup(x, y)

    def trainer_cable(self):
        on = not self.tr_cable.on
        self.tr_cable.set(on)
        self.trainer_do(lambda: self.sim.set_cable(on), "Kabel " + ("ein" if on else "aus"))

    def trainer_case_falsestart(self):
        sim = self.sim
        self.trainer_do(lambda: sim.impulse(CH_START), "Übungsfall Fehlstart: Start ausgelöst")
        self.trainer_paper("→ Falschstart: am CP E1 drücken (Nummer von der Startzeit entfernen), das Boot "
                           "startet nochmals. TM550: Zeit in der App als Fehlimpuls verwerfen")

    def trainer_case_cable(self):
        self.trainer_do(lambda: self.sim.set_cable(False), "Übungsfall: Kabel 10 s ab")
        self.tr_cable.set(False)

        def back():
            if self.sim is not None:
                self.sim.set_cable(True)
            if getattr(self, "tr_cable", None) is not None and self.tr_cable.winfo_exists():
                self.tr_cable.set(True)
        self.root.after(10000, back)

    def trainer_case_restart(self):
        sim = self.sim
        self.trainer_do(sim.restart, "Übungsfall: Gerät aus und wieder ein")
        if sim.device == "cp545":
            self.trainer_paper("→ Ethernet ist aus: F › Einstellungen › Ethernet › Std Connexion")
        else:
            self.trainer_paper("→ TM550 verbindet wieder, Uhrzeit am Gerät prüfen")

    def trainer_case_reopen(self):
        sim = self.sim
        self.trainer_do(lambda: (sim.close_run(), sim.open_run(same=True)), "Übungsfall: Lauf neu geöffnet")

    def trainer_case_wrongnr(self):
        sim = self.sim
        if sim.device == "cp545":
            wrong = (sim.next.get(CH_START) or 1) + 7
            sim.next[CH_START] = wrong
            self.trainer_do(lambda: sim.impulse(CH_START), f"Übungsfall: Start mit falscher Nummer {wrong}")
            self.trainer_paper("→ korrigieren: falsche Nr R E1 richtige Nr Enter")
        else:
            self.trainer_paper("→ TM550: Nummern vergibt die App, dort Nummer ändern")

    def trainer_save(self):
        folder = os.path.join(self.data_path, "training")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"uebung_{time.strftime('%Y%m%d_%H%M%S')}.txt")
        paper = self.tr_paper.get("1.0", "end").strip() if getattr(self, "tr_paper", None) else ""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Übungsprotokoll\n\n" + "\n".join(self.tr["log"]) + "\n\nPapierstreifen / Meldungen\n"
                     + paper + "\n\nApp-Log\n" + "".join(line for line, _t, _f in self.log_lines[-300:]))
        self.log(f"Übungsprotokoll gespeichert: {path}", tag="ok")
        self.open_folder(path)
        return path

    def trainer_close(self):
        if self.sim is not None:
            self.sim.on_event = self.sim.on_line = None
            if self.sim.offline:
                self.sim.set_cable(True)
        self.trainer.destroy()

    def sim_status(self, text):
        if getattr(self, "lbl_sim", None) is not None and self.lbl_sim.winfo_exists():
            self.lbl_sim.configure(text=text)

    def sim_do(self, what):
        if self.sim is None:
            return
        if what == "start":
            self.sim_status(f"Start Nr {self.sim.start()}")
        elif what == "finish":
            nr = self.sim.finish()
            self.sim_status(f"Ziel (CP: Nr {nr})" if nr else "Ziel ohne Boot")
        elif what == "drop":
            self.sim.drop_next = True
            self.sim_status("Die nächste Zeitmeldung geht verloren")

    def sim_toggle_auto(self):
        self._sim_auto = not getattr(self, "_sim_auto", False)
        if self._sim_auto:
            self._sim_next = time.time()
            self.sim_auto_tick()

    def sim_auto_tick(self):
        if not getattr(self, "_sim_auto", False) or self.sim is None:
            return
        import random
        now = time.time()
        if now >= self._sim_next:
            self.sim_do("start")
            self._sim_next = now + 15
            self.root.after(int(random.uniform(20, 40) * 1000), lambda: self.sim and self.sim_do("finish"))
        self.root.after(500, self.sim_auto_tick)

    def sim_replay_dialog(self):
        path = filedialog.askopenfilename(parent=self.sim_win, title="Log abspielen",
                                          initialdir=os.path.join(self.data_path, RAW_DIR),
                                          filetypes=[("Rohdaten oder Text", "*.jsonl *.txt *.log"), ("Alle", "*.*")])
        if path:
            self.sim_replay(path, float(self.var_sim_speed.get()))

    def sim_replay(self, path, speed=5.0):
        """Aufgezeichnete Zeilen (Rohdaten .jsonl oder PuTTY-Log) mit den Originalabstaenden abspielen."""
        items = []
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("{"):
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        if d.get("dev", "A") == "A":
                            items.append((float(d.get("t", 0)), str(d.get("line", ""))))
                    elif re.match(r"^(T[N\-\*\+=C]|RR|OP|CL)\s", line):
                        items.append((None, line))
        except OSError as exc:
            messagebox.showerror("Log abspielen", str(exc))
            return
        if not items:
            messagebox.showinfo("Log abspielen", "Keine Zeitmeldungen in der Datei gefunden.")
            return
        # ohne Zeitstempel: Zeitabstaende aus den Tageszeiten der Zeilen
        base, out = None, []
        for t, line in items:
            if t is None:
                info = parse_thcom(line)
                t = info["abs"] if info and info.get("kind") == "time" else (out[-1][0] if out else 0)
            base = t if base is None else base
            out.append((t, line))
        self.sim_status(f"Spielt {len(out)} Zeilen ab ({speed:g}×)")
        self.log(f"Simulator: {os.path.basename(path)} wird abgespielt ({len(out)} Zeilen, {speed:g}×)")
        t0 = out[0][0]
        for t, line in out:
            delay = max(0, int((t - t0) / speed * 1000))
            self.root.after(delay, lambda l=line: self.sim and self.sim.replay_line(l))

    def close_simulator(self):
        self._sim_auto = False
        if self.cp is not None and self.cp.host == "127.0.0.1" and self.sim and self.cp.port == self.sim.port:
            self.disconnect_all()
            self.set_connected(False, "nicht verbunden")
        if self.sim is not None:
            self.sim.close()
            self.sim = None
            self.log("Simulator beendet")
        if getattr(self, "sim_win", None) is not None and self.sim_win.winfo_exists():
            self.sim_win.destroy()

    # ================================================================== #
    # PDF und Druck
    # ================================================================== #
    def pdf_folder(self):
        folder = self.settings["export_dir"] or os.path.join(self.data_path, "pdf")
        os.makedirs(folder, exist_ok=True)
        return folder

    def pdf_doc(self, what):
        label = self.event_label() or "SWV Wettkampf"
        doc = PdfDoc(f"{what}", f"{label}   ·   Stand {time.strftime('%d.%m.%Y %H:%M')}")
        mode = self.settings["wettkampf"]
        if what == "Rangliste":
            for cat in self.categories:
                ranked = self.ranking(cat)
                nk = [(nr, code) for nr, code in sorted(self.status.items())
                      if (self.category_of(nr) or {}).get("name") == cat["name"]]
                if not ranked and not nk:
                    continue
                doc.heading(f"{cat['name']}   ({cat['min']}-{cat['max']})")
                rows = []
                for rank, nr, _t in ranked:
                    p = self.participants.get(nr, {})
                    pen = self.penalty(nr)
                    rows.append([f"{rank}.", nr, display_name(p, mode), p.get("verein", ""),
                                 self.results[nr]["str"], f"+{pen}" if pen else "", self.disp_time(nr)])
                doc.table([("Rang", .07, "right"), ("Nr", .07, "right"), ("Name", .30, "left"),
                           ("Verein", .24, "left"), ("Zeit", .11, "right"), ("Straf", .08, "right"),
                           ("Total", .13, "right")], rows)
                if nk:
                    doc.note("Nicht klassiert: " + ", ".join(
                        f"Nr {nr} {display_name(self.participants.get(nr, {}), mode)} ({code})".replace(" ()", "")
                        for nr, code in nk))
        elif what == "Startliste":
            rows = []
            for i, nr in enumerate(self.start_order, 1):
                p = self.participants.get(nr, {})
                cat = self.category_of(nr)
                rows.append([i, nr, display_name(p, mode), p.get("verein", ""),
                             cat["name"] if cat else ("Test" if self.is_test(nr) else ""),
                             self.status.get(nr, "") or (self.results[nr]["str"] if nr in self.results else "")])
            doc.table([("Pos", .07, "right"), ("Nr", .07, "right"), ("Name", .30, "left"), ("Verein", .24, "left"),
                       ("Kategorie", .17, "left"), ("Zeit/Status", .15, "right")], rows)
        else:  # Zeitprotokoll wie der Papierstreifen des CP
            why = {"ok": "", "locked": "gesperrt", "nobody": "ohne Boot", "reserve": "nur Reserve", "fehl": "Fehlimpuls", "prell": "Prellzeit",
                   "unassigned": "ohne Nummer (CP)", "cancelled": "storniert (CP)", "invalid": "ungültig",
                   "dup": "doppelt (Reserve)", "ignored": "ausgeschieden"}
            rows = []
            for k, r in sorted(self.cp_recs.items(), key=lambda x: x[1]["abs"]):
                where = {CH_START: "Start", CH_FINISH: "Ziel"}.get(k[2], f"Eingang {k[2]}")
                day = EPOCH_2000 + datetime.timedelta(days=int(r["abs"] // 86400))
                rows.append([day.strftime("%d.%m."), fmt_tod(r["abs"] % 86400), where,
                             ("Reserve " if k[0] == "B" else "") + str(k[3]), r.get("cp_nr", ""), r.get("nr") or "",
                             why.get(r["status"], r["status"]) + (" ausgeschieden" if r.get("dnf") else "")])
            if not rows:
                doc.note("Keine Rohzeiten vom CP vorhanden (nur bei Ethernet oder USB).")
            doc.table([("Tag", .08, "left"), ("Tageszeit", .15, "right"), ("Messpunkt", .12, "left"),
                       ("Seq", .12, "right"), ("CP-Nr", .09, "right"), ("Nr", .08, "right"),
                       ("Bemerkung", .36, "left")], rows)
        return doc

    def make_pdf(self, what, print_it=False):
        doc = self.pdf_doc(what)
        name = f"{self.event_prefix()}_{what}.pdf"
        path = os.path.join(self.pdf_folder(), name)
        try:
            with open(path, "wb") as fh:
                fh.write(doc.build(f"SWV Live-Ranking {APP_VERSION}"))
        except OSError as exc:
            messagebox.showerror("PDF", f"PDF konnte nicht gespeichert werden:\n{exc}")
            return None
        self.log(f"PDF gespeichert: {path}", tag="ok")
        if IS_WINDOWS:
            # Ueber den Explorer oeffnen: dann ruft ein signiertes Programm den PDF-Reader auf und dieser
            # zeigt keine Sicherheitswarnung wegen der unsignierten App. Gedruckt wird im Reader (Ctrl+P).
            try:
                subprocess.Popen(["explorer.exe", os.path.normpath(path)])
            except OSError as exc:
                messagebox.showwarning("PDF", f"Gespeichert unter\n{path}\n\nÖffnen nicht möglich: {exc}")
            else:
                if print_it:
                    self.log("PDF geöffnet: im PDF-Reader mit Ctrl+P drucken", tag="ok")
        return path

    def open_pdf_menu(self, event=None):
        menu = self._menu()
        for what in ("Rangliste", "Startliste", "Zeitprotokoll"):
            menu.add_command(label=f"{what} als PDF", command=lambda w=what: self.make_pdf(w))
        menu.add_separator()
        for what in ("Rangliste", "Startliste"):
            menu.add_command(label=f"{what} drucken (öffnet PDF, Ctrl+P)",
                             command=lambda w=what: self.make_pdf(w, print_it=True))
        w = self.btn_pdf
        x, y = w.winfo_rootx(), w.winfo_rooty() + w.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

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
        if hasattr(self, "cmb_usb"):
            self.cmb_usb["values"] = values
            if self.cmb_usb.get() not in values:
                want = self.settings["conn"]["usb_port"]
                match = next((label for label, dev in self.port_map.items() if dev == want), None)
                self.cmb_usb.set(match or (values[0] if values else want))
        if hasattr(self, "cmb_usb_b"):
            self.fill_backup_combos()

    def toggle_connection(self):
        if self.usb_mode():
            if self.cp is not None:
                self.cp.stop()
                self.set_conn_status("trenne ...", GOLD)
            else:
                self.connect_usb()
            return
        if self.eth_mode():
            if self.eth_job is not None:
                self.eth_job = None
                self.set_connected(False, "nicht verbunden")
                self.log("Verbinden abgebrochen", tag="warn")
            elif self.cp is not None:
                self.cp.stop()
                self.set_conn_status("trenne ...", GOLD)
            else:
                want = (self.cmb_cp.get() or "").split()[0] if self.cmb_cp.get().strip() else ""
                if want.startswith(("127.0.0.1:", "localhost:")):
                    self.connect_gprs(want)
                else:
                    self.start_eth_job(connect=True)
            return
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
        self.serial_base = f"{reader.port} verbunden"
        self.serial_last_rx = time.time()
        self.serial_silent = None
        self.serial_lines0 = None
        if was_reconnecting:
            self.log(f"{reader.port} wieder verbunden", tag="ok")
            self.add_ticker(f"Verbindung zum CP 545 wieder hergestellt ({reader.port})", "ziel")
            if self.cmb_port.get().split(" - ")[0].strip() != reader.port:
                self.refresh_ports()
                match = next((label for label, dev in self.port_map.items() if dev == reader.port), reader.port)
                self.cmb_port.set(match)
        else:
            self.log(f"Verbunden mit {reader.port}", tag="ok")

    # ---------------- Datenueberwachung RS232 ---------------- #
    def serial_alive(self):
        return (not self.eth_mode() and self.reader is not None and self.reader.is_alive()
                and not self.reconnecting and getattr(self, "serial_base", None))

    def serial_rx(self):
        self.serial_last_rx = time.time()
        if self.serial_silent == "data":
            self.serial_ok_again("Daten vom CP 545 wieder da")

    def serial_ok_again(self, text):
        self.serial_silent = None
        self.set_connected(True, self.serial_base)
        self.log(text, tag="ok")
        self.add_ticker(text, "ziel")

    def serial_problem(self, kind, text):
        if self.serial_silent:
            return
        self.serial_silent = kind
        self.set_conn_status(text, RED)
        self.log(text, tag="error")
        self.add_ticker(text, "warn")

    def on_serial_lines(self, lines):
        state = "  ".join(f"{k} {'ein' if v else 'aus'}" for k, v in lines.items())
        self.log(f"Steuerleitungen: {state}", focus=False)
        if self.serial_lines0 is None:
            self.serial_lines0 = lines
            return
        dropped = [k for k, v in lines.items() if self.serial_lines0.get(k) and not v]
        if dropped:
            self.serial_problem("lines", f"Kabel zum CP getrennt ({', '.join(dropped)} aus), Kabel prüfen")
        elif self.serial_silent == "lines":
            self.serial_ok_again("Kabel zum CP wieder verbunden")

    def serial_watch_tick(self):
        """Jede Sekunde: Abbruch erkennen, wenn waehrend eines Laufs keine Laufzeit mehr kommt."""
        self.root.after(1000, self.serial_watch_tick)
        if not self.serial_alive():
            return
        age = time.time() - self.serial_last_rx
        running = self.live_time is not None and not self.live_final
        if running and age > SERIAL_SILENCE_S and not self.serial_silent:
            self.serial_problem("data", "keine Daten vom CP, Kabel prüfen")
            return
        if self.serial_silent:
            return
        if age >= 60:
            mins = int(age // 60)
            ago = f"{mins} min" if mins < 60 else f"{mins // 60} h {mins % 60} min"
            self.set_conn_status(f"{self.serial_base} · letzte Daten vor {ago}", GREEN_TEXT)
        elif self._conn_status[0] != self.serial_base:
            self.set_conn_status(self.serial_base, GREEN_TEXT)

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
        self.set_conn_status(text, color or (GREEN_TEXT if connected else MUTED))
        self.btn_connect.configure(text="Trennen" if connected else "Verbinden",
                                   bg=DARK_RED if connected else GREEN)

    def log(self, text, focus=True, tag=None):
        """focus=False: nur im Tab 'Alle' (Rohdaten). Sonst in beiden Tabs."""
        line = f"{time.strftime('%H:%M:%S')}  {text}\n"
        DIAG.log(logging.WARNING if tag in ("warn", "error") else logging.INFO, f"LOG[{tag or '-'}] {text}")
        self.log_lines.append((line, tag, focus))
        del self.log_lines[:-LOG_MAX_LINES * 2]
        self._log_insert(line, tag, focus)

    def _log_insert(self, line, tag, focus):
        if not hasattr(self, "log_tabs"):
            return
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

    def open_manual_startlist(self):
        """Startliste von Hand: Nummern in Startreihenfolge (Komma, Leerzeichen, Zeilen, Bereiche «101-130») oder
        eine Zeile pro Boot «Nr; Name 1; Name 2; Verein» (auch aus Excel kopiert, Tab getrennt)."""
        dlg = self._toplevel("Startliste eingeben")
        dlg.columnconfigure(0, weight=1)
        tk.Label(dlg, text="Startnummern in Startreihenfolge, z.B. «1-12, 201-215, 301» oder eine Zeile pro Boot: "
                           "«101; Meier; Muster; WFV Muster» (aus Excel kopiert geht auch).",
                 bg=PANEL, fg=TEXT, font=self.f_side, justify="left", wraplength=int(560 * self.ui_scale)).grid(
            row=0, column=0, sticky="w")
        txt = tk.Text(dlg, height=10, width=60, bg=INPUT_BG, fg=INPUT_FG, insertbackground=TEXT, font=self.f_log,
                      relief="flat", highlightthickness=0)
        txt.grid(row=1, column=0, sticky="nsew", pady=(8, 6))
        dlg.rowconfigure(1, weight=1)
        lbl = tk.Label(dlg, text="", bg=PANEL, fg=MUTED, font=self.f_side, justify="left", anchor="w",
                       wraplength=int(560 * self.ui_scale))
        lbl.grid(row=2, column=0, sticky="w")
        var = tk.StringVar(value="append" if self.start_order else "replace")
        rf = tk.Frame(dlg, bg=PANEL)
        rf.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self._radio(rf, "Ersetzen", var, "replace").pack(side="left", padx=(0, 8))
        self._radio(rf, "Anhängen", var, "append").pack(side="left")
        state = {"items": [], "warn": []}

        def refresh(_e=None):
            items, warn = parse_manual_startlist(txt.get("1.0", "end"))
            state.update(items=items, warn=warn)
            cats = {}
            for nr, _f in items:
                c = self.range_category(nr)
                key = c["name"] if c else "ohne Kategorie"
                cats[key] = cats.get(key, 0) + 1
            head = ", ".join(str(n) for n, _f in items[:12]) + (" …" if len(items) > 12 else "")
            text = (f"{len(items)} Starts: {head}\n" + " · ".join(f"{k} {v}" for k, v in cats.items())
                    if items else "Noch keine Nummern erkannt.")
            if warn:
                text += "\n" + "; ".join(warn[:4])
            lbl.configure(text=text, fg=GOLD if warn else MUTED)

        txt.bind("<KeyRelease>", refresh)
        txt.bind("<<Paste>>", lambda e: self.root.after(20, refresh))

        def take():
            items = state["items"]
            if not items:
                messagebox.showwarning("Startliste", "Keine Startnummern erkannt.", parent=dlg)
                return
            mode = var.get()
            if mode == "replace" and (self.results or self.course) and not messagebox.askyesno(
                    "Startliste", "Es gibt schon Starts oder Resultate. Startliste trotzdem ersetzen?\nResultate, "
                                  "Notizen und Strafpunkte bleiben pro Startnummer erhalten.", parent=dlg):
                return
            parts = {} if mode == "replace" else dict(self.participants)
            order = [] if mode == "replace" else list(self.start_order)
            added = skipped = 0
            for nr, f in items:
                if nr in parts and mode == "append":
                    skipped += 1
                    continue
                old = self.participants.get(nr, {})
                cat = self.range_category(nr)
                parts[nr] = {"nr": nr, "p1": f[0] if len(f) > 0 else old.get("p1", ""),
                             "p2": f[1] if len(f) > 1 else old.get("p2", ""),
                             "verein": f[2] if len(f) > 2 else old.get("verein", ""),
                             "kategorie": f[3] if len(f) > 3 else (cat["name"] if cat else old.get("kategorie", "")),
                             "notiz": old.get("notiz", ""), "strafpunkte": old.get("strafpunkte", 0)}
                if nr not in order:
                    order.append(nr)
                added += 1
            self.participants, self.start_order = parts, order
            self._club_printed, self._print_prev_club = set(), None
            self.rebuild_order_index()
            self.rebuild_cat_lookup()
            if mode == "replace" or not getattr(self, "startlist_source", ""):
                self.startlist_source = "von Hand eingegeben"
            self.update_startlist_label()
            self.log(f"Startliste {'ersetzt' if mode == 'replace' else 'ergänzt'}: {added} Starts von Hand"
                     + (f", {skipped} schon vorhanden" if skipped else ""), tag="ok")
            dlg.destroy()
            self.on_data_changed()
            self.cp_sync_next("Startliste")

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self._button(btns, "Übernehmen", take, BLUE).pack(side="right")
        self._button(btns, "Abbrechen", dlg.destroy).pack(side="right", padx=(0, 8))
        refresh()
        self._place(dlg)
        txt.focus_set()
        self.manual_startlist_dlg = (dlg, txt, var, take, refresh)

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

        preview = tk.Text(dlg, height=12, width=90, bg=INPUT_BG, fg=TEXT, font=self.f_log, relief="flat",
                          highlightthickness=0, wrap="none")
        lbl_sum = tk.Label(dlg, text="", bg=PANEL, fg=TEXT, font=self.f_side, anchor="w", justify="left")
        lbl_warn = tk.Label(dlg, text="", bg=PANEL, fg=GOLD, font=self.f_side, anchor="w", justify="left")
        var_cats = tk.BooleanVar(value=self.settings["cats_auto"])

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
            cats, cat_warn = derive_category_ranges(order, parts)
            text = f"{len(order)} Starts, {clubs} Vereine, {len(cats)} Kategorien in der Datei."
            if issues["ohne_nr"]:
                text += f"\n{issues['ohne_nr']} Zeilen ohne gültige Startnummer werden übersprungen."
            if issues["doppelt"]:
                text += f"\nDoppelte Startnummern (nur erster Eintrag): {', '.join(map(str, issues['doppelt'][:15]))}"
            if cats:
                text += "\nKategorien: " + ", ".join(f"{c} {lo}-{hi} ({n})" for c, lo, hi, n in cats)
            lbl_sum.configure(text=text, wraplength=720)
            lbl_warn.configure(text="\n".join("⚠ " + w for w in cat_warn), wraplength=720)
            if cat_warn:
                lbl_warn.grid()
            else:
                lbl_warn.grid_remove()

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
        lbl_warn.grid(row=r + 3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._check(dlg, "Kategorien und Nummernbereiche aus der Startliste übernehmen "
                         f"(bis ..99, ab 900 bis 950, {TEST_RANGE[0]}-{TEST_RANGE[1]} Test)", var_cats).grid(
            row=r + 4, column=0, columnspan=2, sticky="w", pady=(6, 0))

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
                    if old.get("best_hand"):
                        p["best_hand"] = True
            self.participants = parts
            self.start_order = order
            self._club_printed, self._print_prev_club = set(), None  # neue Startliste: Vereinsdruck neu
            self.rebuild_order_index()
            self.startlist_source = os.path.basename(path)
            self.settings["wettkampf"] = var_mode.get()
            self.var_mode.set(var_mode.get())
            self.update_mode_buttons()
            self.save_settings()
            self.settings["cats_auto"] = bool(var_cats.get())
            self.save_settings()
            if hasattr(self, "sw_cats_auto"):
                self.sw_cats_auto.set(self.settings["cats_auto"])
            if var_cats.get():
                self.apply_startlist_categories(order, parts)
            else:
                self.rebuild_cat_lookup()
            self.update_startlist_label()
            self.log(f"Startliste geladen: {len(order)} Starts aus {self.startlist_source}", tag="ok")
            dlg.destroy()
            self.on_data_changed()

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=r + 5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._button(btns, "Importieren", do_import, BLUE).pack(side="right")
        self._button(btns, "Abbrechen", dlg.destroy).pack(side="right", padx=(0, 8))
        refresh()
        self._center(dlg)
        dlg.grab_set()

    def apply_startlist_categories(self, order, parts, only_changes=False):
        """Nummernbereiche der Kategorien aus der Startliste setzen. -> Liste der Aenderungen"""
        changed = []
        ranges, warnings = derive_category_ranges(order, parts)
        for name, lo, hi, _n in ranges:
            cat = self._cat_lookup.get(name.casefold())
            if cat and (cat["min"], cat["max"]) == (lo, hi):
                if not only_changes:
                    changed.append(f"{cat['name']} {lo}-{hi}")
                continue
            if cat:
                cat["min"], cat["max"] = lo, hi
            else:
                cat = {"name": name.upper(), "min": lo, "max": hi, "rekord": ""}
                self.categories.append(cat)
                self.rebuild_cat_lookup()
            changed.append(f"{cat['name']} {lo}-{hi}")
        if only_changes and not changed:
            return []
        for w in warnings:
            self.log(f"Kategorien: {w}", tag="warn")
        self.rebuild_cat_lookup()
        self.save_categories()
        self.refresh_category_list()
        self.build_cards()
        if changed:
            self.log("Kategorien aus Startliste: " + ", ".join(changed), tag="ok")
        return changed

    def sync_categories(self):
        """Bereiche automatisch nachfuehren, wenn sich die Startliste geaendert hat."""
        if not self.settings["cats_auto"] or not self.start_order or getattr(self, "_syncing_cats", False):
            return
        self._syncing_cats = True
        try:
            if self.apply_startlist_categories(self.start_order, self.participants, only_changes=True):
                self._rank_cache = None
        finally:
            self._syncing_cats = False

    def toggle_cats_auto(self):
        self.settings["cats_auto"] = not self.settings["cats_auto"]
        self.save_settings()
        if self.settings["cats_auto"]:
            self.log("Kategoriebereiche werden automatisch aus der Startliste nachgeführt", tag="ok")
            self.on_data_changed()
        else:
            self.log("Kategoriebereiche: Automatik aus, Bereiche bleiben wie eingestellt", tag="warn")

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
        dlg.columnconfigure(0, weight=1)
        head = (f"Nr {nr} ist nicht in der Startliste. Bitte erfassen (oder leer schliessen):" if unknown
                else f"Teilnehmer Nr {nr}")
        tk.Label(dlg, text=head, bg=PANEL, fg=GOLD, font=self.f_side_head, anchor="w", justify="left",
                 wraplength=self.narrow_wrap()).grid(row=0, column=0, sticky="w", pady=(0, 8))
        labels = ("Vorname", "Nachname") if mode == "einzel" else ("Steuerfahrer", "Vorderfahrer")
        fields = {}
        clubs = sorted({x.get("verein") for x in self.participants.values() if x.get("verein")}, key=str.casefold)
        specs = [("p1", labels[0], "entry"), ("p2", labels[1], "entry"), ("verein", "Verein", "club"),
                 ("notiz", "Notiz für Speaker", "entry"), ("status", "Status", "status")]
        if nr in self.order_index:
            specs.append(("after", "Einfügen nach Nr", "entry"))
        status_opts = ["klassiert", "DNS nicht gestartet", "DNF ausgeschieden", "DSQ disqualifiziert"]
        for i, (key, label, kind) in enumerate(specs, start=1):
            tk.Label(dlg, text=label, bg=PANEL, fg=TEXT, font=self.f_side, anchor="w").grid(
                row=2 * i - 1, column=0, sticky="w", pady=(4, 0))
            if kind == "club":
                w = self._combo(dlg, clubs, width=10)
                w.set(p.get("verein", ""))
            elif kind == "status":
                w = self._combo(dlg, status_opts, width=10, state="readonly")
                code = self.status.get(nr)
                w.set(next((o for o in status_opts if code and o.startswith(code)), status_opts[0]))
            else:
                w = self._entry(dlg, width=10)
                if key == "after":
                    idx = self.order_index[nr]
                    w.insert(0, str(self.start_order[idx - 1]) if idx > 0 else "Anfang")
                else:
                    w.insert(0, str(p.get(key, "") or ""))
            w.grid(row=2 * i, column=0, sticky="ew", pady=(1, 0))
            fields[key] = w
        row_after = 2 * len(specs) + 1
        lbl_pos = tk.Label(dlg, text="", bg=PANEL, fg=MUTED, font=self.f_side, anchor="w", justify="left",
                           wraplength=self.narrow_wrap())
        if "after" in fields:
            lbl_pos.grid(row=row_after, column=0, sticky="w", pady=(2, 4))

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
            new_code = fields["status"].get().split()[0]
            new_code = None if new_code == "klassiert" else new_code
            if new_code != self.status.get(nr):
                self.set_status(nr, new_code)
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
        btns.grid(row=row_after + 1, column=0, sticky="ew", pady=(10, 0))
        self._button(btns, "Speichern", save, BLUE).pack(side="right")
        self._button(btns, "Später" if unknown else "Abbrechen", close).pack(side="right", padx=(0, 8))
        dlg.bind("<Return>", lambda e: save())
        dlg.bind("<Escape>", lambda e: close())
        dlg.protocol("WM_DELETE_WINDOW", close)
        self._place(dlg, narrow=True)
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
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)
        top = tk.Frame(win, bg=PANEL)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.columnconfigure(1, weight=1)
        tk.Label(top, text="Suche", bg=PANEL, fg=TEXT, font=self.f_side_bold).grid(row=0, column=0, padx=(0, 8))
        e_q = self._entry(top, width=10)
        e_q.grid(row=0, column=1, sticky="ew")
        tk.Label(top, text="Name, Verein oder Startnummer", bg=PANEL, fg=MUTED, font=self.f_side).grid(
            row=1, column=1, sticky="w")
        lbl_n = tk.Label(win, text="", bg=PANEL, fg=MUTED, font=self.f_side, anchor="w", justify="left",
                         wraplength=self.narrow_wrap())
        lbl_n.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 2))
        sc = self.ui_scale
        cols = [("mark", "", int(22 * sc)), ("nr", "Nr", int(44 * sc)), ("name", "Name", int(120 * sc)),
                ("verein", "Verein", int(90 * sc))]
        tree = ttk.Treeview(win, columns=[c[0] for c in cols], show="headings", style="Dark.Treeview",
                            selectmode="browse", height=11)
        for key, label, width in cols:
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w", stretch=key in ("name", "verein"))
        tree.grid(row=2, column=0, sticky="nsew")
        sb = tk.Scrollbar(win, orient="vertical", command=tree.yview)
        sb.grid(row=2, column=1, sticky="ns")
        tree.configure(yscrollcommand=sb.set)
        lbl_sel = tk.Label(win, text="Teilnehmer in der Liste anklicken", bg=PANEL, fg=GOLD, font=self.f_side_bold,
                           anchor="w", justify="left", wraplength=self.narrow_wrap())
        lbl_sel.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 2))
        txt = tk.Text(win, height=4, bg=INPUT_BG, fg=INPUT_FG, insertbackground=INPUT_FG, font=self.f_side,
                      relief="flat", wrap="word", highlightthickness=1, highlightbackground=BORDER,
                      highlightcolor=BLUE, state="disabled")
        txt.grid(row=4, column=0, columnspan=2, sticky="ew")
        lbl_ok = tk.Label(win, text="", bg=PANEL, fg=GREEN_TEXT, font=self.f_side, anchor="w")
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
                tree.insert("", "end", iid=str(nr), values=("✎" if p.get("notiz") else "", nr, display_name(p, mode),
                                                            p.get("verein", "")))
            if new_nr is not None:
                tree.insert("", "end", iid=f"new{new_nr}", values=("", new_nr, "neu anlegen", ""))
            total = len(hits)
            lbl_n.configure(text=f"{total} Treffer" + (" (höchstens 300 angezeigt)" if total >= 300 else ""))

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
            lbl_ok.configure(text=f"Gespeichert: {self.order_label(nr)}" if note else f"Notiz gelöscht: Nr {nr}", fg=GREEN_TEXT)
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
        tk.Label(win, text="Strg+Enter speichert", bg=PANEL, fg=MUTED, font=self.f_side, anchor="w").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))
        win.bind("<Escape>", close)
        win.protocol("WM_DELETE_WINDOW", close)
        fill()
        self._place(win, narrow=True)
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
            in_list = any(p.get("kategorie", "").casefold() == cat["name"].casefold()
                          for p in self.participants.values())
            if self.settings["cats_auto"] and in_list:
                self.settings["cats_auto"] = False
                self.save_settings()
                self.sw_cats_auto.set(False)
                self.log(f"Bereich von {cat['name']} von Hand geändert: automatische Bereiche aus der Startliste "
                         "ausgeschaltet", tag="warn")
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
        # v1.21: Sperrnummer 999 wird einmal auf 9999 umgestellt (999 kann eine Testnummer sein)
        if not settings.get("_mig_lock9999"):
            if settings["timing"].get("lock_nr") == 999:
                settings["timing"]["lock_nr"] = 9999
            settings["_mig_lock9999"] = True
        # v1.22: Praezision einmal auf 1/10 (Fehlerbericht 26.11.2026: aus alten Versionen stand noch 1/100)
        if not settings.get("_mig_prec10"):
            settings["timing"]["prec_digits"] = 1
            settings["_mig_prec10"] = True
        if settings["wettkampf"] not in ("einzel", "paar"):
            settings["wettkampf"] = "einzel"
        if not re.fullmatch(r"[A-Za-z0-9_\-]{16,}", settings["web"]["key"]):
            settings["web"]["key"] = secrets.token_urlsafe(18)
        return settings

    def save_settings(self):
        flat = dict(flatten_settings(self.settings))
        old = getattr(self, "_settings_flat", None)
        if old is not None:
            changed = [f"{k}={'***' if is_secret_key(k) else v!r}" for k, v in flat.items() if old.get(k) != v]
            if changed:
                DIAG.info("Einstellung: " + ", ".join(changed)[:2000])
        self._settings_flat = flat
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
        win.geometry(f"{int(980 * self.ui_fit)}x{int(520 * self.ui_fit)}")
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
        tree.tag_configure(ST_APPROVED, foreground=ACCENT)
        tree.tag_configure(ST_SENT, foreground=GREEN_TEXT)
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

    def set_web_url(self, text, fg=None):
        self._set(self.lbl_web_url, text=text, fg=fg or MUTED)

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
                         f"oder «QR-Code» weitergeben.", GREEN_TEXT)
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
        show = self.settings["show"]
        ticker = None
        if show.get("ticker"):
            ticker = [{"t": t, "text": text, "tag": tag if tag in ("warn", "ziel", "test") else ""}
                      for t, text, tag in list(self.ticker)[:15]]
        note = [t.strip() for t, _tag in self.note_segments() if t.strip()]  # leer ohne Schalter «Notizen»
        data = {"time": time.strftime("%H:%M:%S"), "live": live, "ziel": ziel, "cats": cats, "next": nxt,
                "ticker": ticker, "note": note, "theme": THEME}
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def build_api(self):
        """Daten fuer andere Programme (Anzeigetafel, Livestream): nur lesen, ohne Speaker-Notizen."""
        mode = self.settings["wettkampf"]
        enc = lambda d: json.dumps(d, ensure_ascii=False).encode("utf-8")  # noqa: E731

        def person(nr):
            p = self.participants.get(nr, {})
            cat = self.category_of(nr)
            return {"nr": nr, "name": display_name(p, mode), "verein": p.get("verein", ""),
                    "kategorie": cat["name"] if cat else "", "test": self.is_test(nr)}

        results = []
        for cat in self.categories:
            ranked = [dict(person(nr), rang=rank, zeit=self.disp_time(nr), sekunden=round(self.total_secs(nr), 3),
                           strafpunkte=self.penalty(nr)) for rank, nr, _t in self.ranking(cat)]
            nk = [dict(person(nr), status=code) for nr, code in sorted(self.status.items())
                  if (self.category_of(nr) or {}).get("name") == cat["name"]]
            results.append({"kategorie": cat["name"], "von": cat["min"], "bis": cat["max"], "rangliste": ranked,
                            "nicht_klassiert": nk})
        course = [dict(person(nr), start=fmt_tod(tod % 86400), laufzeit=self.running_text(tod),
                       naechstes_ziel=i == 0) for i, (tod, nr, _k) in enumerate(self.course)]
        live = {"laufend": person(self.current_nr) if self.current_nr else None, "zeit": self.live_time,
                "fertig": bool(self.live_final), "ziel": person(self.ziel_nr) if self.ziel_nr else None,
                "zielzeit": self.results[self.ziel_nr]["str"] if self.ziel_nr in self.results else None,
                "stand": time.strftime("%H:%M:%S"), "wettkampf": self.event_label()}
        events = [{"zeit": t[0], "text": t[1]} for t in self.ticker[:30]]
        start = [dict(person(nr), status=self.status.get(nr)) for nr in self.next_starters(count=200)]
        return {"live": enc(live), "results": enc(results), "course": enc(course), "events": enc(events),
                "startlist": enc(start)}

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
                self.web.publish(self.build_web_snapshot(), self.build_api())
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
        dlg.resizable(False, False)
        cat = self.category_of(nr)
        who = self.who_text(nr)
        head = f"Nr {nr}  ({cat['name'] if cat else 'ohne Kategorie'})" + (f"  {who}" if who else "")
        if self.is_test(nr):
            head = f"Nr {nr}  (Testnummer, erscheint nicht im Ranking)"
        tk.Label(dlg, text=head, bg=PANEL, fg=GOLD, font=self.f_side_head, justify="left", anchor="w",
                 wraplength=self.narrow_wrap()).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 12))
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
        self._place(dlg, narrow=True)
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
        data = self.autosave_data()
        try:
            tmp = os.path.join(self.data_path, AUTOSAVE_FILE + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.data_path, AUTOSAVE_FILE))
        except OSError as exc:
            self.log(f"Autosave fehlgeschlagen: {exc}", tag="error")

    def autosave_data(self):
        return {
            "version": 2,
            "results": {str(k): v for k, v in self.results.items()},
            "startlist": {"order": self.start_order, "source": self.startlist_source,
                          "participants": {str(k): v for k, v in self.participants.items()}},
            "status": {str(k): v for k, v in self.status.items()},
            "cp": {"run": self.cp_run, "last_start": self.last_start_nr,
                   "last_finish": list(self.last_finish_key) if self.last_finish_key else None,
                   "recs": [[list(k), {f: (list(v) if isinstance(v, tuple) else v) for f, v in r.items()}]
                            for k, r in self.cp_recs.items()]},
        }

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
                    "cp": v.get("cp") if isinstance(v.get("cp"), list) else None,
                }
            sl = data.get("startlist") or {}
            parts = {int(k): v for k, v in (sl.get("participants") or {}).items()}
            order = [int(n) for n in sl.get("order", [])]
            status = {int(k): v for k, v in (data.get("status") or {}).items() if v in ("DNS", "DNF", "DSQ")}
            cpd = data.get("cp") or {}
            recs = {}
            for k, r in cpd.get("recs", []):
                for f in ("start", "done", "cp_start", "twin"):
                    if isinstance(r.get(f), list):
                        r[f] = tuple(r[f])
                recs[tuple(k)] = r
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return
        if not results and not order:
            return
        text = f"{len(results)} Resultate" + (f" und eine Startliste mit {len(order)} Starts" if order else "")
        if messagebox.askyesno("Gespeicherte Sitzung", f"{text} aus der letzten Sitzung gefunden.\nWiederherstellen?",
                               default="yes"):
            self.results = results
            self.participants, self.start_order = parts, order
            self.startlist_source = str(sl.get("source", ""))
            self.status, self.cp_recs = status, recs
            self.cp_run = int(cpd.get("run") or 0)
            self.last_start_nr = cpd.get("last_start")
            self.last_finish_key = tuple(cpd["last_finish"]) if cpd.get("last_finish") else None
            self.course = self.compute_course()
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
        self.cp_recs.clear()
        self.status.clear()
        self.course, self.last_finish_key, self.finish_override = [], None, None
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
        if self.cp is not None:
            self.cp.stop()
            self.cp.join(1.5)
        self.stop_backup()
        if self.sim is not None:
            self.sim.close()
        self.web.stop()
        self.save_autosave()
        self.save_settings()
        if self.settings["net_restore"].get("pending") and IS_WINDOWS:
            # Netzwerkkarte zurueck auf automatische Adresse (Windows fragt nach Berechtigung)
            try:
                self.root.withdraw()
            except tk.TclError:
                pass
            ok, msg = set_dhcp(self.settings["net_restore"]["adapter"])
            if ok:
                self.settings["net_restore"] = {"pending": False, "adapter": ""}
                self.save_settings()
        u = self.settings["updates"]
        if u.get("install_on_exit") and not getattr(self, "_setup_started", False) \
                and self.update_ready_for(u.get("ready_tag")):
            self.start_setup(u["ready_path"])  # vom Benutzer gewaehlt: beim Beenden installieren
        self.root.destroy()


def main():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            # eigene App-Kennung: die Taskleiste zeigt dann das SWV-Symbol statt dem von Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SWV.LiveRanking")
        except Exception:
            pass
    root = tk.Tk()
    LiveRankingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
