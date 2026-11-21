# Hinweise für Claude

- Korrekturen sammeln, erst umsetzen, wenn Stefan «korrigiere jetzt» schreibt.
- Bei jedem Release (neue `APP_VERSION`): `python tools/screenshot.py` mit Anzeige (Linux: Xvfb :99) ausführen.
  Das Skript legt `docs/screenshots/ui_v<Version>.png` an, entfernt ältere Screenshots und aktualisiert das Bild im README.
  Screenshot, CHANGELOG und Code im selben Commit.
- Tests: `tests/test_*.py` (brauchen eine Anzeige).
- Release baut GitHub Actions automatisch bei neuer `APP_VERSION` auf `main`.
