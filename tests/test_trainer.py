"""Trainingsfenster: Tastenfolgen am nachgebauten CP 545 und TM550 wirken wie am echten Geraet auf die App."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_trainer"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)

root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.open_folder = lambda *a: None
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
o = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()

def keys(seq):
    for k in seq.split():
        app.trainer_key(k); pump(0.05)

# --- CP 545
win = app.open_trainer("cp545"); pump(3.0)
check("Trainer CP verbunden", app.cp is not None and app.cp_device == "cp545" and win.winfo_exists())
keys("E1"); pump(0.6); keys("E1"); pump(0.6); keys("E1"); pump(0.6)
check("drei Starts per Taste E1", [c[1] for c in app.course] == [1, 2, 3])
check("Papierstreifen zeigt Starts", app.tr_paper.get("1.0", "end").count("TN") >= 3)
keys("2 R 0"); pump(2.0)
check("2 R 0 storniert Start 2", [c[1] for c in app.course] == [1, 3])
keys("3 R E1 7 Enter"); pump(1.0)
check("3 R E1 7 Enter nummeriert um", [c[1] for c in app.course] == [1, 7])
keys("1 R 0 ."); pump(1.0)
check("1 R 0 . disqualifiziert", [c[1] for c in app.course] == [7])
keys("E4"); pump(1.0)
check("Ziel per E4", 7 in app.results and not app.course)
app.trainer_case_cable(); pump(1.5)
check("Kabel ab: App merkt Abbruch", app.sim.offline)
app.sim.set_cable(True); app.tr_cable.set(True); pump(6.0)
check("Kabel wieder: App verbunden", app.cp is not None and app.sim.clients)
path = app.trainer_save()
check("Protokoll gespeichert", os.path.exists(path) and "Taste E1" in open(path, encoding="utf-8").read())
app.trainer_close(); pump(0.3)

# --- TM550
win = app.open_trainer("tm550"); pump(5.0)
check("Trainer TM550 verbunden", app.cp_device == "tm550" and app.sim.device == "tm550")
n0 = len(app.course)
app.trainer_key("E1"); pump(0.8)
check("TM550 Start Nummer aus der App", len(app.course) == n0 + 1)
app.trainer_close(); pump(0.3)
app.disconnect_all(); pump(0.5)
app.sim.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
