"""Wechsel Menü oben -> Seitenleiste (Fehlerbericht 27.11.2026): kein Hin-und-her der Anordnung, Felder rechts."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_layout"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1920x1000+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
pump(1)
app.settings["nav_layout"] = "top"; app.rebuild_ui(m.THEME); pump(2)
app.toggle_sidebar_pin(); pump(2)
n = {"c": 0}
orig = app.apply_font_scale
def counted():
    n["c"] += 1
    return orig()
app.apply_font_scale = counted
pump(3)
check("nach dem Anpinnen ruhig (kein Neuberechnen im Takt)", n["c"] <= 1)
check("Spalte neben den Karten", app.right_panel.grid_info().get("in") is app.content)
check("Ticker in der Spalte sichtbar", app.panel_ticker.winfo_ismapped())
check("«Als nächstes» nicht über die ganze Höhe", app.panel_next.winfo_height() < app.right_panel.winfo_height() * 0.8)
app.toggle_sidebar_pin(); pump(2)
check("zurück: Spalte links ab der Menüleiste", app.right_panel.grid_info().get("in") is app.main)
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
