#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SWV Live-Ranking
TAG Heuer Chronoprinter CP 545, Anzeigetafel-Protokoll HL970 / HL980

Abhaengigkeiten : Python 3.9+, pyserial   (pip install pyserial)
Start           : python swv_live_ranking.py
Build (.exe)    : build.bat  (PyInstaller --onefile --windowed)

Protokoll (ASCII, STX ... LF):
  \x0223  Nr  22\n     Startnummer
  \x0213 4:32   \n     Laufzeit (ganze Sekunden)  -> nur Live-Anzeige
  \x0213 4:33.00\n     Zielzeit (mit Dezimalpunkt) -> Ranking
  \x0243  Rk  21\n     Rang des CP 545            -> ignoriert
"""

import csv
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # App startet trotzdem, Verbinden meldet dann einen Fehler
    serial = None

# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #
APP_TITLE = "SWV Live-Ranking  |  TAG Heuer CP 545"
DEFAULT_BAUD = 9600
TOP_N = 5
BLINK_SECONDS = 30
BLINK_INTERVAL_MS = 450
POLL_INTERVAL_MS = 30
LOG_MAX_LINES = 300

BG = "#0f172a"
PANEL = "#1e293b"
BORDER = "#334155"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
BLUE = "#2563eb"
GREEN = "#10b981"
GOLD = "#facc15"
WHITE = "#ffffff"
RED = "#ef4444"
INPUT_BG = "#f8fafc"
INPUT_FG = "#0f172a"

DEFAULT_CATEGORIES = [
    {"name": "AKTIVE", "min": 1, "max": 199},
    {"name": "SENIOREN", "min": 300, "max": 399},
    {"name": "VETERANEN", "min": 400, "max": 499},
    {"name": "FRAUEN", "min": 500, "max": 599},
    {"name": "JUNIOREN", "min": 600, "max": 699},
    {"name": "JUNGFAHRER", "min": 700, "max": 799},
    {"name": "SCHÜLER", "min": 800, "max": 899},
]

CATEGORIES_FILE = "swv_kategorien.json"
AUTOSAVE_FILE = "swv_resultate_autosave.json"
ICON_FILES = ("swv_logo.png", "logo.png", "image_928d28.png")


# --------------------------------------------------------------------------- #
# Pfade (funktioniert als Skript und als PyInstaller-.exe)
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


# --------------------------------------------------------------------------- #
# Protokoll
# --------------------------------------------------------------------------- #
_TIME_CHARS = re.compile(r"^[0-9:.]+$")


def parse_time(text):
    """'4:33.00' -> 273.0 | '14.20' -> 14.2 | '1:02:03.4' -> 3723.4 | ungueltig -> None"""
    t = text.strip().replace(",", ".")
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
    """
    Liefert:
      ("nr", 22)
      ("running", "4:32", 272.0)
      ("final", "4:33.00", 273.0)
      None  (Rang 43, unbekannt, defekt)
    """
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
    return None  # "43" (Rang) und alles andere wird ignoriert


def format_manual_time(minutes, seconds, tenths):
    if minutes > 0:
        return f"{minutes}:{seconds:02d}.{tenths}"
    return f"{seconds}.{tenths}"


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
            self.q.put(("error", f"Port {self.port} konnte nicht geöffnet werden: {exc}"))
            return

        self.q.put(("connected", self.port))
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
                    self.q.put(("line", frame.decode("latin-1", errors="replace")))
                if len(buf) > 4096:
                    buf.clear()
        except Exception as exc:
            if not self.stop_event.is_set():
                self.q.put(("error", f"Verbindung unterbrochen: {exc}"))
        finally:
            try:
                ser.close()
            except Exception:
                pass
            self.q.put(("disconnected", self.port))


# --------------------------------------------------------------------------- #
# Anwendung
# --------------------------------------------------------------------------- #
class LiveRankingApp:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.reader = None
        self.data_path = data_dir()

        self.categories = self.load_categories()
        self.results = {}          # nr -> {"secs": float, "str": str, "ts": float}
        self.current_nr = None
        self.live_time = None
        self.blink = {}            # nr -> Endzeitpunkt Blinken
        self.blink_phase = False
        self.prev_top = {}         # Kategorie-Name -> Set Startnummern in Top 5
        self.cards = []
        self.port_map = {}
        self._scale_job = None

        self.setup_window()
        self.setup_fonts()
        self.setup_styles()
        self.build_ui()
        self.refresh_ports()
        self.build_cards()
        self.load_autosave()

        self.root.after(POLL_INTERVAL_MS, self.poll_queue)
        self.root.after(BLINK_INTERVAL_MS, self.blink_tick)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- Fenster / Stil ---------------- #
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
        fam = "Segoe UI" if sys.platform.startswith("win") else "DejaVu Sans"
        self.f_status = tkfont.Font(family=fam, size=-28, weight="bold")
        self.f_title = tkfont.Font(family=fam, size=-22, weight="bold")
        self.f_row = tkfont.Font(family=fam, size=-28, weight="bold")
        self.f_first = tkfont.Font(family=fam, size=-36, weight="bold")
        self.f_side = tkfont.Font(family=fam, size=10)
        self.f_side_bold = tkfont.Font(family=fam, size=10, weight="bold")
        self.f_side_head = tkfont.Font(family=fam, size=11, weight="bold")
        self.f_log = tkfont.Font(family="Consolas" if sys.platform.startswith("win") else "DejaVu Sans Mono", size=9)
        self.f_dialog = tkfont.Font(family=fam, size=-40, weight="bold")

    def setup_styles(self):
        self.root.option_add("*TCombobox*Listbox.background", INPUT_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", INPUT_FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", BLUE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", WHITE)
        self.root.option_add("*TCombobox*Listbox.font", self.f_side)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Port.TCombobox", fieldbackground=INPUT_BG, background="#e2e8f0",
                        foreground=INPUT_FG, arrowcolor=INPUT_FG, padding=4)
        style.map("Port.TCombobox",
                  fieldbackground=[("readonly", INPUT_BG), ("!disabled", INPUT_BG)],
                  foreground=[("readonly", INPUT_FG), ("!disabled", INPUT_FG)],
                  selectbackground=[("!disabled", BLUE)],
                  selectforeground=[("!disabled", WHITE)])

    # ---------------- Widgets-Helfer ---------------- #
    def _button(self, parent, text, cmd, color=BORDER):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg=WHITE,
                         activebackground=BLUE, activeforeground=WHITE, relief="flat",
                         bd=0, padx=10, pady=5, font=self.f_side_bold, cursor="hand2")

    def _entry(self, parent, width=10, **kw):
        return tk.Entry(parent, width=width, bg=INPUT_BG, fg=INPUT_FG, insertbackground=INPUT_FG,
                        relief="flat", font=self.f_side, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=BLUE, **kw)

    def _label(self, parent, text, bold=False, fg=TEXT):
        return tk.Label(parent, text=text, bg=PANEL, fg=fg,
                        font=self.f_side_bold if bold else self.f_side, anchor="w")

    def _section(self, parent, title):
        frm = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        frm.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(frm, text=title, bg=PANEL, fg=GOLD, font=self.f_side_head,
                 anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        body = tk.Frame(frm, bg=PANEL)
        body.pack(fill="x", padx=10, pady=(0, 10))
        return body

    @staticmethod
    def _set(widget, **kw):
        changed = {k: v for k, v in kw.items() if str(widget.cget(k)) != str(v)}
        if changed:
            widget.configure(**changed)

    # ---------------- Aufbau UI ---------------- #
    def build_ui(self):
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Seitenleiste (scrollbar, falls der Bildschirm zu niedrig ist)
        outer = tk.Frame(self.root, bg=BG, width=358)
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
            if w is None or not str(w).startswith(str(outer)) or isinstance(w, (tk.Listbox, tk.Text)):
                return
            if not sbar.winfo_ismapped():
                return
            if event.num == 4:
                step = -1
            elif event.num == 5:
                step = 1
            else:
                step = -1 if event.delta > 0 else 1
            canvas.yview_scroll(step * 3, "units")

        self.root.bind_all("<MouseWheel>", on_wheel, add="+")
        self.root.bind_all("<Button-4>", on_wheel, add="+")
        self.root.bind_all("<Button-5>", on_wheel, add="+")
        self.build_sidebar(side)

        # Hauptbereich
        main = tk.Frame(self.root, bg=BG)
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=10)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=0)
        main.rowconfigure(1, weight=1)
        self.main = main

        status = tk.Frame(main, bg=BG)
        status.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        status.columnconfigure(0, weight=1, uniform="status")
        status.columnconfigure(1, weight=1, uniform="status")
        self.lbl_live = tk.Label(status, text="LAUFEND: -", bg=BLUE, fg=WHITE, font=self.f_status,
                                 anchor="w", padx=16, pady=10, width=1)
        self.lbl_live.grid(row=0, column=0, sticky="ew", padx=(6, 3))
        self.lbl_ziel = tk.Label(status, text="ZIEL: -", bg=GREEN, fg=WHITE, font=self.f_status,
                                 anchor="w", padx=16, pady=10, width=1)
        self.lbl_ziel.grid(row=0, column=1, sticky="ew", padx=(3, 6))

        self.cards_area = tk.Frame(main, bg=BG)
        self.cards_area.grid(row=1, column=0, sticky="nsew")
        self.cards_area.bind("<Configure>", lambda e: self.schedule_font_scale())

    def build_sidebar(self, side):
        tk.Label(side, text="SWV Live-Ranking", bg=BG, fg=TEXT, font=self.f_side_head,
                 anchor="w").pack(fill="x", padx=12, pady=(12, 0))

        # 1. Verbindung
        b = self._section(side, "Verbindung")
        b.columnconfigure(0, weight=1)
        self._label(b, "COM-Port").grid(row=0, column=0, columnspan=2, sticky="w")
        self.cmb_port = ttk.Combobox(b, style="Port.TCombobox", font=self.f_side)
        self.cmb_port.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self._button(b, "⟳", self.refresh_ports).grid(row=1, column=1, sticky="e", padx=(6, 0), pady=(2, 6))
        self._label(b, "Baudrate").grid(row=2, column=0, columnspan=2, sticky="w")
        self.e_baud = self._entry(b, width=10)
        self.e_baud.insert(0, str(DEFAULT_BAUD))
        self.e_baud.grid(row=3, column=0, sticky="w", pady=(2, 6))
        self._label(b, "8N1", fg=MUTED).grid(row=3, column=1, sticky="e")
        self.btn_connect = self._button(b, "Verbinden", self.toggle_connection, GREEN)
        self.btn_connect.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.lbl_conn = self._label(b, "Nicht verbunden", fg=MUTED)
        self.lbl_conn.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # 2. Kategorien
        b = self._section(side, "Kategorien & Nummern-Range")
        b.columnconfigure(0, weight=1)
        b.columnconfigure(1, weight=1)
        b.columnconfigure(2, weight=1)
        self.lst_cat = tk.Listbox(b, height=7, bg=BG, fg=TEXT, selectbackground=BLUE,
                                  selectforeground=WHITE, relief="flat", font=self.f_side,
                                  highlightthickness=1, highlightbackground=BORDER,
                                  exportselection=False, activestyle="none")
        self.lst_cat.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.lst_cat.bind("<<ListboxSelect>>", self.on_category_select)
        self._label(b, "Name").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._label(b, "Von").grid(row=1, column=1, sticky="w", pady=(6, 0))
        self._label(b, "Bis").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.e_cat_name = self._entry(b, width=12)
        self.e_cat_name.grid(row=2, column=0, sticky="ew", padx=(0, 4))
        self.e_cat_min = self._entry(b, width=5)
        self.e_cat_min.grid(row=2, column=1, sticky="ew", padx=(0, 4))
        self.e_cat_max = self._entry(b, width=5)
        self.e_cat_max.grid(row=2, column=2, sticky="ew")
        self._button(b, "Übernehmen", self.category_update).grid(row=3, column=0, sticky="ew", pady=(6, 0), padx=(0, 4))
        self._button(b, "Hinzufügen", self.category_add).grid(row=3, column=1, sticky="ew", pady=(6, 0), padx=(0, 4))
        self._button(b, "Löschen", self.category_delete, "#7f1d1d").grid(row=3, column=2, sticky="ew", pady=(6, 0))
        self.refresh_category_list()

        # 3. Manuelle Zeiterfassung
        b = self._section(side, "Manuelle Zeiterfassung")
        b.columnconfigure(1, weight=1)
        self._label(b, "Startnummer").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.e_manual_nr = self._entry(b, width=8)
        self.e_manual_nr.grid(row=0, column=1, sticky="ew")
        self.e_manual_nr.bind("<Return>", lambda e: self.open_manual_dialog())
        self._button(b, "Zeit manuell erfassen", self.open_manual_dialog, BLUE).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # 4. Export
        b = self._section(side, "Daten")
        b.columnconfigure(0, weight=1)
        self._button(b, "Resultate als CSV exportieren", self.export_csv, GREEN).grid(row=0, column=0, sticky="ew")
        self._button(b, "Resultate zurücksetzen", self.reset_results, "#7f1d1d").grid(
            row=1, column=0, sticky="ew", pady=(6, 0))
        self.lbl_count = self._label(b, "0 Resultate erfasst", fg=MUTED)
        self.lbl_count.grid(row=2, column=0, sticky="w", pady=(4, 0))

        # Protokoll-Log
        frm = tk.Frame(side, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        frm.pack(fill="x", padx=10, pady=10)
        tk.Label(frm, text="Empfangene Daten", bg=PANEL, fg=GOLD, font=self.f_side_head,
                 anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        tabs = tk.Frame(frm, bg=PANEL)
        tabs.pack(fill="x", padx=10, pady=(0, 4))
        holder = tk.Frame(frm, bg=PANEL)
        holder.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.log_tabs = {}
        for key, label in (("focus", "Fokussiert"), ("all", "Alle")):
            btn = tk.Button(tabs, text=label, command=lambda k=key: self.show_log_tab(k), fg=WHITE,
                            activebackground=BLUE, activeforeground=WHITE, relief="flat", bd=0,
                            padx=12, pady=3, font=self.f_side_bold, cursor="hand2")
            btn.pack(side="left", padx=(0, 4))
            txt = tk.Text(holder, height=10, bg="#020617", fg=MUTED, font=self.f_log, relief="flat",
                          state="disabled", wrap="word" if key == "focus" else "none",
                          highlightthickness=0)
            txt.grid(row=0, column=0, sticky="nsew")
            txt.tag_configure("ziel", foreground=GREEN)
            txt.tag_configure("warn", foreground=GOLD)
            txt.tag_configure("error", foreground=RED)
            txt.tag_configure("ok", foreground="#38bdf8")
            self.log_tabs[key] = (btn, txt)
        self.show_log_tab("focus")

    def show_log_tab(self, key):
        for k, (btn, _txt) in self.log_tabs.items():
            btn.configure(bg=BLUE if k == key else BORDER)
        txt = self.log_tabs[key][1]
        txt.tkraise()
        txt.see("end")

    # ---------------- Kategorie-Karten ---------------- #
    def build_cards(self):
        """Nur bei Kategorie-Änderungen aufrufen. Daten-Updates laufen über update_rankings()."""
        for card in self.cards:
            card["frame"].destroy()
        self.cards = []
        for r in range(12):
            self.cards_area.rowconfigure(r, weight=0, uniform="")
        rows = max(1, -(-len(self.categories) // 3))
        for r in range(rows):
            self.cards_area.rowconfigure(r, weight=1, uniform="row")
        for c in range(3):
            self.cards_area.columnconfigure(c, weight=1, uniform="col")

        for i, cat in enumerate(self.categories):
            f = tk.Frame(self.cards_area, bg=PANEL, highlightthickness=2, highlightbackground=BORDER)
            f.grid(row=i // 3, column=i % 3, sticky="nsew", padx=6, pady=6)
            f.grid_propagate(False)
            f.columnconfigure(0, weight=0)
            f.columnconfigure(1, weight=0)
            f.columnconfigure(2, weight=1)
            title = tk.Label(f, text=f"{cat['name']}   {cat['min']}-{cat['max']}", font=self.f_title,
                             bg=PANEL, fg=MUTED, anchor="w")
            title.grid(row=0, column=0, columnspan=3, sticky="ew", padx=14, pady=(8, 2))
            rows_w = []
            for k in range(TOP_N):
                font = self.f_first if k == 0 else self.f_row
                l_txt = tk.Label(f, text="", font=font, bg=PANEL, fg=WHITE, anchor="w")
                l_arr = tk.Label(f, text="", font=font, bg=PANEL, fg=WHITE)
                l_time = tk.Label(f, text="", font=font, bg=PANEL, fg=WHITE, anchor="w")
                l_txt.grid(row=k + 1, column=0, sticky="w", padx=(14, 4))
                l_arr.grid(row=k + 1, column=1, padx=6)
                l_time.grid(row=k + 1, column=2, sticky="w", padx=(4, 14))
                f.rowconfigure(k + 1, weight=1)
                rows_w.append({"txt": l_txt, "arrow": l_arr, "time": l_time,
                               "nr": None, "rank": None, "color": WHITE})
            self.cards.append({"cat": cat, "frame": f, "title": title, "rows": rows_w})

        self.prev_top = {}
        self.update_rankings(initial=True)
        self.schedule_font_scale()

    def schedule_font_scale(self):
        if self._scale_job is not None:
            self.root.after_cancel(self._scale_job)
        self._scale_job = self.root.after(80, self.apply_font_scale)

    def apply_font_scale(self):
        self._scale_job = None
        w = self.cards_area.winfo_width()
        h = self.cards_area.winfo_height()
        if w < 50 or h < 50:
            return
        rows = max(1, -(-len(self.categories) // 3))
        card_w = w / 3 - 16
        card_h = h / rows - 16
        px = int(min(card_h / 8.6, card_w / 17.5))
        px = max(12, min(px, 110))
        self.f_row.configure(size=-px)
        self.f_first.configure(size=-int(px * 1.25))
        self.f_title.configure(size=-max(11, int(px * 0.75)))
        self.f_status.configure(size=-max(14, min(56, int(min(self.main.winfo_width() / 45,
                                                             self.main.winfo_height() / 20)))))
        col0 = self.f_first.measure("5. Nr. 888")
        for card in self.cards:
            card["frame"].columnconfigure(0, minsize=col0)

    # ---------------- Ranking ---------------- #
    def category_of(self, nr):
        for cat in self.categories:
            if cat["min"] <= nr <= cat["max"]:
                return cat
        return None

    def ranking(self, cat):
        entries = sorted((r["secs"], nr) for nr, r in self.results.items() if self.category_of(nr) is cat)
        ranked, prev, rank = [], None, 0
        for i, (secs, nr) in enumerate(entries):
            if secs != prev:
                rank, prev = i + 1, secs
            ranked.append((rank, nr, secs))
        return ranked

    def _arrow_color(self, row, now):
        until = self.blink.get(row["nr"])
        if until and now < until:
            return RED if self.blink_phase else row["color"]
        return row["color"]

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
                if k < len(ranked):
                    rank, nr, _ = ranked[k]
                    color = GOLD if rank == 1 else WHITE
                    font = self.f_first if rank == 1 else self.f_row
                    txt, arrow, tstr = f"{rank}. Nr. {nr}", "➔", f"{self.results[nr]['str']}s"
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

        n = len(self.results)
        self._set(self.lbl_count, text=f"{n} Resultat{'e' if n != 1 else ''} erfasst")

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

    def register_final(self, nr, secs, tstr, source="CP 545"):
        self.results[nr] = {"secs": secs, "str": tstr, "ts": time.time()}
        cat = self.category_of(nr)
        cat_name = cat["name"] if cat else "ohne Kategorie"
        self._set(self.lbl_ziel, text=f"ZIEL: Nr {nr} ({cat_name}) ➔ {tstr}s")
        self.log(f"ZIEL Nr {nr} ({cat_name}) {tstr}s [{source}]", tag="ziel")
        self.update_rankings()
        self.save_autosave()

    # ---------------- Serielle Daten ---------------- #
    def poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "line":
                    self.handle_line(payload)
                elif kind == "connected":
                    self.set_connected(True, f"Verbunden: {payload}")
                    self.log(f"Verbunden mit {payload}", tag="ok")
                elif kind == "disconnected":
                    self.set_connected(False, "Nicht verbunden")
                    self.reader = None
                    self.log(f"Verbindung zu {payload} getrennt", tag="warn")
                elif kind == "error":
                    self.set_connected(False, "Fehler")
                    self.reader = None
                    self.log(payload, tag="error")
                    messagebox.showerror("Verbindung", payload)
        except queue.Empty:
            pass
        self.root.after(POLL_INTERVAL_MS, self.poll_queue)

    def update_live_label(self):
        nr_txt = self.current_nr if self.current_nr is not None else "-"
        self._set(self.lbl_live, text=f"LAUFEND: Nr {nr_txt} ➔ {self.live_time or '-'}")

    def handle_line(self, text):
        self.log("<STX>" + text.replace("\r", "<CR>"), focus=False)
        msg = parse_message(text)
        if msg is None:
            return
        if msg[0] == "nr":
            # Der CP 545 wiederholt die Startnummer nach jeder Zeit: Zeit nur bei neuer Nummer zuruecksetzen
            if msg[1] != self.current_nr:
                self.current_nr = msg[1]
                self.live_time = None
            self.update_live_label()
        elif msg[0] in ("running", "final"):
            _, tstr, secs = msg
            self.live_time = tstr
            self.update_live_label()
            if msg[0] == "final":
                if self.current_nr is None:
                    self.log("Zielzeit ohne aktive Startnummer verworfen", tag="warn")
                    return
                prev = self.results.get(self.current_nr)
                if prev and prev["str"] == tstr and time.time() - prev["ts"] < 10:
                    return  # Wiederholung derselben Zielmeldung
                self.register_final(self.current_nr, secs, tstr)

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
        elif not values and not self.cmb_port.get():
            self.cmb_port.set("")

    def toggle_connection(self):
        if self.reader is not None and self.reader.is_alive():
            self.reader.stop()
            self.lbl_conn.configure(text="Trenne ...")
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
        self.reader = SerialReader(port, baud, self.q)
        self.reader.start()
        self.lbl_conn.configure(text=f"Verbinde mit {port} ...")

    def set_connected(self, connected, text):
        self.lbl_conn.configure(text=text, fg=GREEN if connected else MUTED)
        self.btn_connect.configure(text="Trennen" if connected else "Verbinden",
                                   bg="#7f1d1d" if connected else GREEN)

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

    # ---------------- Kategorien ---------------- #
    def refresh_category_list(self):
        self.lst_cat.delete(0, "end")
        for cat in self.categories:
            self.lst_cat.insert("end", f"{cat['name']}  ({cat['min']}-{cat['max']})")

    def on_category_select(self, _event=None):
        sel = self.lst_cat.curselection()
        if not sel:
            return
        cat = self.categories[sel[0]]
        for entry, value in ((self.e_cat_name, cat["name"]), (self.e_cat_min, cat["min"]),
                             (self.e_cat_max, cat["max"])):
            entry.delete(0, "end")
            entry.insert(0, str(value))

    def read_category_fields(self, ignore_index=None):
        name = self.e_cat_name.get().strip()
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
        return {"name": name, "min": lo, "max": hi}

    def category_update(self):
        sel = self.lst_cat.curselection()
        if not sel:
            messagebox.showinfo("Kategorie", "Zuerst eine Kategorie in der Liste anklicken.")
            return
        cat = self.read_category_fields(ignore_index=sel[0])
        if cat:
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
        if messagebox.askyesno("Kategorie", f"Kategorie '{cat['name']}' löschen?"):
            del self.categories[sel[0]]
            self.categories_changed()

    def categories_changed(self, select=None):
        self.save_categories()
        self.log("Kategorien geändert: " + ", ".join(f"{c['name']} {c['min']}-{c['max']}" for c in self.categories))
        self.refresh_category_list()
        if select is not None:
            self.lst_cat.selection_set(select)
            self.lst_cat.see(select)
        self.build_cards()

    def load_categories(self):
        path = os.path.join(self.data_path, CATEGORIES_FILE)
        try:
            with open(path, encoding="utf-8") as fh:
                cats = json.load(fh)
            cats = [{"name": str(c["name"]), "min": int(c["min"]), "max": int(c["max"])} for c in cats]
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
            self.log(f"Kategorien nicht gespeichert: {exc}")

    # ---------------- Manuelle Zeiterfassung ---------------- #
    def open_manual_dialog(self):
        try:
            nr = int(self.e_manual_nr.get().strip())
        except ValueError:
            messagebox.showwarning("Manuelle Zeit", "Gültige Startnummer eingeben.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Zeit manuell erfassen - Nr {nr}")
        dlg.configure(bg=PANEL, padx=24, pady=20)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        if self.icon_img is not None:
            dlg.iconphoto(False, self.icon_img)

        cat = self.category_of(nr)
        tk.Label(dlg, text=f"Nr {nr}  ({cat['name'] if cat else 'ohne Kategorie'})", bg=PANEL, fg=GOLD,
                 font=self.f_side_head).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 12))
        for col, text in ((0, "Min"), (2, "Sek"), (4, "1/10")):
            tk.Label(dlg, text=text, bg=PANEL, fg=MUTED, font=self.f_side).grid(row=1, column=col)

        def make_vcmd(maxlen):
            return (dlg.register(lambda p: p == "" or (p.isdigit() and len(p) <= maxlen)), "%P")

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
            secs = m * 60 + s + z / 10
            if nr in self.results and not messagebox.askyesno(
                    "Manuelle Zeit", f"Nr {nr} hat bereits {self.results[nr]['str']}s. Überschreiben?", parent=dlg):
                return
            self.register_final(nr, secs, format_manual_time(m, s, z), source="manuell")
            dlg.destroy()
            self.e_manual_nr.delete(0, "end")
            self.e_manual_nr.focus_set()

        btns = tk.Frame(dlg, bg=PANEL)
        btns.grid(row=3, column=0, columnspan=5, sticky="ew", pady=(16, 0))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        self._button(btns, "Speichern", save, GREEN).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._button(btns, "Abbrechen", dlg.destroy).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        dlg.bind("<Return>", lambda e: save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        dlg.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dlg.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dlg.winfo_height()) // 3
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        dlg.grab_set()
        fields[0][0].focus_set()

    # ---------------- Export / Persistenz ---------------- #
    def export_rows(self):
        rows = []
        for cat in self.categories:
            for rank, nr, secs in self.ranking(cat):
                rows.append([cat["name"], rank, nr, self.results[nr]["str"], f"{secs:.2f}"])
        for nr in sorted(n for n in self.results if self.category_of(n) is None):
            r = self.results[nr]
            rows.append(["OHNE KATEGORIE", "", nr, r["str"], f"{r['secs']:.2f}"])
        return rows

    def export_csv(self):
        if not self.results:
            messagebox.showinfo("Export", "Noch keine Resultate vorhanden.")
            return
        path = filedialog.asksaveasfilename(
            title="Resultate exportieren", defaultextension=".csv",
            filetypes=[("CSV (Excel)", "*.csv")],
            initialfile=f"SWV_Resultate_{time.strftime('%Y-%m-%d_%H%M')}.csv")
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
        self.log(f"Export: {path}")
        messagebox.showinfo("Export", f"{len(self.results)} Resultate exportiert:\n{path}")

    def save_autosave(self):
        try:
            tmp = os.path.join(self.data_path, AUTOSAVE_FILE + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({str(k): v for k, v in self.results.items()}, fh)
            os.replace(tmp, os.path.join(self.data_path, AUTOSAVE_FILE))
        except OSError as exc:
            self.log(f"Autosave fehlgeschlagen: {exc}")

    def load_autosave(self):
        path = os.path.join(self.data_path, AUTOSAVE_FILE)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            results = {int(k): {"secs": float(v["secs"]), "str": str(v["str"]), "ts": float(v.get("ts", 0))}
                       for k, v in data.items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return
        if results and messagebox.askyesno(
                "Gespeicherte Resultate",
                f"{len(results)} Resultate aus der letzten Sitzung gefunden.\nWiederherstellen?"):
            self.results = results
            self.update_rankings(initial=True)
            self.log(f"{len(results)} Resultate wiederhergestellt")
        elif results:
            self.save_autosave()

    def reset_results(self):
        if not self.results:
            return
        if not messagebox.askyesno("Zurücksetzen",
                                   f"Alle {len(self.results)} Resultate löschen?\nVorher exportieren!"):
            return
        self.results.clear()
        self.blink.clear()
        self.current_nr = None
        self.live_time = None
        self._set(self.lbl_ziel, text="ZIEL: -")
        self._set(self.lbl_live, text="LAUFEND: -")
        self.update_rankings(initial=True)
        self.save_autosave()
        self.log("Resultate zurückgesetzt")

    def on_close(self):
        if self.reader is not None:
            self.reader.stop()
        self.save_autosave()
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
