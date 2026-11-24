"""Startliste von Hand eingeben: Nummern, Bereiche, Zeilen mit Angaben, Ersetzen und Anhaengen."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_slh"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
it, w = m.parse_manual_startlist("1-3, 201 - 203\n301 302")
check("Nummern und Bereiche", [n for n, _f in it] == [1, 2, 3, 201, 202, 203, 301, 302] and not w)
it, w = m.parse_manual_startlist("Nr\tName\tVerein\n101\tMeier\tMuster\tWFV Muster\n102;Keller;;RC Rheinfelden")
check("Zeilen mit Angaben, Kopfzeile übersprungen", it == [(101, ["Meier", "Muster", "WFV Muster"]),
                                                           (102, ["Keller", "", "RC Rheinfelden"])])
it, w = m.parse_manual_startlist("5, 5, 9-1, 1-900, x")
check("Warnungen", [n for n, _f in it] == [5] and len(w) == 4)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.message_dialog = lambda *a, **k: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
app.open_manual_startlist(); pump(0.5)
dlg, txt, var, take, refresh = app.manual_startlist_dlg
txt.insert("1.0", "3, 1, 2\n101\tMeier\tMuster\tWFV Muster"); refresh()
check("Vorschau zählt", "4 Starts" in [c for c in dlg.winfo_children() if isinstance(c, tk.Label)][1].cget("text"))
take(); pump(0.3)
check("Startliste in Reihenfolge", app.start_order == [3, 1, 2, 101] and app.participants[101]["verein"] == "WFV Muster")
check("Kategorie aus Range", app.participants[1]["kategorie"] == app.range_category(1)["name"])
app.open_manual_startlist(); pump(0.3)
dlg, txt, var, take, refresh = app.manual_startlist_dlg
check("Standard Anhängen bei bestehender Liste", var.get() == "append")
txt.insert("1.0", "2, 4-5"); refresh(); take(); pump(0.3)
check("angehängt, doppelte übersprungen", app.start_order == [3, 1, 2, 101, 4, 5])
app.open_manual_startlist(); pump(0.3)
dlg, txt, var, take, refresh = app.manual_startlist_dlg
var.set("replace"); txt.insert("1.0", "7-8"); refresh(); take(); pump(0.3)
check("ersetzt", app.start_order == [7, 8] and 101 not in app.participants)
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
