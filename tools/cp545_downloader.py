import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import serial
import serial.tools.list_ports
import threading
import time

class CP545Downloader:
    def __init__(self, root):
        self.root = root
        self.root.title("TAG Heuer CP 545 - Speicher Ausleser")
        self.root.geometry("450x350")
        self.root.resizable(False, False)
        
        # Style
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Variablen
        self.selected_port = tk.StringVar()
        self.is_downloading = False
        
        # UI Elemente bauen
        self.create_widgets()
        self.refresh_ports()

    def create_widgets(self):
        # Hauptframe
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Titel
        title_label = ttk.Label(main_frame, text="CP 545 Daten-Download", font=("Arial", 14, "bold"))
        title_label.pack(pady=(0, 15))
        
        # Port Auswahl Frame
        port_frame = ttk.Frame(main_frame)
        port_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(port_frame, text="1. COM-Port auswählen:").pack(side=tk.LEFT, padx=(0, 10))
        self.port_combobox = ttk.Combobox(port_frame, textvariable=self.selected_port, width=15, state="readonly")
        self.port_combobox.pack(side=tk.LEFT, padx=(0, 5))
        
        refresh_btn = ttk.Button(port_frame, text="🔄", width=3, command=self.refresh_ports)
        refresh_btn.pack(side=tk.LEFT)
        
        # Status / Anleitung
        self.status_label = ttk.Label(main_frame, text="Bereit. Port wählen und auf 'Download starten' klicken.", 
                                      foreground="blue", font=("Arial", 10, "italic"), wraplength=400)
        self.status_label.pack(pady=15)
        
        # Download Button
        self.download_btn = ttk.Button(main_frame, text="2. Download starten & Datei speichern", 
                                       command=self.start_download_thread, state=tk.DISABLED)
        self.download_btn.pack(fill=tk.X, ipady=10, pady=10)
        
        # Log/Vorschau-Fenster
        ttk.Label(main_frame, text="Empfangene Daten (Vorschau):").pack(anchor=tk.W)
        self.log_text = tk.Text(main_frame, height=6, width=50, state=tk.DISABLED, font=("Courier", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combobox['values'] = ports
        if ports:
            self.port_combobox.current(0)
            self.download_btn.config(state=tk.NORMAL)
            self.status_label.config(text="Port ausgewählt. Klicke auf 'Download starten' und löse DANN den Export am CP 545 aus.", foreground="black")
        else:
            self.selected_port.set("")
            self.download_btn.config(state=tk.DISABLED)
            self.status_label.config(text="KEIN GERÄT GEFUNDEN! Bitte USB-Kabel prüfen und Liste aktualisieren.", foreground="red")

    def start_download_thread(self):
        # Speicherort vom Benutzer abfragen, bevor es losgeht
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Textdateien", "*.txt"), ("Alle Dateien", "*.*")],
            title="Lauf speichern unter..."
        )
        if not file_path:
            return # Abgebrochen
            
        # Thread starten, damit die GUI nicht einfriert
        threading.Thread(target=self.download_logic, args=(file_path,), daemon=True).start()

    def download_logic(self, file_path):
        self.is_downloading = True
        self.download_btn.config(state=tk.DISABLED)
        self.port_combobox.config(state=tk.DISABLED)
        
        self.status_label.config(text="Warte auf Daten vom CP 545... (Jetzt am Gerät den Download starten!)", foreground="orange")
        
        # Log leeren
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state=tk.DISABLED)

        ser = None
        try:
            # Verbindung öffnen (CP 545 nutzt standardmäßig 9600, über USB oft egal, aber sicher ist sicher)
            ser = serial.Serial(self.selected_port.get(), baudrate=9600, timeout=0.1)
            
            with open(file_path, "w", encoding="utf-8") as f:
                last_data_time = time.time()
                data_received_at_least_once = False
                
                while self.is_downloading:
                    # Zeile oder Block lesen
                    if ser.in_waiting > 0:
                        line = ser.readline().decode('utf-8', errors='ignore')
                        if line:
                            # In Datei schreiben
                            f.write(line)
                            f.flush()
                            
                            # In GUI Vorschau anzeigen
                            self.log_text.config(state=tk.NORMAL)
                            self.log_text.insert(tk.END, line)
                            self.log_text.see(tk.END)
                            self.log_text.config(state=tk.DISABLED)
                            
                            # Timer zurücksetzen
                            last_data_time = time.time()
                            if not data_received_at_least_once:
                                data_received_at_least_once = True
                                self.status_label.config(text="Daten werden empfangen...", foreground="green")
                    else:
                        time.sleep(0.05)
                    
                    # Automatischer Timeout-Check (2 Sekunden keine Daten mehr)
                    if data_received_at_least_once and (time.time() - last_data_time > 2.0):
                        break
                        
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler bei der Kommunikation:\n{str(e)}")
        finally:
            if ser and ser.is_open:
                ser.close()
            
            self.is_downloading = False
            self.root.after(0, self.finish_download, data_received_at_least_once, file_path)

    def finish_download(self, success, path):
        self.port_combobox.config(state="readonly")
        self.download_btn.config(state=tk.NORMAL)
        
        if success:
            self.status_label.config(text=f"Download erfolgreich beendet!\nDatei gespeichert.", foreground="green")
            messagebox.showinfo("Erfolg", f"Der Lauf wurde erfolgreich importiert und gespeichert unter:\n{path}")
        else:
            self.status_label.config(text="Abgebrochen. Es wurden keine Daten empfangen.", foreground="red")

if __name__ == "__main__":
    root = tk.Tk()
    app = CP545Downloader(root)
    root.mainloop()