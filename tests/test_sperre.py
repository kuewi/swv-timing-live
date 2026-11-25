"""Start und Ziel sperren (Pause): Sperrnummer am CP vorgeladen, Impulse ignoriert, Schalter blinkt rot,
Rueckfrage bei Booten auf der Strecke, Freigeben stellt die naechste Nummer wieder ein."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_sperre"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
asked = []
app.message_dialog = lambda kind, title, msg, *a, **k: asked.append(title) or True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
def logs(): return " | ".join(l[0] for l in app.log_lines[-80:])
o = [101, 102, 103, 104]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
started = lambda: [c[1] for c in app.course]
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
S = m.SimCP()
app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(4)
check("vorgeladen 101", S.next[m.CH_START] == 101)

app.toggle_lock("lock_start"); pump(2)
check("Start gesperrt: Sperrnummer 9999 am CP", app.tset()["lock_start"] and S.next[m.CH_START] == 9999)
app.blink_tick(); app.blink_tick()
sw = app.timing_switches["lock_start"]
check("Schalter blinkt", getattr(sw, "_blink", None) is not None)
S.start(); pump(2)
check("Startimpuls ignoriert", started() == [] and "bei gesperrtem Start ignoriert" in logs())
check("Sperrnummer wieder vorgeladen", S.next[m.CH_START] == 9999)
check("als gesperrt aufgeführt", any(r["status"] == "locked" for r in app.cp_recs.values()))
app.toggle_lock("lock_start"); pump(2)
check("Freigegeben: 101 wieder vorgeladen", not app.tset()["lock_start"] and S.next[m.CH_START] == 101)
app.blink_tick()
check("Schalter blinkt nicht mehr", getattr(sw, "_blink", None) is None)

S.start(); pump(1.5)
check("Start 101", started() == [101])
app.toggle_lock("lock_finish"); pump(2)
check("Rückfrage bei Boot auf der Strecke", "Ziel sperren" in asked)
check("Ziel gesperrt: 9999 auf Eingang Ziel", S.next[m.CH_FINISH] == 9999)
S.finish(); pump(1.5)
check("Zielimpuls ignoriert", 101 not in app.results and started() == [101])
app.toggle_lock("lock_finish"); pump(2)
S.finish(); pump(1.5)
check("nach Freigabe Ziel an 101", 101 in app.results)
app.disconnect_all(); pump(1); S.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
