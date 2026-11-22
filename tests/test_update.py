"""Version im Fenster, Update-Pruefung und -Download (GitHub-Zugriffe ersetzt)."""
import hashlib, os, sys, shutil, time, tempfile, tkinter as tk
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
D = os.path.join(tempfile.gettempdir(), "swv_test_update"); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
m.data_dir = lambda: D
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)

check("Versionsvergleich", m.parse_version("v1.10.2") > m.parse_version("1.9.9") and m.parse_version("v1.10.0") == (1, 10, 0))
check("nur GitHub über HTTPS", m._https_allowed("https://github.com/kuewi/x") and not m._https_allowed("http://github.com/x")
      and not m._https_allowed("https://evil.example/x"))
payload = b"SETUP-BYTES" * 1000
digest = hashlib.sha256(payload).hexdigest()
newer = ".".join(str(x) for x in (m.parse_version(m.APP_VERSION)[0], m.parse_version(m.APP_VERSION)[1] + 1, 0))
calls = {"fetch": 0}
def fake_release(url=None, timeout=8):
    calls["fetch"] += 1
    return {"version": m.parse_version(newer), "tag": "v" + newer, "body": "- Neu: Testfunktion", "html_url": "https://github.com/x",
            "setup": f"SWV_LiveRanking_Setup_{newer}.exe", "setup_url": "https://github.com/dl/setup.exe",
            "sums_url": "https://github.com/dl/SHA256SUMS.txt"}
m.fetch_latest_release = fake_release
sums = {"txt": f"{digest}  SWV_LiveRanking_Setup_{newer}.exe\n"}
m.fetch_text = lambda url, timeout=10: sums["txt"]
def fake_download(url, path, progress=None, timeout=30):
    open(path, "wb").write(payload)
    if progress: progress(len(payload), len(payload))
    return hashlib.sha256(payload).hexdigest()
m.download_file = fake_download

root = tk.Tk(); root.geometry("1400x800+0+0")
app = m.LiveRankingApp(root)
asked = []
app.dialog_hook = lambda kind, title, msg, d=None: asked.append((kind, title, msg)) or True
launched = []
app.launch_setup = lambda path: launched.append(path)
app.installed_build = lambda: True
def pump(sec=0.4):
    end = time.time() + sec
    while time.time() < end: root.update(); time.sleep(0.02)
check("Version im Fenstertitel", f"v{m.APP_VERSION}" in root.title())
app.settings["updates"]["last_check"] = 0
app.check_updates(manual=False); pump(1.0)
check("neue Version angeboten mit Release-Text", any("Neue Version" == t and "Testfunktion" in msg for _k, t, msg in asked))
check("Setup geladen, Prüfsumme ok, gestartet", launched and open(launched[0], "rb").read() == payload)
# falsche Pruefsumme
launched.clear(); asked.clear()
sums["txt"] = f"{'0' * 64}  SWV_LiveRanking_Setup_{newer}.exe\n"
app.check_updates(manual=True); pump(1.0)
check("falsche Prüfsumme: nicht gestartet", not launched and any(k == "error" for k, _t, _m in asked))
# abgelehnt: beim naechsten automatischen Start nicht erneut fragen
asked.clear()
app.dialog_hook = lambda kind, title, msg, d=None: asked.append((kind, title, msg)) or False
app.check_updates(manual=True); pump(1.0)
asked.clear(); app.settings["updates"]["last_check"] = 0
app.check_updates(manual=False); pump(1.0)
check("abgelehnte Version nicht sofort wieder angeboten", not asked)
# aktuelle Version
m.fetch_latest_release = lambda url=None, timeout=8: dict(fake_release(), version=m.parse_version(m.APP_VERSION), tag="v" + m.APP_VERSION)  # zaehlt via fake_release
asked.clear(); app.check_updates(manual=True); pump(1.0)
check("aktuell: Meldung bei manueller Suche", any("aktuell" in msg for _k, _t, msg in asked))
# Abschalten
app.settings["updates"]["check"] = False; app.settings["updates"]["last_check"] = 0
n = calls["fetch"]; app.check_updates(manual=False); pump(0.5)
check("abgeschaltet: keine Prüfung beim Start", calls["fetch"] == n)
print("GESAMT", "OK" if all(ok) else "FEHLER")
