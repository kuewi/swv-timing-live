# Notizen: ALGE-TIMING (Anzeigetafeln und Zeitmessgeräte)

Stand 25.11.2026. Kein Verein nutzt derzeit ALGE-Geräte mit der App, deshalb nicht umgesetzt. Grundlagen:
- THCOM08 (TAG Heuer, 16.08.2012): Parameter 015, das Dokument liegt nicht im Repo;
- ALGE-Handbücher Timy, Timy2, Timy3 (RS232 und Anzeigetafel), GAZ5 und D-LINE (Anzeigetafel) von
  alge-timing.com;
- FDS-Dokument zur TBox (siehe [fds_tbox.md](fds_tbox.md)), das ALGE als Ausgabeprotokoll nennt.

Nicht am Gerät getestet. Was hier steht, stammt aus den Unterlagen und muss vor einer Umsetzung mit einem echten
Gerät geprüft werden.

## Wo ALGE vorkommt

| Fall | Richtung | Für die App |
| --- | --- | --- |
| CP 545 / CP 540 steuert eine ALGE-Anzeigetafel | CP → Tafel (RS232) | App liest mit, wie heute bei der TAG-Anzeige |
| ALGE-Zeitmessgerät (Timy, Timy2, Timy3) statt CP | Timy → PC (RS232/USB) | neues Geräteprofil, nur Empfang |
| ALGE-Tafel (GAZ, D-LINE) am PC | App → Tafel | Speaker-/Publikumsanzeige ohne TAG-Tafel |
| FDS TBox mit Ausgabe «ALGE» | TBox → Tafel | wie CP → ALGE-Tafel |

## CP 545 / CP 540: Anzeige-Ausgang auf ALGE

THCOM08, Parameter 015 «RS232 Main definition» (CP540):

| Wert | Ausgabe am RS232-Hauptanschluss |
| --- | --- |
| 0 | RS232-Daten für den PC (THCOM08-Zeilen) |
| 1 | Anzeige TAG HL960 und HL990 |
| 2 | Anzeige TAG HL970 und HL980 |
| 3 | Anzeige ALGE |

- Lesen `#RP 015`, schreiben `#WP 015 X`, Antwort `&P 015 X`. Die Baudrate steht in Parameter 016
  (0 = 2400, 1 = 9600, 2 = 9600 mit Flusskontrolle, 3 = 38400, 4 = 57600). ALGE-Tafeln brauchen 2400 Baud.
- Parameter 019 (Aux2, CP540) hat dieselben Werte wie 015.
- Für den CP 545 nicht geprüft. Vermutlich gleich, das CP-545-Handbuch nennt die Anzeige-Auswahl im Menü.
- Die App wertet in der Verbindungsart RS232 heute das TAG-Anzeigeprotokoll aus. Steht der CP auf ALGE (3),
  versteht sie den Datenstrom nicht. Für die App den CP auf TAG-Anzeige (1 oder 2) lassen oder einen
  ALGE-Parser ergänzen (unten).

## Protokoll ALGE-Anzeigetafel (GAZ, D-LINE)

Schnittstelle: RS232 ohne Handshake, ASCII, 1 Start-, 8 Daten-, 1 Stoppbit, keine Parität. ALGE-Standard
2400 Baud; D-LINE auch 4800, 9600 und 19200. Zeilenende CR (0x0D), bei manchen Geräten LF + CR.
Anschluss an der Tafel: Bananenstecker gelb (Daten, RXD) und schwarz (Masse), RS485 weiss/blau.

Zeile (Timy2-Handbuch, Abschnitt 12.3), Positionen ab 1:

| Position | Inhalt |
| --- | --- |
| 1-3 | Startnummer `NNN` (Hunderter, Zehner, Einer) |
| 4 | Kennung: `.` = laufende Zeit, Buchstabe = Eingang |
| 5-8 | Leerzeichen |
| ab 9 | Zeit `HH:MM:SS.zht` (z = 1/10, h = 1/100, t = 1/1000) |
| danach | Rang `RR` oder 2 Leerzeichen |
| Ende | CR |

Formen:
- Laufende Zeit ohne 1/10: `NNN.xxxxxxxxM:SSxxxx` bzw. `NNN.xxxxHH:MM:SSxxxx`.
- Laufende Zeit mit 1/10: `NNN.xxxxHH:MM:SS.zxx`.
- Zielzeit (Eingang C1): `NNNCxxxxHH:MM:SS.zhtRR`.
- Gesamtzeit: `NNNDxxxxHH:MM:SS.zhtRR`.
- Zwischenzeiten: `A` = C2, `B` = C3, `E` = C4, `F` = C5, `G` = C6, `H` = C7, `I` = C8.
- Geschwindigkeit: `NNNSxxx©xxxxsxss.ssxRR`, `©` = Einheit (01 km/h, 02 m/s, 03 mph).

(`x` = Leerzeichen.)

