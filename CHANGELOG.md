# Änderungen

## v1.15.0 (22.11.2026)
- CP 545: Startnummern lädt die App nur noch vor, wenn der CP sie annimmt. Laut Gerätetest geht das nur in der Zeitmessart NET TIME mit offenem Lauf. Ohne Lauf lehnt der CP ab (AK F), in PTB SEQUENTIEL 1-4 bestätigt er, übernimmt aber nichts (Zurücklesen 0000). In diesen Fällen schaltet die App das Vorladen für die Verbindung ab, meldet das einmal und nummeriert die Starts aus der Startreihenfolge wie beim TM550. Bisher kam bei jedem Start nach drei Versuchen «nicht gesetzt»
- Die Zeitmessart liest die App aus der Lauf-Meldung des CP (OP bzw. DS). Öffnet am CP ein Lauf in NET TIME, lädt sie wieder vor
- Simulator: CP mit Zeitmessart und ohne offenen Lauf wie am Gerät (keine Nummern, keine Laufzeiten vom CP)

## v1.14.1 (22.11.2026)
- TM550: Das Tagesfeld in den Zeitzeilen ist kein verlässliches Datum (Display 22.11.2026, Zeilen Tag 9793 = 24.10.2026, früher auch 189). Die App nimmt beim TM550 als Haupt- und Reservegerät den Tag vom PC-Datum beim Empfang, über Mitternacht anhand der Uhrzeit. Die Uhrprüfung vergleicht beim TM550 damit nur die Uhrzeit, der Reserve-Versatz springt nicht mehr
- Gesperrter Kontakt ohne Zählnummer (`TC           04 …`, TM550 mit AT START) erscheint im Log benannt und zählt nicht als Impuls
- Simulator TM550 schickt wie das echte Gerät ein abweichendes Tagesfeld
- `fernbefehle_test.ps1`: Gruppe H prüft, was die App im Betrieb braucht (Startnummer vorladen, Zeit nachfragen). Anleitung: Test für andere Zeitmessarten am CP

## v1.14.0 (22.11.2026)
Aus dem Gerätetest vom 22.11.2026:
- TM550: Knopf «Lauf öffnen (TM550)» öffnet einen Lauf über die Verbindung (`#WC 002`). «Lauf vom Gerät laden» ohne offenen Lauf bietet das direkt an. Der CP 545 öffnet keinen Lauf auf Befehl, dort erscheint ein Hinweis
- Download (`#DL`) nur noch mit offenem Lauf, am CP auch nicht mehr ersatzweise Lauf 1
- Beantwortet das Gerät keine Befehle mehr, schickt aber weiter Zeiten, meldet die App das einmal mit Abhilfe (Gerät aus und ein, beim CP danach Ethernet einschalten). Zeiten werden weiter übernommen
- Uhr von Haupt- und Reservegerät wird gegen den PC geprüft. Ab 60 s Abweichung Warnung im Log und Ticker
- Hinweis an allen Stellen, dass Ethernet am CP nach jedem Einschalten neu eingeschaltet werden muss (Suche ohne Fund, Verbindungsabbruch, Verbindung abgewiesen, Hinweistext)
- Simulator und Übungsgerät: Befehle wie am echten Gerät (`#WC 001/002/012`, `#SLR/#SLA/#SLC`, `#PL` druckt auf den Papierstreifen), Übungsfall «Gerät neu gestartet» (CP: Ethernet aus, im F-Menü wieder einschalten)
- `fernbefehle_test.ps1`: `-Nur A,G` für einzelne Gruppen, `#DL` nur mit offenem Lauf, neue Gruppe G (Lauf über Startliste bzw. `#WC 002 nn` öffnen). Anleitung mit Testergebnissen ergänzt

## v1.13.1 (22.11.2026)
- Zeitzeilen ohne Stunden oder Minuten werden erkannt (Gerät auf 00:00 synchronisiert, z.B. `TN         1  1        4.30700   365`), bisher verworfen
- Resultatzeilen (RR/GR) mit angehängtem Feld werden gelesen. IR (Zwischenzeit), DR (Differenz Parallelstart) und VE (Geschwindigkeit) erscheinen im Log mit Namen. Zeitzeilen mit negativem Statuscode (skiFFS) zählen nicht als Impuls
- `tools/geraetetest/`: PowerShell-Skripte für Gerätetests, neu `fernbefehle_test.ps1` (Lauf öffnen/schliessen, Resultate auslesen, Startliste im Gerät, Druckzeile)

