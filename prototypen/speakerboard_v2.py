import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import serial
import serial.tools.list_ports
import threading
import time
import re
import csv
import os

class CP545Board:
    def __init__(self, root):
        self.root = root
        self.root.title("Schweizer Wasserfahrverband - CP 545 Live Ranking")
        
        self.root.state('zoomed')
        self.root.configure(bg="#0f172a")

        self.set_app_icon()

        # Kategorien-Speicher
        self.categories = {
            "AKTIVE": (1, 199),
            "SENIOREN": (300, 399),
            "VETERANEN": (400, 499),
            "FRAUEN": (500, 599),
            "JUNIOREN": (600, 699),
            "JUNGFAHRER": (700, 799),
            "SCHÜLER": (800, 899)
        }
        
        # Ergebnisse
        self.results = {cat: [] for cat in self.categories}
        
        # Blinken
        self.blinking_items = {}
        self.blink_state = False

        # Widget-Referenzen
        self.card_widgets = {}

        self.is_running = False
        self.ser = None

        self.active_stnr = None
        self.active_time_str = None

        self.apply_dark_styles()
        self.setup_ui()
        self.refresh_ports()

        # Blink-Timer
        self.root.after(500, self.update_blinking_effect)

    def set_app_icon(self):
        # Versucht spezifisch das hochgeladene Logo einzubinden
        icon_candidates = ["image_928d28.png", "swv_logo.png", "logo.png"]
        for icon_file in icon_candidates:
            if os.path.exists(icon_file):
                try:
                    img = tk.PhotoImage(file=icon_file)
                    self.root.iconphoto(True, img)
                    break
                except Exception:
                    pass

    def apply_dark_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        bg_dark = "#0f172a"
        bg_card = "#1e293b"
        fg_white = "#ffffff"

        style.configure(".", background=bg_dark, foreground=fg_white)
        style.configure("TFrame", background=bg_dark)
        style.configure("TLabelframe", background=bg_card, foreground=fg_white, bordercolor="#334155", relief="solid")
        style.configure("TLabelframe.Label", background=bg_card, foreground="#38bdf8", font=("Arial", 12, "bold"))
        
        style.configure("TLabel", background=bg_dark, foreground=fg_white)
        
        style.configure("TButton", background="#2563eb", foreground="white", font=("Arial", 10, "bold"), borderwidth=0)
        style.map("TButton", background=[("active", "#1d4ed8")])
        
        style.configure("Manual.TButton", background="#eab308", foreground="black", font=("Arial", 10, "bold"))
        style.map("Manual.TButton", background=[("active", "#ca8a04")])

        style.configure("Export.TButton", background="#10b981", foreground="white", font=("Arial", 10, "bold"))
        style.map("Export.TButton", background=[("active", "#059669")])

        # Combobox Lesbarkeit im Dropdown verbessern
        style.configure("TCombobox", fieldbackground="#334155", background="#334155", foreground="white")
        self.root.option_add('*TCombobox*Listbox.background', '#ffffff')
        self.root.option_add('*TCombobox*Listbox.foreground', '#000000')
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#2563eb')
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')

        style.configure("TEntry", fieldbackground="#334155", foreground="white")

    def setup_ui(self):
        main_container = ttk.Frame(self.root, padding="10")
        main_container.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_container, width=300)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        right_frame = ttk.Frame(main_container)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Geteilter oberer Balken (Laufende Zeit Links / Ziel Rechts)
        top_banner_frame = tk.Frame(right_frame, bg="#0f172a")
        top_banner_frame.pack(fill=tk.X, pady=(0, 10))

        # Links (Blau) - Laufende Zeit
        self.banner_left = tk.Label(
            top_banner_frame, 
            text="LAUFEND: --", 
            font=("Arial", 18, "bold"), 
            bg="#2563eb", 
            fg="white", 
            height=2
        )
        self.banner_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        # Rechts (Grün) - Letztes Ziel
        self.banner_right = tk.Label(
            top_banner_frame, 
            text="ZIEL: Noch kein Einlauf", 
            font=("Arial", 18, "bold"), 
            bg="#10b981", 
            fg="white", 
            height=2
        )
        self.banner_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        # 1. Verbindung
        conn_group = ttk.LabelFrame(left_frame, text="1. Verbindung (CP 545)", padding="10")
        conn_group.pack(fill=tk.X, pady=5)

        ttk.Label(conn_group, text="Port:").grid(row=0, column=0, sticky=tk.W)
        self.port_cb = ttk.Combobox(conn_group, width=10, state="readonly")
        self.port_cb.grid(row=0, column=1, padx=5, pady=2)
        ttk.Button(conn_group, text="🔄", width=3, command=self.refresh_ports).grid(row=0, column=2)

        ttk.Label(conn_group, text="Baud:").grid(row=1, column=0, sticky=tk.W)
        self.baud_entry = ttk.Entry(conn_group, width=13)
        self.baud_entry.insert(0, "9600")
        self.baud_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=2)

        self.btn_connect = ttk.Button(conn_group, text="Verbinden", command=self.toggle_connection)
        self.btn_connect.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        # 2. Kategorien
        cat_group = ttk.LabelFrame(left_frame, text="2. Kategorien & Nummern-Range", padding="10")
        cat_group.pack(fill=tk.X, pady=8)

        self.cat_listbox = tk.Listbox(
            cat_group, 
            height=5, 
            bg="#1e293b", 
            fg="white", 
            selectbackground="#2563eb", 
            highlightthickness=0,
            font=("Arial", 9)
        )
        self.cat_listbox.pack(fill=tk.X, pady=(0, 5))
        self.cat_listbox.bind("<<ListboxSelect>>", self.on_cat_select)
        self.update_cat_listbox()

        ttk.Label(cat_group, text="Name:").pack(anchor=tk.W)
        self.entry_name = ttk.Entry(cat_group)
        self.entry_name.pack(fill=tk.X, pady=2)

        range_frame = ttk.Frame(cat_group)
        range_frame.pack(fill=tk.X, pady=4)
        
        ttk.Label(range_frame, text="Min:").pack(side=tk.LEFT)
        self.entry_min = ttk.Entry(range_frame, width=5)
        self.entry_min.pack(side=tk.LEFT, padx=3)

        ttk.Label(range_frame, text="Max:").pack(side=tk.LEFT)
        self.entry_max = ttk.Entry(range_frame, width=5)
        self.entry_max.pack(side=tk.LEFT, padx=3)

        ttk.Button(cat_group, text="Speichern / Anpassen", command=self.add_or_update_category).pack(fill=tk.X, pady=(5, 0))

        # 3. Manuelle Zeiterfassung
        manual_group = ttk.LabelFrame(left_frame, text="3. Manuelle Zeiterfassung", padding="10")
        manual_group.pack(fill=tk.X, pady=8)

        ttk.Label(manual_group, text="Startnummer:").pack(anchor=tk.W)
        self.manual_stnr_entry = ttk.Entry(manual_group)
        self.manual_stnr_entry.pack(fill=tk.X, pady=4)

        ttk.Button(manual_group, text="⏱ Zeit manuell erfassen", style="Manual.TButton", command=self.open_manual_time_dialog).pack(fill=tk.X)

        # 4. Export
        export_group = ttk.LabelFrame(left_frame, text="4. Daten-Export", padding="10")
        export_group.pack(fill=tk.X, pady=8)

        ttk.Button(export_group, text="📄 CSV / Excel exportieren", style="Export.TButton", command=self.export_to_csv).pack(fill=tk.X)

        # Grid für Karten
        self.cards_frame = ttk.Frame(right_frame)
        self.cards_frame.pack(fill=tk.BOTH, expand=True)
        
        for i in range(3):
            self.cards_frame.columnconfigure(i, weight=1)
        for i in range(3):
            self.cards_frame.rowconfigure(i, weight=1)

        self.init_category_cards()

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_cb['values'] = ports
        if ports:
            self.port_cb.current(0)

    def on_cat_select(self, event):
        selection = self.cat_listbox.curselection()
        if selection:
            cat_text = self.cat_listbox.get(selection[0])
            cat_name = cat_text.split(" (")[0]
            if cat_name in self.categories:
                mn, mx = self.categories[cat_name]
                self.entry_name.delete(0, tk.END)
                self.entry_name.insert(0, cat_name)
                self.entry_min.delete(0, tk.END)
                self.entry_min.insert(0, str(mn))
                self.entry_max.delete(0, tk.END)
                self.entry_max.insert(0, str(mx))

    def add_or_update_category(self):
        name = self.entry_name.get().strip().upper()
        try:
            min_st = int(self.entry_min.get())
            max_st = int(self.entry_max.get())
            if not name or min_st > max_st:
                raise ValueError
            
            self.categories[name] = (min_st, max_st)
            if name not in self.results:
                self.results[name] = []
                
            self.update_cat_listbox()
            self.init_category_cards()
            self.entry_name.delete(0, tk.END)
            self.entry_min.delete(0, tk.END)
            self.entry_max.delete(0, tk.END)
        except ValueError:
            messagebox.showerror("Fehler", "Bitte gültigen Namen und Nummern eingeben.")

    def update_cat_listbox(self):
        self.cat_listbox.delete(0, tk.END)
        for cat, (mn, mx) in self.categories.items():
            self.cat_listbox.insert(tk.END, f"{cat} ({mn} - {mx})")

    def toggle_connection(self):
        if not self.is_running:
            port = self.port_cb.get()
            baud = self.baud_entry.get()
            if not port:
                return
            try:
                self.ser = serial.Serial(port, baudrate=int(baud), timeout=0.1)
                self.is_running = True
                self.btn_connect.config(text="Trennen", style="Export.TButton")
                threading.Thread(target=self.read_serial_loop, daemon=True).start()
            except Exception as e:
                messagebox.showerror("Fehler", f"Verbindung fehlgeschlagen:\n{e}")
        else:
            self.is_running = False
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.btn_connect.config(text="Verbinden", style="TButton")

    def time_str_to_seconds(self, t_str):
        try:
            t_str = t_str.strip()
            if ":" in t_str:
                parts = t_str.split(":")
                mins = float(parts[0])
                secs = float(parts[1])
                return mins * 60.0 + secs
            else:
                return float(t_str)
        except ValueError:
            return 999999.0

    def register_final_time(self, stnr, time_str):
        seconds = self.time_str_to_seconds(time_str)
        
        assigned_cat = None
        for cat, (mn, mx) in self.categories.items():
            if mn <= stnr <= mx:
                assigned_cat = cat
                break

        cat_disp = assigned_cat if assigned_cat else "OHNE KAT"
        
        # Grünen rechten Balken aktualisieren
        self.banner_right.config(text=f"ZIEL: Nr {stnr} ({cat_disp}) ➔ {time_str}s")

        if assigned_cat:
            self.results[assigned_cat] = [item for item in self.results[assigned_cat] if item[0] != stnr]
            self.results[assigned_cat].append((stnr, seconds, time_str))
            self.results[assigned_cat].sort(key=lambda x: x[1])
            
            top_5_stnrs = [item[0] for item in self.results[assigned_cat][:5]]
            if stnr in top_5_stnrs:
                self.blinking_items[(assigned_cat, stnr)] = time.time() + 30.0

            self.update_card_content()

    def open_manual_time_dialog(self):
        stnr_raw = self.manual_stnr_entry.get().strip()
        if not stnr_raw.isdigit():
            messagebox.showerror("Fehler", "Bitte eine gültige Startnummer eingeben.")
            return

        stnr = int(stnr_raw)

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Zeit erfassen für Nr. {stnr}")
        dlg.geometry("380x200")
        dlg.configure(bg="#1e293b")
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text=f"Manuelle Zeit für Startnummer {stnr}", font=("Arial", 12, "bold"), bg="#1e293b", fg="white").pack(pady=10)

        input_frame = tk.Frame(dlg, bg="#1e293b")
        input_frame.pack(pady=10)

        tk.Label(input_frame, text="Min (mm)", bg="#1e293b", fg="#94a3b8", font=("Arial", 9)).grid(row=0, column=0, padx=5)
        e_min = ttk.Entry(input_frame, width=4, font=("Arial", 16, "bold"), justify="center")
        e_min.grid(row=1, column=0, padx=5)
        e_min.insert(0, "00")

        tk.Label(input_frame, text=":", font=("Arial", 16, "bold"), bg="#1e293b", fg="white").grid(row=1, column=1)

        tk.Label(input_frame, text="Sek (ss)", bg="#1e293b", fg="#94a3b8", font=("Arial", 9)).grid(row=0, column=2, padx=5)
        e_sec = ttk.Entry(input_frame, width=4, font=("Arial", 16, "bold"), justify="center")
        e_sec.grid(row=1, column=2, padx=5)
        e_sec.insert(0, "00")

        tk.Label(input_frame, text=".", font=("Arial", 16, "bold"), bg="#1e293b", fg="white").grid(row=1, column=3)

        tk.Label(input_frame, text="Zehntel (z)", bg="#1e293b", fg="#94a3b8", font=("Arial", 9)).grid(row=0, column=4, padx=5)
        e_tenths = ttk.Entry(input_frame, width=4, font=("Arial", 16, "bold"), justify="center")
        e_tenths.grid(row=1, column=4, padx=5)
        e_tenths.insert(0, "0")

        def save_manual_time():
            m_str = e_min.get().strip().zfill(2)
            s_str = e_sec.get().strip().zfill(2)
            z_str = e_tenths.get().strip()

            if not (m_str.isdigit() and s_str.isdigit() and z_str.isdigit()):
                messagebox.showerror("Fehler", "Bitte nur Zahlen eingeben.", parent=dlg)
                return

            mins = int(m_str)
            secs = int(s_str)
            
            if secs >= 60:
                messagebox.showerror("Fehler", "Sekunden müssen kleiner als 60 sein.", parent=dlg)
                return

            if mins > 0:
                time_str = f"{mins}:{s_str}.{z_str}"
            else:
                time_str = f"{secs}.{z_str}"

            self.register_final_time(stnr, time_str)
            self.manual_stnr_entry.delete(0, tk.END)
            dlg.destroy()

        ttk.Button(dlg, text="💾 Zeit Speichern", style="Export.TButton", command=save_manual_time).pack(pady=15)

    def read_serial_loop(self):
        rx_buffer = ""
        while self.is_running:
            if self.ser and self.ser.in_waiting > 0:
                try:
                    data = self.ser.read(self.ser.in_waiting).decode('latin1', errors='ignore')
                    rx_buffer += data

                    while '\n' in rx_buffer:
                        line, rx_buffer = rx_buffer.split('\n', 1)
                        line = line.replace('\x02', '').strip()
                        if not line:
                            continue

                        if line.startswith("23"):
                            m = re.search(r'Nr\s+(\d+)', line)
                            if m:
                                self.active_stnr = int(m.group(1))

                        elif line.startswith("13"):
                            time_val = line[2:].strip()
                            if time_val:
                                self.active_time_str = time_val

                                st_disp = self.active_stnr if self.active_stnr else "--"
                                # Blauen linken Balken aktualisieren
                                self.root.after(0, lambda s=st_disp, t=time_val: 
                                    self.banner_left.config(text=f"LAUFEND: Nr {s} ➔ {t}"))

                                if "." in time_val and self.active_stnr is not None:
                                    stnr = self.active_stnr
                                    t_str = time_val
                                    self.root.after(0, self.register_final_time, stnr, t_str)

                except Exception:
                    pass
            else:
                time.sleep(0.05)

    def update_blinking_effect(self):
        now = time.time()
        self.blinking_items = {k: expiry for k, expiry in self.blinking_items.items() if expiry > now}
        self.blink_state = not self.blink_state
        self.update_card_content()
        self.root.after(500, self.update_blinking_effect)

    def init_category_cards(self):
        """ Baut das Grundgerüst ohne Wort 'Platz' mit übersichtlicher Schriftgröße """
        for widget in self.cards_frame.winfo_children():
            widget.destroy()

        self.card_widgets = {}
        row, col = 0, 0

        for cat in self.categories:
            card = ttk.LabelFrame(self.cards_frame, text=f"Kategorie: {cat}", padding="8")
            card.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")

            empty_lbl = tk.Label(card, text="Keine Zeiten vorhanden", font=("Arial", 11), bg="#1e293b", fg="#64748b")
            empty_lbl.pack(anchor=tk.W, pady=5)

            rows_dict = []
            for idx in range(1, 6):
                r_frame = tk.Frame(card, bg="#1e293b")
                
                # Format ohne "Platz", z.B. "1. Nr. 100 "
                font_size = 16 if idx == 1 else 13
                font_style = ("Arial", font_size, "bold")

                lbl_left = tk.Label(r_frame, text="", font=font_style, bg="#1e293b", fg="white")
                lbl_left.pack(side=tk.LEFT)

                lbl_arrow = tk.Label(r_frame, text="", font=font_style, bg="#1e293b", fg="#38bdf8")
                lbl_arrow.pack(side=tk.LEFT)

                lbl_time = tk.Label(r_frame, text="", font=font_style, bg="#1e293b", fg="white")
                lbl_time.pack(side=tk.LEFT)

                rows_dict.append({
                    "frame": r_frame,
                    "left": lbl_left,
                    "arrow": lbl_arrow,
                    "time": lbl_time
                })

            self.card_widgets[cat] = {
                "card": card,
                "empty": empty_lbl,
                "rows": rows_dict
            }

            col += 1
            if col > 2:
                col = 0
                row += 1

        self.update_card_content()

    def update_card_content(self):
        """ Aktualisiert die Top 5 Einträge pro Kategorie """
        for cat, widgets in self.card_widgets.items():
            top_times = self.results.get(cat, [])[:5]

            if not top_times:
                widgets["empty"].pack(anchor=tk.W, pady=5)
                for r in widgets["rows"]:
                    r["frame"].pack_forget()
            else:
                widgets["empty"].pack_forget()
                for idx in range(5):
                    row_w = widgets["rows"][idx]
                    if idx < len(top_times):
                        item = top_times[idx]
                        stnr = item[0]
                        t_str = item[2]

                        is_blinking = (cat, stnr) in self.blinking_items
                        if is_blinking:
                            arrow_color = "#ef4444" if self.blink_state else "#facc15"
                        else:
                            arrow_color = "#38bdf8"

                        text_color = "#facc15" if idx == 0 else "#ffffff"

                        # Anzeige-Format: "1. Nr. 100 "
                        row_w["left"].config(text=f"{idx+1}. Nr. {stnr} ", fg=text_color)
                        row_w["arrow"].config(text="➔ ", fg=arrow_color)
                        row_w["time"].config(text=f"{t_str}s", fg=text_color)

                        row_w["frame"].pack(fill=tk.X, anchor=tk.W, pady=2)
                    else:
                        row_w["frame"].pack_forget()

    def export_to_csv(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV-Datei (Excel)", "*.csv"), ("Alle Dateien", "*.*")],
            title="Ergebnisse exportieren"
        )
        if not file_path:
            return

        try:
            with open(file_path, mode='w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(["Kategorie", "Rang", "Startnummer", "Zeit (String)", "Zeit (Sekunden)"])

                for cat, items in self.results.items():
                    for rank, item in enumerate(items, 1):
                        stnr = item[0]
                        sec = item[1]
                        t_str = item[2]
                        writer.writerow([cat, rank, stnr, t_str, f"{sec:.2f}"])

            messagebox.showinfo("Erfolg", f"Ergebnisse erfolgreich exportiert nach:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Fehler", f"Export fehlgeschlagen:\n{e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = CP545Board(root)
    root.mainloop()