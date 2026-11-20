"""REST-API und WebSocket der Browser-Anzeige."""
import os, sys, shutil, time, tempfile, json, socket, base64, threading, urllib.request, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_api"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
root = tk.Tk(); app = m.LiveRankingApp(root); app.dialog_hook = lambda *a: True
def pump(sec=0.5):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
app.participants = {5: {"nr": 5, "p1": "Anna", "p2": "", "kategorie": "AKTIVE", "verein": "K", "notiz": "geheim", "strafpunkte": 0}}
app.start_order = [5]; app.rebuild_order_index(); app.on_data_changed()
key = app.settings["web"]["key"]; port = 18089
app.web.start("127.0.0.1", port, key); pump(1.0)
base = f"http://127.0.0.1:{port}"
def get(path):
    try:
        with urllib.request.urlopen(base + path, timeout=3) as r: return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e: return e.code, b"", {}
st, body, hd = get(f"/api/v1/live?key={key}")
check("API live 200", st == 200 and json.loads(body)["stand"])
st, body, hd = get(f"/api/v1/startlist?key={key}")
check("API startlist ohne Notizen", st == 200 and json.loads(body)[0]["nr"] == 5 and b"geheim" not in body)
check("CORS für API", hd.get("Access-Control-Allow-Origin") == "*")
check("ohne Schlüssel 403", get("/api/v1/live")[0] == 403)
check("Doku-Seite", get(f"/api?key={key}")[0] == 200)
# WebSocket
msgs = []
def ws_client():
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    k = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET /ws?key={key}&stream=all HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {k}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp: resp += s.recv(1)
    msgs.append(resp.split(b"\r\n")[0])
    end = time.time() + 4
    while time.time() < end and len(msgs) < 12:
        h = s.recv(2); n = h[1] & 0x7F
        if n == 126: n = int.from_bytes(s.recv(2), "big")
        data = b""
        while len(data) < n: data += s.recv(n - len(data))
        if h[0] & 0x0F == 1: msgs.append(json.loads(data))
    s.close()
t = threading.Thread(target=ws_client); t.start()
for i in range(25):
    pump(0.2)
    if i == 8: app.register_final(5, 61.2, "1:01.20", source="Test")
t.join(6)
check("WebSocket-Handshake 101", msgs and b"101" in msgs[0])
check("WebSocket liefert Stand mit Ranglisten", len(msgs) >= 2 and "results" in msgs[1] and "display" in msgs[1])
check("Änderung wird gepusht", any(isinstance(x, dict) and x.get("results") and x["results"][0]["rangliste"] for x in msgs[1:]))
app.web.stop()
print("GESAMT", "OK" if all(ok) else "FEHLER")