## v1.13.0 (22.11.2026)
- Verbindung: Hauptgerät und Reserve-Gerät je mit eigener Verbindungsart. Hauptgerät RS232, Ethernet oder USB, Reserve keines, Ethernet oder USB. Damit CP 545 über USB und TM550 über Ethernet, umgekehrt oder beide über Ethernet. Netzwerkkarte erscheint, sobald eines der Geräte Ethernet nutzt, und wird auch für eine Reserve über Ethernet vorbereitet. IP der Reserve aus der Suche oder eingetippt, die App fragt das Gerät ab (CP 545 oder TM550). Reserve lässt sich während des Betriebs wechseln. Die Suche wählt als Hauptgerät nie die Adresse der Reserve
- Üben: CP 545 und TM550 nach Fotos nachgebaut. CP 545 hochkant mit Papierstreifen, Display, Tasten E1 bis E4, Zahlenblock 7-8-9 oben, * 0 R, ⇧ F C links, ▲ ↵ ▼ rechts, grüne Kanaltasten 1 bis 4 mit roter LED. Rückseite mit Buchsen 4 3 2 1, POWER, USB, RS 232, ETHERNET. TM550 in Schildform mit roten Tasten E1 bis E4, Farbdisplay (Uhrzeit, Eingänge, letzte Zeiten, Statuszeile), ON, SHIFT, Pfeilkreuz mit OK. Rückseite mit RS 232, ETHERNET, Buchsen 1 bis 4, USB-C und DC. Klick auf die Ethernet-Buchse zieht bzw. steckt das Kabel
- README zeigt Bilder der beiden Übungsgeräte, werden bei jedem Release neu aufgenommen

## v1.12.0 (22.11.2026)
- ITS/Vola TM550 als Zeitmessgerät, über USB (COM-Port) und Ethernet (Port 7000). Die App erkennt das Gerät an der Seriennummer. Am TM550 empfohlen: Modus TIMING, Start E1, Ziel E4, NO IDENTIFICATION, Lauf offen, kurze Sperrzeit am Ziel
- TM550: die App vergibt die Startnummern aus der Startreihenfolge (keine Vorladung möglich), vom Gerät gesperrte Doppelkontakte werden im Log gezeigt und nicht als Storno gewertet, fehlende Zeilen holt die App per Download des offenen Laufs
- Eingänge für Start und Ziel einstellbar (Zeitmessung, 1 bis 4)
- Reserve-Gerät: CP 545 als Hauptgerät, TM550 (oder zweiter CP) als Reserve über Ethernet oder USB. Die App lernt den Uhrversatz aus gemeinsamen Impulsen, übernimmt Impulse, die dem Hauptgerät fehlen, und bei Ausfall des Hauptgeräts sofort alle Zeiten der Reserve. Warnung, wenn die Reserve einen Impuls nicht sieht oder der Versatz springt
- Üben: CP 545 und TM550 als eigenes Fenster mit Display, Tastatur (Nr R 0, Nr R 0 ., Nr R E1 neue Nr Enter, E1 bis E4), Lauf-Menü, klickbaren Bananenbuchsen (Rechtsklick = Doppelkontakt), Netzwerkkabel ein/aus, Papierstreifen und Übungsfällen (Fehlstart, Kabel 10 s ab, Lauf neu öffnen, falsche Nummer, Doppelkontakt). Übungsprotokoll wird im Datenordner unter `training` gespeichert. Nachbau nach den Handbüchern, keine Original-Firmware
- Fenstertitel zeigt das verbundene Gerät

## v1.11.0 (22.11.2026)
- Version im Fenstertitel und neben dem Logo
- Update-Prüfung: beim Start (abschaltbar unter «Daten») und mit «Jetzt nach Updates suchen». Neue Version mit Release-Text, auf Ja wird das Setup von GitHub geladen, mit SHA-256 geprüft und gestartet, die App schliesst sich. Ohne Installation: Hinweis mit Link zur Download-Seite. Abgelehnte Version wird 12 Stunden nicht erneut angeboten
- Release enthält `SHA256SUMS.txt`, Release-Text kommt aus dem CHANGELOG

## v1.10.1 (21.11.2026)
- Fehlerbericht ad4f: Lauf am CP geschlossen und mit derselben Nummer wieder geöffnet (Zählung beginnt wieder bei 1): die bisherigen Zeiten werden als eigene Runde abgelegt, neue Zeiten wieder verarbeitet, Resultate bleiben. Erkennung auch, wenn dieselbe Zählnummer mit neuer Uhrzeit kommt
- Wechsel Ethernet ↔ USB oder neues Verbinden in derselben Sitzung: Zeiten, die der CP in der Zwischenzeit gepuffert hat, werden nachgetragen
- Ethernet-Suche: hat die Netzwerkkarte keine Verbindung (kein Kabel), meldet die App das direkt mit Prüfpunkten. Liste der Netzwerkkarten wird bei jeder Suche aufgefrischt. Jeder Suchschritt und jeder Verbindungsabbruch (mit zuletzt gesendeter und empfangener Zeile) im Diagnose-Log

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
