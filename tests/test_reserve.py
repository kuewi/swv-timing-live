"""CP 545 als Hauptgeraet, TM550 als Reserve: Uhrabgleich, Uebernahme bei fehlendem Impuls und bei Ausfall."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_reserve"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
o = list(range(21, 30))
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
A = m.SimCP()
B = m.SimCP(device="tm550", clock_offset=-281.25)
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
app.connect_cp("127.0.0.1", A.port); pump(2.5)
app.start_backup(f"usb:socket://127.0.0.1:{B.port}"); pump(2.0)
check("Reserve verbunden und als TM550 erkannt", app.backup_connected() and app.cp_b_device == "tm550")
def both(fn_a, fn_b):
    fn_a(); fn_b(); pump(0.6)
both(A.start, B.start); both(A.start, B.start)
check("Uhrversatz gelernt", app.b_offset is not None and abs(app.b_offset + 281.25) < 0.05)
check("normal: nur Hauptgerät zählt", [c[1] for c in app.course] == [21, 22]
      and not any(k[0] == "B" and r["status"] == "ok" for k, r in app.cp_recs.items()))
# Impuls nur bei der Reserve (Hauptgeraet hat ihn verpasst)
t0 = m.local_abs()
B.start(); A.seq[1] += 0; pump(4.0)
starts = [c for c in app.course]
check("fehlender Start von der Reserve übernommen", [c[1] for c in starts] == [21, 22, 23])
check("Zeit auf die Uhr des Hauptgeräts umgerechnet", abs(starts[-1][0] - t0) < 0.5)
check("Hinweis im Ticker", any("Reserve" in str(x) for x in list(app.ticker)[:5]))
# Impuls nur beim Hauptgeraet: Warnung
A.start(); pump(4.0)
check("Warnung: Reserve hat Impuls nicht", any("Reserve-Gerät hat den Impuls" in l[0] for l in app.log_lines))
B.start(); pump(0.2)   # Reserve nachziehen (gleiche Zaehlung, wird mit A nicht gepaart -> uebernommen?) 
pump(4.0)
# Ausfall des Hauptgeraets
n_course = [c[1] for c in app.course]
A.drop_clients(); A.alive = False; A.sock.close(); pump(1.5)
B.finish(); pump(1.0)
check("bei Ausfall: Zielzeit der Reserve sofort übernommen", n_course[0] in app.results)
app.stop_backup(); pump(0.5)
print("GESAMT", "OK" if all(ok) else "FEHLER")
