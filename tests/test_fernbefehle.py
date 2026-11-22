"""Erkenntnisse aus dem Geraetetest 22.11.2026: Lauf oeffnen (TM550), kein #DL ohne Lauf, Uhr falsch,
Geraet antwortet nicht mehr auf Befehle, CP nach Neustart ohne Ethernet."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_fern"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
shown = []
def _dlg(kind, title, message, **kw):
    shown.append((title, message)); return True
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
app.message_dialog = _dlg
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
def logs(): return " | ".join(l[0] for l in app.log_lines[-60:])
o = list(range(1, 30))
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()

# TM550 ohne offenen Lauf: Laden fragt und oeffnet den Lauf mit #WC 002
S = m.SimCP(device="tm550"); S.close_run()
app.reset_caps("tm550"); app.connect_cp("127.0.0.1", S.port); app.cp.checksum = True; pump(6)
check("TM550 kein Lauf erkannt", app.cp_run == 0)
sent = []
orig = app.cp_query
app.cp_query = lambda text, *a, **k: (sent.append(text), orig(text, *a, **k))[1]
app.cp_download_run(); pump(5)
check("kein #DL ohne Lauf", not any(t.startswith("#DL") for t in sent))
check("#WC 002 gesendet und Lauf offen", "#WC 002" in sent and app.cp_run == S.run and S.run_open)
app.cp_open_run(); pump(0.3)
check("Lauf offen: kein zweites #WC 002", sent.count("#WC 002") == 1 and "bereits offen" in str(shown[-1]))
app.disconnect_all(); pump(1); S.close()

# CP: kein Lauf -> kein #DL, Hinweis; Lauf oeffnen lehnt CP ab
S = m.SimCP(); S.close_run()
app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(4)
sent.clear(); shown.clear()
app.cp_download_run(); pump(0.5)
check("CP ohne Lauf: kein #DL, Hinweis", not any(t.startswith("#DL") for t in sent) and "kein Lauf" in str(shown))
app.cp_open_run(); pump(0.5)
check("CP: Lauf öffnen nur Hinweis", "#WC 002" not in sent and "NET TIME" in str(shown[-1]))

# Uhr des Geraets falsch: Warnung nach zwei Impulsen
S.clock_offset = -3 * 3600 - 300
S.start(); pump(0.6); S.start(); pump(0.8)
check("Uhr-Warnung", "geht 3 h 5 min nach" in logs())
S.clock_offset = 0

# Geraet beantwortet keine Befehle mehr, Zeiten kommen weiter
S._cmd = lambda t, c: None; S._cmd_tm550 = lambda t, p, c: None
for _ in range(3):
    app.cp_query("#RP 003", ("param", "003"))
pump(14)
S.start(); pump(1)
check("Hinweis: antwortet nicht auf Befehle", "beantwortet keine Befehle mehr" in logs())
app.disconnect_all(); pump(1); S.close()

# CP neu gestartet: Ethernet aus, Verbindung scheitert mit Hinweis, nach Einschalten wieder da
S = m.SimCP()
app.reset_caps("cp545"); app.connect_cp("127.0.0.1", S.port); pump(3)
S.restart(); pump(8)
check("Hinweis Ethernet einschalten", "Ethernet am CP wieder einschalten" in logs())
S.enable_ethernet(); pump(10)
check("nach Ethernet ein wieder verbunden", app.cp is not None and app.cp.connected and S.clients)
app.disconnect_all(); pump(1); S.close()

# TM550 mit falschem Tagesfeld (-29 Tage): keine Uhr-Warnung, Zeiten mit PC-Tag
S = m.SimCP(device="tm550")
app.reset_caps("tm550"); app.connect_cp("127.0.0.1", S.port); app.cp.checksum = True; pump(6)
n_before = logs().count("Uhr TM550")
S.start(); pump(1.5); S.start(); pump(1.5)
check("TM550 Tagesfeld falsch: keine Uhr-Warnung", logs().count("Uhr TM550") == n_before)
S.clock_offset = -200; S.start(); pump(1.5); S.start(); pump(1.5)
check("TM550 Uhr 3 min nach: Warnung", "Uhr TM550 geht 3 min" in logs())
app.disconnect_all(); pump(1); S.close()

# Simulator-Befehle wie am Geraet
T = m.SimCP(device="tm550"); C = m.SimCP()
check("CP #SLC öffnet Lauf", (C._cmd("#SLC", None), C.run)[1] == 2 and C.run_open)
check("TM #WC 002 leerer Lauf behält Nummer", (T._cmd_tm550("#WC 002", ["#WC", "002"], None), T.run)[1] == 1)
T.close(); C.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
