"""v1.23: Prellzeit in Sekunden, Sync-Zeile TM550 (kein Start), Uhren pruefen und TM550 nach CP stellen,
Handimpuls am Hauptgeraet an die Reserve (#WC 014 beim TM550)."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_uhr"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
for txt, want in (("0.2", 0.2), ("0,2", 0.2), ("0.2s", 0.2), ("0,2 s", 0.2), (".3", 0.3), ("1", 1.0)):
    check(f"Eingabe «{txt}» = {want} s", abs(m.parse_seconds_input(txt) - want) < 1e-9)
for bad in ("", "abc", "-1", "0,2,3"):
    try:
        m.parse_seconds_input(bad); check(f"«{bad}» abgelehnt", False)
    except ValueError:
        check(f"«{bad}» abgelehnt", True)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
asked = []
app.message_dialog = lambda *a, **k: asked.append(a) or True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
def logs(n=120): return " | ".join(l[0] for l in app.log_lines[-n:])
e = app.timing_entries["prell_finish_ms"]
check("Feld zeigt Sekunden (0.3)", e.get() == "0.3")
e.delete(0, "end"); e.insert(0, "0,2 s"); app.save_timing()
check("«0,2 s» gespeichert als 200 ms, Anzeige 0.2", app.tset()["prell_finish_ms"] == 200 and e.get() == "0.2")
e.delete(0, "end"); e.insert(0, "0.3"); app.save_timing()
o = list(range(21, 30))
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
A = m.SimCP()
B = m.SimCP(device="tm550", fw="1.48", clock_offset=-15.7)
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
app.connect_cp("127.0.0.1", A.port); pump(3)
app.start_backup(f"usb:socket://127.0.0.1:{B.port}"); pump(9)
check("Verbindung orange, solange die Uhren nicht abgeglichen sind", app.connection_level() == 1
      and "Uhren nicht abgeglichen" in app._conn_status[0])
check("Knopf «Uhren prüfen» aktiv", str(app.btn_clock._o["state"]) != "disabled")
check("Uhrenprüfung beim ersten Verbinden gestartet", getattr(app, "_clock_check", False)
      and "Uhren prüfen" in logs())
# Sync-Zeile der Reserve: kein Start
B.send("TN    0    0 01 00:00:00.00000  9826"); pump(1)
check("Sync-Zeile: kein Boot auf der Strecke", not app.course and "Uhr synchronisiert" in logs())
# Testimpuls am Ziel an beiden Geraeten
A.impulse(m.CH_FINISH); B.impulse(m.CH_FINISH); pump(2)
check("Abweichung erkannt, Rückfrage TM550 stellen", any("TM550" in str(a) for a in asked))
check("Stellen angekündigt", "Uhr wird in" in logs())
t_end = time.time() + 70
while time.time() < t_end and not any(c.startswith("#WC 007 02") for c in B.cmds):
    pump(0.5)
pump(3)
check("#WC 007 02 an den TM550 geschickt", any(c.startswith("#WC 007 02") for c in B.cmds))
check("TM550-Uhr jetzt nahe der CP-Uhr", abs(B.clock_offset - A.clock_offset) < 0.3)
A.impulse(m.CH_FINISH); B.impulse(m.CH_FINISH); pump(2)
check("Kontrolle: Uhren stimmen überein", "stimmen überein" in logs())
check("Verbindung jetzt grün", app.connection_level() == 2)
# Wettkampf: Knopf gesperrt
A.start(); B.start(); pump(2)
check("Knopf während Wettkampf gesperrt", str(app.btn_clock._o["state"]) == "disabled")
check("Uhrversatz neu gelernt", app.b_offset is not None and abs(app.b_offset) < 0.3)
# Handimpuls Ziel am Hauptgeraet: Reserve bekommt die Zeit
A.impulse(m.CH_FINISH, manual=True); pump(3)
check("Ziel Nr 21 vom Handimpuls", 21 in app.results)
check("Reserve: #WC 014 04 geschickt", any(c.startswith("#WC 014 04") for c in B.cmds))
check("Reserve-Zeile (T+) verarbeitet, keine Abweichung", "nur beim Reserve" not in logs(40)
      and "Abweichung" not in logs(40))
app.stop_backup(); app.disconnect_all(); pump(1); A.close(); B.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
