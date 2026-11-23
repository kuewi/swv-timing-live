# Notizen: FDS TBox / DBox

Stand 23.11.2026. Kein Verein hat derzeit eine TBox von FDS, deshalb nicht umgesetzt. Grundlage: FDS-Dokument
«TBox / DBox Wired Communication Protocols», Version EN 1.12 (Oktober 2026), erhältlich bei FDS
(www.fdstiming.com). Das Dokument selbst liegt nicht im Repo.

## Geräte und Anschlüsse

- TBox (Modelle u.a. TBox-40, TBox-41, TBox-Radio) und DBox.
- USB (virtueller COM-Port) und RS232 (Klinke, TBox-41 und DBox mit zweitem RS232). Kein Ethernet; über eine
  RS232-Ethernet-Box ginge es, dann ohne Prüfsumme.
- 8 Datenbits, 1 Stoppbit. Bei USB muss die App DTR setzen (macht sie schon, wie beim TM550).
- Welches Protokoll auf welchem Anschluss läuft, ist ein Parameter der TBox (USB: 060, RS232: 050/052) oder
  wird mit dem «Device Manager» von FDS eingestellt.

## Protokolle der TBox

| Protokoll | Inhalt | Für die App |
| --- | --- | --- |
| FDS-Timer | Text, TAG-Heuer-kompatibel (THCOM08) | Stufe 1 |
| FDS-Binary | binär, volle Steuerung | Stufe 2 |
| ALGE, SEICO | nur Zeitausgabe | nicht nötig |
| FDS-Display, Printer | nur Ausgabe an Anzeige/Drucker | nicht nötig |

## Stufe 1: FDS-Timer (Text), Aufwand rund 1 Tag

- Zeilen wie CP 545: `TN`/`AN NNNN SSSS CC HH:MM:SS.FFFFF DDDDD`, Tage ab 1.1.2000, Eingang 1-99 oder
  M1-M9 (Hand), Prüfsumme CS16 nach TAB wie beim CP, optional.
- Befehle laut Dokument:
  - `#DL RRRR`: Lauf laden, 0 = aktueller Lauf, Antwort `DS` … `DE`
  - `#WC 007 TT HH:mm DD/MM/YY`: Synchronisation (1 intern, 2 manuell, 3 auf Null, 5 GPS)
  - `#WC 008 NN`: Handimpuls auf Eingang NN
  - «Time Stamps Recall» wird erwähnt, ein Befehl ist im Textteil nicht beschrieben
- Nicht beschrieben: Startnummer vorladen, `#SN`, `#RP`, Quittungen `AK`.
- Umsetzung in der App: neues Geräteprofil wie TM550 (Startnummern aus der Startreihenfolge, Nachholen über
  `#DL 0`), Gerät in der App von Hand wählen (keine Seriennummer im Textmodus), Simulator-Profil, Tests.

## Stufe 2: FDS-Binary, Aufwand rund 3-4 Tage plus Gerätetest

Rahmen: `DLE SOF SEQ FLAGS NUTZDATEN DLE EOF LRC2 LRC1`, DLE = 0x10 (in Kopf und Daten verdoppelt),
SOF 0x02, EOF 0x03, Prüfsumme LRC1/LRC2 (laufende Summen über Kopf und Nutzdaten), Zahlen little endian.
FLAGS: Quittung anfordern, Quittung mit/ohne Daten, Befehl abgelehnt. Meldungen ab ID 128 schickt die TBox
von sich aus (SEQ 0). Eingangspuffer der TBox: 16 Rahmen.

Was die App damit könnte:

| ID | Inhalt | Nutzen |
| --- | --- | --- |
| Befehl 016 | Startnummer für den nächsten Impuls auf Eingang n | Nummern vorladen wie am CP 545 |
| Befehl 012 | Zeit nachfragen (Zählnummer, Eingang) | gezielt nachholen |
| Befehl 011 | Lauf laden (0 = aktuell) | vollständig nachholen |
| Befehl 013 | Druckzeile, max. 24 Zeichen ASCII | Vereinswechsel drucken (FDS-Drucker) |
| Befehl 010 | Synchronisation | Uhr aus der App stellen |
| Meldung 129/130 | neue/nachgefragte Zeit mit Eingang, Zählnummer, Startnummer, Flags | Zeitzeilen |
| Meldung 136 | bestehende Zeit mit neuer Startnummer | Nummernkorrektur am Gerät übernehmen |
| Meldung 134 | Resultat (Auto-Timing) | Kontrolle |
| Parameter 038/039 | letzte Zählnummer pro Eingang | Lücken sofort erkennen |
| Parameter 033/030 | Gerätezeit, Synchro-Status | Uhrprüfung |
| Parameter 040 | Sperrzeit pro Eingang (10 ms) | Prellzeit aus der App setzen |
| Parameter 032 | Präzision | Präzision aus der App setzen |
| Parameter 002/004 | Geräteinfo, Akku | Erkennung, Akkuanzeige |
| Parameter 011 | Laufzähler | Laufnummer |

Flags einer Zeit (Meldung 129): von Eingang, Handzeit, softwareerzeugt, kopiert, eingefügt; Funkstatus;
«Zeiten verpasst»; über Funk weitergeleitet.

Umsetzung: Rahmen lesen/schreiben, Binärmeldungen in die internen Zeitzeilen übersetzen (Strecke, Ranking,
Reserve-Gerät bleiben unverändert), Simulator für das Binärprotokoll, Tests.

## Offen, erst am Gerät prüfbar

- Tageszählung: Text ab 1.1.2000, Binär ab 1.1.2001 (laut Dokument).
- Ob die TBox im Textmodus Befehle quittiert und welches Recall-Format sie nutzt.
- Verhalten bei Unterbruch (puffert sie wie der CP oder nicht wie der TM550).
- Funkeingänge (TBox-41: Radio A-F) auf Kanäle gelegt, für die App normale Eingänge.
- Testskript wie `tools/geraetetest/fernbefehle_test.ps1` für Text und Binär (rund 1 Stunde).

## Reihenfolge, sobald ein Verein eine TBox hat

1. Testskript an der TBox laufen lassen.
2. Stufe 1 (Textprotokoll) einbauen.
3. Stufe 2 (Binär), wenn Nummern vorladen oder Prellzeit aus der App gebraucht werden.
