import os, sys, shutil, time, threading, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
import tempfile; D = os.path.join(tempfile.gettempdir(), "swv_test_watch"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D); m.data_dir = lambda: D
root = tk.Tk(); root.geometry("1366x768+0+0")
app = m.LiveRankingApp(root)
def pump(sec):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
# echte Verbindung ueber loop://
app.cmb_port.set("loop://"); app.toggle_connection(); pump(1.5)
print("1", app.lbl_conn_head.cget("text"), app.serial_base)
ser = None
# Lauf simulieren: running
app.q.put(("line", "13   0:05", app.reader)); pump(0.5)
print("2 running", app.live_time, app.live_final)
pump(6.5)
print("3", app.lbl_conn_head.cget("text"), app.serial_silent, [t[1] for t in app.ticker[:1]])
app.q.put(("line", "13   0:12", app.reader)); pump(1.2)
print("4", app.lbl_conn_head.cget("text"), app.serial_silent, [t[1] for t in app.ticker[:1]])
# Steuerleitungen
app.on_serial_lines({"CTS": True, "DSR": True, "CD": False})
app.on_serial_lines({"CTS": False, "DSR": False, "CD": False}); pump(0.3)
print("5", app.lbl_conn_head.cget("text"), app.serial_silent)
app.on_serial_lines({"CTS": True, "DSR": True, "CD": True}); pump(0.3)
print("6", app.lbl_conn_head.cget("text"), app.serial_silent)
# idle: final, alt
app.q.put(("line", "13   0:20.00", app.reader)); pump(0.5)
app.serial_last_rx = time.time() - 250; pump(1.3)
print("7", app.lbl_conn_head.cget("text"))
print([l[0].strip() for l in app.log_lines if "Steuer" in l[0]][:3])
