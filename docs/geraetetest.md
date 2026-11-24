# Gerätetest mit PowerShell (CP 545 und TM550)

Prüft ohne die App, welche Befehle CP 545 und TM550 annehmen. Ergebnis: je eine Textdatei pro Gerät
und Verbindung, die für den Einbau in die App ausgewertet wird.

Nur ausserhalb eines Rennens: der Test schliesst und öffnet Läufe und schreibt eine Startliste ins Gerät.

| Gerät | IP | Port | Prüfsumme |
| --- | --- | --- | --- |
| PC | 192.168.1.55 / 255.255.255.0 | | |
| CP 545 | 192.168.1.50 | 13500 | nein |
| TM550 | 192.168.1.51 | 7000 | ja (macht das Skript) |

Dauer: etwa 15 Minuten pro Gerät und Verbindung.

## 1. Skripte holen

PowerShell öffnen (Startmenü › «PowerShell»), dann:

```powershell
$d = "$env:USERPROFILE\Documents\SWV Geraetetest"
New-Item -ItemType Directory -Force $d | Out-Null
cd $d
$u = "https://raw.githubusercontent.com/kuewi/swv-timing-live/main/tools/geraetetest"
Invoke-WebRequest "$u/fernbefehle_test.ps1" -OutFile fernbefehle_test.ps1
Invoke-WebRequest "$u/tm550_test.ps1" -OutFile tm550_test.ps1
Unblock-File .\*.ps1
dir
```

`dir` zeigt beide Dateien. Dieses Fenster bleibt für alle weiteren Schritte offen.

## 2. App schliessen

SWV Live-Ranking beenden. Der CP 545 nimmt auf Port 13500 nur eine Verbindung an, ein COM-Port nur ein
Programm.

## 3. Geräte vorbereiten

**CP 545**
- Einschalten, Papier eingelegt.
- Ethernet einschalten (F › Einstellungen › Ethernet), IP 192.168.1.50. **Nach jedem Einschalten des CP
  ist Ethernet wieder aus** und muss neu eingeschaltet werden.
- Datum und Uhrzeit am CP prüfen.
- Ein Lauf ist offen. Laufnummer notieren.

**TM550**
- Einschalten.
- Communication › Ethernet: IP 192.168.1.51, Port 7000.
- Modus TIMING, Identifikation NO IDENTIFICATION, ein Lauf ist offen. Laufnummer notieren.
- Datum und Uhrzeit am Gerät stimmen (der TM550 stand nach dem Ausschalten auf 8.7.2000).

Beide Geräte brauchen verschiedene IPs. Hat der CP 545 eine andere IP als .50, diese im Aufruf mit
`-Ip` angeben.

## 4. Netzwerk am PC

Kabel PC ↔ Gerät direkt, oder PC und beide Geräte an einen Switch.

Name der Netzwerkkarte suchen:

```powershell
Get-NetAdapter | Format-Table Name, Status, LinkSpeed
```

Die Karte mit dem Kabel zum Gerät steht auf «Up». Ihr Name (z.B. `Ethernet`) wird unten gebraucht.

PC-Adresse setzen: PowerShell **als Administrator** öffnen (Rechtsklick auf PowerShell › «Als
Administrator ausführen»), dann (`Ethernet` durch den Namen ersetzen):

```powershell
New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.1.55 -PrefixLength 24
```

Meldet Windows, die Adresse gebe es schon: passt, weiter. Das Administrator-Fenster wieder schliessen,
weiter im normalen Fenster aus Schritt 1.

## 5. Verbindung prüfen

```powershell
Test-NetConnection 192.168.1.50 -Port 13500   # CP 545
Test-NetConnection 192.168.1.51 -Port 7000    # TM550
```

Erwartet: `TcpTestSucceeded : True`. Der TM550 beantwortet keinen Ping, die Ping-Warnung ist dort normal.

Bei `False`: Kabel, Lämpchen an der Buchse, IP am Gerät und Ethernet am Gerät prüfen, Schritt 4
wiederholen.

## 6. Test CP 545 über Ethernet

```powershell
powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device cp545 -Ip 192.168.1.50
```

Das Skript fragt jede Gruppe mit `j`/`n` ab. Alle mit `j` beantworten.

