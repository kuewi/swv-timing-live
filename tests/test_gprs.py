"""Quelle «GPRS Interface» auf 127.0.0.1:Port: nur Empfang, keine Befehle, Zeilen wie vom CP."""
import os, sys, shutil, time, socket, threading, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_gprs"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
check("ip:port", m.split_hostport("127.0.0.1:9000", 7000) == ("127.0.0.1", 9000)
      and m.split_hostport("192.168.1.50", 7000) == ("192.168.1.50", 7000))
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("127.0.0.1", 0)); srv.listen(1)
port = srv.getsockname()[1]; got, conn = [], []
def serve():
    c, _ = srv.accept(); conn.append(c); c.settimeout(0.2)
    while True:
        try:
            d = c.recv(512)
            if not d: break
            got.append(d)
        except socket.timeout:
            continue
        except OSError:
            break
threading.Thread(target=serve, daemon=True).start()
root = tk.Tk(); root.geometry("1600x900+0+0")
app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
o = [7, 8]
app.participants = {n: {"nr": n, "p1": f"V{n}", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "",
                        "strafpunkte": 0} for n in o}
app.start_order = list(o); app.rebuild_order_index(); app.on_data_changed()
app.var_conn.set("ethernet"); app.on_conn_mode_change(); pump(0.1)
app.cmb_cp.set(f"127.0.0.1:{port}"); app.toggle_connection(); pump(2)
check("verbunden als GPRS Interface", app.cp_device == "gprs" and app.cp is not None and app.cp.connected)
d = m.local_abs(); day, tod = divmod(d, 86400)
def tline(nr, seq, ch, t):
    h, r = divmod(t % 86400, 3600); mi, sec = divmod(r, 60)
    return f"TN {nr:4d} {seq:4d} M{ch} {int(h):02d}:{int(mi):02d}:{sec:08.5f} {int(day):5d}\r\n".encode()
conn[0].sendall(tline(7, 1, 1, tod)); pump(1)
conn[0].sendall(tline(7, 1, 4, tod + 30.5)); pump(1.5)
check("Start und Ziel ausgewertet", 7 in app.results)
check("keine Befehle gesendet", b"".join(got) == b"")
app.disconnect_all(); pump(1); srv.close()
print(f"{sum(ok)}/{len(ok)} OK"); root.destroy(); sys.exit(0 if all(ok) else 1)
