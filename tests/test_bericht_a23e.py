"""Nachstellung Fehlerbericht 20261121-013551-a23e: Storno einer alten Startzeit nach dem Wiederverbinden,
RR zu einer Zielzeit ohne Boot, Zielzeit ohne Nummer."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_a23e"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
m.DEFAULT_SETTINGS["timing"]["prec_digits"] = 2  # Bericht mit 1/100
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)

check("Zeile ohne Nummer erkannt", (m.parse_thcom("TN        10 M4  2:30:23.40200  9821") or {}).get("nr") == 0)
check("Antwort ohne Nummer erkannt", (m.parse_thcom("AN        10 M4  2:30:23.40200  9821") or {}).get("seq") == 10)

root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
o = [301, 302, 303]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "VETERANEN", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
sim = m.SimCP()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
app.connect_cp("127.0.0.1", sim.port); pump(2.5)
day = int(m.local_abs() // 86400)
def L(s): sim.replay_line(s.replace("DDDD", f"{day:4d}")); pump(0.25)
L("OP 01  00  NET TIME")
L("TN  301    7 M1  2:28:38.20900  DDDD")          # erster Start 301
check("301 auf der Strecke", [c[1] for c in app.course] == [301])
# nach dem Wiederverbinden: Neustart 301 (Seq 8), dann Storno der alten Startzeit (Seq 7)
L("TN  301    8 M1  2:29:25.04900  DDDD")
L("AC  301    7 M1  2:28:38.20900  DDDD")
check("301 nach Storno der alten Startzeit weiter auf der Strecke", 301 in [c[1] for c in app.course]
      and app.status.get(301) is None)
L("TN  111    9 M1  2:29:46.22400  DDDD")
check("Strecke 301 vor 111", [c[1] for c in app.course] == [301, 111])
L("TN  111    7 M4  2:30:01.10700  DDDD")
check("erster Zielimpuls an 301", 301 in app.results and abs(app.results[301]["secs"] - 36.05) < 0.02)
L("TN  301    8 M4  2:30:15.56800  DDDD")
L("RR    3  301          50.51000")
check("zweiter Zielimpuls an 111, RR des CP für 301 nicht übernommen",
      111 in app.results and abs(app.results[301]["secs"] - 36.05) < 0.02)
L("TN  111    9 M4  2:30:18.85400  DDDD")
L("RR    0  111          32.63000")
check("RR zu Zielzeit ohne Boot nicht übernommen", abs(app.results[111]["secs"] - 29.34) < 0.02)
L("TN        10 M4  2:30:23.40200  DDDD")
check("Zielzeit ohne Nummer als Impuls ohne Boot", len(app.pending_impulses()) == 2)
app.cp.stop(); pump(0.4); sim.close()

# Bericht 7ed8: Kategorie in gemischter Schreibweise, Blinken trotz Neuaufbau der Karten
r, w = m.derive_category_ranges([601, 602, 677], {601: {"kategorie": "Jungfahrer"}, 602: {"kategorie": "Jungfahrer"},
                                                  677: {"kategorie": "JUNGFAHRER"}})
check("Gross/Klein: eine Kategorie, keine Überschneidung", len(r) == 1 and r[0][0] == "Jungfahrer"
      and not any("überschneiden" in x for x in w))
app.participants.update({n: {"nr": n, "p1": "J", "p2": "", "kategorie": k, "verein": "K", "notiz": "",
                             "strafpunkte": 0} for n, k in ((601, "Jungfahrer"), (677, "JUNGFAHRER"))})
app.start_order += [601, 677]; app.rebuild_order_index(); app.on_data_changed(); pump(0.2)
check("Nachführen danach ruhig", app.apply_startlist_categories(app.start_order, app.participants,
                                                                 only_changes=True) == [])
app.blink.clear()
app.results[302] = {"secs": 40.0, "str": "40.00", "ts": time.time(), "source": "Test", "run": 1, "prev": None,
                    "status": "offen", "cp": None}
app._rank_cache = None
app.build_cards(); pump(0.2)
check("neues Resultat blinkt trotz Neuaufbau", 302 in app.blink)
print("GESAMT", "OK" if all(ok) else "FEHLER")
