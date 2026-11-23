"""TM550 1.48 als Reserve in TIMING: Startnummern vorgeladen und uebernommen. Impuls nur bei der Reserve:
Abweichung melden und fragen, welches Geraet gilt."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_rtm148"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.message_dialog = lambda *a, **k: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
def logs(): return " | ".join(l[0] for l in app.log_lines[-80:])
o = list(range(21, 30))
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
A = m.SimCP()
B = m.SimCP(device="tm550", fw="1.48", clock_offset=-15.7)
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
app.connect_cp("127.0.0.1", A.port); pump(3)
app.start_backup(f"usb:socket://127.0.0.1:{B.port}"); pump(4)
check("Reserve TM550 1.48 erkannt, Vorladen möglich", app.cp_b_device == "tm550" and app.backup_preload_ok())
check("Reserve: nächste Nummer 21 vorgeladen", B.next[m.CH_START] == 21)
A.start(); B.start(); pump(2)
check("Reserve-Start mit Nummer 21", any(l.startswith("TN 0021") for l in
                                         [B.fmt(r[0], r[1], s_, ch, r[2]) for (ch, s_), r in B.recs.items()]))
check("Reserve: danach 22 vorgeladen", B.next[m.CH_START] == 22)
check("Uhrversatz gelernt", app.b_offset is not None and abs(app.b_offset + 15.7) < 0.1)
# Ziel nur bei der Reserve: Abweichung, vorlaeufig uebernommen, Rueckfrage
B.finish(); pump(5)
check("Abweichung gemeldet", "Abweichung" in logs() and 21 in app.results)
check("Rückfrage offen", any(d.winfo_exists() for d in getattr(app, "_b_dialogs", [])))
key = max((k for k in app.cp_recs if k[0] == "B" and k[2] == m.CH_FINISH), key=lambda k: app.cp_recs[k]["abs"])
app.backup_decide(key, "main", remember=True); pump(0.5)
check("Hauptgerät gilt: Zielzeit verworfen, 21 wieder auf der Strecke", 21 not in app.results
      and [c[1] for c in app.course] == [21] and app.cp_recs[key]["status"] == "reserve")
check("als «nur Reserve» aufgeführt", key in app.pending_impulses())
check("Rückfrage geschlossen", not any(d.winfo_exists() for d in getattr(app, "_b_dialogs", [])))
B.finish(); pump(5)
check("für die Sitzung: weitere Reserve-Impulse verworfen ohne Frage", 21 not in app.results
      and "Hauptgerät gilt für diese Sitzung" in logs())
A.finish(); pump(2)
check("Ziel vom Hauptgerät", 21 in app.results)
app.stop_backup(); app.disconnect_all(); pump(1); A.close(); B.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
