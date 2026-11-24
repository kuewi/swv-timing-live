"""TM550 Firmware 1.48 und CP 545 VB16 nach dem Test vom 23.11.2026: Vorladen in TIMING, Nummern mit Nullen,
Doppelkontakt als TN-Zeile, Zeitmessarten, Praezision, Falschstart, Lauf oeffnen in PTB SEQ."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_fw148"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)

i = m.parse_thcom("TN 0150    2 01 22:56:35.98600  9823\t06D1")
check("Zeile mit Nummer 0150", i["nr"] == 150 and i["ch"] == 1 and i["seq"] == 2 and i["day"] == 9823)
check("IR-Zeile ist Notiz", m.parse_thcom("IR 1    0150    00:00:03.48100")["kind"] == "note")
check("&P 026 ohne Nummer", m.parse_thcom("&P 026 00    0")["values"] == ["00", "0"])
check("Zeitmessarten", m.mode_numbers("tm550", "TIMING") == "yes" and m.mode_numbers("tm550", "CIRCUIT") == "no"
      and m.mode_numbers("cp545", "START - FINISH") == "yes" and m.mode_numbers("cp545", "PTB SEQUENTIEL 1-4") == "no"
      and m.mode_label("CIRCUIT") == "LAP (CIRCUIT)")

root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.message_dialog = lambda *a, **k: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
def logs(): return " | ".join(l[0] for l in app.log_lines[-120:])
o = [21, 22, 23, 24, 25, 26, 27, 28]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
started = lambda: [c[1] for c in app.course]
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)

# --- TM550 1.48, TIMING
S = m.SimCP(device="tm550", fw="1.48", bounce=True)
app.reset_caps("tm550"); app.connect_cp("127.0.0.1", S.port); app.cp.checksum = True; pump(6)
check("TM550 1.48: Vorladen in TIMING", app.cp_caps["preload"] and not app.cp_caps["ignore_nr"]
      and S.next[m.CH_START] == 21)
S.start(); pump(5)
check("Start mit Nummer vom Gerät, nächste vorgeladen", started() == [21] and S.next[m.CH_START] == 22)
S.start(); pump(4)
S.finish(); pump(2)
check("Ziel an 21, Doppelkontakt als Prellimpuls", 21 in app.results and started() == [22]
      and "Doppelkontakt" in logs())
check("Tagesfeld vom Gerät", all(abs(r["abs"] - m.local_abs()) < 120 for r in app.cp_recs.values()))
# SPEED: Vorladen aus, App nummeriert
S.close_run(); pump(1); S.set_mode("SPEED"); S.open_run(); pump(3)
check("SPEED: Vorladen aus", not app.cp_caps["preload"] and app.cp_caps["ignore_nr"])
# BASIC: #WP 026 -> AK F
S.close_run(); pump(1); S.set_mode("BASIC"); S.open_run(); pump(3)
check("BASIC: Vorladen aus", not app.cp_caps["preload"])
# Praezision 1/10: TM550 ohne Versatz
app.var_prec.set("1"); app.set_prec_digits(); app.cp_write_precision(); pump(10)
check("TM550 Präzision 1/10", S.prec == 1 and app.cp_prec == 1 and m.RESULT_DEC == 1)
check("Anzeige 1/10", m.fmt_secs(61.239) == "1:01.2")
app.disconnect_all(); pump(1); S.close()

# --- CP 545 VB16
app.course.clear(); app.cp_recs.clear(); app.results.clear(); app.last_start_nr = None
S = m.SimCP(fw="VB16")
app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(5)
check("Präzision beim Verbinden gesendet", S.prec == 2)
app.cp_write_precision(); pump(3)
check("CP Präzision 1/10: geschrieben 1, gelesen 2", S.prec == 2 and app.cp_prec == 2)
app.var_prec.set("2"); app.set_prec_digits(); app.cp_write_precision(); pump(3)
check("CP Präzision 1/100: geschrieben 2, gelesen 3", S.prec == 3 and app.cp_prec == 3)
S.start(); pump(1.5)
first = started()[0] if started() else None
S.false_start(); pump(1.5)
check("Falschstart: Boot wieder am Start", first is not None and first not in started()
      and app.next_starters(1) == [first] and first not in app.status)
check("Falschstart: Nummer wieder vorgeladen", S.next[m.CH_START] == first)
S.start(); pump(1.5)
check("Neustart mit derselben Nummer", started() == [first])
S.finish(); pump(2)
r = app.results.get(first)
check("Resultat 1/100 bleibt (RR des CP mit 1/100 gleich)", r is not None and "CP meldet" not in
      " ".join(l[0] for l in app.log_lines[-20:]))
# Lauf oeffnen nur in PTB SEQ
S.close_run(); pump(1)
app.cp_open_run(ask=False); pump(2)
check("NET TIME: Lauf nicht per Befehl", not S.run_open)
S.mode = "PTB SEQUENTIEL 1-4"; S.open_run(); pump(1); S.close_run(); pump(1)
app.cp_open_run(ask=False); pump(3)
check("PTB SEQ: Lauf per #WC 002 geöffnet", S.run_open and app.cp_run == S.run)
app.disconnect_all(); pump(1); S.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
