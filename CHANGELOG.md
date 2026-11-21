# Änderungen

## v1.10.0 (21.11.2026)
- SWV-Logo: Symbol für .exe, Setup, Desktop, Startmenü, Fenster und Taskleiste (eigene App-Kennung), Logo oben in der Seitenleiste. Vektor-Nachzeichnung in `assets/swv_logo.svg`
- Fehlerbericht a23e: Storno einer älteren Startzeit am CP (z.B. nachgeholt nach einem Unterbruch) setzt das Boot nicht mehr auf DNF, wenn es inzwischen neu gestartet ist
- Fehlerbericht a23e: Zeit des CP (RR) gilt nur für die Zielzeit, die der CP direkt davor gemeldet hat. Gehört diese keinem oder einem anderen Boot, bleibt die Zeit der App
- Fehlerbericht a23e: Zeilen ohne Startnummer (z.B. `TN        10 M4 ...`) werden erkannt, die App fragt sie nicht mehr endlos nach
- Fehlerbericht 7ed8: Kategorienamen ohne Unterschied von Gross/Klein («JUNGFAHRER» = «Jungfahrer»), kein ständiges Nachführen der Bereiche mehr. Ein Neuaufbau der Ranglisten behält das Blinken neuer Resultate

## v1.9.1 (21.11.2026)
- Nummer ändern auf der Fahrstrecke: Hinweis mit der Tastenfolge für den CP (alte Nr R E1 neue Nr Enter), weil der CP 545 nicht ferngesteuert umnummeriert. Auf der Fahrstrecke steht «CP führt noch Nr X», bis der CP nachgezogen hat
- Korrektur an der Tastatur des CP (T*) gilt immer, auch nach einer Änderung in der App

## v1.9.0 (20.11.2026)
- Installer `SWV_LiveRanking_Setup_x.y.z.exe`: Programm in «Programme», Startmenü, optional Desktop, Eintrag unter «Apps» mit Version und Deinstallation. Eine neue Version ersetzt die installierte, ältere Versionen nur nach Rückfrage. Versionsinfo in den Dateieigenschaften der .exe
- Datenordner `Dokumente\SWV Live-Ranking` (Einstellungen, Autosave, `logs`, `rohdaten`, `fehlerberichte`, `pdf`), bleibt bei Update und Deinstallation. Daten vom bisherigen Ort werden beim ersten Start übernommen. Knopf «Datenordner öffnen»
- Diagnose-Log (10 × 5 MB): Bedienung, Meldungen und Antworten, jede Zeile vom und zum CP, Zuordnungsentscheide, geänderte Einstellungen, Programmfehler mit Traceback. Programmfehler erscheinen zusätzlich in der App
- «Fehler melden» (Knopf oben in der Seitenleiste, Taste F12): Zeitpunkt wird sofort markiert, Beschreibung eingeben, ZIP mit Beschreibung, Session-Dump, Logs, Rohdaten, Autosave und Bildschirmfoto. Liste der Berichte für den späteren Upload ins Onlinetool
- DNS rückgängig: Nummer wieder einfügen hebt DNS auf, Rechtsklick in «Als nächstes» zeigt die Abwesenden zum Einfügen
- DSQ auf der Strecke: «fährt weiter ins Ziel» behält das Boot in der Zielreihenfolge, sein Zielimpuls wird ihm zugeordnet, nicht klassiert. «ist schon draussen» wie bisher
- Schalter «Start sperren» und «Ziel sperren» direkt in den Bannern «Laufend» und «Ziel» (Ethernet und USB)
- Seitenleiste versenkbar: fährt am linken Rand heraus und wieder weg, oder angepinnt. «Startliste» und «Manuelle Zeiterfassung» zuklappbar
- PDF über den Explorer öffnen, damit der PDF-Reader nicht wegen der unsignierten App warnt. Drucken im Reader mit Ctrl+P

## v1.8.1 (20.11.2026)
- USB am CP 545 bestätigt (COM-Port, 9600 Bd, Prüfsumme CS16 stimmt)
- Puffer des CP beim Verbinden: der CP schickt zuerst alle Zeilen seit dem letzten Abholen (auch alte Läufe). Beim ersten Verbinden werden diese nicht als neue Impulse gewertet, nur Lauf und Sequenzen übernommen. Nach einem Unterbruch in derselben Sitzung werden die verpassten Zeiten nachgetragen. Gilt auch für Ethernet

## v1.8.0 (20.11.2026)
- Verbindungsart «USB»: CP 545 direkt per USB-Kabel (virtueller COM-Port), gesteuert wie über Ethernet. Rahmen nach THCOM08 für RS232 mit TAB und Prüfsumme, Zeilen mit falscher Prüfsumme werden verworfen und per `#RT` nachgeholt. Optional ACK nach jeder Zeile (Flow Ctrl). Findet den Port nach dem Ausstecken wieder, auch mit neuer COM-Nummer
- Überholen per Ziehen: ein Boot unter «Auf Fahrstrecke» auf ein anderes ziehen, es übernimmt dessen Platz in der erwarteten Zielreihenfolge. Die Reihenfolge bleibt im Autosave, neu gestartete Boote kommen hinten dazu

## v1.7.0 (20.11.2026) Zeitmessung wie OpenSkiPro2 / SkiPro
- Zielimpulse ordnet die App selbst zu: das Boot, das als nächstes erwartet wird (Überholen berücksichtigt). Der CP wird mit `#WP 026 04` nur noch für seinen Papierstreifen nachgeführt
- Fehlende Zeiten werden mit `#RT` nachgeholt (Sequenzlücke oder Abfrage beim Heartbeat)
- «Lauf vom CP laden» (`#DL`): übernimmt nur Zeiten, die der App fehlen, z.B. nach einem Neustart
- Fehlimpulse: Prellzeit für Start und Ziel (ms) und Mindestfahrzeit (s) einstellbar; Zielzeit nachträglich ungültig schalten
- Start und Ziel sperren: Impulse werden ohne Nummer gespeichert und unter «Auf Fahrstrecke» von Hand zugeordnet
- Rohimpulse als Grundlage: jede Zeile des CP sofort in `rohdaten/JJJJ-MM-TT.jsonl`, Rohzeiten im Autosave, «Resultate aus Rohzeiten neu berechnen»
- Status DNS, DNF, DSQ: Rechtsklick in «Als nächstes» (DNS), Menü auf der Fahrstrecke (DNF, DSQ), Rechtsklick in der Rangliste (DSQ), Teilnehmerfenster. Nicht klassierte stehen im Kartentitel, in PDF und API
- Gleiche angezeigte Zeit = gleicher Rang, bei Gleichstand höhere Startnummer zuerst
- Simulator in der App: Start, Ziel, verlorene Zeile, automatischer Ablauf, Log abspielen (Rohdaten oder PuTTY-Log)
- Reserve-CP: zweiter CP über Ethernet, seine Zeiten werden übernommen, solange der Haupt-CP fehlt
- API: `/api/v1/live`, `/results`, `/course`, `/startlist`, `/events` und WebSocket `/ws` (Browser-Anzeige jetzt live, Rückfall auf Abfrage)
- PDF und Drucken: Rangliste, Startliste, Zeitprotokoll (ohne Zusatzmodule)
- Zeiten über Mitternacht (Tag aus der Meldung des CP)

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
