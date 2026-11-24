"""Diagnose-Log, Programmfehler, Fehlerbericht, DNS wieder einfuegen, DSQ faehrt weiter, Sperr-Schalter im
Banner, Seitenleiste versenken, Datenordner und Uebernahme alter Daten."""
import os, sys, json, shutil, time, tempfile, zipfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_diag"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)

root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.settings["nav_layout"] = "side"; app.apply_sidebar_mode()  # Tests mit angepinnter Seitenleiste
def pump(sec=0.4):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
logf = os.path.join(D, "logs", "swv_live_ranking.log")
check("Diagnose-Log angelegt", os.path.exists(logf))

o = [21, 22, 23, 24]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
sim = m.SimCP()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.2)
app.connect_cp("127.0.0.1", sim.port); pump(1.5)
check("Banner-Schalter sichtbar im Ethernet-Modus", app.banner_locks["lock_start"][0].winfo_manager() == "pack")

# DNS und wieder einfuegen
app.set_status(22, "DNS"); pump(0.2)
check("22 DNS nicht mehr als nächstes", 22 not in app.next_numbers() if hasattr(app, "next_numbers") else
      "Nr 22" not in app.txt_next.get("1.0", "end"))
err = app.insert_number("22", 24); pump(0.2)
check("22 wieder eingefügt, DNS aufgehoben", err is None and 22 not in app.status
      and app.start_order.index(22) == app.start_order.index(24) - 1)

# Starts: 21, 23, 22
for _ in range(3):
    sim.start(); pump(0.4)
course = [c[1] for c in app.course]
check("3 Boote auf der Strecke", len(course) == 3)
first = course[0]
app.set_status(first, "DSQ", keep_on_course=True); pump(0.3)
check("DSQ-Boot bleibt auf der Strecke", [c[1] for c in app.course][0] == first)
check("Anzeige «DSQ, fährt noch»", "DSQ, fährt noch" in app.txt_course.get("1.0", "end"))
sim.finish(); pump(0.6)
check("Zielimpuls gehört dem DSQ-Boot", first in app.results and first not in [c[1] for c in app.course])
check("DSQ nicht klassiert", all(nr != first for _r, nr, _t in app.ranking(app.category_of(first))))
second = app.course[0][1]
sim.finish(); pump(0.6)
check("nächster Zielimpuls richtig", second in app.results)

# Sperr-Schalter im Banner
app.banner_locks["lock_finish"][1].command(); pump(0.2)
check("Banner-Schalter sperrt Ziel", app.settings["timing"]["lock_finish"]
      and app.timing_switches["lock_finish"].on)
app.banner_locks["lock_finish"][1].command(); pump(0.2)
check("Banner-Schalter gibt frei", not app.settings["timing"]["lock_finish"])

# Programmfehler in einem Callback
def boom():
    raise ValueError("Testfehler 42")
root.after(10, boom); pump(0.5)
check("Programmfehler im Log der App", any("Testfehler 42" in l[0] for l in app.log_lines))
for h in m.DIAG.handlers: h.flush()
txt = open(logf, encoding="utf-8").read()
check("Traceback im Diagnose-Log", "Traceback" in txt and "Testfehler 42" in txt)
check("CP-Zeilen im Diagnose-Log", "CP A> #WP 026" in txt and "CP A< TN" in txt)
check("Zuordnungsentscheid im Diagnose-Log", "Zielimpuls" in txt and "erwartet:" in txt)

# Fehlerbericht
dlg = app.open_report_dialog(); pump(0.2)
txtw = [w for w in dlg.winfo_children() if isinstance(w, tk.Text)][0]
txtw.insert("1.0", "Zielzeit ging an das falsche Boot")
dlg.event_generate("<Control-Return>"); pump(0.5)
zips = [f for f in os.listdir(os.path.join(D, "fehlerberichte")) if f.endswith(".zip")]
check("Bericht als ZIP", len(zips) == 1)
z = zipfile.ZipFile(os.path.join(D, "fehlerberichte", zips[0]))
names = z.namelist()
man = json.loads(z.read("manifest.json"))
check("Inhalt vollständig", {"manifest.json", "beschreibung.txt", "session.json"} <= set(names)
      and any(n.startswith("logs/") for n in names) and any(n.startswith("rohdaten/") for n in names))
