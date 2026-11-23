"""Bedienung: Seitenleiste angepinnt / versenkt / Menue oben mit Ausklappfeldern. «Empfangene Daten» bleibt
immer sichtbar unten links."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_layout"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
pump(1)
def log_left_bottom():
    log = app.log_frame
    x = log.winfo_rootx() - root.winfo_rootx(); y = log.winfo_rooty() - root.winfo_rooty()
    return log.winfo_ismapped() and x < 120 and y + log.winfo_height() > root.winfo_height() - 60
check("Pfeil-Knopf ohne Text", app.btn_pin.cget("text") in ("⇤", "⇥"))
check("angepinnt: Log unten links", log_left_bottom())
app.toggle_sidebar_pin(); pump(0.8)
check("versenkt: Log weiter unten links", log_left_bottom() and not app.side_outer.winfo_ismapped())
app.toggle_sidebar_pin(); pump(0.5)
app._drop_watch = lambda: None  # Xvfb: Maus steht nicht ueber dem Ausklappfeld
app.var_nav.set("top"); app.set_nav_layout("top"); pump(0.8)
check("Menü oben: Knöpfe je Abschnitt", app.topbar.winfo_ismapped() and len(app.top_buttons) >= 8
      and not app.side_outer.winfo_ismapped())
check("Menü oben: Log unten links", log_left_bottom())
app.toggle_dropdown("zeitmessung"); pump(0.5)
check("Ausklappfeld zeigt Zeitmessung", app.side_outer.winfo_ismapped() and app._drop_key == "zeitmessung")
check("nur dieser Abschnitt", sum(1 for _k, _t, b in app.side_boxes if b.winfo_ismapped()) == 1)
app.toggle_dropdown("zeitmessung"); pump(0.3)
check("nochmals klicken schliesst", not app.side_outer.winfo_ismapped())
app.toggle_dropdown("daten"); pump(0.3); app.close_dropdown(); pump(0.2)
app.set_nav_layout("side"); pump(0.8)
check("zurück zur Seitenleiste", app.side_outer.winfo_ismapped() and not app.topbar.winfo_ismapped()
      and sum(1 for _k, _t, b in app.side_boxes if b.winfo_ismapped()) >= 8)
app.rebuild_ui("light"); pump(1)
check("Neuaufbau (Design) ohne Fehler", log_left_bottom())
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
