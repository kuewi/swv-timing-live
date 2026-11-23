"""CP 545 ohne NET TIME bzw. ohne offenen Lauf: Startnummern vergibt die App (Test 22.11.2026)."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_zma"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
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
o = [101, 102, 103, 104, 105, 106, 107, 108]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
started = lambda: [c[1] for c in app.course]
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)

# 1) PTB SEQUENTIEL mit Lauf: #WP 026 AK C, liest 0 -> App nummeriert
S = m.SimCP(); S.mode = "PTB SEQUENTIEL 1-4"
app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(5)

check("PTB: Vorladen aus", not app.cp_caps["preload"] and "vergibt keine Startnummern" in logs())
n_err = logs().count("nach 3 Versuchen")
S.start(); pump(0.8); S.start(); pump(0.8)
check("PTB: App nummeriert 101, 102", started() == [101, 102])
check("PTB: keine Fehler-Wiederholung", logs().count("nach 3 Versuchen") == n_err)
S.finish(); pump(0.8)
check("PTB: Ziel ohne Nummer an 101", 101 in app.results and started() == [102])
# Zeitmessart wechselt auf NET TIME (neuer Lauf): wieder vorladen
S.mode = "NET TIME"; S.close_run(); pump(0.5); S.open_run(); pump(3)
check("NET TIME: Vorladen wieder ein", app.cp_caps["preload"] and S.next[m.CH_START] == 103)
S.start(); pump(1)
check("NET TIME: Nummer vom CP", 103 in started())
app.disconnect_all(); pump(1); S.close()

# 2) NET TIME ohne Lauf: #WP 026 AK F -> App nummeriert, ohne Wiederholungen
app.course.clear()
S = m.SimCP(); S.close_run()
app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(5)
check("ohne Lauf: Vorladen aus", not app.cp_caps["preload"])
S.start(); pump(1)
check("ohne Lauf: App gibt nächste Nummer", started() and started()[-1] == 104)
S.open_run(); pump(3)
check("Lauf geöffnet: Vorladen ein, nächste 105", app.cp_caps["preload"] and S.next[m.CH_START] == 105)
app.disconnect_all(); pump(1); S.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