check("Manifest mit Beschreibung", man["beschreibung"] == "Zielzeit ging an das falsche Boot" and man["id"])
sess = json.loads(z.read("session.json"))
check("Session-Dump mit Rohzeiten und Strecke", sess["cp"]["recs"] and "course" in sess and sess["log"])
check("Geheimnisse entfernt", "token" not in json.dumps(sess["settings"]).lower() or
      sess["settings"]["online"]["token"] in ("", "***"))
check("Markierung im Log", "FEHLERMELDUNG" in z.read(f"logs/swv_live_ranking.log").decode())
q = json.load(open(os.path.join(D, "fehlerberichte", "offen.json"), encoding="utf-8"))
check("Bericht in der Liste offen", q and q[-1]["id"] == man["id"])

# Seitenleiste
app._drop_watch = lambda: None
app.toggle_sidebar_pin(); pump(0.3)
check("versenkt: Menü oben", app.side_outer.winfo_manager() == "" and app.topbar.winfo_ismapped())
app.toggle_dropdown("startliste"); pump(0.3)
check("Ausklappfeld", app.side_outer.winfo_manager() == "place")
app.close_dropdown(); pump(0.2)
check("Ausklappfeld zu", app.side_outer.winfo_manager() == "")
app.toggle_sidebar_pin(); pump(0.2)
check("wieder angepinnt", app.side_outer.winfo_manager() == "grid" and app.settings["nav_layout"] == "side")
check("Startliste zuklappbar", "startliste" in app.settings["collapsed"] and "manuell" in app.settings["collapsed"])

# Nummer aendern: Hinweis mit Tastenfolge, spaetere Korrektur am CP hat Vorrang
seen = []
app.dialog_hook = lambda kind, title, msg, d=None: seen.append(msg) or True
sim.start(); pump(0.5)
k, r = max(((k, r) for k, r in app.cp_recs.items() if k[2] == 1 and r["status"] == "ok" and not r.get("done")),
           key=lambda x: x[1]["abs"])
cpn = r["cp_nr"]
app.cp_change_number(k, r["nr"], 77); pump(0.3)
check("Hinweis mit Tastenfolge", seen and f"{cpn}  R  E1  77  Enter" in seen[-1])
check("Fahrstrecke: CP führt noch alte Nr", f"CP führt noch Nr {cpn}" in app.txt_course.get("1.0", "end"))
day = int(r["abs"] // 86400)
tod = m.fmt_tod(r["abs"] % 86400)
sim.replay_line(f"T- {cpn:4d} {k[3]:4d} M1 {tod} {day:5d}"); pump(0.3)
sim.replay_line(f"T* {88:4d} {k[3]:4d} M1 {tod} {day:5d}"); pump(0.5)
check("Korrektur am CP gilt", app.cp_recs[k]["nr"] == 88 and app.cp_recs[k]["cp_nr"] == 88
      and 88 in [c[1] for c in app.course] and "CP führt noch" not in app.txt_course.get("1.0", "end"))
app.dialog_hook = lambda *a: True

app.cp.stop(); pump(0.5); sim.close()

# Datenordner und Uebernahme
old = os.path.join(tempfile.gettempdir(), "swv_old_dir"); new = os.path.join(tempfile.gettempdir(), "swv_new_dir")
for d in (old, new): shutil.rmtree(d, ignore_errors=True)
os.makedirs(os.path.join(old, "rohdaten")); os.makedirs(new)
for name in (m.SETTINGS_FILE, m.AUTOSAVE_FILE): open(os.path.join(old, name), "w").write("{}")
open(os.path.join(old, "rohdaten", "x.jsonl"), "w").write("1")
m.legacy_data_dirs = lambda: [old]
check("alte Daten übernommen", m.migrate_data(new) == old and os.path.exists(os.path.join(new, m.AUTOSAVE_FILE))
      and os.path.exists(os.path.join(new, "rohdaten", "x.jsonl")))
check("nur beim ersten Start", m.migrate_data(new) is None)
print("GESAMT", "OK" if all(ok) else "FEHLER")
