"""Reserve mit falscher Uhr (TM550 nach Firmware-Update 8 h 41 min vor), Starts nur an der Reserve:
Versatz aus der Eingangszeit geschaetzt, Hauptgeraet bekommt die naechste Nummer, neuer Lauf der Reserve
verwechselt keine Zeiten."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_ruhr"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.message_dialog = lambda *a, **k: True
app._b_rule = "reserve"   # ohne Rueckfrage
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
o = list(range(21, 30))
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
A = m.SimCP()
B = m.SimCP(device="tm550", fw="1.48", clock_offset=8 * 3600 + 41 * 60)
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
app.connect_cp("127.0.0.1", A.port); pump(3)
A.start(); pump(1.5)          # Hauptgeraet: Uhr bekannt
check("Start 21 am CP", [c[1] for c in app.course] == [21] and A.next[m.CH_START] == 22)
app.start_backup(f"usb:socket://127.0.0.1:{B.port}"); pump(4)
B.next[m.CH_START] = 22
B.start(); pump(5)            # nur an der Reserve
c = [x for x in app.course if x[1] == 22]
check("Start 22 nur an der Reserve übernommen", bool(c))
check("Startzeit trotz falscher Reserve-Uhr nahe der PC-Zeit", c and abs(c[0][0] - m.local_abs()) < 10)
check("Laufzeit vernünftig", app.cp_offset() is not None and abs(app.cp_offset()) < 5)
check("CP bekommt die nächste Nummer 23", A.next[m.CH_START] == 23)
# Reserve oeffnet neuen Lauf, Zaehlnummern beginnen wieder bei 1
B.close_run(); pump(0.5); B.open_run(); pump(1)
B.next[m.CH_START] = 23
B.start(); pump(5)
check("neuer Lauf der Reserve: Nr 23 auf der Strecke", 23 in [x[1] for x in app.course])
app.stop_backup(); app.disconnect_all(); pump(1); A.close(); B.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
