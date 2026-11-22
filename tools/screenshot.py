"""Screenshots fuer das aktuelle Release: docs/screenshots/ui_v<APP_VERSION>.png und die Trainingsfenster
sim_cp545_v<APP_VERSION>.png, sim_tm550_v<APP_VERSION>.png.
Aeltere Screenshots in diesem Ordner werden entfernt, README zeigt den neuen.
Braucht eine Anzeige (unter Linux z.B. Xvfb :99) und ImageMagick 'import'.
Alle Namen sind erfunden."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import swv_live_ranking as m  # noqa: E402

OUT_DIR = os.path.join(ROOT, "docs", "screenshots")
DEMO = [  # nr, Vorname Name, Verein, Kategorie
    (3, "Lena Brunner", "WFV Muster", "AKTIVE"), (5, "Jonas Keller", "PC Beispielwil", "AKTIVE"),
    (8, "Mia Huber", "WFV Muster", "AKTIVE"), (11, "Noah Frei", "PC Seedorf", "AKTIVE"),
    (14, "Lara Meier", "WFV Muster", "AKTIVE"), (205, "Peter Graf", "PC Beispielwil", "SENIOREN"),
    (207, "Urs Baumann", "PC Seedorf", "SENIOREN"), (211, "Hans Wyss", "WFV Muster", "SENIOREN"),
    (304, "Kurt Studer", "PC Seedorf", "VETERANEN"), (309, "Fritz Gerber", "WFV Muster", "VETERANEN"),
    (402, "Anna Roth", "PC Beispielwil", "FRAUEN"), (406, "Sara Kunz", "WFV Muster", "FRAUEN"),
    (503, "Tim Zbinden", "PC Seedorf", "JUNIOREN"), (507, "Luca Moser", "WFV Muster", "JUNIOREN"),
    (604, "Elia Steiner", "PC Beispielwil", "JUNGFAHRER"), (608, "Nina Bühler", "WFV Muster", "JUNGFAHRER"),
    (702, "Ben Lüthi", "PC Seedorf", "SCHÜLER"), (705, "Emma Schmid", "WFV Muster", "SCHÜLER"),
]
TIMES = {3: 312.44, 5: 305.81, 8: 318.02, 11: 309.37, 205: 331.65, 207: 327.90, 304: 344.12,
         402: 336.58, 503: 321.77, 604: 352.40, 702: 371.95, 211: 333.08}


def main():
    data = tempfile.mkdtemp()
    m.data_dir = lambda: data
    root = tk.Tk()
    root.geometry("1600x900+0+0")
    app = m.LiveRankingApp(root)
    app.dialog_hook = lambda *a: True

    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    app.settings["event"] = {"name": "Demo-Wettkampf", "von": "21.11.26", "bis": ""}
    app.participants = {}
    for nr, name, club, cat in DEMO:
        first, last = name.split(" ", 1)
        app.participants[nr] = {"nr": nr, "p1": f"{first} {last}", "p2": "", "kategorie": cat, "verein": club,
                                "notiz": "", "strafpunkte": 0}
    app.start_order = [d[0] for d in DEMO]
    app.rebuild_order_index()
    app.on_data_changed()
    for nr, secs in TIMES.items():
        app.register_final(nr, secs, m.fmt_secs(secs) if hasattr(m, "fmt_secs") else f"{secs:.2f}", source="Demo")
    sim = m.SimCP()
    app.var_conn.set("ethernet")
    app.on_conn_mode_change()
    app.connect_cp("127.0.0.1", sim.port)
    pump(3.0)
    for _ in range(2):
        sim.start()
        pump(1.2)
    pump(2.0)
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"ui_v{m.APP_VERSION}.png")
    subprocess.run(["import", "-window", "root", "-crop", "1600x900+0+0", out], check=True)
    for name in os.listdir(OUT_DIR):
        if name.startswith("ui_v") and name != os.path.basename(out):
            os.remove(os.path.join(OUT_DIR, name))
    readme = os.path.join(ROOT, "README.md")
    text = open(readme, encoding="utf-8").read()
    img = f"![Oberfläche v{m.APP_VERSION}](docs/screenshots/{os.path.basename(out)})"
    if re.search(r"!\[Oberfläche v[^\]]*\]\(docs/screenshots/[^)]*\)", text):
        text = re.sub(r"!\[Oberfläche v[^\]]*\]\(docs/screenshots/[^)]*\)", img, text)
    else:
        lines = text.split("\n")
        lines.insert(1, f"\n{img}\n")
        text = "\n".join(lines)
    # Trainingsfenster CP 545 und TM550
    shots = []
    for dev, label in (("cp545", "CP 545"), ("tm550", "TM550")):
        win = app.open_trainer(dev)
        pump(3.0)
        if dev == "cp545":
            for k in ("K1", "K1", "K4"):
                app.trainer_key(k)
                pump(0.6)
            for k in ("1", "2", "R"):
                app.trainer_key(k)
        else:
            for k in ("E1", "E1", "E4"):
                app.trainer_key(k)
                pump(0.6)
        pump(0.5)
        win.update()
        name = f"sim_{dev}_v{m.APP_VERSION}.png"
        wid = win.wm_frame() or hex(win.winfo_id())
        subprocess.run(["import", "-window", wid, os.path.join(OUT_DIR, name)], check=True)
        shots.append((label, name))
        app.trainer_close()
        pump(0.3)
    for name in os.listdir(OUT_DIR):
        if name.startswith("sim_") and name not in [n for _l, n in shots]:
            os.remove(os.path.join(OUT_DIR, name))
    block = "\n".join(f"![Simulator {lab} v{m.APP_VERSION}](docs/screenshots/{n})" for lab, n in shots)
    pat = r"(?:!\[Simulator [^\]]*\]\(docs/screenshots/[^)]*\)\n?)+"
    if re.search(pat, text):
        text = re.sub(pat, block + "\n", text, count=1)
    elif "### Üben\n" in text:
        text = text.replace("### Üben\n", "### Üben\n\n" + block + "\n", 1)
    open(readme, "w", encoding="utf-8").write(text)
    if app.cp is not None:
        app.cp.stop()
    sim.close()
    if app.sim is not None:
        app.sim.close()
    shutil.rmtree(data, ignore_errors=True)
    print(out)


if __name__ == "__main__":
    main()
