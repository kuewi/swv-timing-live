import os, sys, shutil, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
import tempfile; D = os.path.join(tempfile.gettempdir(), "swv_test_sync"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D); m.data_dir = lambda: D
root = tk.Tk(); app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
cats = {1: "AKTIVE", 3: "AKTIVE", 205: "SENIOREN", 308: "VETERANEN", 401: "FRAUEN", 651: "JUNIOREN"}
app.participants = {n: {"nr": n, "p1": "x", "p2": "", "kategorie": c, "verein": "W", "notiz": "", "strafpunkte": 0} for n, c in cats.items()}
app.start_order = list(cats); app.rebuild_order_index()
app.on_data_changed(); root.update()
print([(c["name"], c["min"], c["max"]) for c in app.categories])
print("card titles", [c["title"].cget("text") if "title" in c else "" for c in app.cards][:6])
# Hand-Aenderung schaltet Automatik aus
app.lst_cat.selection_set(1); app.on_category_select()
app.e_cat_min.delete(0, "end"); app.e_cat_min.insert(0, "200"); app.e_cat_max.delete(0, "end"); app.e_cat_max.insert(0, "250")
app.category_update(); root.update()
print("auto", app.settings["cats_auto"], [(c["name"], c["min"], c["max"]) for c in app.categories][1])
app.on_data_changed(); print([(c["name"], c["min"], c["max"]) for c in app.categories][1])
print([l[0].strip()[10:] for l in app.log_lines if "Kategor" in l[0] or "Bereich" in l[0]])
