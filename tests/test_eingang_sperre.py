"""Eingaenge am Geraet sperren (Gruppe P/Q, 25.11.2026): App schreibt #WP 006, liest #RP 006 zurueck, folgt
der roten Sperrtaste am CP 545 (Abfrage) und SHIFT + Ex am TM550 (&P 023 von selbst). TM550 &P 002 mit anderen
Eingaengen gibt eine Warnung, falsche Uhr am Geraet ebenfalls."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_eingang"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
m.LOCK_POLL_S = 1.0
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.message_dialog = lambda *a, **k: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
def logs(): return " | ".join(l[0] for l in app.log_lines[-120:])
o = [101, 102, 103]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
check("Sperrnummer Standard 9999, Präzision 1/10", app.lock_number() == 9999 and app.tset()["prec_digits"] == 1)

# --- CP 545
S = m.SimCP()
app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(6)
app.toggle_lock("lock_start"); pump(2)
check("CP: Start gesperrt -> #WP 006 01 0", S.inputs[1] == 0)
n = len(S.recs)
S.impulse(1, manual=False); pump(0.5)
check("CP: Buchse 1 gesperrt, kein Impuls", len(S.recs) == n)
S.impulse(1, manual=True); pump(1)
check("CP: grüne Taste löst trotzdem aus (M1)", len(S.recs) == n + 1)
app.toggle_lock("lock_start"); pump(2)
check("CP: freigegeben -> 1", S.inputs[1] == 1 and not app.tset()["lock_start"])
S.cycle_input(4); pump(4)
check("CP: rote Sperrtaste 4 am Gerät -> Ziel in der App gesperrt", app.tset()["lock_finish"]
      and "am CP 545" in logs())
S.cycle_input(4); pump(4)
check("CP: wieder geöffnet -> Ziel frei", not app.tset()["lock_finish"])
app.disconnect_all(); pump(1); S.close()

# --- TM550 1.48
S = m.SimCP(device="tm550", fw="1.48", clock_offset=-58000)
app.reset_caps("tm550"); app.connect_cp("127.0.0.1", S.port); pump(9)
app.toggle_lock("lock_start"); pump(10)
check("TM550: Start gesperrt -> 2", S.inputs[1] == 2)
n = len(S.recs)
S.impulse(1, manual=True); pump(0.5)
check("TM550: gesperrt, auch Taste E1 ohne Impuls", len(S.recs) == n)
app.toggle_lock("lock_start"); pump(4)
check("TM550: freigegeben -> 0", S.inputs[1] == 0)
S.cycle_input(4); pump(1.5)
check("TM550: SHIFT+E4 (senden) -> Ziel gesperrt", app.tset()["lock_finish"])
S.cycle_input(4); S.cycle_input(4); pump(1.5)
check("TM550: zweimal weiter -> offen", not app.tset()["lock_finish"])
S.send("&P 002 03 01 01 03 00 00 00 00 00 00 00 00 00 01"); pump(1)
check("TM550: andere Eingänge gemeldet", "misst Start E1, Ziel E3" in logs())
S.start(); pump(1.5); S.start(); pump(1.5)
check("TM550: falsche Uhr gemeldet mit Menüweg", "Synchronisation › Manual oder GPS" in logs())
app.disconnect_all(); pump(1); S.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
