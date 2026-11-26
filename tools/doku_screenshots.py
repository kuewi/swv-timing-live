"""Bilder fuer das Benutzerhandbuch und das Training: docs/handbuch/bilder/*.png.
Nur bei «update Doku» laufen lassen. Braucht eine Anzeige (Xvfb) und ImageMagick 'import'.
Alle Namen sind erfunden (Demo-Daten aus tools/screenshot.py)."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import swv_live_ranking as m  # noqa: E402
from screenshot import DEMO, TIMES  # noqa: E402

OUT = os.path.join(ROOT, "docs", "handbuch", "bilder")
W, H = 1600, 900


def main():
    data = tempfile.mkdtemp()
    m.data_dir = lambda: data
    root = tk.Tk()
    root.geometry(f"{W}x{H}+0+0")
    app = m.LiveRankingApp(root)
    app.dialog_hook = lambda *a: True
    app._drop_watch = lambda: None  # Ausklappfeld nicht wegen der Mausposition schliessen
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        os.remove(os.path.join(OUT, name))

    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    def shot(name, win=None):
        pump(0.6)
        path = os.path.join(OUT, name + ".png")
        if win is None:
            subprocess.run(["import", "-window", "root", "-crop", f"{W}x{H}+0+0", path], check=True)
        else:
            win.update()
            wid = win.wm_frame() or hex(win.winfo_id())
            subprocess.run(["import", "-window", wid, path], check=True)
        print(path)

    def dialogs():
        return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]

    def press(win, text):
        stack = [win]
        while stack:
            w = stack.pop()
            try:
                if w.cget("text") == text:
                    w.invoke() if hasattr(w, "invoke") else w.event_generate("<Button-1>")
                    return True
            except tk.TclError:
                pass
            stack.extend(w.winfo_children())
        print("Knopf fehlt:", text)
        return False

    def close_dialogs():
        for w in dialogs():
            if w is not getattr(app, "trainer", None):
                w.destroy()
        pump(0.2)

    # Leere App nach dem ersten Start
    shot("01_start_leer")

    app.e_event_name.insert(0, "Demo-Wettkampf")
    app.e_event_from.insert(0, "21.11.2026")
    app.save_event_fields(normalize=True)
    rows = [["Nr", "Vorname", "Name", "Verein", "Kategorie"]]
    for nr, name, club, cat in DEMO:
        first, last = name.split(" ", 1)
        rows.append([nr, first, last, club, cat])
    app.open_import_dialog(os.path.join(data, "Startliste_Demo.xlsx"), rows)
    pump(1.0)
    shot("05_import_dialog")
    close_dialogs()

    app.open_manual_startlist()
    pump(0.8)
    shot("06_startliste_eingeben")
    close_dialogs()

    app.open_import_dialog(os.path.join(data, "Startliste_Demo.xlsx"), rows)
    pump(0.8)
    press(dialogs()[-1], "Importieren")
    pump(0.8)
    close_dialogs()
    for nr, secs in TIMES.items():
        app.register_final(nr, secs, m.fmt_secs(secs), source="Demo")
    pump(0.5)

    sim = m.SimCP()
    app.var_conn.set("ethernet")
    app.on_conn_mode_change()
    app.connect_cp("127.0.0.1", sim.port)
    pump(3.0)
    for _ in range(2):
        sim.start()
        pump(2.5)  # naechste Nummer ist vorgeladen, bevor das naechste Boot startet
    pump(2.0)
    close_dialogs()
    shot("02_uebersicht")

    for key, name in (("verbindung", "03_verbindung"), ("zeitmessung", "04_zeitmessung"),
                      ("wettkampf", "03a_wettkampf"), ("startliste", "07_startliste"), ("manuell", "07a_manuell"), ("speaker", "07b_speaker"), ("kategorien", "08_kategorien"),
                      ("online", "09_onlinetool"), ("web", "10_browser_anzeige"),
                      ("daten", "11_daten")):
        if key not in app.top_buttons:
            print("fehlt:", key)
            continue
        app.toggle_dropdown(key)
        pump(0.8)
        shot(name)
        app.close_dropdown()
        pump(0.3)

    # Ziel gesperrt (Rueckfrage wegen Booten auf der Strecke mit Ja beantworten)
    ask = m.messagebox.askyesno
    m.messagebox.askyesno = lambda *a, **k: True
    app.toggle_lock("lock_finish")
    pump(1.5)
    shot("12_ziel_gesperrt")
    app.toggle_lock("lock_finish")
    m.messagebox.askyesno = ask
    pump(0.5)

    app.open_report_dialog()
    pump(0.8)
    shot("13_fehler_melden")
    close_dialogs()

    # Seitenleiste angepinnt
    app.set_nav_layout("side")
    pump(1.5)
    shot("14_seitenleiste")
    app.set_nav_layout("top")
    pump(1.0)

    if app.cp is not None:
        app.cp.stop()
    sim.close()
    pump(0.5)

    for dev in ("cp545", "tm550"):
        win = app.open_trainer(dev)
        pump(3.0)
        shot(f"20_trainer_{dev}_leer", win)
        if dev == "cp545":
            for k in ("K1", "K1", "K4"):
                app.trainer_key(k)
                pump(0.6)
        else:
            for k in ("E1", "E1", "E4"):
                app.trainer_key(k)
                pump(0.6)
        pump(2.0)
        win.lift()
        pump(0.5)
        shot(f"21_trainer_{dev}_lauf", win)
        app.trainer_close()
        pump(0.5)

    if app.sim is not None:
        app.sim.close()
    shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    main()
