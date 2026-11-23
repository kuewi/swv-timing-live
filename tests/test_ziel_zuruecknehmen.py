"""Zielzeit in der App ungueltig schalten (Fehlimpuls): CP fuehrt das Boot als fertig. Die App versucht, die
Nummer auf den Zieleingang vorzuladen, und sagt bei Ablehnung, was am CP zu tun ist."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_zz"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.message_dialog = lambda *a, **k: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
def logs(): return " | ".join(l[0] for l in app.log_lines[-60:])
o = [201, 202, 203]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "SENIOREN", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
S = m.SimCP(); app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(4)
S.start(); pump(1.5); S.finish(); pump(1.5)
check("Ziel 201", 201 in app.results)
fkey = app.last_finish_key
app.invalidate_finish(fkey); pump(3)
check("201 wieder auf der Strecke", [c[1] for c in app.course] == [201] and 201 not in app.results)
check("Hinweis: CP nimmt Nr nicht an, «201 E4»", "201 E4" in logs())
S.finish(); pump(1.5)
check("nächster Zielimpuls (am CP ohne Nummer) gehört 201", 201 in app.results)
app.disconnect_all(); pump(1); S.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
