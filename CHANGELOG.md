# Änderungen

## v1.22.0 (26.11.2026)
Aus den Fehlerberichten vom 26.11.2026 (CP 545 über USB als Hauptgerät, TM550 über USB als Reserve):
- Ziel freigeben schreibt die echte Zielnummer wieder an den CP. Vorher blieb dort die Sperrnummer 9999: der Zielimpuls von Nr 1 ging am CP an 9999, Nr 1 lief am CP weiter (überholen von 202 schien dann schiefzugehen)
- Abgleich Haupt- und Reserve-Gerät: Toleranz 0,05 s plus Auflösung des gröberen Geräts (TM550 auf 1/10 schneidet Zehntel ab, vorher fest 0,05 s: «nur beim Reserve-Gerät» bei 301, 302, 304 und «Reserve hat den Impuls nicht erhalten»). Bei mehreren Impulsen gilt der nächstgelegene (204/301 wurden vertauscht)
- Doppelkontakt: Zweitimpuls innerhalb der Prellzeit nur an einem Gerät wird ohne Rückfrage «Abweichung» verworfen. Die Prellzeit Start/Ziel der App geht als Sperrzeit der Eingänge an CP 545 (1/100 s) und TM550 (1/1000 s), damit der CP einen Zweitimpuls nicht dem nächsten Boot gibt (00:59:26.18 ging am CP an Nr 301)
- Handimpuls am Hauptgerät (z.B. Boot am CP mit der grünen Taste beenden): keine Warnung mehr, die Reserve habe ihn nicht erhalten
- Beim Verbinden gelten gesperrte Eingänge des Hauptgeräts auch in der App (Start/Ziel sperren eingeschaltet, Eintrag «beim Verbinden»). Die Reserve bekommt den Zustand der App. Ist in der App gesperrt, wird am Gerät gesperrt
- Präzision einmal auf 1/10 umgestellt (aus alten Versionen stand noch 1/100). Eine Änderung in der App geht bei verbundenem Gerät sofort an Haupt- und Reserve-Gerät
- Resultate immer mit der Präzision der App (vorher nach «Präzision am Gerät einstellen» 1:30.30 statt 1:30.3, bei Nr 1 33.70). Die Warnung «CP meldet 22.6s, App rechnete 22.60s» kommt nur noch bei echter Abweichung
- Menü oben: Spalte links ab der Menüleiste mit «Als nächstes am Start» (füllt die Höhe), «Auf Fahrstrecke» und «Empfangene Daten». Ereignis-Ticker und Speaker-Notiz rechts neben LAUFEND und ZIEL. Passt die Zeit im Feld ZIEL nicht, fällt die Kategorie weg (steht in der Zeile darunter)
- «Auf Fahrstrecke»: eine Zeile pro Boot, nur Nr und Name, mindestens 3 Boote ohne Scrollen
- Abfrage der Sperren und des Laufs alle 5 s und Nachfragen `#RT` nur noch im Diagnose-Log
- CP-Suche: findet sie nichts, kommt ein Hinweis mit Adressbereich und Menüweg (F › Einstellungen › Ethernet › Std Connexion, Adresse unter «User Connexion»). Bei schon richtiger Adresse der Netzwerkkarte nur noch eine Suche
- Programmfehler beim Aufklappen einer Auswahlliste im Menü oben behoben (KeyError 'popdown')
- Uhrwarnung: beim TM550 1.18 (falsches Tagesfeld der Firmware) zählt wieder nur die Uhrzeit, ab 1.4 auch das Datum