| Gruppe | Was passiert | Am Gerät beobachten und notieren |
| --- | --- | --- |
| A Lesen | Seriennummer, Uhrzeit, Laufnummer, Betriebsart | nichts |
| B Drucken | `#PL SWV TEST 1234` | Druckt der CP die Zeile? |
| C Lauf | Lauf schliessen, neuen Lauf öffnen | Druckt der CP «CLOSE/OPEN RUN»? Welche Laufnummer ist jetzt offen? |
| D Auslesen | alle Resultate (`#WC 012`), dann Download des Laufs (nur wenn ein Lauf offen ist) | Druckt der CP dabei etwas? |
| E Startliste | Startliste 101, 102, 103 ins Gerät | Gelb erscheint die Aufforderung: innerhalb 30 s **3 Start-Impulse** auslösen (Taste 1 oder Buchse 1). Zeigt das Display die Nummern 101, 102, 103? |
| E2 | Startliste wieder löschen | mit `j` bestätigen |
| G Lauf öffnen | Lauf schliessen, nur Startliste löschen und abschliessen (`#SLR`, `#SLC`), sonst `#WC 002` mit Laufnummer | Ist danach ein Lauf offen, welche Nummer? |
| H App-Befehle | nächste Startnummer 150 vorladen und zurücklesen, Zeit nachfragen (`#RT`) | gelbe Aufforderung: 1 Start- und 1 Ziel-Impuls. Startet Nr 150? |
| I Präzision | Präzision lesen, nacheinander 1, 2 und 3 schreiben, zurücklesen, danach alter Wert | nach jeder gelben Aufforderung 1 Impuls auslösen. Ändert sich die Anzahl Stellen am Display und auf dem Papier? |
| M Zeitmessarten | siehe «Komplett-Test mit neuer Firmware» | Anzeige je Zeitmessart |
| N Nummern zuordnen | siehe «Komplett-Test mit neuer Firmware» | Nummer am Display |
| O Ziel zurücknehmen | Nr 40 ins Ziel, dann `#WP 026 04 0040` und nochmals Ziel, danach Tastatur «41 E4», «E4 allein» | Bekommt der zweite Zielimpuls Nr 40? Papier und Display |
| F Format | 10 s zuhören | 1 Start- und 1 Ziel-Impuls auslösen |

Einzelne Gruppen: `-Nur G` oder `-Nur A,G` anhängen.

Am Ende steht die Zusammenfassung, z.B. `#WC 002  AK C`. Die Logdatei heisst
`fernbefehle_cp545_<Datum>.txt` und liegt im Ordner aus Schritt 1.

### Andere Zeitmessart am CP (z.B. PTB Sequentiel 1-4)

Am CP die Zeitmessart umstellen und den Test mit `-Nur A,D,H,F` wiederholen. Dabei notieren, was am
Display und auf dem Papier erscheint. Danach wieder auf NET TIME und einen Lauf öffnen.

### Präzision

`-Nur I` am CP 545 und am TM550. Prüft, ob die App die Präzision am Gerät einstellen kann.

## 7. Test TM550 über Ethernet

```powershell
powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device tm550 -Ip 192.168.1.51
```

Gleicher Ablauf wie in Schritt 6, mit diesen Unterschieden:
- Antworten brauchen bis 3 s, das Skript wartet entsprechend.
- Gruppe B: der TM550 hat keinen Drucker, `AK F` oder `AK R` ist zu erwarten.
- Gruppe C: am Display prüfen, ob «OPEN» erscheint und welcher Lauf offen ist. Das ist der wichtigste
  Punkt: geht das, kann die App den Lauf selbst öffnen.
- Gruppe E: Start-Impulse mit Taste E1 oder Buchse 1. Mit NO IDENTIFICATION kamen keine Nummern mit.
  Zweiter Versuch: am TM550 Identifikation auf AT START, dann `-Nur E`; dritter Versuch mit MANUAL.
  Danach wieder auf NO IDENTIFICATION stellen.
- Nach dem Test am TM550 wieder einen Lauf öffnen, falls Gruppe C ihn geschlossen hat.

## 8. Optional: über USB

COM-Port suchen (Gerät per USB angeschlossen):

```powershell
[System.IO.Ports.SerialPort]::GetPortNames()
```

Der TM550 war bisher COM14. Aufruf mit `-Com` statt `-Ip`:

```powershell
powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device tm550 -Com COM14
powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device cp545 -Com COM5
```

Ablauf wie oben. Bei «Zugriff verweigert» hat noch ein anderes Programm den Port offen (App, alter
PowerShell-Test): schliessen und nochmals.

## 9. Aufräumen

- CP 545 und TM550: gewünschten Lauf wieder öffnen, Startliste im Gerät ist gelöscht (Gruppe E2).
- PC-Adresse zurück auf automatisch, PowerShell **als Administrator** (`Ethernet` ersetzen):

```powershell
Remove-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.1.55 -Confirm:$false
Set-NetIPInterface -InterfaceAlias "Ethernet" -Dhcp Enabled
```

Die App stellt die Karte beim nächsten Verbinden selbst wieder um.

## 10. Ergebnis zurückgeben

Die Dateien `fernbefehle_*.txt` aus dem Ordner `Dokumente\SWV Geraetetest` hochladen, dazu die Notizen
aus den Tabellen (was der CP gedruckt hat, welcher Lauf offen war, was das Display bei der Startliste
gezeigt hat).

