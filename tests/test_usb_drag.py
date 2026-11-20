"""CP per USB (COM-Port, Rahmen mit TAB und Pruefsumme) und Ueberholen per Ziehen auf der Fahrstrecke.
Der COM-Port wird mit pyserial 'socket://' auf den eingebauten Simulator im RS232-Rahmenformat umgeleitet."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_usb"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)

# Pruefsumme laut THCOM08-Beispiel: "#PL Hello" -> 02B0
check("CS16 Beispiel aus THCOM08", m.thcom_cs16(b"#PL Hello") == "02B0")
check("Rahmen mit gültiger Prüfsumme", m.split_serial_frame("PL Hello\t02B0\r") == ("PL Hello", True))
check("Rahmen mit falscher Prüfsumme", m.split_serial_frame("PL Hello\t02B1")[1] is False)
check("Rahmen ohne Prüfsumme", m.split_serial_frame("PL Hello\t") == ("PL Hello", True))

root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.5):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
o = [21, 22, 23, 24, 25]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()

sim = m.SimCP(rs232=True)
# Puffer des CP wie in Stefans Test: alte Zeiten aus einem anderen Lauf und dem aktuellen Lauf
day = int(m.local_abs() // 86400)
sim.pending = [f"TN  300    8 M1 11:11:50.39000 {day:5d}", "RR    3  125          21.60000", "CL 05",
               "OP 01  00  NET TIME", f"TN    1    1 M1 11:31:21.84000 {day:5d}",
               f"TN    1    1 M4 11:34:09.69000 {day:5d}", "RR    1    1        2:47.85000",
               f"TN  603    2 M1 11:53:59.49000 {day:5d}"]
sim.seq = {1: 2, 4: 1}
app.var_conn.set("usb"); app.on_conn_mode_change(); pump(0.2)
check("USB-Rahmen sichtbar", app.frm_usb.winfo_ismapped() and not app.frm_eth.winfo_ismapped())
app.cmb_usb.set(f"socket://127.0.0.1:{sim.port}")
app.toggle_connection(); pump(2.5)
check("alte Zeiten aus dem Puffer nicht übernommen", not app.cp_recs and not app.results and not app.course)
check("Lauf und Sequenzen aus dem Puffer", app.cp_run == 1 and app.cp_lastseq.get(("A", 1, 1)) == 2)
check("Hinweis im Log", any("ältere Zeiten" in l[0] for l in app.log_lines))
check("über USB verbunden, 21 vorgeladen", app.cp and app.cp.connected and app.cp.link == "usb" and sim.next[1] == 21)
check("Einstellung gespeichert", app.settings["conn"]["usb_port"].startswith("socket://"))
for _ in range(4):
    sim.start(); pump(0.4)
check("4 Boote auf der Strecke", [c[1] for c in app.course] == [21, 22, 23, 24])
# Zeile mit falscher Pruefsumme wird verworfen
for cl in list(sim.clients):
    cl.sendall(b"TN   99 0099 M1 10:00:00.00000 9999\t0000\r\n")
pump(0.4)
check("falsche Prüfsumme verworfen", not any(r["nr"] == 99 for r in app.cp_recs.values()))

# Ziehen: 23 vor 21 (ganz nach unten)
pump(0.3); app.update_course_panel(); root.update()
def center(nr):
    rng = app.txt_course.tag_ranges(f"crs{nr}")
    app.txt_course.see(rng[0]); root.update()
    x, y, w, h = app.txt_course.bbox(rng[0])
    return x + 5, y + h // 2
class E:  # Ereignis-Ersatz
    def __init__(s, x, y): s.x, s.y, s.x_root, s.y_root = x, y, x, y
x, y = center(23); app.on_course_press(E(x, y))
x2, y2 = center(21); app.on_course_motion(E(x, y + 20)); app.on_course_motion(E(x2, y2))
check("Ziel beim Ziehen markiert", app._crs_drag["target"] == 21 and app.txt_course.tag_ranges("drop"))
app.on_course_release(E(x2, y2)); pump(0.5)
check("23 kommt als nächstes", [c[1] for c in app.course] == [23, 21, 22, 24])
check("CP auf 23 nachgeführt", sim.next[4] == 23)
check("Anzeige (überholt)", "(überholt)" in app.txt_course.get("1.0", "end"))
# 21 hinter 24 ziehen (ganz nach oben)
x, y = center(21); app.on_course_press(E(x, y))
x2, y2 = center(24); app.on_course_motion(E(x, y - 20)); app.on_course_motion(E(x2, y2))
app.on_course_release(E(x2, y2)); pump(0.3)
check("21 ganz hinten", [c[1] for c in app.course] == [23, 22, 24, 21])
# neues Boot kommt hinten dazu
sim.start(); pump(0.5)
check("neu gestartete 25 hinten", [c[1] for c in app.course] == [23, 22, 24, 21, 25])
sim.finish(); pump(0.6)
check("Zielimpuls an 23", 23 in app.results and [c[1] for c in app.course] == [22, 24, 21, 25])
# einfacher Klick oeffnet weiterhin das Menue
opened = []
app._popup = lambda menu, ev: opened.append(menu.entrycget(0, "label"))
x, y = center(24); app.on_course_press(E(x, y)); app.on_course_release(E(x, y))
check("Klick ohne Ziehen: Menü", opened and "24" in opened[0])
# Reihenfolge bleibt im Autosave
app.save_autosave()
keys = {r["nr"]: r.get("order") for k, r in app.cp_recs.items() if k[2] == 1}
check("Reihenfolge im Datensatz", keys[21] is not None)
# Unterbruch: CP puffert, nach dem Wiederverbinden werden die Zeiten nachgetragen
before = [c[1] for c in app.course]
sim.drop_clients(); pump(0.3)
sim.finish(); pump(0.2)             # Ziel 22 waehrend dem Unterbruch
pump(3.5)
check("wieder verbunden", app.cp.connected)
pump(1.0)
check("Zielzeit aus dem Unterbruch übernommen", 22 in app.results and [c[1] for c in app.course] == before[1:])
# Trennen
app.toggle_connection(); pump(1.0)
check("getrennt", app.cp is None)
sim.close()
print("GESAMT", "OK" if all(ok) else "FEHLER")