## v1.21.0 (26.11.2026)
Nach den Gerätetests P und Q vom 25.11.2026 (Eingänge sperren) und den Fotos der Gerätemenüs:
- Start und Ziel sperren sperrt jetzt auch den Eingang am Gerät: CP 545 mit `#WP 006 0k 0` (schwarzer Balken), TM550 mit `#WP 006 0k 2` (rotes Kästchen). Freigeben öffnet ihn wieder. Die App liest den Zustand zurück und warnt, wenn er nicht stimmt. Gilt für Haupt- und Reserve-Gerät
- Sperren am Gerät: rote Sperrtaste am CP 545 (Abfrage alle 5 s) und SHIFT + E1 bis E4 am TM550 (Meldung `&P 023` von selbst) schalten «Start sperren» bzw. «Ziel sperren» in der App mit, mit Eintrag im Ticker
- Sperrnummer 9999 statt 999 (gespeicherte 999 wird einmal umgestellt). Sie bleibt bei gesperrtem Start vorgeladen, weil die grüne Taste am CP auch bei gesperrtem Eingang auslöst
- Präzision ab Werk 1/10 (gespeicherte Einstellungen bleiben)
- TM550: meldet `&P 002` andere Eingänge für Start/Ziel als die App, kommt eine Warnung
- Falsche Uhr am Gerät: die Meldung nennt Datum und Uhrzeit des Geräts und den Menüweg (TM550: Synchronisation › Manual oder GPS, CP 545: F › Synchronisation)
- USB ohne eine Zeile vom Gerät: Hinweis auf Baudrate und «9600 Bds Flow control» am TM550
- «Als nächstes am Start»: ganze Liste der noch nicht gestarteten Nummern, Nummern bestätigen von Hand (grüner Haken) oder aus der Startliste/Onlinetool (Spalte «Bestätigt», blauer Haken, grün geht vor). Mehrfachauswahl mit Ctrl und Shift, Knöpfe «✓ Bestätigen», «Aufheben», «↓» zur nächsten Nummer, Zähler «x von y bestätigt», unbestätigte nächste Nummer orange, Rechtsklick mit «Alle Bestätigungen zurücksetzen»
- Menü oben: Ereignis-Ticker in der linken Spalte wieder sichtbar («Als nächstes» und «Auf Fahrstrecke» kürzer, beide scrollen)
- Browser-Anzeige: Ereignis-Ticker (letzte 15) und Speaker-Notiz des Boots auf der Strecke (nur mit Schalter «Notizen»)
- Knopf «Handbuch ▾» neben «Fehler melden»: lädt Benutzerhandbuch bzw. Training (PDF) in der aktuellen Fassung von GitHub, ohne Internet die zuletzt geladene
- «Netzwerkkarte am PC» nur bei Ethernet: beim Hauptgerät, bei Hauptgerät USB und Reserve Ethernet bei der Reserve
- Simulator CP 545: Display wie am Gerät (Laufnummer, Balken der gesperrten Eingänge, Uhrzeit, NT/PT, nächste Start- und Zielnummer, Boot mit laufender Zeit), rote Sperrtasten, Menü F mit Hauptmenü, Einstellungen (16 Einträge), Zeitmessart (15), Rückfragen mit * = JA, Ethernet über Einstellungen › Ethernet › Std Connexion, Papier «Sock error RST 0» beim Trennen
- Simulator TM550: Kästchen über E1 bis E4 (offen, senden, gesperrt), Eingangsnamen grün/blau, WAIT GPS, Zeilen pro Boot mit Start, Ziel und Laufzeit, Menü Run und Hauptmenü (11 Einträge mit Untermenüs), SHIFT + Ex schaltet 0 → 1 → 2 → 0 und meldet `&P 023`
- Gerätetest: Gruppen P und Q (Eingänge lesen, sperren, Buchse und Taste)