## Komplett-Test mit neuer Firmware (CP 545 VB16, TM550 1.48)

Skript neu holen (Schritt 1), sonst fehlen die Gruppen M und N. Das Skript fragt am Anfang nach der
Firmware am Gerät, diese eintippen.

Neu im Skript:
- Gruppe A liest zusätzlich Präzision (`#RP 001`) und vorgeladene Nummer (`#RP 026 01`).
- Gruppe I schreibt die Präzision 0, 1, 2, 3 und 5 (0 = 1/10 beim CP in NET TIME?).
- Gruppe M: jede Zeitmessart einzeln. Das Skript fordert zum Umstellen auf, öffnet bei Bedarf den
  Lauf mit `#WC 002`, lädt Nr 150 vor, wartet 30 s auf Impulse und fragt die erste Zeit mit `#RT` nach.
  TM550: BASIC, TIMING, SPEED, LAP. CP 545: NET TIME, PTB SEQUENTIEL 1-4, START-FINISH.
- Gruppe N: Nummern ausserhalb der App zuordnen, je Durchgang 60 s Zeit. Die Zusammenfassung zeigt
  pro Zeile Art, Nummer und Kanal (z.B. `TN nr 8 k1`, `T- nr 9 k4`).

Reihenfolge pro Gerät, jeweils über Ethernet:

1. CP 545: Ethernet einschalten, NET TIME, Lauf offen. Dann
   `powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device cp545 -Ip 192.168.1.50`
   und alle Gruppen mit `j`.
2. TM550: TIMING, NO IDENTIFICATION bzw. MANUAL IDENTIFICATION, Lauf offen, Smartphone-App verbunden.
   Dann `powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device tm550 -Ip 192.168.1.51`
   und alle Gruppen mit `j`. In Gruppe N vor jedem Durchgang die Identifikation am TM550 umstellen,
   wie in der gelben Zeile angegeben.
3. Beide Geräte zusätzlich über USB (Schritt 8), mindestens `-Nur A,C,H,M`.
4. Optional TM550 mit Protocol DOCK statt dem bisherigen Protokoll: `-Nur A,F`, damit sichtbar wird,
   ob sich das Zeilenformat ändert. Danach zurückstellen.

Am Gerät notieren:

| Punkt | CP 545 | TM550 |
| --- | --- | --- |
| Gruppe B: wird gedruckt? | Papier | mit Printer BLE verbunden? |
| Gruppe C: Lauf geöffnet in NET TIME? | | |
| Gruppe M: Anzeige je Zeitmessart | Display, Papier | Balken B1 bis B4, Anzahl Zeilen |
| Gruppe M: Anzeigetafel über RS232 | | läuft in BASIC, TIMING, SPEED, LAP? |
| Gruppe N: Nummer am Display und auf der Anzeigetafel | | nach Synchronisieren in der Smartphone-App |

## Ergebnisse 23.11.2026 (CP 545 VB16, TM550 1.48)

| Befehl | CP 545 (VB16) | TM550 (1.48) |
| --- | --- | --- |
| `#SN` | `SN 04755 CP545 VB16` | `SN 00059 TM550 1.48` |
| `#PL Text` | druckt die Zeile | AK F (auch mit Printer BLE) |
| `#WC 002` Lauf öffnen | nur in PTB SEQUENTIEL 1-4, sonst AK F | in allen Zeitmessarten; AK F, wenn schon ein Lauf offen ist |
| Startnummer vorladen `#WP 026` | NET TIME mit Lauf, danach zählt der CP selbst weiter (150, 151). Ohne Lauf AK F, PTB SEQ zurückgelesen 0000 | TIMING: zurückgelesen 0150, Start kommt als `TN 0150`, danach wieder leer. BASIC AK F, SPEED und LAP angenommen ohne Wirkung |
| `#RP 026` ohne Nummer | `&P 026 01 0000` | `&P 026 00    0` |
| `#RT` | in allen Zeitmessarten | BASIC und TIMING: Antwort als `TN`-Zeile; SPEED und LAP nur AK C |
| `#RP 120` | AK R | keine Antwort |
| Präzision `#WP 001 n` | zurückgelesen n+1. Zeitzeilen n+1 Stellen, Resultat (RR, Papier) n Stellen: 1 = Resultat 1/10 (Zeiten 1/100), 0 = ganze Sekunden (Zeiten 1/10). 5 überschreibt die Kanalspalte. (Test 24.11.: mit 0 kam RR 1:02 bei Zeiten 04.5/06.8) | ohne Versatz: 0 = 1 s, 1 = 1/10 … 5 = 1/100000 |
| Tagesfeld | 9823, stimmt | 9823, stimmt (1.18 lag daneben) |
| Doppelkontakt | | als zweite `TN` ohne Nummer 0,10 bis 0,13 s später (1.18: als `TC`). Kam im Test vom Kabel mit Bananensteckern an E4, nicht von der Firmware; mit Taster kein regulärer Fall |
| `IR`-Zeile | | im Ziel mit Nummer und Laufzeit |
| LAP | | meldet sich als `OP nn CIRCUIT` |
| Statuszeilen | | `&P 001/002/008/023/025/033/038`, `DS/DE` von selbst |
| Tastatur / Smartphone-App | Umnummerieren: `T-` alte Nr, `T*` neue Nr (gleiche Zählnummer). Falschstart (E1): `TC`. DNF/DSQ (R 0): keine Zeile | AT START und AUTOMATIC: Nummer auf Start und Ziel. Korrektur in der Smartphone-App: `T*` neue Nr, gelöschte Zeit `TC`. MANUAL mit Smartphone-App: nur `CL/OP 05` im Wechsel, keine Zeiten (ungeklärt) |

