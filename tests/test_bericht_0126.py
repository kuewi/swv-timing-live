"""Fehlerberichte 26.11.2026 (v1.21.0, CP 545 Haupt, TM550 Reserve):
- Ziel freigeben schreibt die echte Zielnummer zurueck (sonst ging der Zielimpuls am CP an 9999)
- gesperrte Eingaenge am Hauptgeraet beim Verbinden in die App uebernehmen
- Abgleich Haupt/Reserve: Toleranz nach Aufloesung, naechster Impuls, Doppelkontakt still verworfen,
  Handimpuls am Hauptgeraet ohne Reserve-Warnung
- Resultate mit der Praezision der App, Praezision einmal auf 1/10, Sperrzeit (004) ans Geraet."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_0126"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)

# Migration Praezision
st = m.deep_merge(m.DEFAULT_SETTINGS, {"timing": {"prec_digits": 2}})
with open(os.path.join(D, "settings.json"), "w", encoding="utf-8") as fh:
    import json; json.dump({"timing": {"prec_digits": 2}}, fh)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.message_dialog = lambda *a, **k: True
check("gespeicherte 1/100 einmal auf 1/10", app.tset()["prec_digits"] == 1 and app.settings.get("_mig_prec10"))
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
def logs(n=200): return " | ".join(l[0] for l in app.log_lines[-n:])
o = [1, 201, 202, 203]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE" if n < 200 else "SENIOREN",
                        "verein": "K", "notiz": "", "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)

# --- CP 545 mit gesperrten Eingaengen beim Verbinden
S = m.SimCP()
S.inputs[1] = 0; S.inputs[4] = 0
app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(11)
check("Sperren vom Gerät übernommen (Start und Ziel)", app.tset()["lock_start"] and app.tset()["lock_finish"])
check("Meldung «beim Verbinden»", "beim Verbinden" in logs())
check("Sperrzeit ans Gerät geschrieben (004, 1/100 s)", "#WP 004 04 0030" in " ".join(S.cmds))
app.toggle_lock("lock_start"); pump(2); app.toggle_lock("lock_finish"); pump(2)
check("freigegeben, am Gerät offen", S.inputs[1] == 1 and S.inputs[4] == 1)
# Ziel sperren mit Boot auf der Strecke, freigeben: Zielnummer wieder 1
S.start(); pump(2)
app.set_lock("lock_finish", True); pump(2)
check("Ziel gesperrt: Sperrnummer am CP", S.next.get(m.CH_FINISH) == 9999)
app.set_lock("lock_finish", False); pump(3)
check("Ziel freigegeben: Zielnummer wieder Nr 1", S.next.get(m.CH_FINISH) == 1)
S.finish(); pump(2)
check("Zielimpuls am CP unter Nr 1, Resultat Nr 1", any(v[1] == 1 for (ch, _q), v in S.recs.items() if ch == 4)
      and 1 in app.results)
r1 = app.results.get(1, {})
check("Resultat mit 1/10 formatiert", r1.get("str", "").count(".") == 1 and len(r1["str"].split(".")[1]) == 1)
check("keine Warnung «CP meldet ... App rechnete»", "App rechnete" not in logs())
app.disconnect_all(); pump(1); S.close()

# --- Abgleich Haupt/Reserve
app.main_connected = lambda: True
app.backup_connected = lambda: True
app.cp_device, app.cp_b_device = "cp545", "tm550"
app.cp_caps["preload"] = False; app.cp_run = 1
app.backup_reset()
base = m.local_abs()
def line(ch, seq, t, manual=False): return {"kind": "time", "type": "TN", "nr": 0, "seq": seq, "manual": manual,
                                            "ch": ch, "tod": t % 86400, "day": int(t // 86400), "abs": t,
                                            "answer": False, "text": ""}
app.b_offset = 100.0
check("Toleranz CP 1/100 Zeilen, TM 1/10: 0,15 s", abs(app.backup_tol() - 0.15) < 1e-9)
app.backup_note_main(line(1, 1, base + 0.05))
app.backup_time(line(1, 1, base + 100.0 - 0.01))  # TM schneidet ab: 0,06 s Differenz
check("0,06 s Differenz wird gepaart", not app.b_pend and not app.a_pend)
# Doppelkontakt am Ziel: Haupt 10.08 und 10.18, Reserve 10.00 und 10.10 (+Versatz)
app.backup_note_main(line(4, 2, base + 10.08))
app.backup_note_main(line(4, 3, base + 10.18))
app.backup_time(line(4, 2, base + 110.00))
app.backup_time(line(4, 3, base + 110.10))
check("nächstgelegener Impuls gepaart (keiner offen)", not app.b_pend and not app.a_pend)
# Zweitimpuls nur an der Reserve: still verworfen, keine Abweichung
n = len(app.log_lines)
app.backup_note_main(line(4, 4, base + 20.00))
app.backup_time(line(4, 4, base + 120.02))
app.backup_time(line(4, 5, base + 120.12))
for x in app.b_pend: x[0] -= 10
app.backup_tick()
check("Reserve-Zweitimpuls in der Prellzeit ohne Abweichung", "nur beim Reserve-Gerät" not in logs(len(app.log_lines) - n + 1))
# Handimpuls am Hauptgeraet: keine Warnung
app._b_warn_t = 0
app.backup_note_main(line(4, 6, base + 40.0, manual=True))
for x in app.a_pend: x[0] -= 10
app.backup_tick()
check("Handimpuls am Hauptgerät ohne Reserve-Warnung", "nicht erhalten" not in logs(5) and not app.a_pend)
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
