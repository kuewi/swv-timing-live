"""Nachstellung Fehlerbericht 20261121-022304-ad4f: Lauf am CP geschlossen und mit derselben Nummer wieder
geoeffnet (Seq beginnt wieder bei 1), dazu Wechsel der Verbindung mit gepufferten Zeiten."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_ad4f"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
m.DEFAULT_SETTINGS["timing"]["prec_digits"] = 2  # Bericht mit 1/100
m.DEFAULT_SETTINGS["_mig_prec10"] = True
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
o = [1, 201, 202, 203, 204, 205]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE" if n < 100 else "SENIOREN",
                        "verein": "K", "notiz": "", "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
sim = m.SimCP()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
app.connect_cp("127.0.0.1", sim.port); pump(2.5)
day = int(m.local_abs() // 86400)
def L(s): sim.replay_line(s.replace("DDDD", f"{day:4d}")); pump(0.25)
for line in ("OP 01  00  NET TIME",
             "TN    1    1 M1  3:09:24.35500  DDDD", "TN    1    1 M4  3:10:25.29700  DDDD",
             "TN  201    2 M1  3:10:45.98300  DDDD", "TN  201    2 M4  3:11:50.80700  DDDD",
             "TN  202    3 M1  3:12:02.45300  DDDD", "TN  202    3 M4  3:12:29.74600  DDDD"):
    L(line)
check("erste Runde: 1, 201, 202 im Ziel", {1, 201, 202} <= set(app.results))
L("CL 01"); L("OP 01  00  NET TIME")
L("TN  203    1 M1  3:15:15.13100  DDDD")
check("nach Wiederöffnen: 203 auf der Strecke", [c[1] for c in app.course] == [203])
L("TN  204    2 M1  3:16:26.91500  DDDD")
L("TN  203    1 M4  3:17:31.67800  DDDD"); L("RR    1  203        2:16.54000")
L("TN  204    2 M4  3:17:47.90900  DDDD"); L("RR    1  204        1:20.99000")
check("203 und 204 im Ziel", abs(app.results.get(203, {}).get("secs", 0) - 136.54) < 0.02
      and abs(app.results.get(204, {}).get("secs", 0) - 80.99) < 0.02)
check("frühere Resultate unverändert", abs(app.results[201]["secs"] - 64.82) < 0.02
      and abs(app.results[202]["secs"] - 27.29) < 0.02)
check("alte Runde abgelegt", any(k[1] == 1001 for k in app.cp_recs))
# Neubeginn ohne CL/OP (z.B. Speicher geloescht): gleiche Seq, andere Zeit
L("TN  205    1 M1  3:20:00.00000  DDDD")
check("Kollision erkannt, 205 auf der Strecke", [c[1] for c in app.course] == [205]
      and any(k[1] == 2001 for k in app.cp_recs))
# Wechsel der Verbindung: Zielzeit faellt in die Zeit ohne Verbindung
app.cp.stop(); pump(1.0)
sim.replay_line(f"TN  205    1 M4  3:21:00.00000  {day:4d}"); pump(0.2)
check("CP puffert ohne Verbindung", sim.pending)
app.connect_cp("127.0.0.1", sim.port); pump(4.5)
check("nach neuem Verbinden: gepufferte Zielzeit übernommen", abs(app.results.get(205, {}).get("secs", 0) - 60.0) < 0.02)
# Autosave und Wiederherstellen mit abgelegten Runden
app.save_autosave()
app.cp.stop(); pump(0.5); sim.close()
print("GESAMT", "OK" if all(ok) else "FEHLER")
