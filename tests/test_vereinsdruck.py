"""Vereinswechsel auf dem CP-Papierstreifen (#PL)."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_vd"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.message_dialog = lambda *a, **k: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
clubs = {1: "Pontoniere Zürich", 2: "Pontoniere Zürich", 3: "RC Rheinfelden", 4: "RC Rheinfelden", 5: "Wasserfahrer Bärn"}
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": c, "notiz": "",
                        "strafpunkte": 0} for n, c in clubs.items()}
app.start_order = list(clubs); app.rebuild_order_index(); app.on_data_changed()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
S = m.SimCP(); printed = []
S.on_event = lambda t: printed.append(t[7:]) if t.startswith("Druck: ") else None
app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(5)
check("erster Verein vor dem ersten Start", printed == ["> Pontoniere Zuerich (2)"])
S.start(); pump(1)
check("innerhalb Verein nichts", len(printed) == 1)
S.start(); pump(1)
check("nach letztem Boot: nächster Verein", printed[-1] == "> RC Rheinfelden (2)")
S.start(); pump(1); S.start(); pump(1)
check("dritter Verein, Umlaut", printed[-1] == "> Wasserfahrer Baern (1)" and len(printed) == 3)
app.disconnect_all(); pump(0.5)
app.connect_cp("127.0.0.1", S.port); pump(5)
check("Neuverbinden druckt nicht doppelt", len(printed) == 3)
app.toggle_print_club(); S.start(); pump(1)
check("Schalter aus: nichts", len(printed) == 3)
check("Breite", all(len(p) <= m.CP_PRINT_WIDTH for p in printed))
check("Grund im Log", any("Vereinsdruck: nichts gedruckt" in l[0] for l in app.log_lines))
app.disconnect_all(); pump(0.5); S.close()
# Start ausserhalb der Reihenfolge: Startliste 11 (A), 13 (A), 12 (B); gestartet 11, dann 12
app.toggle_print_club()
c2 = {11: "Club A", 13: "Club A", 12: "Club B"}
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": c, "notiz": "",
                        "strafpunkte": 0} for n, c in c2.items()}
app.start_order = [11, 13, 12]; app.rebuild_order_index(); app.on_data_changed()
app._club_printed, app._print_prev_club = set(), None
app.cp_recs.clear(); app.course = []; app.results.clear(); app.last_start_nr = None
S = m.SimCP(); printed.clear()
S.on_event = lambda t: printed.append(t[7:]) if t.startswith("Druck: ") else None
app.connect_cp("127.0.0.1", S.port); pump(5)
S.next[m.CH_START] = 11; S.start(); pump(1.5)
S.next[m.CH_START] = 12; S.start(); pump(1.5)
check("Start ausserhalb der Reihenfolge: Verein sofort gedruckt", "> Club B (1)" in printed)
app.disconnect_all(); pump(0.5); S.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
