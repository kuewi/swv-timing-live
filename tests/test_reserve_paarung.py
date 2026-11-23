"""Reserve-Geraet: Paarung nach Geraetezeit (bekannter Uhrversatz), einstellbare Wartezeit, verspaetete Zeile
des Hauptgeraets ergibt kein Doppel und keine Warnung."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_rpaar"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.main_connected = lambda: True
app.backup_connected = lambda: True
o = [11, 12, 13]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
app.var_conn.set("ethernet"); app.on_conn_mode_change()
app.reset_caps("cp545"); app.cp_caps["preload"] = False; app.cp_run = 1
base = m.local_abs()
def line(ch, seq, t): return {"kind": "time", "type": "TN", "nr": 0, "seq": seq, "manual": True, "ch": ch,
                              "tod": t % 86400, "day": int(t // 86400), "abs": t, "answer": False, "text": ""}
app.b_offset = 5.0
# Reserve-Zeile zuerst, Hauptzeile 4 s spaeter am PC (Rx-Fenster waere vorbei), gleiche Geraetezeit
app.backup_time(line(1, 1, base + 5.0)); app.b_pend[-1][0] -= 4.0
app.backup_note_main(line(1, 1, base + 0.01))
check("Paarung nach Gerätezeit trotz 4 s Verzug", not app.b_pend and not app.a_pend)
check("Wartezeit Standard 3 s", app.backup_wait() == 3.0)
app.settings["conn"]["backup_wait_s"] = 6
check("Wartezeit einstellbar", app.backup_wait() == 6.0)
# Reserve uebernimmt nach Ablauf der Wartezeit, Hauptzeile kommt danach
app.backup_time(line(1, 2, base + 25.0)); app.b_pend[-1][0] -= 7.0
app.backup_tick()
check("Reserve-Zeit übernommen", any(k[0] == "B" and r["nr"] == 11 for k, r in app.cp_recs.items()))
late = line(1, 2, base + 20.0)
app.on_cp_time(late, "A"); n_warn = len(app.log_lines)
app.backup_note_main(late)
check("verspätete Hauptzeile: Doppel erkannt", app.cp_recs[("A", 1, 1, 2)]["status"] == "dup")
check("keine Warnung, nicht wartend", not app.a_pend and "kam verspätet" in app.log_lines[-1][0])
check("nur ein Boot auf der Strecke", [c[1] for c in app.compute_course()] == [11])
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
