import sys
import os
import time
import json
import serial
import serial.tools.list_ports
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

class TimekeepingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TAG Heuer CP 545 - Live Ranking & Speaker Board")
        
        # FEHLER-FIX: Geometrie muss mit "x" definiert werden
        self.root.geometry("1300x800")
        self.root.minsize(1000, 650)
        
        self.log_filename = "wettkampf_zeiten_log.txt"
        
        self.categories_config = {
            "Aktive": {"min": 1, "max": 299},
            "Senioren": {"min": 300, "max": 399},
            "Veteranen": {"min": 400, "max": 499},
            "Frauen": {"min": 500, "max": 599},
            "Junioren": {"min": 600, "max": 699},
            "Jungfahrer": {"min": 700, "max": 799},
            "Schüler": {"min": 800, "max": 899}
        }
        
        self.results = {}
        self.last_top3 = {}
        self.blinking_labels = {}
        
        self.serial_running = False
        self.serial_thread = None
        
        self.setup_styles()
        self.create_widgets()
        self.refresh_com_ports()
        self.rebuild_ranking_ui_sections()
        self.update_ranking_display()
        
        self.run_blink_loop()

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('.', background='#111827', foreground='#f3f4f6')
        self.style.configure('TLabel', background='#111827', foreground='#f3f4f6')
        self.style.configure('TFrame', background='#111827')
        self.style.configure('TLabelframe', background='#1f2937', foreground='#f3f4f6', bordercolor='#4b5563')
        self.style.configure('TLabelframe.Label', background='#1f2937', foreground='#38bdf8', font=('Helvetica', 11, 'bold'))
        self.style.configure('TButton', font=('Helvetica', 10, 'bold'), background='#374151', foreground='#ffffff')
        self.style.map('TButton', background=[('active', '#4b5563')])
        self.style.configure('Action.TButton', font=('Helvetica', 11, 'bold'), background='#10b981', foreground='#ffffff')
        self.style.map('Action.TButton', background=[('active', '#059669')])
        
        self.style.configure('Custom.TEntry', foreground='#000000', fieldbackground='#ffffff')
        self.style.configure('Custom.TCombobox', foreground='#000000', fieldbackground='#ffffff')

    def create_widgets(self):
        main_container = ttk.Frame(self.root, padding=10)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        self.live_time_frame = ttk.Frame(main_container, height=100)
        self.live_time_frame.pack(fill=tk.X, pady=(0, 10))
        self.live_time_frame.pack_propagate(False)
        
        self.lbl_big_time = tk.Label(
            self.live_time_frame, 
            text="WARTE AUF IMPULS...", 
            font=('Helvetica', 34, 'bold'), 
            bg='#ef4444', 
            fg='#ffffff',
            anchor='center'
        )
        self.lbl_big_time.pack(fill=tk.BOTH, expand=True)
        
        mid_frame = ttk.Frame(main_container)
        mid_frame.pack(fill=tk.BOTH, expand=True)
        
        self.left_panel = ttk.Frame(mid_frame, width=340)
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        self.left_panel.pack_propagate(False)
        
        right_panel = ttk.Frame(mid_frame)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        conn_box = ttk.LabelFrame(self.left_panel, text=" 1. Verbindung (CP 545 RS232) ", padding=8)
        conn_box.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(conn_box, text="Port:").grid(row=0, column=0, sticky='w', pady=2)
        self.cb_ports = ttk.Combobox(conn_box, width=12, state="readonly", style='Custom.TCombobox')
        self.cb_ports.grid(row=0, column=1, sticky='w', padx=5, pady=2)
        
        btn_refresh_ports = ttk.Button(conn_box, text="🔄", width=3, command=self.refresh_com_ports)
        btn_refresh_ports.grid(row=0, column=2, sticky='w', padx=2, pady=2)
        
        ttk.Label(conn_box, text="Baud:").grid(row=1, column=0, sticky='w', pady=2)
        self.ent_baud = ttk.Entry(conn_box, width=15, style='Custom.TEntry')
        self.ent_baud.insert(0, "9600")
        self.ent_baud.grid(row=1, column=1, columnspan=2, sticky='w', padx=5, pady=2)
        
        self.btn_connect = ttk.Button(conn_box, text="Verbindung Starten", command=self.toggle_connection)
        self.btn_connect.grid(row=2, column=0, columnspan=3, sticky='we', pady=6)
        
        self.config_box = ttk.LabelFrame(self.left_panel, text=" 2. Kategorien verwalten ", padding=8)
        self.config_box.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.btn_apply = ttk.Button(self.config_box, text="Bereiche Aktualisieren", command=self.apply_categories)
        self.btn_apply.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 2))
        
        add_cat_frame = ttk.Frame(self.config_box, padding=4)
        add_cat_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 5))
        
        ttk.Label(add_cat_frame, text="Name:", font=('Helvetica', 9)).grid(row=0, column=0, sticky='w')
        self.ent_new_name = ttk.Entry(add_cat_frame, width=10, style='Custom.TEntry')
        self.ent_new_name.grid(row=0, column=1, padx=2)
        
        ttk.Label(add_cat_frame, text="Min:", font=('Helvetica', 9)).grid(row=0, column=2, sticky='w')
        self.ent_new_min = ttk.Entry(add_cat_frame, width=5, style='Custom.TEntry')
        self.ent_new_min.grid(row=0, column=3, padx=2)
        
        ttk.Label(add_cat_frame, text="Max:", font=('Helvetica', 9)).grid(row=0, column=4, sticky='w')
        self.ent_new_max = ttk.Entry(add_cat_frame, width=5, style='Custom.TEntry')
        self.ent_new_max.grid(row=0, column=5, padx=2)
        
        btn_add_cat = ttk.Button(add_cat_frame, text="+", width=3, command=self.add_new_category)
        btn_add_cat.grid(row=0, column=6, padx=4)

        self.ent_new_name.bind("<Return>", lambda event: self.add_new_category())
        self.ent_new_min.bind("<Return>", lambda event: self.add_new_category())
        self.ent_new_max.bind("<Return>", lambda event: self.add_new_category())

        self.cat_list_canvas = tk.Canvas(self.config_box, bg='#1f2937', highlightthickness=0, height=180)
        self.cat_list_scrollbar = ttk.Scrollbar(self.config_box, orient="vertical", command=self.cat_list_canvas.yview)
        self.cat_list_inner = ttk.Frame(self.cat_list_canvas)
        
        self.cat_list_inner.bind(
            "<Configure>",
            lambda e: self.cat_list_canvas.configure(scrollregion=self.cat_list_canvas.bbox("all"))
        )
        self.cat_list_canvas.create_window((0, 0), window=self.cat_list_inner, anchor="nw")
        self.cat_list_canvas.configure(yscrollcommand=self.cat_list_scrollbar.set)
        
        self.cat_list_canvas.pack(fill=tk.BOTH, expand=True, pady=2)
        
        actions_box = ttk.LabelFrame(self.left_panel, text=" 3. Wettkampf-Aktionen ", padding=8)
        actions_box.pack(fill=tk.X, side=tk.BOTTOM)
        
        btn_finish_race = ttk.Button(actions_box, text="🏁 Wettkampf abschliessen", style='Action.TButton', command=self.finish_competition)
        btn_finish_race.pack(fill=tk.X, ipady=5)
        
        self.speaker_box = ttk.LabelFrame(right_panel, text=" SPEAKER BOARD - TOP 3 PRO KATEGORIE ", padding=10)
        self.speaker_box.pack(fill=tk.BOTH, expand=True)
        
        self.canvas = tk.Canvas(self.speaker_box, bg='#111827', highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.speaker_box, orient="vertical", command=self.canvas.yview)
        
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        def on_canvas_configure(event):
            self.canvas.itemconfig(self.canvas_window, width=event.width)

        self.canvas.bind('<Configure>', on_canvas_configure)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

    def refresh_com_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.cb_ports['values'] = ports
        if ports:
            self.cb_ports.current(0)
        else:
            self.cb_ports.set("Kein Port!")

    def rebuild_category_inputs(self):
        for widget in self.cat_list_inner.winfo_children():
            widget.destroy()
            
        ttk.Label(self.cat_list_inner, text="Kat.", font=('Helvetica', 9, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(self.cat_list_inner, text="Min-Nr.", font=('Helvetica', 9, 'bold')).grid(row=0, column=1, sticky='w', padx=10)
        ttk.Label(self.cat_list_inner, text="Max-Nr.", font=('Helvetica', 9, 'bold')).grid(row=0, column=2, sticky='w', padx=10)
        ttk.Label(self.cat_list_inner, text="Löschen", font=('Helvetica', 9, 'bold')).grid(row=0, column=3, padx=5)
        
        self.entries_config = {}
        row_idx = 1
        for cat_name, limits in self.categories_config.items():
            ttk.Label(self.cat_list_inner, text=cat_name).grid(row=row_idx, column=0, sticky='w', pady=2)
            
            en_min = ttk.Entry(self.cat_list_inner, width=6, style='Custom.TEntry')
            en_min.insert(0, str(limits["min"]))
            en_min.grid(row=row_idx, column=1, padx=10, pady=2)
            
            en_max = ttk.Entry(self.cat_list_inner, width=6, style='Custom.TEntry')
            en_max.insert(0, str(limits["max"]))
            en_max.grid(row=row_idx, column=2, padx=10, pady=2)
            
            # FEHLER-FIX: sticky="center" entfernt (Standardverhalten zentriert automatisch im Grid)
            btn_delete = tk.Button(
                self.cat_list_inner, 
                text="➖", 
                bg='#ef4444', 
                fg='#ffffff', 
                relief=tk.FLAT,
                font=('Helvetica', 8, 'bold'),
                width=3,
                command=lambda name=cat_name: self.delete_category(name)
            )
            btn_delete.grid(row=row_idx, column=3, padx=5, pady=2)
            
            self.entries_config[cat_name] = {"min": en_min, "max": en_max}
            row_idx += 1

    def delete_category(self, cat_name):
        if cat_name in self.categories_config:
            del self.categories_config[cat_name]
        self.rebuild_category_inputs()
        self.rebuild_ranking_ui_sections()
        self.update_ranking_display()

    def rebuild_ranking_ui_sections(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        self.cat_frames = {}
        all_cats = list(self.categories_config.keys())
        
        num_cols = 2
        num_rows = (len(all_cats) + 1) // 2
        
        for c in range(num_cols):
            self.scrollable_frame.grid_columnconfigure(c, weight=1)
        for r in range(num_rows):
            self.scrollable_frame.grid_rowconfigure(r, weight=1)
            
        for idx, cat_name in enumerate(all_cats):
            row = idx // 2
            col = idx % 2
            
            frame = tk.Frame(self.scrollable_frame, bg='#1f2937', bd=1, relief=tk.SOLID)
            frame.grid(row=row, column=col, sticky="nsew", padx=6, pady=6, ipady=4)
            
            lbl_title = tk.Label(frame, text=f"Kategorie: {cat_name.upper()}", font=('Helvetica', 12, 'bold'), bg='#374151', fg='#38bdf8', anchor='w', padx=8, pady=4)
            lbl_title.pack(fill=tk.X)
            
            self.cat_frames[cat_name] = []
            for i in range(3):
                lbl_row = tk.Label(
                    frame, 
                    text="Keine Zeiten registriert" if i == 0 else "", 
                    font=('Consolas', 12), 
                    bg='#1f2937', 
                    fg='#9ca3af', 
                    anchor='w', 
                    padx=10, 
                    pady=3
                )
                lbl_row.pack(fill=tk.X, expand=True)
                self.cat_frames[cat_name].append(lbl_row)

    def add_new_category(self):
        name = self.ent_new_name.get().strip()
        vmin_str = self.ent_new_min.get().strip()
        vmax_str = self.ent_new_max.get().strip()
        
        if not name or not vmin_str or not vmax_str:
            messagebox.showerror("Fehler", "Bitte alle Felder ausfüllen.")
            return
            
        try:
            vmin = int(vmin_str)
            vmax = int(vmax_str)
            if vmin > vmax:
                raise ValueError("Min darf nicht grösser als Max sein.")
                
            if name in self.categories_config:
                raise ValueError("Kategorie existiert bereits.")
                
            self.categories_config[name] = {"min": vmin, "max": vmax}
            
            self.ent_new_name.delete(0, tk.END)
            self.ent_new_min.delete(0, tk.END)
            self.ent_new_max.delete(0, tk.END)
            
            self.rebuild_category_inputs()
            self.rebuild_ranking_ui_sections()
            self.update_ranking_display()
            self.ent_new_name.focus_set()
            
        except ValueError as e:
            messagebox.showerror("Eingabefehler", f"Fehler beim Erstellen: {e}")

    def apply_categories(self):
        try:
            new_config = {}
            for cat_name, entries in self.entries_config.items():
                vmin = int(entries["min"].get().strip())
                vmax = int(entries["max"].get().strip())
                if vmin > vmax:
                    raise ValueError(f"Min darf nicht grösser als Max sein bei {cat_name}.")
                new_config[cat_name] = {"min": vmin, "max": vmax}
            
            self.categories_config = new_config
            self.rebuild_ranking_ui_sections()
            self.update_ranking_display()
            messagebox.showinfo("Erfolg", "Kategorie-Nummernbereiche live aktualisiert!")
        except ValueError as e:
            messagebox.showerror("Eingabefehler", f"Ungültige Werte: {e}")

    def toggle_connection(self):
        if self.serial_running:
            self.serial_running = False
            if self.serial_thread:
                self.serial_thread.join(timeout=1)
            self.btn_connect.config(text="Verbindung Starten")
            self.lbl_big_time.config(text="VERBINDUNG GETRENNT", bg='#374151')
        else:
            port = self.cb_ports.get()
            if not port or port == "Kein Port!":
                messagebox.showerror("Fehler", "Wähle einen gültigen COM-Port aus.")
                return
            try:
                baud = int(self.ent_baud.get().strip())
            except ValueError:
                messagebox.showerror("Fehler", "Baudrate muss numerisch sein.")
                return
                
            self.serial_running = True
            self.btn_connect.config(text="Trennen")
            self.lbl_big_time.config(text="VERBUNDEN - WARTE AUF IMPULS...", bg='#10b981')
            
            self.serial_thread = threading.Thread(target=self.listen_serial, args=(port, baud), daemon=True)
            self.serial_thread.start()

    def listen_serial(self, port, baud):
        try:
            ser = serial.Serial(port, baud, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=1)
            while self.serial_running:
                if ser.in_waiting > 0:
                    raw_line = ser.readline()
                    line = raw_line.decode('utf-8', errors='ignore').strip()
                    if line:
                        self.root.after(0, self.process_time_data, line)
                time.sleep(0.01)
            ser.close()
        except Exception as e:
            self.serial_running = False
            self.root.after(0, self.handle_serial_error, str(e))

    def handle_serial_error(self, err_msg):
        self.btn_connect.config(text="Verbindung Starten")
        self.lbl_big_time.config(text="VERBINDUNGSFEHLER", bg='#ef4444')
        messagebox.showerror("Serieller Fehler", f"Verbindung abgebrochen:\n{err_msg}")

    def process_time_data(self, raw_string):
        with open(self.log_filename, "a", encoding="utf-8") as log_file:
            log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {raw_string}\n")

        parts = [p for p in raw_string.split() if p]
        if len(parts) < 2:
            return
            
        try:
            stnr = None
            zeit_str = parts[-1]
            
            for part in parts[1:-1]:
                if part.isdigit():
                    stnr = int(part)
                    break
                    
            if stnr is None:
                if parts[0].isdigit():
                    stnr = int(parts[0])
                else:
                    return

            seconds = self.parse_time_to_seconds(zeit_str)
            
            self.results[stnr] = {
                "raw_time": zeit_str,
                "seconds": seconds,
                "timestamp": time.time()
            }
            
            kat = self.get_category_for_number(stnr)
            if kat != "Allgemein":
                self.lbl_big_time.config(
                    text=f"STNR: {stnr} ({kat}) -> {zeit_str}",
                    bg='#3b82f6'
                )
                self.update_ranking_display()
            
        except Exception as e:
            print(f"Parsing-Fehler bei String '{raw_string}': {e}")

    def parse_time_to_seconds(self, time_str):
        try:
            if ":" in time_str:
                parts = time_str.split(":")
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
                elif len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            return float(time_str)
        except ValueError:
            return time.time()

    def get_category_for_number(self, num):
        for cat_name, limits in self.categories_config.items():
            if limits["min"] <= num <= limits["max"]:
                return cat_name
        return "Allgemein"

    def update_ranking_display(self):
        categorized_lists = {cat: [] for cat in self.categories_config.keys()}
        
        for stnr, data in self.results.items():
            kat = self.get_category_for_number(stnr)
            if kat in categorized_lists:
                categorized_lists[kat].append((stnr, data))
                
        now = time.time()
        
        for cat_name, label_widgets in self.cat_frames.items():
            if cat_name not in categorized_lists:
                continue
                
            sub_list = categorized_lists[cat_name]
            sub_list.sort(key=lambda x: x[1]["seconds"])
            
            current_top3_ids = [item[0] for item in sub_list[:3]]
            previous_top3_ids = self.last_top3.get(cat_name, [])
            
            for idx in range(3):
                widget = label_widgets[idx]
                key = (cat_name, idx)
                
                if idx < len(sub_list):
                    stnr, data = sub_list[idx]
                    prefix = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉"
                    text_str = f"{prefix} Platz {idx+1}: Start-Nr. {stnr:<4} -> Zeit: {data['raw_time']}"
                    
                    widget.config(text=text_str)
                    
                    is_new_entry = (stnr not in previous_top3_ids)
                    is_rank_improved = (idx < len(previous_top3_ids) and previous_top3_ids[idx] != stnr)
                    is_fresh_pulse = (data['timestamp'] > now - 2.0)
                    
                    if (is_new_entry or is_rank_improved) and is_fresh_pulse:
                        self.blinking_labels[key] = {
                            "end_time": now + 30.0,
                            "state": True,
                            "widget": widget
                        }
                        widget.config(bg='#eab308', fg='#111827')
                    
                    if key not in self.blinking_labels:
                        widget.config(bg='#1f2937', fg='#f3f4f6')
                        
                else:
                    if idx == 0:
                        widget.config(text="Keine Zeiten in dieser Kategorie", fg='#64748b', bg='#1f2937')
                    else:
                        widget.config(text="", bg='#1f2937')
                    
                    if key in self.blinking_labels:
                        del self.blinking_labels[key]
            
            self.last_top3[cat_name] = current_top3_ids

    def run_blink_loop(self):
        now = time.time()
        expired_keys = []
        
        for key, blink_data in self.blinking_labels.items():
            if now > blink_data["end_time"]:
                blink_data["widget"].config(bg='#1f2937', fg='#f3f4f6')
                expired_keys.append(key)
            else:
                if blink_data["state"]:
                    blink_data["widget"].config(bg='#1f2937', fg='#eab308')
                else:
                    blink_data["widget"].config(bg='#eab308', fg='#111827')
                
                blink_data["state"] = not blink_data["state"]
                
        for key in expired_keys:
            if key in self.blinking_labels:
                del self.blinking_labels[key]
                
        self.root.after(500, self.run_blink_loop)

    def finish_competition(self):
        if not self.results:
            messagebox.showwarning("Achtung", "Es sind noch keine gemessenen Daten vorhanden.")
            return

        race_name = simpledialog.askstring("Wettkampf abschliessen", "Bitte geben Sie den Namen des Wettkampfs ein:")
        if not race_name:
            messagebox.showinfo("Abgebrochen", "Wettkampf wurde nicht beendet.")
            return
            
        clean_name = "".join([c for c in race_name if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
        clean_name = clean_name.replace(' ', '_')
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        final_filename = f"Wettkampf_{clean_name}_{timestamp}.json"
        export_text_filename = f"Wettkampf_{clean_name}_{timestamp}_Rangliste.txt"
        
        try:
            export_data = {
                "wettkampf_name": race_name,
                "zeitstempel_abschluss": time.strftime('%Y-%m-%d %H:%M:%S'),
                "kategorien_struktur": self.categories_config,
                "ergebnisse": self.results
            }
            with open(final_filename, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=4)
                
            with open(export_text_filename, "w", encoding="utf-8") as f:
                f.write(f"RANGLISTE: {race_name}\n")
                f.write(f"Abgeschlossen am: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("="*50 + "\n\n")
                
                all_cats = list(self.categories_config.keys())
                for cat in all_cats:
                    f.write(f"KATEGORIE: {cat.upper()}\n")
                    f.write("-"*30 + "\n")
                    
                    cat_runners = []
                    for stnr, data in self.results.items():
                        if self.get_category_for_number(stnr) == cat:
                            cat_runners.append((stnr, data))
                    
                    cat_runners.sort(key=lambda x: x[1]["seconds"])
                    
                    if not cat_runners:
                        f.write("  Keine Teilnehmer in dieser Kategorie\n")
                    else:
                        for rank, (stnr, data) in enumerate(cat_runners, 1):
                            f.write(f"  {rank}. Platz | Start-Nr: {stnr:<4} | Zeit: {data['raw_time']}\n")
                    f.write("\n")

            self.results.clear()
            self.blinking_labels.clear()
            self.last_top3.clear()
            self.update_ranking_display()
            self.lbl_big_time.config(text="WETTKAMPF BEENDET & GESPEICHERT", bg='#10b981')
            
            if os.path.exists(self.log_filename):
                os.remove(self.log_filename)
                
            messagebox.showinfo("Wettkampf Beendet", f"Erfolgreich gespeichert unter:\n- {final_filename}\n- {export_text_filename}\n\nDie App wurde zurückgesetzt.")
            
        except Exception as e:
            messagebox.showerror("Fehler beim Speichern", f"Daten konnten nicht gesichert werden:\n{e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = TimekeepingApp(root)
    root.mainloop()