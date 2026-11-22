"""Update-Pruefung: Zertifikatspruefer der Reihe nach, Pruefung nie aus (Bericht 22.11.2026 CERTIFICATE_VERIFY_FAILED)."""
import os, sys, ssl, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
a, b = ssl.create_default_context(), ssl.create_default_context()
m._SSL_CTX[:] = [("windows", a), ("python+certifi", b)]
seen = []
def fake(req, timeout=None, context=None):
    seen.append(context)
    if context is a:
        raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get issuer certificate"))
    return "OK"
urllib.request.urlopen = fake
check("Rückfall auf zweiten Prüfer", m._urlopen("x", 5) == "OK" and seen == [a, b])
check("alle Prüfer mit Zertifikatsprüfung", all(c.verify_mode == ssl.CERT_REQUIRED and c.check_hostname for _n, c in m._SSL_CTX))
seen.clear()
def fake2(req, timeout=None, context=None):
    seen.append(context); raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED"))
urllib.request.urlopen = fake2
try:
    m._urlopen("x", 5); check("alle scheitern: Fehler", False)
except urllib.error.URLError as e:
    check("alle scheitern: Zertifikatsfehler weitergegeben", "CERTIFICATE_VERIFY_FAILED" in str(e) and len(seen) == 2)
def fake3(req, timeout=None, context=None):
    seen.append(context); raise urllib.error.URLError("timed out")
seen.clear(); urllib.request.urlopen = fake3
try:
    m._urlopen("x", 5)
except urllib.error.URLError:
    check("anderer Fehler: kein zweiter Versuch", len(seen) == 1)
print(f"{sum(ok)}/{len(ok)} OK"); sys.exit(0 if all(ok) else 1)
