# Änderungen

## v1.6.2 (20.11.2026) Korrekturen in der App
- Der CP 545 kennt `#WC 013` nicht (Antwort AK R): Nummer ändern, Ausgeschieden und Zielzeit umbuchen führt die App selbst. Jede Startzeit führt die Nummer des CP und die richtige Nummer, spätere Meldungen des CP werden umgebucht
- Ausgeschiedene Boote bleiben im CP auf der Strecke: die App lädt mit `#WP 026 04` das richtige nächste Ziel vor
- Fahrzeit rechnet die App sofort aus Start- und Zielzeit, das RR des CP bestätigt sie
- Testnummern lassen sich in die Startreihenfolge einfügen (Vermerk «Test»)
- «Auf Fahrstrecke» als Fluss: oben zuletzt gestartet, unten das nächste Boot im Ziel, darunter der letzte Zieleinlauf

## v1.6.1 (20.11.2026) Korrekturen
- RS232: Abbruch wird erkannt, wenn während eines Laufs länger als 5 s keine Laufzeit kommt (Kabel am CP oder RJ11 ausgesteckt, USB-Adapter bleibt am PC). Status rot, Ticker und Log, automatisch zurück auf «verbunden», sobald wieder Daten kommen
- RS232: ohne Boot auf der Strecke zeigt die Kopfzeile das Alter der letzten Daten
- RS232: Steuerleitungen CTS, DSR und CD werden protokolliert und, falls das Kabel sie führt, als sofortige Abbruchmeldung genutzt
- Ethernet: Suche zuerst ohne Umstellung der Netzwerkkarte (keine Adminrechte nötig, wenn der PC schon im Netz 192.168.1.x ist, z.B. mit der Windows-Einstellung «Alternative Konfiguration»)
- Aufklapplisten folgen dem hellen oder dunklen Design
- Kategoriebereiche werden bei jeder Änderung der Startliste automatisch nachgeführt (auch nach Wiederherstellen der Sitzung und beim Einfügen). Schalter im Abschnitt Kategorien, eine Änderung von Hand schaltet die Automatik aus

## v1.6.0 (20.11.2026) Ethernet-Steuerung
- Verbindungsart RS232 (auswerten) oder Ethernet (THCOM08, CP aktiv steuern)
- Nächste Startnummer vorladen mit Zurücklesen, ausgeschieden, Nummer ändern, Überholen, Zielzeit umbuchen
- Tab «Auf Fahrstrecke», Tab «Als nächstes» scrollbar mit nächster Nummer zuunterst, Doppelklick fügt ein
- Netzwerkkarte automatisch auf 192.168.1.55, beim Beenden zurück auf DHCP, CP-Suche 192.168.1.50 bis .59
- Fenster links über der Seitenleiste, eigene Meldungsfenster, dunkle Titelleisten, helles Design
- Kategoriebereiche aus der Startliste bis ..99, ab 900 bis 950, 951 bis 999 Test

## v1.5.0 (19.11.2026) Apple-Design
- Oberfläche im Apple-Stil, «Einfügen nach Nr», «Notiz hinzufügen» mit Suche

## v1.4.0 (19.11.2026) Korrekturen und eigene Leser
- Eingebaute Leser für .xls, .xlsx und CSV, QR-Code eingebaut, Wiederverbinden nach USB-Abbruch
- Verschiebbare Kategoriekarten, Testnummern, Wettkampfname und Datum

## v1.3.0 (19.11.2026) Speaker-Funktionen und Startliste
- Startliste Einzel und Paar, Teilnehmer erfassen, Strafpunkte nur im Speaker-Ranking
- Ticker, Bestzeit-Vergleich, Rangprognose, Statistik, Browser-Anzeige, Vereinsexport, Onlinetool vorbereitet

## v1.2.0 (19.11.2026)
- Laufzeit ohne Blinken, Log mit Tabs «Fokussiert» und «Alle»

## v1.1.0 (18.11.2026)
- Erste Version SWV Live-Ranking

## v0.2.0 / v0.1.0
- Prototypen Speaker-Board