Weitere Kennungen laut GAZ5-Handbuch:
- `J` = Tafeladresse A bis J (Tafel 1 bis 10) bei mehreren Tafeln an einer Leitung.
- Startnummer bis 4 Stellen (Nt, Nh, Nz, Ne).
- Rang 2 Stellen.
- D-LINE kennt zusätzlich ein «erweitertes Protokoll» mit Geräteadresse ([A1-40], [A3 nn]) und freier
  Zuordnung der Zeichen zu den Stellen. Dessen Byte-Aufbau steht nicht in den Unterlagen.

## Protokoll ALGE-Zeitmessgerät → PC (Timy, Timy2, Timy3)

Schnittstelle: RS232 oder USB (virtueller COM-Port), ASCII, 8N1. Timy3 ab Werk 9600 Baud (2400 bis 38400),
der alte Timy fest 38400 Baud.

Zeile (Timy2-Handbuch, Abschnitt 12.1): `yNNNNxCCCxHH:MM:SS.zhtqxGGRRRR` + CR

| Feld | Inhalt |
| --- | --- |
| `y` | Info: Leerzeichen = normal, `?` = Zeit ohne gültige Startnummer, `m` = aus dem Speicher, `c` = gelöscht (CLEAR), `C` = Speicherzeit gelöscht, `d` = disqualifiziert, `i` = von Hand eingegeben, `n` = neue Startnummer |
| `NNNN` | Startnummer bzw. laufende Nummer, ohne führende Nullen |
| `CCC` | Kanal: `c0` Start, `c1` Ziel, `c2` bis `c8` weitere; `M` dahinter = Handauslösung (Taste); `RT` Laufzeit, `TT` Gesamtzeit, `SQ` Rundenzeit, `kmh` Geschwindigkeit |
| `HH:MM:SS.zhtq` | Tageszeit bis 1/10000 s (Beispiele zum Teil mit Komma statt Punkt) |
| `GG` | Gruppe bzw. Runde oder leer |
| `RRRR` | Rang, nur bei Ranglisten-Ausgabe |

Beispiele aus den Handbüchern:
- `0033 C0 07:50:40.2828 00`: Impuls 33, Kanal 0.
- `0044 C1M 07:50:42.66 00`: Kanal 1, Handauslösung, 1/100.
- ` 0020 c0 15:44:15,0077 00`: normal.
- `m 0008 c1 15:44:00,2849 00`: aus dem Speicher.
- `C 0011 c0 15:44:01,0366 00`: Speicherzeit gelöscht.

Zwischen den Impulsen schickt der Timy jede 1/10 s die laufende Zeit (`07:50:40.2`).

Genauigkeit: C0 bis C4 1/10000, C5 bis C8 und Handkanäle 1/100.

Befehle PC → Timy (Auszug): `NSF?` (Programmversion), `TIMYINIT` (Hardware-Nummer), `RSM` (Speicher über
RS232 senden), `KL0/KL1` (Tastatur sperren), `DTS`/`DTF` (Sperrzeit Start/Ziel, z.B. `DTS09.99`),
`BE0/BE1` (Piepton), `PRI…` (Drucker). Startnummer vorladen und einzelne Zeiten nachfragen sind nicht
beschrieben.

## Mögliche Umsetzung in der App

1. **ALGE-Anzeigestrom lesen** (CP auf Anzeige ALGE, oder ALGE-Gerät am Anzeigeausgang): Parser für die
   Tafelzeile in der Verbindungsart RS232, Kennung `.` = laufend, `C` = Ziel mit Rang. Aufwand etwa ½ Tag.
   Wie heute beim TAG-Anzeigeprotokoll nur Endzeiten, keine Startzeiten, keine Korrekturen.
2. **ALGE-Timy als Zeitmessgerät**: neues Geräteprofil, nur Empfang.
   - Zeilen `c0`/`c1` → Start/Ziel.
   - Info-Zeichen `c`/`C`/`d` → storniert, `?` → ohne Nummer.
   - Startnummern aus der Startreihenfolge wie beim TM550 ohne Vorladen.
   - Die laufende Zeit (1/10-Zeilen) verwerfen.
   - Nachholen über `RSM` (Speicher senden) prüfen.
   - Aufwand etwa 1 bis 2 Tage plus Gerätetest.
3. **ALGE-Tafel aus der App ansteuern**: die App sendet Startnummer, Zeit und Rang im Tafelformat an einen
   COM-Port (2400 Baud). Damit liesse sich eine vorhandene GAZ/D-LINE als Publikumsanzeige nutzen. Aufwand
   etwa ½ Tag, mit Einstellung des Anschlusses und Test an einer echten Tafel.

Offen: Wird beim CP 545 der Parameter 015 = 3 unterstützt? Welche ALGE-Geräte haben die Vereine? Das
erweiterte D-LINE-Protokoll ist nicht beschrieben.
