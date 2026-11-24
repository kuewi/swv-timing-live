"""13''-Laptop (1280 x 720 nutzbar): Oberflaeche verkleinert sich, Dialoge passen auf den Bildschirm und die
Knoepfe bleiben sichtbar."""
import os, sys, shutil, time, tempfile, tkinter as tk
os.environ["SWV_SCREEN"] = "1280x720"
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_klein"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1280x672+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
pump(1)
check("Grösse automatisch verkleinert", app.ui_fit < 0.85 and app.ui_scale < 0.85)
def find(w, text):
    for c in w.winfo_children():
        try:
            if c.cget("text") == text:
                return c
        except tk.TclError:
            pass
        r = find(c, text)
        if r is not None:
            return r
    return None
def visible(btn):
    return btn is not None and btn.winfo_ismapped() and btn.winfo_rooty() + btn.winfo_height() <= 720 \
        and btn.winfo_rootx() + btn.winfo_width() <= 1280
rows = [["Startnummer", "Name 1", "Vorname 1", "Name 2", "Vorname 2", "Verein", "Kategorie"]]
rows += [[str(100 + i), f"Meier{i}", "Hans", f"Muster{i}", "Fritz", "WFV Muster", "SENIOREN"] for i in range(60)]
app.open_import_dialog(os.path.join(D, "startliste.xlsx"), rows); pump(1)
dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
check("Startliste importieren passt auf den Bildschirm", dlg.winfo_rooty() + dlg.winfo_height() <= 720)
check("Knopf «Importieren» sichtbar", visible(find(dlg, "Importieren")))
dlg.destroy()
app.open_report_dialog(); pump(0.8)
dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
check("Fehler melden passt", dlg.winfo_rooty() + dlg.winfo_height() <= 720)
dlg.destroy()
app.set_ui_size("1.1"); pump(1)
check("Grösse 110 % einstellbar", abs(app.ui_fit - 1.1) < 0.01)
app.set_ui_size("auto"); pump(1)
check("zurück auf Auto", app.ui_fit < 0.85)
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
