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
| F Format | 10 s zuhören | 1 Start- und 1 Ziel-Impuls auslösen |

Einzelne Gruppen: `-Nur G` oder `-Nur A,G` anhängen.

Am Ende steht die Zusammenfassung, z.B. `#WC 002  AK C`. Die Logdatei heisst
`fernbefehle_cp545_<Datum>.txt` und liegt im Ordner aus Schritt 1.

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