## v1.20.0 (25.11.2026)
Aus den Fehlerberichten vom 24.11.2026 (CP 545 über USB, TM550 1.48 als Reserve):
- Reserve mit falscher Uhr (TM550 nach dem Firmware-Update: 07:39 statt 22:57, Tag 26001): Bis ein Impuls-Paar den genauen Uhrversatz liefert, schätzt die App ihn aus der Eingangszeit am PC (etwa ±0,3 s). Die Laufzeit hängt nie mehr an der Uhr der Reserve (vorher z.B. 522:17 bei Nr 204). Die Rückfrage nennt «Uhr der Reserve geschätzt»
- Start nur an der Reserve: Der CP bekommt danach die nächste Nummer. Vorher nahm die App an, der CP habe selbst weitergezählt, und der CP startete dieselbe Nummer nochmals (Wiederholungsfahrt)
- Neuer Lauf an der Reserve (Zählnummern wieder ab 1): alte und neue Zeiten werden nicht mehr verwechselt (Nr 5 blieb am Start). Mehrere Rückfragen zum selben Impuls werden zusammengefasst
- Präzision CP 545 richtiggestellt: `#WP 001 n` gibt n Stellen im Resultat (RR, Papier) und n+1 in den Zeitzeilen. Für 1/10 schreibt die App jetzt 1 (vorher 0: Papier 1:02 statt 1:02.3). Die Präzision geht beim Verbinden automatisch an Haupt- und Reserve-Gerät. Ein RR des CP mit weniger Stellen überschreibt das Resultat der App nicht mehr
- Vereinswechsel auf dem Papier: beim ersten der beiden Ereignisse «letzter Fahrer des alten Vereins im Ziel» oder «erster Fahrer des neuen Vereins gestartet» (vorher schon beim Start des letzten Fahrers des alten Vereins)
- Nachfrage `#RT` nach einer Zählnummer, die der CP nicht hat, hört nach 3 Versuchen auf (vorher alle 15 s AK F)
- Vorladen: Startet ein Boot, während die App die Nummer schreibt, erzwingt sie die alte Nummer nicht mehr (konnte zwei gleiche Nummern ergeben)
- Menü oben: links eine Spalte mit «Als nächstes am Start», «Auf Fahrstrecke», Ticker und ganz unten «Empfangene Daten», rechts die Ranglisten
- `fernbefehle_test.ps1` Gruppe I stellt die Präzision am CP richtig zurück

## v1.19.0 (24.11.2026)
- Kleine Bildschirme (13''-Laptops): Die Oberfläche passt sich an die nutzbare Fläche an (Bezug 1600 × 900 bei 100 %), Schriften, Abstände und Seitenleiste werden kleiner. Unter Daten › Grösse der Oberfläche: Auto, 90 %, 100 %, 110 %, wirkt sofort. Dialoge sind höchstens so hoch wie der Bildschirm, Tabellen und Textfelder schrumpfen, die Knöpfe (z.B. «Importieren» bei Startliste einlesen) bleiben sichtbar
- Menü oben ist der Standard. Ist eine Seitenleiste angepinnt, bleibt sie
- Im Menü oben ist «Empfangene Daten» das erste Feld oben links im Kartenraster. Die Ranglisten behalten die volle Höhe, die Spalte rechts (Als nächstes am Start, Auf Fahrstrecke, Ticker) ebenfalls
- «Verbindung» in Farbe: grün = Haupt- und Reserve-Gerät verbunden, orange = eines, rot = keines (Knopf im Menü oben, Titel in der Seitenleiste)
- «Fehler melden» steht rot direkt neben der Versionsnummer, im Menü oben und in der Seitenleiste. Die Abschnittsknöpfe im Menü oben brechen bei schmalem Fenster in eine zweite Zeile um, statt Knöpfe aus dem Bild zu schieben
- Startliste › «Startliste eingeben»: Nummern in Startreihenfolge von Hand, mit Bereichen («1-12, 201-215, 301») oder eine Zeile pro Boot mit Angaben (Tab oder Semikolon, aus Excel kopiert). Vorschau mit Anzahl, Kategorien und Warnungen (doppelt, ungültig), Ersetzen oder Anhängen
- Vereinsdruck: Startet ein Boot ausserhalb der Reihenfolge mit neuem Verein, druckt der CP den Verein sofort. Wird nichts gedruckt, steht der Grund im Log. Neuer Lauf oder neue Startliste setzen «schon gedruckt» zurück
- «CP: kein Lauf offen» erscheint nur noch einmal statt alle 15 Sekunden
- USB-Gerät weg (Kabel gezogen oder ausgeschaltet): verständliche Meldung statt «ClearCommError … PermissionError»

## v1.18.1 (24.11.2026)
- Update: Die App schliesst sich nie mehr von selbst. Das Setup wird im Hintergrund geladen und geprüft, die Versionsanzeige wird orange. Danach wählen: «Jetzt installieren» (nur ohne verbundenes Gerät und ohne Boote auf der Strecke, sonst gesperrt mit Grund), «In 8 Stunden» (erinnert nur in einem ruhigen Moment, sonst eine Stunde später) oder «Beim Beenden der App» (Setup startet, nachdem du die App geschlossen hast). Klick auf die orange Versionsnummer öffnet die Auswahl wieder

