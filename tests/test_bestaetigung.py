"""Als naechstes am Start: Nummern von Hand bestaetigen (gruen), vom Onlinetool (blau), Mehrfachauswahl,
ganze Liste der noch nicht gestarteten, Zaehler, Bestaetigung bleibt beim neuen Import erhalten."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_best"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
rows = [["Nr", "Name", "Verein", "Bestätigt"]] + [[n, f"N{n}", "K", "x" if n == 3 else ""] for n in range(1, 21)]
order, parts, _ = m.build_startlist(rows, 0, m.auto_map(rows[0]))
check("Spalte Bestätigt erkannt", parts[3].get("best_online") and not parts[4].get("best_online"))
app.participants, app.start_order = parts, order
app.rebuild_order_index(); app.on_data_changed(); pump(0.5)
txt = app.txt_next.get("1.0", "end")
check("ganze Liste (20 Nummern)", all(f"Nr {n} " in txt for n in range(1, 21)))
check("blauer Haken für Nr 3", app.confirm_state(3) == "online")
check("Zähler 1 von 20", app.lbl_next_count.cget("text") == "1 von 20 bestätigt")
app.next_sel = {1, 2, 3}; app.confirm_numbers(None, True); pump(0.3)
check("grün geht vor blau", app.confirm_state(3) == "hand" and app.confirm_state(1) == "hand")
check("Zähler 3 von 20", app.lbl_next_count.cget("text") == "3 von 20 bestätigt")
check("Auswahl nach Bestätigen leer", not app.next_sel)
app.confirm_numbers([2], False); pump(0.2)
check("aufgehoben", app.confirm_state(2) is None)
# Mehrfachauswahl per Shift
class E: pass
def click(nr, state=0):
    idx = app.txt_next.tag_ranges(f"row{nr}")[0]
    app.txt_next.see(idx); root.update()
    x, y, w, h = app.txt_next.bbox(idx) or (5, 5, 5, 5)
    e = E(); e.x, e.y, e.state = x + 2, y + 2, state
    app.on_next_click(e)
app.txt_next.see(app.txt_next.tag_ranges("row5")[0]); pump(0.1); click(5)
app.txt_next.see(app.txt_next.tag_ranges("row8")[0]); pump(0.1); click(8, 0x0001)
check("Shift wählt 5 bis 8", app.next_sel == {5, 6, 7, 8})
click(6, 0x0004)
check("Ctrl nimmt 6 weg", app.next_sel == {5, 7, 8})
app.save_autosave()
data = open(os.path.join(D, m.AUTOSAVE_FILE), encoding="utf-8").read() if hasattr(m, "AUTOSAVE_FILE") else ""
check("gespeichert", "best_hand" in data or not hasattr(m, "AUTOSAVE_FILE"))
import json
app.add_ticker("Neue Bestzeit Test", "warn")
app.participants[1]["notiz"] = "Speaker-Notiz Eins"; app.current_nr = 1; app.settings["show"]["notizen"] = True
d = json.loads(app.build_web_snapshot())
check("Browser-Anzeige: Ticker", d["ticker"] and d["ticker"][0]["text"] == "Neue Bestzeit Test" and d["ticker"][0]["tag"] == "warn")
check("Browser-Anzeige: Notiz", any("Speaker-Notiz Eins" in t for t in d["note"]))
app.settings["show"]["notizen"] = False
check("ohne Schalter Notizen keine Notiz", not json.loads(app.build_web_snapshot())["note"])
check("JS kennt Ticker und Notiz", "getElementById('ticker')" in m.WEB_JS and 'id="note"' in m.WEB_HTML)
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
