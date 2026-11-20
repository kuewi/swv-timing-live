import os, sys, shutil, time, tkinter as tk
os.environ["SWV_CP_HOSTS"] = "127.0.0.1"; os.environ["SWV_CP_PORTS"] = "17000,23500"
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import swv_live_ranking as m
from cpsim import CPSim
import tempfile; D = os.path.join(tempfile.gettempdir(), "swv_test"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D); m.data_dir = lambda: D
answers = []
sim = CPSim()
root = tk.Tk(); root.geometry("1920x1080+0+0")
app = m.LiveRankingApp(root)
app.dialog_hook = lambda kind, title, msg, default: (answers.append((kind, title, msg)), True)[1]
def pump(sec=0.5):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.02)
# Startliste
o = [101, 102, 103, 104, 105, 301, 302]
p = {n: {"nr": n, "p1": f"Vor{n}", "p2": f"Nach{n}", "kategorie": "AKTIVE" if n < 300 else "SENIOREN",
         "verein": "Klub A" if n < 104 else "Klub B", "vnr": "", "staver": "", "fg": "", "bemerkung": "",
         "notiz": "", "strafpunkte": 0} for n in o}
app.participants, app.start_order = p, o; app.rebuild_order_index(); app.on_data_changed()
pump(0.3)
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.3)
print("panel course packed:", app.panel_course.winfo_manager())
app.toggle_connection(); pump(3)
print("status:", app.lbl_conn_head.cget("text"), "| found", app.cp_found)
print("sim received:", sim.received)
print("sim next:", sim.next, "cp_next_start", app.cp_next_start)
# Starts
sim.start(); pump(0.6); print("course", [c[1] for c in app.course], "sim next", sim.next)
sim.start(); pump(0.6); print("course", [c[1] for c in app.course], "sim next", sim.next)
pump(1.2)
print("LIVE:", app.lbl_live.cget("text"))
print("course panel:\n", app.txt_course.get("1.0", "end").strip())
print("next panel:\n", app.txt_next.get("1.0", "end").strip())
# Ueberholen: 102 vor 101
app.cp_set_next_finish(102); pump(0.8)
print("override", app.finish_override, "sim next4", sim.next[4], [c[1] for c in app.course])
sim.finish(); pump(1.2)
print("results", {k: v["str"] for k, v in app.results.items()}, "course", [c[1] for c in app.course])
sim.finish(); pump(1.2)
print("results", {k: v["str"] for k, v in app.results.items()}, "course", [c[1] for c in app.course])
# Einfuegen vor 104 im Panel -> 900? Testnummer abgelehnt; 150 neu
print("insert err:", app.insert_number("960", 104))
print("insert:", app.insert_number("150", 104), app.start_order)
pump(1); print("sim next after insert", sim.next[1], "| next panel bottom:", app.txt_next.get("end-3l", "end").strip())
tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
print("dialogs:", [t.title() for t in tops], [t.winfo_geometry() for t in tops])
for t in tops: t.destroy()
# Start 103 -> wait next 150? order: 101 102 103 150 104
sim.start(); pump(0.8)
print("started", app.last_start_nr, "sim next", sim.next[1])
# Nummer aendern 103 -> 105
app.cp_change_number(app.course_key(103), 103, 105); pump(1.0)
print("course after renumber", [c[1] for c in app.course])
# Ausgeschieden 105
app.cp_cancel_start(105); pump(1.0)
print("course after dnf", [c[1] for c in app.course], "dnf", app.dnf)
print("ticker:", [t[1] for t in app.ticker[:6]])
# Verbindungsabbruch
sim.drop_clients(); pump(4)
print("status after drop:", app.lbl_conn_head.cget("text"))
sim.start(); pump(1); print("course", [c[1] for c in app.course])
print("ALL:", app.log_tabs["all"][1].get("end-12l", "end").strip()); print("answers", answers)
print("focus log tail:\n", app.log_tabs["focus"][1].get("end-15l", "end").strip())
app.on_close() if False else None
sim.close()