## v1.18.0 (24.11.2026)
- Reserve-Gerät: Hat nur die Reserve einen Impuls, meldet die App die Abweichung und fragt in einem Fenster, welches Gerät gilt («Reserve übernehmen» oder «Hauptgerät gilt»), auf Wunsch für die ganze Sitzung. Das Rennen läuft weiter, bis zur Antwort gilt die Zeit der Reserve vorläufig. Verworfene Impulse stehen unter «Auf Fahrstrecke» als «nur Reserve». Ist das Hauptgerät getrennt, übernimmt die Reserve ohne Frage
- TM550 1.48 als Reserve in TIMING: bekommt die nächste Startnummer vorgeladen (mit Prüfsumme), seine Nummern werden übernommen. Verschiedene Nummern von Haupt- und Reserve-Gerät für denselben Impuls werden gemeldet, es gilt das Hauptgerät. Sperrnummer auch an der Reserve
- Zielzeit ungültig schalten (Fehlimpuls): Die App lädt die Nummer am CP wieder auf den Zieleingang vor. Lehnt der CP ab (für ihn ist das Boot schon im Ziel), sagt sie, was am CP einzugeben ist («Nr E4»). Beim TM550 Hinweis auf die Smartphone-App
- Versionsnummer neben dem Logo: grün = aktuell, rot leuchtend = neuere Version verfügbar, grau = nicht geprüft. Klick lädt und installiert die neue Version (mit Rückfrage) bzw. prüft sofort. Prüfung beim Start und alle 6 Stunden
- Neben dem Pfeil oben links: Knopf für helles/dunkles Design (Schalter unter Wettkampf entfällt). Der Pfeil versenkt die Seitenleiste ins Menü oben mit Ausklappfeldern und pinnt sie wieder an (Streifen am linken Rand entfällt, Einstellung unter Daten entfällt)
- Scrollen in Seitenleiste und Ranglisten feiner: 40 px je Mausrad-Raste, Touchpads nach Stärke
- Doppelkontakt: Häufen sie sich auf einem Eingang (3 in 10 Minuten), meldet die App einmal, dass der Eingang prellt. Übungsgerät TM550 ohne Doppelkontakt von selbst (Rechtsklick auf die Buchse löst einen aus). Doku richtiggestellt: der Doppelkontakt im Test kam vom Kabel mit Bananensteckern
- `fernbefehle_test.ps1`: Gruppe O (Zielzeit zurücknehmen am CP)

