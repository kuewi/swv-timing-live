"""Haupt- und Reservegeraet mit eigener Verbindung: USB + Ethernet, Ethernet + USB, beide Ethernet."""
import os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_gemischt"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
o = list(range(1, 40))
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()

def set_bk(mode):
    app.var_bk.set(mode); app.on_backup_mode_change(); pump(0.1)

# 1) CP 545 ueber USB, TM550 ueber Ethernet
A = m.SimCP(); B = m.SimCP(device="tm550", clock_offset=-12.5)
os.environ["SWV_CP_PORTS"] = f"{B.port},{B.port}"; os.environ["SWV_CP_HOSTS"] = "127.0.0.1"
app.var_conn.set("usb"); app.on_conn_mode_change(); pump(0.1)
set_bk("ethernet")
check("Reserve-Block mit IP-Feld sichtbar, Netzwerkkarte sichtbar",
      app.frm_bk_eth.winfo_manager() and app.frm_net.winfo_manager() and not app.frm_bk_usb.winfo_manager())
app.cmb_usb.set(f"socket://127.0.0.1:{A.port}")
app.cmb_cp_b.set("127.0.0.1")
check("eingetippte IP gilt als Reserve", app.selected_backup() == "127.0.0.1")
app.toggle_connection(); pump(6.0)
check("Haupt USB verbunden", app.main_connected() and app.cp.link == "usb")
check("Reserve Ethernet verbunden als TM550", app.backup_connected() and app.cp_b_device == "tm550")
A.start(); B.start(); pump(0.8); A.start(); B.start(); pump(0.8)
check("Versatz gelernt (USB + Ethernet)", app.b_offset is not None and abs(app.b_offset + 12.5) < 0.1)
app.toggle_connection(); pump(1.5)
check("beide getrennt", app.cp is None and app.cp_b is None)
A.close(); B.close()

# 2) TM550 ueber USB, CP 545 ueber Ethernet als Reserve
A = m.SimCP(device="tm550"); B = m.SimCP()
os.environ["SWV_CP_PORTS"] = f"{B.port},{B.port}"
app.cp_found = []
app.cmb_usb.set(f"socket://127.0.0.1:{A.port}")
app.cmb_cp_b.set("127.0.0.1")
app.toggle_connection(); pump(7.0)
check("Haupt TM550 USB, Reserve CP Ethernet", app.cp_device == "tm550" and app.backup_connected()
      and app.cp_b_device == "cp545")
app.toggle_connection(); pump(1.5)
A.close(); B.close()

# 3) beide Ethernet (verschiedene Ports simulieren zwei IPs nicht; Reserve per USB-Socket im Ethernet-Hauptmodus)
A = m.SimCP(); B = m.SimCP(device="tm550")
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
set_bk("usb")
check("Ethernet-Haupt: Reserve-USB-Block sichtbar", app.frm_bk_usb.winfo_manager() and app.frm_net.winfo_manager())
app.port_map = {f"socket://127.0.0.1:{B.port}": f"socket://127.0.0.1:{B.port}"}; app.fill_backup_combos()
app.connect_cp("127.0.0.1", A.port); app.connect_backup(); pump(5.0)
check("Haupt Ethernet, Reserve USB", app.main_connected() and app.backup_connected() and app.cp_b_device == "tm550")
app.disconnect_all(); pump(1.0)
A.close(); B.close()

# 4) beide Ethernet: Reserve-IP aus der Suche, Hauptgeraet nimmt nicht die Reserve-IP
app.cp_found = [("127.0.0.1", "CP545 Nr 1"), ("127.0.0.2", "TM550 Nr 59")]
app.settings["conn"]["cp_ip"] = "127.0.0.1"
set_bk("ethernet"); app.fill_backup_combos()
vals = list(app.cmb_cp_b["values"])
check("Reserve-Liste ohne Hauptgerät", len(vals) == 1 and vals[0].startswith("127.0.0.2"))
app.cmb_cp_b.current(0)
check("Reserve-Auswahl 127.0.0.2", app.selected_backup() == "127.0.0.2")
set_bk("none")
check("Keines: kein Ziel", app.selected_backup() == "" and not app.frm_bk_eth.winfo_manager())
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
