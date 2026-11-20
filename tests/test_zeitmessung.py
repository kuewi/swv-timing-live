"""Neue Funktionen der Zeitmessung mit dem eingebauten Simulator: Fehlimpulse, Sperren, #RT, #DL,
Mitternacht, Status DNS/DSQ, gleiche Zeiten, Rohdaten, Reserve-CP."""
import os, sys, shutil, time, tempfile, json, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_zm"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.5):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
o = [11, 12, 13, 14, 15, 16]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
app.open_simulator(); pump(3)
sim = app.sim
check("Simulator verbunden, 11 vorgeladen", app.cp and app.cp.connected and sim.next[1] == 11)
# Mindestfahrzeit
app.settings["timing"]["min_run_s"] = 2
sim.start(); pump(0.5); sim.finish(); pump(0.6)
check("Fehlimpuls unter Mindestzeit nicht gewertet", 11 not in app.results and [c[1] for c in app.course] == [11])
check("als Impuls ohne Zuordnung sichtbar", "Fehlimpuls" in app.txt_course.get("1.0", "end"))
pump(1.6); sim.next[4] = 11; sim.finish(); pump(0.8)
check("gültiges Ziel danach", 11 in app.results)
app.settings["timing"]["min_run_s"] = 0
# Prellzeit Ziel
sim.start(); pump(0.4); sim.start(); pump(0.6)
sim.finish(); sim.finish(); pump(0.8)
check("zweiter Zielimpuls innert Prellzeit ungültig", 12 in app.results and 13 not in app.results)
sim.finish(); pump(0.6)
check("13 danach im Ziel", 13 in app.results)
# Ziel sperren und Impuls zuordnen
app.toggle_lock("lock_finish"); sim.start(); pump(0.4); sim.finish(); pump(0.6)
pend = app.pending_impulses()
check("gesperrtes Ziel: ohne Nummer", 14 not in app.results and pend and app.cp_recs[pend[-1]]["status"] == "locked")
app.assign_pending(pend[-1], 14); pump(0.3)
check("von Hand zugeordnet", 14 in app.results)
app.toggle_lock("lock_finish")
# verlorene Zeile -> #RT
sim.start(); pump(0.4)          # 15
sim.drop_next = True; sim.start(); pump(0.4)   # 16 geht verloren
app.cp_probe(); pump(1.0)                       # Abfrage wie beim Heartbeat
sim.finish(); pump(1.0)
check("verlorene Startzeit 16 per #RT nachgeholt", any(r["nr"] == 16 and k[2] == 1 for k, r in app.cp_recs.items()))
check("15 im Ziel", 15 in app.results)
# DNS / DSQ / gleiche Zeiten
app.set_status(12, "DSQ"); pump(0.2)
ranked = [n for _r, n, _t in app.ranking(app.category_of(11))]
check("DSQ nicht in der Rangliste", 12 not in ranked)
check("nicht klassiert im Kartentitel", "nicht klassiert: 12 DSQ" in app.card_title(app.category_of(11)))
app.results[13]["secs"] = app.results[11]["secs"]; app.results[13]["str"] = app.results[11]["str"]
app._rank_cache = None
r = {n: rk for rk, n, _t in app.ranking(app.category_of(11))}
order = [n for _r, n, _t in app.ranking(app.category_of(11))]
check("gleiche Zeit gleicher Rang, höhere Nr zuerst", r[11] == r[13] and order.index(13) < order.index(11))
# Download #DL: Datensaetze loeschen und neu laden
before = sorted(k for k in app.cp_recs)
for k in list(app.cp_recs):
    if k[2] == 1 and app.cp_recs[k]["nr"] == 16:
        del app.cp_recs[k]
app.cp_download_run(); pump(1.5)
check("#DL lädt fehlende Zeit wieder", any(r["nr"] == 16 and k[2] == 1 for k, r in app.cp_recs.items()))
# Rohdaten
raw = os.path.join(D, m.RAW_DIR, time.strftime("%Y-%m-%d") + ".jsonl")
lines = open(raw, encoding="utf-8").read().splitlines()
check("Rohdaten geschrieben", len(lines) > 10 and json.loads(lines[0])["line"])
app.results[15]["secs"] = 99.0; app.results[15]["str"] = "1:39.00"
app.recompute_from_raw(); pump(0.2)
check("Neu berechnen stellt Rohzeit wieder her", app.results[15]["str"] != "1:39.00")
# Mitternacht
t1 = m.parse_thcom("TN   20    1 M1 23:59:58.00000  9820"); t2 = m.parse_thcom("TN   20    1 M4 00:00:03.50000  9821")
check("Zeit über Mitternacht", abs((t2["abs"] - t1["abs"]) - 5.5) < 1e-6)
# Autosave mit Rohzeiten und Status
app.save_autosave()
data = json.load(open(os.path.join(D, m.AUTOSAVE_FILE), encoding="utf-8"))
check("Autosave enthält Rohzeiten und Status", data["cp"]["recs"] and data["status"].get("12") == "DSQ")
# Reserve-CP: zweiter Simulator, Haupt-CP faellt aus
sim_b = m.SimCP(); sim_b.next[1] = 16
app.start_backup("127.0.0.1", sim_b.port); pump(1.5)
check("Reserve verbunden", app.cp_b is not None and app.cp_b.connected)
for c in list(sim.clients):
    c.shutdown(2); c.close()
sim.alive = False; sim.sock.close()
pump(1.0)
sim_b.start(); pump(0.6)
check("Start vom Reserve-CP übernommen, solange Haupt-CP fehlt",
      any(k[0] == "B" and r["nr"] == 16 for k, r in app.cp_recs.items()))
# PDF
paths = [app.make_pdf(w) for w in ("Rangliste", "Startliste", "Zeitprotokoll")]
check("PDF erstellt", all(p and open(p, "rb").read(5) == b"%PDF-" for p in paths))
print("PDF:", paths)
print("Log:", [l[0].strip()[10:] for l in app.log_lines if "nachgeholt" in l[0] or "Download" in l[0]][:4])
print("GESAMT", "OK" if all(ok) else "FEHLER")
sim_b.close()