## v1.17.0 (24.11.2026)
Aus dem Gerätetest vom 23.11.2026 mit CP 545 VB16 und TM550 1.48:
- TM550 ab Firmware 1.48: In der Zeitmessart TIMING lädt die App die nächste Startnummer vor (`#WP 026`), die Startzeit kommt mit dieser Nummer. In BASIC, SPEED und LAP vergibt die App die Nummern. Nummern mit führenden Nullen (`0150`), `IR`-Zeilen, LAP als «CIRCUIT», Statuszeilen (`&P …`, `DS/DE` von selbst) werden erkannt. Das Tagesfeld gilt wieder, ausser es weicht mehr als einen Tag vom PC ab
- Doppelkontakt: Der TM550 1.48 meldet einen zweiten Kontakt als eigene Zeile ohne Nummer (1.18: als TC). Die Prellzeit verwirft sie, im Log nur noch leise als «Doppelkontakt». (Im Test kam der Doppelkontakt vom Kabel mit Bananensteckern an E4, nicht von der Firmware.)
- Falschstart: Wird eine Startzeit am Gerät storniert (`TC`, CP: E1 allein, TM550: in der Smartphone-App gelöscht), ist das Boot wieder als nächstes am Start und die Nummer wird wieder vorgeladen. Bisher wurde es als DNF markiert
- CP: verliert eine Zeit am CP ihre Nummer (`T-`, z.B. Umnummerieren oder Neustart einer Nummer), sagt das Log warum
- Präzision unter Zeitmessung: 1 s, 1/10, 1/100 oder 1/1000, abgeschnitten wie am Gerät. Knopf «Präzision am Gerät einstellen» schreibt `#WP 001` (CP 545: Wert minus 1, kleinste Stufe 1/10; TM550 ohne Versatz) und prüft durch Zurücklesen
- Zeitmessarten: Vorladen beim CP in NET TIME, START-FINISH, START-INTER-FINISH und TRAINING, nicht in PTB SEQ; unbekannte Zeitmessart mit Hinweis. «Lauf öffnen» geht auch am CP 545, aber nur in PTB SEQUENTIEL 1-4
- Start/Ziel sperren: Der Schalter blinkt rot. Am CP (und TM550 in TIMING) wird die Sperrnummer 999 vorgeladen (einstellbar, darf nicht in der Startliste stehen), damit ein Impuls in der Pause keine echte Nummer verbraucht. Impulse werden ignoriert, im Log und Ticker gemeldet und unter «Auf Fahrstrecke» als gesperrt aufgeführt. Sperren mit Booten auf der Strecke fragt nach. Freigeben stellt die nächste Nummer wieder ein
- Bedienung: Knopf zum Versenken der Seitenleiste nur noch mit Pfeil. Unter Daten › Bedienung wählbar: Seitenleiste oder Menü oben mit Ausklappfeldern (gleiche Abschnitte). «Empfangene Daten» bleibt in jeder Ansicht unten links sichtbar
- Reserve-Gerät: Paarung nach Gerätezeit, sobald der Uhrversatz bekannt ist. Wartezeit auf das Hauptgerät einstellbar (Standard 3 s). Kommt die Zeile des Hauptgeräts erst danach, gibt es kein Doppel und keine Warnung
- Quelle «GPRS Interface» (TAG Heuer Timing Online): im Feld Gerät `127.0.0.1:Port` eintippen. Nur Empfang, keine Befehle. TM550 mit Werkseinstellung Port 2101 findet die Suche ebenfalls (`ip:2101`)
- Übungsgerät CP 545 nach Handbuch: Taste «ON» statt «C», `*` löscht die Eingabe, «Nr E1» = nächste Nummer, «E1» allein = Falschstart, Display 8 × 21 Zeichen, Zeitmessart im F-Menü. TM550 als Firmware 1.48 mit Zeitmessarten BASIC/TIMING/SPEED/LAP, SHIFT + E1..E4 sperrt einen Eingang
- Doku: [Funkstrecke HL675 und TAG Heuer Timing Online](docs/funk_und_online.md), Testergebnisse 23.11.2026 in [docs/geraetetest.md](docs/geraetetest.md). `fernbefehle_test.ps1`: Gruppe N mit MANUAL ohne Smartphone-App und DNF/DSQ am CP

## v1.16.0 (23.11.2026)
- Verbindung: eigener Knopf «Reserve verbinden» / «Reserve trennen» mit Zustand im Block Reserve-Gerät. Der Knopf des Hauptgeräts verbindet nur noch das Hauptgerät. Wird das Hauptgerät getrennt, bleibt die Reserve verbunden und liefert alle Zeiten. Eine Änderung der Reserve-Auswahl verbindet nicht mehr von selbst
- CP 545 druckt bei einem Vereinswechsel eine Zeile auf den Papierstreifen, z.B. `> RC Rheinfelden (12)`, sobald das letzte Boot des bisherigen Vereins gestartet ist (beim Verbinden vor dem ersten Start auch für den ersten Verein). Umlaute umgeschrieben, auf 24 Zeichen gekürzt, nie doppelt. Schalter «Vereinswechsel auf CP drucken» unter Zeitmessung. Auch ein CP als Reserve druckt, der TM550 nicht
- Update-Prüfung: Zertifikat von GitHub wird mit der Windows-Prüfung kontrolliert (truststore), Rückfall auf die Zertifikate aus certifi. Behebt «CERTIFICATE_VERIFY_FAILED». Schlägt die Prüfung fehl, bietet die App die Release-Seite im Browser an
- Zeitmessung: Hinweistext und Knopf überlappten die Schalter Start/Ziel sperren
- `fernbefehle_test.ps1`: Gruppe I für die Präzision (#RP/#WP 001)

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
