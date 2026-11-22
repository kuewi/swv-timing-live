"""Abschnitt der Version aus CHANGELOG.md als Release-Text schreiben (den zeigt auch die Update-Meldung)."""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ver, out = sys.argv[1], sys.argv[2]
text = open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8").read()
m = re.search(rf"^## v{re.escape(ver)}\b.*?$\n(.*?)(?=^## v|\Z)", text, re.M | re.S)
body = m.group(1).strip() if m else f"Version {ver}"
body += "\n\nInstallieren: SWV_LiveRanking_Setup_" + ver + ".exe herunterladen und ausführen. " \
        "Eine installierte ältere Version wird ersetzt, die Daten in Dokumente\\SWV Live-Ranking bleiben."
open(out, "w", encoding="utf-8").write(body + "\n")

