"""Korrekturen in der App, wie beim echten CP 545 (#WC 013 wird mit AK R abgelehnt)."""
import os, sys, shutil, time, tempfile, tkinter as tk
os.environ["SWV_CP_HOSTS"] = "127.0.0.1"; os.environ["SWV_CP_PORTS"] = "17004,23504"
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import swv_live_ranking as m
from cpsim import CPSim
D = os.path.join(tempfile.gettempdir(), "swv_test_korr"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
sim = CPSim(17004, 23504)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.5):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
ok = []
def check(name, cond): ok.append(cond); print(("OK  " if cond else "FEHLER ") + name)
o = [201, 202, 203, 204, 205]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "SENIOREN", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); app.toggle_connection(); pump(5)
check("verbunden, 201 vorgeladen", sim.next[1] == 201)
# 1) Testnummer einfuegen vor 203
check("Testnummer 999 eingefuegt", app.insert_number("999", 203) is None and app.start_order[:4] == [201, 202, 999, 203])
for _ in range(3): sim.start(); pump(0.6)
check("Start 201 202 999", [c[1] for c in app.course] == [201, 202, 999])
txt = app.txt_course.get("1.0", "end")
check("Fahrstrecke: 999 oben, 201 unten", txt.index("Nr 999") < txt.index("Nr 202") < txt.index("Nr 201"))
# 2) Nummer aendern 202 -> 205 (nur App)
app.cp_change_number(app.course_key(202), 202, 205); pump(0.5)
check("202 jetzt 205", [c[1] for c in app.course] == [201, 205, 999])
# 3) Ausgeschieden 201 (vorne): CP muss Ziel auf 205 (CP-Nr 202) vorgeladen bekommen
app.cp_cancel_start(201); pump(1.5)
check("201 weg", [c[1] for c in app.course] == [205, 999])
check("CP Zielnummer 202 vorgeladen", sim.next[4] == 202)
sim.finish(); pump(1.0)
check("Ziel CP-202 -> Nr 205", 205 in app.results and 202 not in app.results)
# 4) unbemerkt ueberholt: App erwartet 999, in Wirklichkeit kam 203
sim.start(); pump(0.6)   # 203 startet
sim.finish(); pump(1.0)
check("App gibt Zielzeit dem erwarteten Boot 999", 999 in app.results and [c[1] for c in app.course] == [203])
app.reassign_last_finish(203); pump(1.0)
check("umgebucht: 203 hat Zeit, 999 wieder auf Strecke", 203 in app.results and 999 not in app.results
      and [c[1] for c in app.course] == [999])
sim.finish(); pump(1.0)
check("naechstes Ziel -> Nr 999", 999 in app.results and not app.course)
print("Resultate", {k: v["str"] for k, v in app.results.items()})
print("Ticker", [t[1] for t in app.ticker[:4]])
print("GESAMT", "OK" if all(ok) else "FEHLER")
sim.close()
