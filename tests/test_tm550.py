"""TM550 (ITS/Vola) nach den Tests vom 22.11.2026: USB und Ethernet, Erkennung, Nummern durch die App,
gesperrte Kontakte (TC mit eigener Zeit), Luecke per Download, keine Vorladung."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_tm550"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)

check("Zeile TM550 erkannt", m.parse_thcom("TN         1 04 15:41:10.50000  9822")["ch"] == 4)
check("OP TM550", m.parse_thcom("OP 02 TIMING") == {"kind": "open", "run": 2, "mode": "TIMING"})

root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
o = [21, 22, 23, 24, 25]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()

# --- USB
sim = m.SimCP(device="tm550", bounce=True)
app.var_conn.set("usb"); app.on_conn_mode_change(); pump(0.1)
app.cmb_usb.set(f"socket://127.0.0.1:{sim.port}")
app.toggle_connection(); pump(4.0)
check("TM550 über USB erkannt", app.cp_device == "tm550")
sim.start(); pump(0.5); sim.start(); pump(0.5)
check("Starts mit Nummern aus der Startreihenfolge", [c[1] for c in app.course] == [21, 22])
sim.finish(); pump(0.8)
check("Ziel an 21, gesperrter Kontakt kein Storno", 21 in app.results and [c[1] for c in app.course] == [22]
      and any("Sperrzeit" in l[0] for l in app.log_lines))
check("Vorladen bei FW 1.18 abgelehnt, App nummeriert", not app.cp_caps["preload"] and app.cp_caps["ignore_nr"])
sim.drop_next = True; sim.start(); pump(0.3)      # Zeile geht verloren
sim.start(); pump(3.5)                             # Luecke -> Download des Laufs
check("Lücke per Download geschlossen", [c[1] for c in app.course] == [22, 23, 24])
app.toggle_connection(); pump(1.0); sim.close()

# --- Ethernet, Port unbekannt: #SN ohne Antwort, dann mit Pruefsumme
sim2 = m.SimCP(device="tm550", timing=False)
app.reset_caps("cp545")
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
app.connect_cp("127.0.0.1", sim2.port); pump(12.0)
check("TM550 über Ethernet erkannt (Prüfsumme nachgeschaltet)", app.cp_device == "tm550" and app.cp.checksum)
check("kein Lauf: Hinweis statt Dauerwarnung", sum("kein Lauf offen" in l[0] for l in app.log_lines) <= 1)
sim2.start(); pump(0.6)
check("Start auch ohne Lauf (Lauf 0)", 25 in [c[1] for c in app.course])
app.cp.stop(); pump(0.5); sim2.close()
print("GESAMT", "OK" if all(ok) else "FEHLER")
