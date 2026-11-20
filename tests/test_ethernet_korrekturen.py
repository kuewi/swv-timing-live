import os, sys, shutil, time, tkinter as tk
os.environ["SWV_CP_HOSTS"] = "127.0.0.1"; os.environ["SWV_CP_PORTS"] = "17003,23503"
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import swv_live_ranking as m
from cpsim import CPSim
import tempfile; D = os.path.join(tempfile.gettempdir(), "swv_test"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D); m.data_dir = lambda: D
answers = []
sim = CPSim(17003, 23503, readback=False)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root)
app.dialog_hook = lambda kind, title, msg, default: (answers.append((kind, title)), True)[1]
def pump(sec=0.5):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.02)
o = [201, 202, 203, 204]
p = {n: {"nr": n, "p1": f"V{n}", "p2": f"N{n}", "kategorie": "SENIOREN", "verein": "Klub", "vnr": "", "staver": "",
         "fg": "", "bemerkung": "", "notiz": "", "strafpunkte": 0} for n in o}
app.participants, app.start_order = p, o; app.rebuild_order_index(); app.on_data_changed()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); app.toggle_connection(); pump(6)
print("status", app.lbl_conn_head.cget("text"), "sim next", sim.next, "readback flag", app.cp_readback)
sim.start(); pump(0.4); sim.start(); pump(0.6)
print("course", [c[1] for c in app.course])
# Ziel: CP ordnet 201 zu, eigentlich war es 202 (unbemerkt ueberholt)
sim.finish(); pump(1.2)
print("results", {k: v["str"] for k, v in app.results.items()}, "course", [c[1] for c in app.course])
app.reassign_last_finish(202); pump(2.0); print(app.log_tabs["all"][1].get("end-10l","end"))
print("after reassign results", {k: v["str"] for k, v in app.results.items()}, "course", [c[1] for c in app.course])
print("ticker", [t[1] for t in app.ticker[:4]])
# Nummer auf Strecke zu unbekannter Nummer 250 aendern
app.cp_change_number(app.course_key(201), 201, 250); pump(1.5)
print("course", [c[1] for c in app.course], "dialogs", [t.title() for t in root.winfo_children() if isinstance(t, tk.Toplevel)])
print("order", app.start_order)
for t in root.winfo_children():
    if isinstance(t, tk.Toplevel): t.destroy()
# Theme wechseln waehrend Verbindung
app.toggle_theme(); pump(1.5)
print("after theme: status", app.lbl_conn_head.cget("text"), "btn", app.btn_connect.cget("text"), "course panel:", app.txt_course.get("1.0","end").strip().splitlines()[:2])
sim.start(); pump(1)
print("course", [c[1] for c in app.course])
# Storno mit AK F (falsche seq)
app.cp_query("#WC 013 01 0099    C", "ack", on_ok=lambda i: print("ok?"), on_fail=lambda r: print("fail:", r)); pump(1)
# zurueck auf RS232
app.var_conn.set("rs232"); app.on_conn_mode_change(); pump(1.5)
print("rs232: cp", app.cp, "course packed", app.panel_course.winfo_manager(), "status", app.lbl_conn_head.cget("text"))
print("answers", answers)
print("settings conn", app.settings["conn"], app.settings["theme"])
sim.close()