Offen für den nächsten Test:
- Gruppe O: Zielzeit zurücknehmen. Nimmt der CP `#WP 026 04` für ein Boot an, das für ihn schon im Ziel ist? Was
  machen «Nr E4» und «E4 allein» an der Tastatur?
- TM550 MANUAL IDENTIFICATION ohne verbundene Smartphone-App, Gruppe N.
- CP 545 DNF und DSQ (`Nr R 0`, `Nr R 0 *`) mit offenem Lauf in NET TIME, Gruppe N.

## Ergebnisse 22.11.2026

| Befehl | CP 545 (VB08) | TM550 (1.18) |
| --- | --- | --- |
| `#SN`, `#ID`, `#RP 003` | AK C | AK C |
| `#!T` | AK C | AK R |
| `#PL Text` | druckt die Zeile | «PL TO BE IMPLEMENTED», AK R |
| `#WC 001` Lauf schliessen | schliesst (CL nn) | schliesst (CL nn) |
| `#WC 002` Lauf öffnen | AK F, öffnet nicht | öffnet (OP nn TIMING), leerer Lauf behält die Nummer |
| `#WC 012` | AK R | DS 01 … AN/AC … DE 01, ohne AK |
| `#SLR/#SLA/#SLC` | AK C, `#SLC` öffnete einen neuen Lauf, Nummern nicht übernommen | AK C, ohne Wirkung bei NO IDENTIFICATION |
| Lauf öffnen über Startliste | 2. Versuch mit leerer Liste: kein Lauf | |
| Startliste mit AT START | | ohne Wirkung, Impulse ohne Nummer |
| Tagesfeld der Zeitzeilen | Tage ab 1.1.2000, stimmt | stimmt nicht mit dem Datum am Display überein (9793 statt 9822) |
| Startnummer vorladen `#WP 026` | nur NET TIME mit Lauf. Ohne Lauf AK F, PTB SEQUENTIEL 1-4 mit Lauf AK C aber Zurücklesen 0000 | AK F |
| Zeile ohne NET TIME / Lauf | ohne Startnummer, keine RR | ohne Startnummer |
| `#RT` Zeit nachfragen | in allen Zeitmessarten, auch ohne Lauf | nicht brauchbar |
| `#DL nn` | einmal ohne Antwort, danach keine Befehle mehr bis Neustart (Ursache unklar), nach Neustart normal | DS … DE |

## Wenn etwas nicht geht

| Meldung | Ursache und Abhilfe |
| --- | --- |
| «Die Ausführung von Skripts ist auf diesem System deaktiviert» | Aufruf genau wie oben mit `powershell -ExecutionPolicy Bypass -File …` |
| «FEHLER: keine Verbindung zu …» | Schritt 5. Läuft die App noch? (Schritt 2) CP neu gestartet? Dann Ethernet am CP wieder einschalten |
| CP sendet Zeiten, beantwortet aber keine Befehle | CP aus und ein, danach Ethernet am CP wieder einschalten |
| Alle Befehle «keine Antwort» beim TM550 | `-Device tm550` vergessen (dann fehlt die Prüfsumme), oder Port nicht 7000 |
| Alle Befehle «keine Antwort» beim CP über USB | am CP USB-Ausgabe auf 9600 Baud prüfen, sonst `-Baud 19200` usw. |
| «Zugriff verweigert» auf COMx | Port von anderem Programm belegt, Schritt 8 |
| Skript hängt bei Gruppe D | Download dauert bei vielen Zeiten; nach höchstens 30 s geht es weiter |

## Älteres Skript `tm550_test.ps1`

Prüft Netz, Ports und Grundbefehle (erster TM550-Test). Für die aktuelle Einstellung:

```powershell
powershell -ExecutionPolicy Bypass -File .\tm550_test.ps1 -Ip 192.168.1.51 -Port 7000 -Com COM14
```
