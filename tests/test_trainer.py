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
keys("K1"); pump(0.6); keys("K1"); pump(0.6); keys("K1"); pump(0.6)
check("drei Starts per Taste E1", [c[1] for c in app.course] == [1, 2, 3])
check("Papierstreifen zeigt Starts", app.tr_paper.get("1.0", "end").count("TN") >= 3)
keys("2 R 0"); pump(2.0)
check("2 R 0 storniert Start 2", [c[1] for c in app.course] == [1, 3])
keys("3 R E1 7 Enter"); pump(1.0)
check("3 R E1 7 Enter nummeriert um", [c[1] for c in app.course] == [1, 7])
keys("1 R 0 ."); pump(1.0)
check("1 R 0 . disqualifiziert", [c[1] for c in app.course] == [7])
keys("K4"); pump(1.0)
check("Ziel per E4", 7 in app.results and not app.course)
app.trainer_case_cable(); pump(1.5)
check("Kabel ab: App merkt Abbruch", app.sim.offline)
app.sim.set_cable(True); app.tr_cable.set(True); pump(6.0)
check("Kabel wieder: App verbunden", app.cp is not None and app.sim.clients)
# Display und Menue CP 545
txt = app.tr_disp.cget("text")
check("CP-Display: Laufnummer und NT in der obersten Zeile", txt.split("\n")[0].startswith(f"{app.sim.run:02d}")
      and txt.split("\n")[0].rstrip().endswith("NT"))
keys("L4"); pump(0.5)
check("rote Taste 4: Balken statt NT", app.sim.inputs[4] == 0 and app.tr_disp.cget("text").split("\n")[0].rstrip().endswith("▬▬"))
n = len(app.sim.recs); app.sim.impulse(4, manual=False); pump(0.3)
check("Buchse 4 gesperrt", len(app.sim.recs) == n)
keys("L4"); pump(0.3)
keys("F"); pump(0.3)
check("F: Hauptmenü mit Lauf schliessen", "Hauptmenü" in app.tr_disp.cget("text") and "Lauf schliessen" in app.tr_disp.cget("text"))
keys("▼ ▼ ▼ ▼ ▼ ▼ Enter"); pump(0.3)
check("Einstellungen geöffnet", "Einstellungen" in app.tr_disp.cget("text") and "Präzision" in app.tr_disp.cget("text"))
keys("Enter"); pump(0.3)
check("Präzision: Cursor auf eingestelltem Wert", "▶1/10 " in app.tr_disp.cget("text").replace("▶1/10\n", "▶1/10 \n"))
keys("F F F"); pump(0.3)
check("F schliesst das Menü", not app.tr["menu"])
app.sim.restart(); pump(0.5)
check("Ethernet aus nach Neustart", app.sim.eth_off)
keys("F"); keys("▼ ▼ ▼ ▼ ▼ ▼ Enter")  # Lauf offen: Cursor auf Rangliste, Einstellungen an 8. Stelle
items = [l for l, _a in app.tr["menu"][-1]["items"]]
eth = items.index("Ethernet")
keys(" ".join(["▼"] * eth) + " Enter Enter"); pump(0.3)
check("Einstellungen › Ethernet › Std Connexion schaltet Ethernet ein", not app.sim.eth_off)
keys("F F F"); pump(6)
path = app.trainer_save()
check("Protokoll gespeichert", os.path.exists(path) and "Taste E1" in open(path, encoding="utf-8").read())
app.trainer_close(); pump(0.3)

# --- TM550
win = app.open_trainer("tm550"); pump(5.0)
check("Trainer TM550 verbunden", app.cp_device == "tm550" and app.sim.device == "tm550")
n0 = len(app.course)
app.trainer_key("E1"); pump(0.8)
check("TM550 Start Nummer aus der App", len(app.course) == n0 + 1)
pump(6); keys("SHIFT E4"); pump(1.5)
check("TM550 SHIFT+E4: senden, App sperrt Ziel", app.sim.inputs[4] == 1 and app.tset()["lock_finish"])
keys("SHIFT E4 SHIFT E4"); pump(1.5)
check("TM550 wieder offen", app.sim.inputs[4] == 0 and not app.tset()["lock_finish"])
keys("◀"); pump(0.2)
check("◀: Menü Run", app.tr["menu"] and app.tr["menu"][-1]["title"] == "Run")
keys("◀"); pump(0.2)
check("◀ aus Run: Hauptmenü mit 11 Einträgen", len(app.tr["menu"][-1]["items"]) == 11)
keys("▼ ▼ ▼ OK"); pump(0.2)
check("Timing modes", app.tr["menu"][-1]["title"] == "Timing modes")
keys("◀ ◀"); pump(0.2)
check("◀ schliesst", not app.tr["menu"])
app.trainer_close(); pump(0.3)
app.disconnect_all(); pump(0.5)
app.sim.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
