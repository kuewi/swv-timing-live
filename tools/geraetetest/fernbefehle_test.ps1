# Fernbefehle-Test fuer SWV Live-Ranking (CP 545 und TM550)
# Prueft, welche THCOM08-Befehle das Geraet annimmt: Lauf oeffnen/schliessen (#WC 002/001),
# Resultate auslesen (#WC 012), Startliste im Geraet (#SLR/#SLA/#SLC), Druckzeile (#PL).
# Jede Gruppe wird vorher abgefragt. NUR AUSSERHALB EINES RENNENS: #WC 001 schliesst den Lauf,
# #SLR loescht die Startliste im Geraet.
# Alles kommt in fernbefehle_<Geraet>_<Datum>.txt neben diesem Skript.
#
# Start (PowerShell im Ordner dieses Skripts):
#   CP 545 Ethernet:  powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device cp545 -Ip 192.168.1.50
#   CP 545 USB:       powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device cp545 -Com COM5
#   TM550 Ethernet:   powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device tm550 -Ip 192.168.1.51
#   TM550 USB:        powershell -ExecutionPolicy Bypass -File .\fernbefehle_test.ps1 -Device tm550 -Com COM14
#   Nur einzelne Gruppen: ... -Nur A,G     (Gruppen A B C D E G H I F M N O P Q R S T U V W X Y Z)
#   M: Zeitmessarten nacheinander (TM550: BASIC, TIMING, SPEED, LAP; CP: z.B. NET TIME, PTB SEQ)
#   N: Nummern zuordnen (TM550-Smartphone-App, Identifikation AT START / MANUAL / AUTOMATIC, CP-Tastatur)
#   P: Eingaenge gesperrt/offen: #RP 006 und 023, Sperren an der Tastatur (CP rote Tasten, TM550 SHIFT+Ex),
#      Ereignismeldungen #EE 1, Sperren per #WP 006. Am Ende werden die Eingaenge wieder geoeffnet.
#   Q: Sperren ueber die Verbindung mit #WP 023 (Status Eingaenge) und #WP 006, Sperrtaste bis zum Balken.
#   R: Sperrzeit #WP 004 (Doppelkontakt), CP: rote Sperrtaste gegen Buchse, TM550: #WP 006 04 2.
#   S: Uhr synchronisieren am Geraet (00:00 und Impuls): welche Zeilen kommen, Uhr danach.
#   T: Ethernet-Menue CP 545 (Std/User Connexion): nur Fragen.
#   U: Sperrzustaende einzeln: je Zustand (per Befehl und per Taste) zuerst NUR Buchse, dann NUR Taste.
#   V: Sperrzeit 004 auf 2 s: zwei Impulse innerhalb 2 s, kommt nur einer? Je Buchse und Taste.
#   W: Zeit von aussen eintragen (THCOM08 9.1): #WC 014 Zeit einfuegen, #WC 008 Handimpuls ausloesen,
#      #!T Uhr abfragen, #WC 011 Ethernet einschalten (nur ueber USB sinnvoll).
#   X: Uhr per Befehl synchronisieren (#WC 007). Verstellt die Uhr des Geraets.
#   Y: CP 545 ueber RS232 (USB-RS232-Adapter): PC als Master fuer die Synchronisation (!T jede volle Sekunde),
#      danach Versatz CP-Uhr zu PC-Uhr aus einem Impuls; CP als Master: sendet er !T?  Nur mit -Com.
#   Z: wie Y, aber Antwort auf jede Anfrage #!T des CP (abwechselnd mit/ohne Pruefsumme) und zur vollen Sekunde
#      ein Puls auf DTR und RTS des Adapters (falls der CP einen Sekunden-Top ueber eine Leitung erwartet).
param(
    [ValidateSet("cp545", "tm550")][string]$Device = "cp545",
    [string]$Ip = "",
    [int]$Port = 0,
    [string]$Com = "",
    [int]$Baud = 9600,
    [switch]$Alles,         # alle Gruppen ohne Rueckfrage
    [string[]]$Nur = @()    # nur diese Gruppen, z.B. -Nur A,G
)

$Nur = @($Nur | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if (-not $Ip -and -not $Com) { $Ip = $(if ($Device -eq "tm550") { "192.168.1.51" } else { "192.168.1.50" }) }
if ($Port -eq 0) { $Port = $(if ($Device -eq "tm550") { 7000 } else { 13500 }) }
$UseCs = ($Device -eq "tm550")          # TM550 antwortet nur auf Befehle mit Pruefsumme
$Wait = $(if ($Device -eq "tm550") { 3000 } else { 1500 })   # ms ohne neue Daten bis "fertig"

$log = Join-Path $PSScriptRoot ("fernbefehle_" + $Device + "_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".txt")
function Log($text) {
    $line = (Get-Date -Format "HH:mm:ss.fff") + "  " + $text
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}
function Cs16($text) {
    $sum = 0
    foreach ($b in [Text.Encoding]::ASCII.GetBytes($text)) { if ($b -ne 0x23) { $sum += $b } }
    return ("{0:X4}" -f ($sum -band 0xFFFF))
}
function Visible($s) {
    return ($s -replace "`t", "<TAB>" -replace "`r", "" -replace "[^\x20-\x7E<>]", "?")
}

# ---------------- Verbindung ----------------
$script:tcp = $null; $script:stream = $null; $script:sp = $null; $script:rest = ""
function Open-Device {
    if ($Com) {
        $script:sp = New-Object System.IO.Ports.SerialPort $Com, $Baud, None, 8, One
        $script:sp.DtrEnable = $true; $script:sp.RtsEnable = $true   # TM550 sendet nur mit DTR/RTS
        $script:sp.Encoding = [Text.Encoding]::GetEncoding(28591)
        $script:sp.Open()
        Log "Verbunden: $Com, $Baud Baud, DTR/RTS an"
    } else {
        $script:tcp = New-Object System.Net.Sockets.TcpClient
        if (-not ($script:tcp.ConnectAsync($Ip, $Port).Wait(4000) -and $script:tcp.Connected)) {
            Log "FEHLER: keine Verbindung zu ${Ip}:$Port"; exit 1
        }
        $script:stream = $script:tcp.GetStream()
        Log "Verbunden: ${Ip}:$Port"
    }
}
function Read-Raw {
    if ($script:sp) { return $script:sp.ReadExisting() }
    $out = ""
    $buf = New-Object byte[] 8192
    while ($script:stream.DataAvailable) {
        $n = $script:stream.Read($buf, 0, $buf.Length)
        $out += [Text.Encoding]::GetEncoding(28591).GetString($buf, 0, $n)
    }
    return $out
}
function Write-Raw($text) {
    $b = [Text.Encoding]::ASCII.GetBytes($text)
    if ($script:sp) { $script:sp.Write($b, 0, $b.Length) } else { $script:stream.Write($b, 0, $b.Length) }
}
# Liest Zeilen, bis $WaitMs lang nichts mehr kommt oder $MaxMs erreicht ist; jede Zeile ins Log.
function Collect([int]$WaitMs = $Wait, [int]$MaxMs = 15000, [string]$Until = "") {
    $lines = New-Object System.Collections.ArrayList
    $start = Get-Date; $last = Get-Date
    while ($true) {
        $chunk = Read-Raw
        if ($chunk) {
            $last = Get-Date
            $script:rest += $chunk
            while ($script:rest -match "^(.*?)\n") {
                $line = $Matches[1].TrimEnd("`r")
                $script:rest = $script:rest.Substring($Matches[0].Length)
                if ($line.Trim()) {
                    Log ("   <- " + (Visible $line))
                    [void]$lines.Add($line)
                    if ($Until -and $line -match $Until) { return $lines }
                }
            }
        }
        $now = Get-Date
        if (($now - $last).TotalMilliseconds -ge $WaitMs) { break }
        if (($now - $start).TotalMilliseconds -ge $MaxMs) { break }
        Start-Sleep -Milliseconds 50
    }
    return $lines
}
function Send-Cmd([string]$cmd, [int]$WaitMs = $Wait, [int]$MaxMs = 15000, [string]$Until = "") {
    $frame = $(if ($UseCs) { $cmd + "`t" + (Cs16 $cmd) + "`r`n" } else { $cmd + "`r`n" })
    Log ("-> " + (Visible $frame.TrimEnd()))
    Write-Raw $frame
    $lines = Collect $WaitMs $MaxMs $Until
    $ak = ($lines | Where-Object { $_ -match "^AK\s*([CFR])" } | Select-Object -First 1)
    $res = $(if ($ak) { ($ak -replace "\t.*", "").Trim() } elseif ($lines.Count) { "Daten ohne AK" } else { "keine Antwort" })
    Log ("   = $cmd : $res")
    $script:summary += ("{0,-22} {1}" -f $cmd, $res)
    return $lines
}
# Fasst Zeitzeilen zusammen: Art (TN, T-, AN ...), Nummer, Kanal. Liefert Text fuer die Zusammenfassung.
function Describe($lines) {
    $parts = @()
    foreach ($l in $lines) {
        if ($l -match "^([TAR][N\-\*C+=R]) (.{4}) +(\S+) +(M?\d+|M?\S+) ") {
            $nr = $Matches[2].Trim(); if (-not $nr) { $nr = "-" }
            $parts += ($Matches[1] + " nr " + $nr + " k" + $Matches[4])
        } elseif ($l -match "^(\S{2})") { $parts += $Matches[1] }
    }
    if (-not $parts.Count) { return "keine Zeilen" }
    return ($parts -join "; ")
}
# Bittet um eine Handlung am Geraet, hoert $Sec Sekunden zu und traegt das Ergebnis ein.
function Observe([string]$label, [string]$todo, [int]$Sec = 30) {
    Write-Host ""
    Write-Host ("$label`: $todo") -ForegroundColor Yellow
    [void](Read-Host "Enter druecken, dann hat man $Sec s Zeit")
    $pre = Collect 300 1000   # Zeilen von vorher (waehrend der Rueckfrage) nicht mitzaehlen
    if ($pre.Count) { Log ("   (" + $pre.Count + " Zeile(n) vor dem Fenster, nicht gezaehlt)") }
    Log "Beobachte $Sec s: $label ($todo)"
    $got = Collect ($Sec * 1000) ($Sec * 1000)
    $script:summary += ("{0,-22} {1}" -f $label, (Describe $got))
    return $got
}

function Ask($title) {
    $id = ($title.Trim() -split "\s+")[0]
    if ($Nur.Count -and -not ($Nur | Where-Object { $_.ToUpper() -eq $id.ToUpper() -or $_.ToUpper() -eq $id.Substring(0, 1).ToUpper() })) {
        return $false
    }
    if ($Alles) { Log "=== $title ==="; return $true }
    Write-Host ""
    $a = Read-Host "$title  ausfuehren? (j/n)"
    $ok = $a -match "^[jJyY]"
    Log ("=== $title : " + $(if ($ok) { "ja" } else { "uebersprungen" }) + " ===")
    return $ok
}

$script:summary = @()
Log "=== Fernbefehle-Test $Device, Pruefsumme: $UseCs ==="
Open-Device
if (-not $UseCs) {
    # Ueber USB erwartet der CP 545 Befehle mit Pruefsumme, wenn er selbst mit Pruefsumme sendet (wie die App:
    # keine Antwort auf #SN ohne Pruefsumme -> mit Pruefsumme weiter)
    $sn = Send-Cmd "#SN"
    if (-not ($sn | Where-Object { $_ -match "^(SN|AK)" })) {
        $UseCs = $true
        Log "Keine Antwort ohne Pruefsumme: Befehle ab jetzt mit Pruefsumme"
        [void](Send-Cmd "#SN")
    }
}
$fw = Read-Host "Firmware am Geraet (z.B. VB16 bzw. 1.48)"
Log "Firmware laut Stefan: $fw"
Start-Sleep -Milliseconds 500
$pre = Collect 800 2000
if ($pre.Count) { Log ("Beim Verbinden " + $pre.Count + " Zeile(n) erhalten") }

# A: nur lesen
if (Ask "A  Lesen: #SN, #ID, #!T, #RP 003 (Lauf), #RP 120 (Betriebsart)") {
    foreach ($c in @("#SN", "#ID", "#!T", "#RP 003", "#RP 120", "#RP 001", "#RP 026 01")) { [void](Send-Cmd $c) }
}

# B: Druckzeile
if (Ask "B  Druckzeile: #PL SWV TEST (CP druckt eine Zeile, TM550 vermutlich AK R/F)") {
    [void](Send-Cmd "#PL SWV TEST 1234")
}

# C: Lauf schliessen und oeffnen
if (Ask "C  Lauf: #WC 001 (schliessen), #RP 003, #WC 002 (neuen Lauf oeffnen), #RP 003") {
    [void](Send-Cmd "#WC 001")
    [void](Send-Cmd "#RP 003")
    [void](Send-Cmd "#WC 002")
    [void](Send-Cmd "#RP 003")
    Log "Bitte am Geraet pruefen und notieren: ist ein neuer Lauf offen, welche Nummer, welche Betriebsart?"
}

# D: Resultate auslesen
if (Ask "D  Resultate auslesen: #WC 012 (erwartet DS ... RR ... DE), danach #DL mit aktuellem Lauf") {
    [void](Send-Cmd "#WC 012" 4000 30000 "^DE\s")
    $run = ""
    $rp = Send-Cmd "#RP 003"
    foreach ($l in $rp) { if ($l -match "^&P\s*003\s+(\d+)") { $run = $Matches[1] } }
    if ($run -and [int]$run -gt 0) { [void](Send-Cmd ("#DL " + $run.PadLeft(2, "0")) 4000 30000 "^DE\s") }
    else { Log "Kein Lauf offen: #DL wird nicht gesendet" }
}

# E: Startliste im Geraet
if (Ask "E  Startliste: #SLR, #SLA 0101, #SLA 0102, #SLA 0103, #SLC, dann 3 Start-Impulse ausloesen") {
    foreach ($c in @("#SLR", "#SLA 0101", "#SLA 0102", "#SLA 0103", "#SLC")) { [void](Send-Cmd $c) }
    Write-Host ""
    Write-Host "Jetzt innerhalb 30 s am Geraet 3 Start-Impulse ausloesen (Taste oder Buchse Start)." -ForegroundColor Yellow
    Log "Warte 30 s auf Start-Impulse (erwartet Nummern 101, 102, 103)"
    $imp = Collect 30000 30000
    $nrs = @()
    foreach ($l in $imp) {
        if ($l -match "^T[N+=] " -and $l.Length -ge 7) {
            $nr = $l.Substring(3, 4).Trim()      # Spalten: TN NNNN SSSS CC HH:MM:SS.FFFFF DDDDD
            $nrs += $(if ($nr) { $nr } else { "(leer)" })
        }
    }
    Log ("Startnummern in den Impulsen: " + $(if ($nrs.Count) { $nrs -join ", " } else { "keine Impulse" }))
    $script:summary += ("{0,-22} {1}" -f "Startliste wirkt", $(if ($nrs -match "^0*101$") { "JA (101 kam)" } else { "nein: " + ($nrs -join ",") }))
    if (Ask "E2 Startliste im Geraet wieder loeschen (#SLR)") { [void](Send-Cmd "#SLR") }
}

# G: Lauf ueber Startliste oeffnen (CP 545 oeffnete beim #SLC einen Lauf), sonst #WC 002 mit Laufnummer
if (Ask "G  Lauf oeffnen: Lauf schliessen, nur #SLR + #SLC, Laufnummer pruefen, sonst #WC 002 mit Nummer") {
    $open = ""; $next = ""
    foreach ($l in (Send-Cmd "#RP 003")) { if ($l -match "^&P\s*003\s+(\d+)\s+(\d+)") { $open = $Matches[1]; $next = $Matches[2] } }
    if ($open -and [int]$open -gt 0) {
        Log "Lauf $open ist offen, wird mit #WC 001 geschlossen"
        [void](Send-Cmd "#WC 001")
        foreach ($l in (Send-Cmd "#RP 003")) { if ($l -match "^&P\s*003\s+(\d+)\s+(\d+)") { $open = $Matches[1]; $next = $Matches[2] } }
    }
    [void](Send-Cmd "#SLR")
    [void](Send-Cmd "#SLC")
    foreach ($l in (Send-Cmd "#RP 003")) { if ($l -match "^&P\s*003\s+(\d+)\s+(\d+)") { $open = $Matches[1]; $next = $Matches[2] } }
    $script:summary += ("{0,-22} {1}" -f "Lauf nach #SLC", $(if ($open -and [int]$open -gt 0) { "offen: $open" } else { "kein Lauf" }))
    if (-not ($open -and [int]$open -gt 0) -and $next) {
        [void](Send-Cmd ("#WC 002 " + $next.PadLeft(2, "0")))
        foreach ($l in (Send-Cmd "#RP 003")) { if ($l -match "^&P\s*003\s+(\d+)") { $open = $Matches[1] } }
        $script:summary += ("{0,-22} {1}" -f "Lauf nach #WC 002 nn", $(if ($open -and [int]$open -gt 0) { "offen: $open" } else { "kein Lauf" }))
    }
    Log "Bitte am Geraet notieren: welcher Lauf ist offen, wurde etwas gedruckt?"
}

# H: was die App im Betrieb braucht: naechste Startnummer vorladen (#WP 026), Zeit nachfragen (#RT)
if (Ask "H  App-Befehle: #RP 026 01, #WP 026 01 0150, #RP 026 01, dann 2 Impulse, #RT der ersten Zeit") {
    [void](Send-Cmd "#RP 026 01")
    [void](Send-Cmd "#WP 026 01 0150")
    $back = Send-Cmd "#RP 026 01"
    $script:summary += ("{0,-22} {1}" -f "Vorladen 150", $(if ($back -match "0150") { "zurueckgelesen" } else { "nicht bestaetigt" }))
    Write-Host ""
    Write-Host "Jetzt innerhalb 20 s 1 Start- und 1 Ziel-Impuls ausloesen." -ForegroundColor Yellow
    $imp = Collect 20000 20000
    $first = $imp | Where-Object { $_ -match "^T[N+=] " } | Select-Object -First 1
    if ($first) {
        $nr = $first.Substring(3, 4).Trim()
        $script:summary += ("{0,-22} {1}" -f "Nummer beim Start", $(if ($nr) { $nr } else { "(leer)" }))
        if ($first -match "^T. .{4} +(\d+) +M?(\d+)") {
            [void](Send-Cmd ("#RT " + $Matches[1].PadLeft(4, "0") + " " + $Matches[2].PadLeft(2, "0")))
        }
    } else { Log "Keine Impulse erhalten" }
}

# I: Praezision lesen und schreiben (#RP/#WP 001), danach urspruenglichen Wert zurueck
if (Ask "I  Praezision: #RP 001, #WP 001 mit 0, 1, 2, 3, 5 (je 1 Impuls ausloesen), dann zurueck auf den alten Wert") {
    $orig = ""
    foreach ($l in (Send-Cmd "#RP 001")) { if ($l -match "^&P\s*001\s+(\S+)") { $orig = $Matches[1] } }
    $script:summary += ("{0,-22} {1}" -f "Praezision vorher", $(if ($orig) { $orig } else { "nicht lesbar" }))
    foreach ($v in @("0", "1", "2", "3", "5")) {
        [void](Send-Cmd "#WP 001 $v")
        $now = ""
        foreach ($l in (Send-Cmd "#RP 001")) { if ($l -match "^&P\s*001\s+(\S+)") { $now = $Matches[1] } }
        Write-Host ""
        Write-Host "Praezision $v gesendet: jetzt innerhalb 10 s 1 Impuls ausloesen." -ForegroundColor Yellow
        $imp = Collect 10000 10000
        $line = $imp | Where-Object { $_ -match "^T[N+=] " } | Select-Object -First 1
        $script:summary += ("{0,-22} {1}" -f "Praezision $v", ("gelesen " + $(if ($now) { $now } else { "-" }) + ", Zeile: " + $(if ($line) { (Visible $line) } else { "kein Impuls" })))
    }
    # CP 545 liest n+1 zurueck (geschrieben n: Resultat n, Zeiten n+1 Stellen), TM550 n
    if ($orig) {
        $back = $(if ($Device -eq "cp545") { [Math]::Max(0, [int]$orig - 1) } else { $orig })
        [void](Send-Cmd "#WP 001 $back"); [void](Send-Cmd "#RP 001")
    }
}

# M: Zeitmessarten. Am Geraet umstellen, Lauf oeffnen, Impulse, Zeilenformat festhalten.
if (Ask "M  Zeitmessarten: je Art am Geraet umstellen, Lauf oeffnen lassen, Start- und Ziel-Impuls") {
    $modes = $(if ($Device -eq "tm550") { @("BASIC", "TIMING", "SPEED", "LAP") } else { @("NET TIME", "PTB SEQUENTIEL 1-4", "START-FINISH") })
    foreach ($m in $modes) {
        Write-Host ""
        $a = Read-Host "Zeitmessart $m am Geraet einstellen (Lauf vorher schliessen), dann Enter. 'n' = ueberspringen"
        if ($a -match "^[nN]") { continue }
        Log "--- Zeitmessart $m ---"
        $open = ""; $next = ""
        [void](Send-Cmd "#RP 120")
        foreach ($l in (Send-Cmd "#RP 003")) { if ($l -match "^&P\s*003\s+(\d+)\s+(\d+)") { $open = $Matches[1]; $next = $Matches[2] } }
        if (-not ($open -and [int]$open -gt 0)) {
            [void](Send-Cmd "#WC 002")
            foreach ($l in (Send-Cmd "#RP 003")) { if ($l -match "^&P\s*003\s+(\d+)") { $open = $Matches[1] } }
        }
        $script:summary += ("{0,-22} {1}" -f "Lauf $m", $(if ($open -and [int]$open -gt 0) { "offen: $open" } else { "kein Lauf" }))
        [void](Send-Cmd "#WP 026 01 0150")
        $back = Send-Cmd "#RP 026 01"
        $script:summary += ("{0,-22} {1}" -f "Vorladen $m", $(if ($back -match "0150") { "150 zurueckgelesen" } else { "nein" }))
        $imp = Observe "Impulse $m" "1 Start-, 1 Zwischen- (falls vorhanden) und 1 Ziel-Impuls ausloesen" 30
        $first = $imp | Where-Object { $_ -match "^T. .{4} +(\d+) +M?(\d+)" } | Select-Object -First 1
        if ($first -and $first -match "^T. .{4} +(\d+) +M?(\d+)") {
            [void](Send-Cmd ("#RT " + $Matches[1].PadLeft(4, "0") + " " + $Matches[2].PadLeft(2, "0")))
        }
        Log "Am Geraet notieren: Anzeige (Balken B1-B4, Zeilen), was gedruckt wurde"
    }
}

# N: Nummern zuordnen ausserhalb der App (TM550-Smartphone-App bzw. CP-Tastatur). Was kommt an?
if (Ask "N  Nummern zuordnen: Startliste, Smartphone-App bzw. CP-Tastatur, je Identifikation 1 Durchgang") {
    $runs = $(if ($Device -eq "tm550") {
        @("MANUAL OHNE APP: MANUAL IDENTIFICATION, Smartphone-App getrennt, Start- und Ziel-Impuls",
          "MANUAL IDENTIFICATION: Start- und Ziel-Impuls, danach in der Smartphone-App Nr 7 zuordnen und synchronisieren",
          "IDENTIFICATION AT START: in der Smartphone-App Nr 8 eingeben und synchronisieren, dann Start- und Ziel-Impuls",
          "AUTOMATIC IDENTIFICATION: Start- und Ziel-Impuls, danach Nr 9 in der Smartphone-App",
          "Korrektur: in der Smartphone-App Nr 9 auf 19 aendern bzw. Zeit loeschen")
    } else {
        @("NET TIME: 7 E1 (Nr 7 an den Start), Start- und Ziel-Impuls",
          "Ohne Nummer: Start-Impuls, danach 8 R Enter-Taste (Nummer zuordnen)",
          "Umnummerieren: 8 R, neue Nummer 18 Enter-Taste",
          "Falschstart: E1 allein nach einem Start, dann * E1 (rueckgaengig)",
          "DNF: Lauf offen in NET TIME, 2 Starts (Nr 30, 31), dann 30 R 0 (DNF) und 31 R 0 * (DSQ)")
    })
    foreach ($r in $runs) {
        Write-Host ""
        $a = Read-Host "Naechster Durchgang: $r  (Enter = los, 'n' = ueberspringen)"
        if ($a -match "^[nN]") { continue }
        [void](Observe ($r.Split(":")[0]) $r 60)
    }
    if ($Device -eq "tm550") {
        Log "--- Startliste mit Identifikation AT START ---"
        foreach ($c in @("#SLR", "#SLA 0101", "#SLA 0102", "#SLC")) { [void](Send-Cmd $c) }
        [void](Observe "Startliste AT START" "2 Start-Impulse (erwartet 101, 102)" 30)
        [void](Send-Cmd "#SLR")
    }
    [void](Send-Cmd "#WC 012" 4000 30000 "^DE\s")
}

# O: Zielzeit in der App zuruecknehmen: nimmt das Geraet die Nummer fuer das Ziel nochmals an?
if (Ask "O  Ziel zuruecknehmen: Nr 40 starten und ins Ziel, dann #WP 026 04 0040 und nochmals Ziel-Impuls") {
    [void](Send-Cmd "#WP 026 01 0040")
    [void](Observe "O Start und Ziel" "1 Start- und 1 Ziel-Impuls (Nr 40 kommt ins Ziel)" 30)
    [void](Send-Cmd "#WP 026 04 0040")
    $back = Send-Cmd "#RP 026 04"
    $script:summary += ("{0,-22} {1}" -f "Ziel 40 nochmals", $(if ($back -match "0040") { "angenommen" } else { "nicht angenommen" }))
    [void](Observe "O Ziel nochmals" "1 Ziel-Impuls: bekommt er Nr 40? Papier und Display notieren" 30)
    [void](Observe "O Tastatur" "CP: Start-Impuls (Nr 41), Ziel-Impuls, dann 41 E4 eingeben, nochmals Ziel-Impuls; danach E4 allein" 60)
}

# P: Eingaenge gesperrt oder offen. Was meldet das Geraet, wenn man an der Tastatur sperrt?
function Note([string]$label, [string]$frage) {
    $a = Read-Host $frage
    Log ("Notiz $label`: " + $a)
    $script:summary += ("{0,-22} {1}" -f ("Notiz " + $label), $a)
}
function Read-Inputs([string]$label) {
    $st = @()
    foreach ($k in 1..4) {
        $v = "-"
        foreach ($l in (Send-Cmd ("#RP 006 0" + $k))) { if ($l -match "^&P\s*006\s+0*$k\s+(\d)") { $v = $Matches[1] } }
        $st += $v
    }
    $d = "-"
    foreach ($l in (Send-Cmd "#RP 023")) { if ($l -match "^&P\s*023\s+(.+?)(\t|$)") { $d = $Matches[1].Trim() } }
    $script:summary += ("{0,-22} {1}" -f $label, ("006 (0 gesperrt, 1 offen): " + ($st -join " ") + " | 023: " + $d))
    return $st
}
if (Ask "P  Eingaenge: Zustand lesen, an der Tastatur sperren und oeffnen, Meldungen #EE 1, Sperren per #WP 006") {
    $lockKey = $(if ($Device -eq "tm550") { "SHIFT und dann E{0}" } else { "rote Sperrtaste {0} (unter der gruenen Taste {0})" })
    Log "--- P1 Zustand lesen ---"
    $orig = Read-Inputs "P1 alle offen"
    foreach ($k in 1..4) { [void](Send-Cmd ("#RP 004 0" + $k)) }
    Note "P1 Display" "Was zeigt das Display ueber bzw. unter E1 bis E4 (Symbole, Farben, Zeichen)?"

    Log "--- P2 Ereignismeldungen einschalten ---"
    $ee = Send-Cmd "#EE 1"
    if (-not ($ee -match "^AK\s*C")) { [void](Send-Cmd "#WC 013 1") }

    foreach ($k in @(1, 4)) {
        Log "--- P3 Eingang $k an der Tastatur ---"
        $todo = ($lockKey -f $k)
        [void](Observe "P3 E$k sperren" "$todo druecken (einmal)" 20)
        [void](Read-Inputs "P3 E$k nach 1x")
        Note "P3 E$k Display 1x" "Was zeigt das Display jetzt bei E$k?"
        [void](Observe "P3 E$k Impuls" "Impuls auf Eingang $k ausloesen (Taste oder Buchse): kommt eine Zeile?" 20)
        if ($Device -eq "tm550") {
            [void](Observe "P3 E$k 2x" "$todo nochmals druecken (dritter Zustand)" 20)
            [void](Read-Inputs "P3 E$k nach 2x")
            Note "P3 E$k Display 2x" "Was zeigt das Display jetzt bei E$k?"
            [void](Observe "P3 E$k Impuls 2" "Impuls auf Eingang $k ausloesen: kommt eine Zeile?" 20)
        }
        $back = $(if ($Device -eq "tm550") { "so oft, bis E$k wieder offen ist (gruen, Pfeil nach oben)" } else { "nochmals (wieder offen)" })
        [void](Observe "P3 E$k oeffnen" "$todo $back" 30)
        [void](Read-Inputs "P3 E$k wieder offen")
    }
    [void](Observe "P4 Tasten" "Handtasten 1 und 4 je einmal druecken, dann eine Zifferntaste: kommen &S-Zeilen?" 20)

    Log "--- P5 Sperren ueber die Verbindung ---"
    [void](Send-Cmd "#WP 006 04 0")
    [void](Read-Inputs "P5 nach #WP 006 04 0")
    Note "P5 Display" "Ist E4 am Display jetzt gesperrt?"
    [void](Observe "P5 Impuls" "Impuls auf Eingang 4 ausloesen: kommt eine Zeile?" 20)
    [void](Send-Cmd "#WP 006 04 1")
    $end = Read-Inputs "P5 nach #WP 006 04 1"

    # Aufraeumen: Eingaenge, die am Anfang offen waren, wieder oeffnen; Ereignismeldungen aus
    foreach ($k in 1..4) {
        if ($orig[$k - 1] -eq "1" -and $end[$k - 1] -ne "1") { [void](Send-Cmd ("#WP 006 0" + $k + " 1")) }
    }
    [void](Send-Cmd "#EE 0")
    Note "P Ende" "Sind am Display alle benutzten Eingaenge wieder offen (j/n)?"
}

# Q: Sperren ueber die Verbindung. 023 = Status Eingaenge (CP-Handbuch 5.9.4: senden, gesperrt, empfangen;
# TM550 1.48 meldet SHIFT+Ex als &P 023: 0 offen, 1 ?, 2 gesperrt). Danach immer den alten Wert zurueck.
function Read-023 {
    $d = ""
    foreach ($l in (Send-Cmd "#RP 023")) { if ($l -match "^&P\s*023\s+(\d)\s+(\d)\s+(\d)\s+(\d)") { $d = ($Matches[1..4] -join " ") } }
    return $d
}
if (Ask "Q  Sperren ueber die Verbindung: #WP 023 auf Eingang 1, #WP 006 auf Eingang 1 und 4, je Buchse und Handtaste, danach zurueck") {
    $o23 = Read-023
    $q0 = Read-Inputs "Q0 vorher"
    $script:summary += ("{0,-22} {1}" -f "Q0 023 vorher", $o23)
    if ($Device -eq "cp545") {
        [void](Observe "Q1 Sperrtaste" "rote Sperrtaste 1 druecken, bis bei E1 ein schwarzer Balken steht (mehrmals oder laenger halten)" 30)
        [void](Read-Inputs "Q1 nach Sperrtaste")
        Note "Q1 Display" "Steht bei E1 ein Balken? Was hast du gedrueckt (einmal, mehrmals, gehalten)?"
        [void](Observe "Q1 Impuls" "Impuls auf Buchse 1 ausloesen: kommt eine Zeile?" 20)
        [void](Observe "Q1 oeffnen" "rote Sperrtaste 1 wieder druecken, bis E1 wieder die Laufnummer zeigt" 30)
        [void](Read-Inputs "Q1 wieder offen")
    }
    if ($o23) {
        $rest = ($o23 -split " ")[1..3] -join " "
        foreach ($v in @("2", "1")) {
            Log "--- Q2 #WP 023 mit E1 = $v ---"
            [void](Send-Cmd "#WP 023 $v $rest")
            [void](Read-Inputs "Q2 nach 023 E1=$v")
            Note "Q2 Display E1=$v" "Was zeigt das Display bei E1 jetzt?"
            [void](Observe "Q2 Impuls E1=$v" "Impuls auf Eingang 1 ausloesen (Buchse, beim TM550 auch Taste E1): kommt eine Zeile?" 20)
            [void](Send-Cmd "#WP 023 $o23")
            [void](Read-Inputs "Q2 zurueck")
        }
    }
    foreach ($k in @(1, 4)) {
        Log "--- Q3 #WP 006 0$k 0 (sperren), Buchse und gruene Taste, dann 1 (oeffnen) ---"
        [void](Send-Cmd "#WP 006 0$k 0")
        [void](Read-Inputs "Q3 E$k nach 006=0")
        Note "Q3 E$k Display" "Steht bei E$k ein schwarzer Balken (j/n)?"
        [void](Observe "Q3 E$k Buchse" "Impuls NUR ueber die Buchse $k ausloesen (Kabel/Taster), nicht mit der Taste am Geraet" 20)
        $hand = $(if ($Device -eq "tm550") { "Taste E$k am Geraet" } else { "gruene Taste $k am Geraet" })
        [void](Observe "Q3 E$k Handtaste" "Jetzt $hand druecken" 20)
        [void](Send-Cmd "#WP 006 0$k 1")
        [void](Read-Inputs "Q3 E$k nach 006=1")
        Note "Q3 E$k offen" "Ist E$k wieder offen (j/n)?"
    }
    if ($o23) { [void](Send-Cmd "#WP 023 $o23") }
    if ($q0[0] -match "^\d$") { [void](Send-Cmd ("#WP 006 01 " + $q0[0])) }
    [void](Read-Inputs "Q Ende")
    Note "Q Ende" "Ist E1 am Display wieder offen (j/n)? Sonst von Hand oeffnen."
}

# R: Sperrzeit (004) schreiben, Doppelkontakt, Sperrtaste gegen Buchse, TM550 Zustand 2 per #WP 006
function Read-004([int]$k) {
    $v = ""
    foreach ($l in (Send-Cmd ("#RP 004 0" + $k))) { if ($l -match "^&P\s*004\s+0*$k\s+(\d+)") { $v = $Matches[1] } }
    return $v
}
if (Ask "R  Sperrzeit #WP 004 auf E4 (0,5 s), Doppelkontakt, CP Sperrtaste gegen Buchse, TM550 #WP 006 04 2") {
    $unit = $(if ($Device -eq "tm550") { 1000 } else { 100 })
    $menu = $(if ($Device -eq "tm550") { "Menue Input blocking time" } else { "F > Einstellungen > Sperre" })
    $o4 = Read-004 4
    $script:summary += ("{0,-22} {1}" -f "R1 004 E4 vorher", $o4)
    $new = $(if ($Device -eq "tm550") { "0500" } else { "0050" })
    Log "--- R1 #WP 004 04 $new (0,5 s) ---"
    [void](Send-Cmd "#WP 004 04 $new")
    $r = Read-004 4
    $script:summary += ("{0,-22} {1}" -f "R1 004 E4 nachher", $r)
    Note "R1 Menue" "Am Geraet $menu oeffnen: zeigt E4 jetzt 0,5 s (Wert notieren), dann zurueck zur Laufanzeige"
    [void](Observe "R2 Doppelkontakt" "Buchse 4 zweimal schnell hintereinander ausloesen (unter 0,5 s, z.B. Stecker kurz wackeln), dann nach 2 s nochmals einmal" 20)
    Note "R2 Papier/Display" "Wie viele Zielzeiten zeigen Papier bzw. Display fuer diese drei Impulse?"
    if ($o4 -match "^\d+$") { [void](Send-Cmd ("#WP 004 04 " + $o4.PadLeft(4, "0"))); [void](Read-004 4) }
    if ($Device -eq "cp545") {
        Log "--- R3 rote Sperrtaste gegen Buchse ---"
        [void](Observe "R3 sperren" "rote Sperrtaste 1 druecken, bis bei E1 ein schwarzer Balken steht" 20)
        [void](Read-Inputs "R3 nach Sperrtaste")
        [void](Observe "R3 Buchse" "Impuls NUR ueber Buchse 1 ausloesen (nicht die gruene Taste)" 20)
        Note "R3 Papier" "Hat der CP fuer diesen Buchsen-Impuls eine Zeit gedruckt bzw. angezeigt (j/n)?"
        [void](Observe "R3 oeffnen" "rote Sperrtaste 1 wieder druecken, bis E1 wieder offen ist" 20)
        [void](Read-Inputs "R3 wieder offen")
    } else {
        Log "--- R3 #WP 006 04 2 (gesperrt) ---"
        [void](Send-Cmd "#WP 006 04 2")
        [void](Read-Inputs "R3 nach 006 04 2")
        Note "R3 Display" "Was zeigt das Kaestchen ueber E4 (Farbe, Pfeil)?"
        [void](Observe "R3 Buchse" "Impuls ueber Buchse 4 ausloesen" 20)
        [void](Observe "R3 Taste" "Taste E4 am Geraet druecken" 20)
        [void](Send-Cmd "#WP 006 04 0")
        [void](Read-Inputs "R3 zurueck")
        Note "R3 offen" "Ist E4 wieder offen (gruen, Pfeil nach oben) (j/n)?"
    }
}

# S: Uhr am Geraet auf 00:00 stellen und mit einem Impuls synchronisieren. Welche Zeile kommt?
if (Ask "S  Uhr synchronisieren: am Geraet 00:00 einstellen, mit Impuls auf E1 ausloesen, Zeilen beobachten") {
    [void](Send-Cmd "#EE 1")
    [void](Send-Cmd "#RP 003")
    if ($Device -eq "tm550") {
        $how = "Menue (Pfeil links bis Hauptmenue) > Synchronisation > Manual: Datum heute, Zeit 00:00:00 einstellen und bestaetigen. Eingang E1 muss offen sein (gruen). Dann Impuls auf Buchse 1"
    } else {
        $how = "Lauf schliessen (F > Lauf schliessen > *), dann F > Synchronisation > Manuell: Datum heute, Zeit 00:00:00, bestaetigen. E1 muss offen sein (kein Balken). Dann Impuls auf Buchse 1"
    }
    [void](Observe "S1 Sync" $how 120)
    Note "S1 Display" "Was zeigt das Display jetzt (Uhrzeit, Hinweis wie SYNC)? Lief die Uhr ab dem Impuls von 00:00 los?"
    [void](Send-Cmd "#RP 003")
    if ($Device -eq "cp545") {
        [void](Observe "S2 Lauf" "Neuen Lauf oeffnen (F > Neuen Lauf oeffnen > *), Zeitmessart NET TIME" 60)
    }
    [void](Observe "S3 Impulse" "Start auf E1 und Ziel auf E4 ausloesen (Zeitformat nach dem Sync)" 30)
    [void](Send-Cmd "#EE 0")
    Note "S Ende" "Uhr nachher wieder auf die richtige Zeit gestellt (j/n)? Sonst vor dem naechsten Einsatz stellen."
}

# T: Ethernet-Menue CP 545 (nur Fragen, kein Befehl)
if ($Device -eq "cp545" -and (Ask "T  Ethernet-Menue CP 545: Std Connexion und User Connexion (nur Fragen)")) {
    Note "T1 Std" "F > Einstellungen > Ethernet > Std Connexion: welche Adresse, Maske, Port zeigt der CP (abschreiben)?"
    Note "T2 Std an" "Ist Ethernet nach Std Connexion eingeschaltet (verbindet die App bzw. dieses Skript per IP) (j/n)?"
    Note "T3 User" "F > Einstellungen > Ethernet > User Connexion: welche Adresse, Maske, Port?"
}

# U: Sperrzustaende einzeln pruefen. Pro Zustand zwei getrennte Fenster: erst nur Buchse, dann nur Taste.
function Count-T($lines) { return @($lines | Where-Object { $_ -match "^T[N+=]" }).Count }
function Try-Both([string]$label, [int]$k) {
    $hand = $(if ($Device -eq "tm550") { "Taste E$k am Geraet" } else { "gruene Taste $k am Geraet" })
    $b = Observe "$label Buchse" "GENAU EINMAL Impuls ueber Buchse $k (Kabel/Taster), Taste am Geraet NICHT druecken" 15
    $t = Observe "$label Taste" "GENAU EINMAL $hand druecken, Buchse NICHT benutzen" 15
    $script:summary += ("{0,-22} {1}" -f "$label Ergebnis", ("Buchse: " + (Count-T $b) + " Zeit(en), Taste: " + (Count-T $t) + " Zeit(en)"))
}
if (Ask "U  Sperrzustaende E4 einzeln: per Befehl und per Taste, je nur Buchse und nur Taste") {
    $o = Read-Inputs "U0 vorher"
    if ($Device -eq "tm550") {
        foreach ($v in @("0", "1", "2")) {
            Log "--- U1 #WP 006 04 $v ---"
            [void](Send-Cmd "#WP 006 04 $v")
            [void](Read-Inputs "U1 006=$v")
            Note "U1 Display $v" "Kaestchen ueber E4 jetzt: Farbe und Pfeil (z.B. gruen hoch, rot runter, rot ohne Pfeil)?"
            Try-Both "U1 006=$v" 4
        }
        [void](Send-Cmd "#WP 006 04 0")
        foreach ($n in 1..2) {
            [void](Observe "U2 SHIFT $n" "SHIFT, dann E4 druecken (einmal), dann nichts mehr" 15)
            [void](Read-Inputs "U2 nach SHIFT $n")
            Note "U2 Display $n" "Kaestchen ueber E4 jetzt: Farbe und Pfeil?"
            Try-Both "U2 SHIFT $n" 4
        }
        [void](Observe "U2 zurueck" "SHIFT, dann E4 nochmals (wieder gruen, Pfeil nach oben)" 15)
    } else {
        Log "--- U1 #WP 006 04 0 ---"
        [void](Send-Cmd "#WP 006 04 0")
        [void](Read-Inputs "U1 006=0")
        Note "U1 Display" "Steht bei E4 ein Balken (j/n)?"
        Try-Both "U1 006=0" 4
        [void](Send-Cmd "#WP 006 04 1")
        [void](Observe "U2 rote Taste" "rote Sperrtaste 4 druecken, bis bei E4 ein Balken steht" 20)
        [void](Read-Inputs "U2 nach roter Taste")
        Try-Both "U2 rote Taste" 4
        [void](Observe "U2 zurueck" "rote Sperrtaste 4 wieder druecken, bis E4 offen ist" 20)
    }
    if ($o[3] -match "^\d$") { [void](Send-Cmd ("#WP 006 04 " + $o[3])) }
    [void](Read-Inputs "U Ende")
    Note "U Ende" "Ist E4 wieder offen (j/n)? Sonst von Hand oeffnen."
}

# V: Sperrzeit wirkt? Auf 2 s stellen, damit zwei Impulse von Hand sicher innerhalb der Sperrzeit liegen.
if (Ask "V  Sperrzeit E4 auf 2 s: zwei Impulse innerhalb 2 s (Buchse, dann Taste), danach alter Wert") {
    $o4 = Read-004 4
    $two = $(if ($Device -eq "tm550") { "2000" } else { "0200" })
    [void](Send-Cmd "#WP 004 04 $two")
    $script:summary += ("{0,-22} {1}" -f "V 004 E4", ((Read-004 4) + " (vorher " + $o4 + ")"))
    $hand = $(if ($Device -eq "tm550") { "Taste E4 am Geraet" } else { "gruene Taste 4 am Geraet" })
    $b = Observe "V1 Buchse" "Buchse 4 ZWEIMAL innerhalb 1 s ausloesen, dann 5 s warten, dann noch EINMAL" 20
    Note "V1 Display" "Wie viele Zielzeiten zeigt das Display bzw. Papier fuer diese 3 Impulse?"
    $t = Observe "V2 Taste" "$hand ZWEIMAL innerhalb 1 s druecken, dann 5 s warten, dann noch EINMAL" 20
    Note "V2 Display" "Wie viele Zielzeiten zeigt das Display bzw. Papier fuer diese 3 Tastendruecke?"
    $script:summary += ("{0,-22} {1}" -f "V Ergebnis", ("Buchse: " + (Count-T $b) + " Zeit(en) fuer 3, Taste: " + (Count-T $t) + " Zeit(en) fuer 3"))
    if ($o4 -match "^\d+$") { [void](Send-Cmd ("#WP 004 04 " + $o4.PadLeft(4, "0"))) }
    $script:summary += ("{0,-22} {1}" -f "V 004 E4 zurueck", (Read-004 4))
}

# W: Zeit von aussen eintragen. Fall: am Hauptgeraet wird von Hand gestoppt, die Reserve soll die Zeit auch haben.
function Last-Time($lines, [string]$ch) {
    # letzte Zeitzeile auf Eingang $ch: Uhrzeit (mit oder ohne Stunden) und Tagesfeld
    $hit = $null
    foreach ($l in $lines) {
        if ($l -match "^T[N+=]\s.*?\s+M?0?$ch\s+((\d{1,2}:)?\d{1,2}:\d{2}\.\d+)\s+(\d+)") { $hit = @($Matches[1], $Matches[3]) }
    }
    return $hit
}
function Plus-Seconds([string]$t, [double]$sec) {
    $p = $t.Split(":")
    if ($p.Count -eq 2) { $p = @("0") + $p }
    $ts = [TimeSpan]::FromHours([double]$p[0]) + [TimeSpan]::FromMinutes([double]$p[1]) + [TimeSpan]::FromSeconds([double]::Parse($p[2], [Globalization.CultureInfo]::InvariantCulture) + $sec)
    return ("{0:00}:{1:00}:{2:00}.{3:00000}" -f [int][Math]::Floor($ts.TotalHours), $ts.Minutes, $ts.Seconds, [int](($ts.TotalSeconds - [Math]::Floor($ts.TotalSeconds)) * 100000))
}
if (Ask "W  Zeit von aussen: #WC 014 Zielzeit einfuegen, #WC 008 Handimpuls Ziel, #!T Uhr, #WC 011 Ethernet (USB)") {
    Log "--- W1 #WC 014: Zielzeit 5 s nach einem Start einfuegen ---"
    $st = Observe "W1 Start" "EINEN Start ueber Buchse 1 ausloesen (Boot auf der Strecke), dann nichts mehr" 15
    $t = Last-Time $st "1"
    if ($t) {
        $fin = Plus-Seconds $t[0] 5
        $day = $t[1].PadLeft(5, "0")   # THCOM08: DDDDD (5 Stellen); CP 545 lehnte 4 Stellen mit AK R ab
        [void](Send-Cmd ("#WC 014 04 0000 " + $fin + " " + $day))
        [void](Collect 3000 5000)
        Note "W1 Display" "Steht das Boot jetzt im Ziel mit Laufzeit 5 s (Display/Papier)? Was genau steht da?"
        $bn = (Read-Host "Welche Startnummer hat das Boot auf der Strecke (Display)? Nur die Zahl").Trim()
        Log "Notiz W1 Nr: $bn"
        if ($bn -match "^\d+$") {
            [void](Send-Cmd ("#WC 014 04 " + $bn.PadLeft(4, "0") + " " + (Plus-Seconds $t[0] 6) + " " + $day))
            Note "W1 mit Nr" "Zweite eingefuegte Zeit (mit dieser Nr, Laufzeit 6 s): Boot jetzt im Ziel? Was zeigt das Geraet?"
        }
    } else { Log "W1: keine Startzeile erkannt, #WC 014 uebersprungen" }
    Log "--- W2 #WC 008 04: Handimpuls auf Eingang 4 ausloesen ---"
    [void](Observe "W2 Start" "EINEN Start ueber Buchse 1 ausloesen, dann nichts mehr" 15)
    [void](Send-Cmd "#WC 008 04")
    [void](Collect 3000 5000)
    Note "W2 Display" "Kam am Geraet ein Zielimpuls an (Boot im Ziel, Papier, Laufzeit)?"
    Log "--- W3 #!T Uhr abfragen ---"
    [void](Send-Cmd "#!T")
    if ($Com) {
        Log "--- W4 #WC 011 1 (Ethernet mit Standard-IP einschalten) ---"
        Note "W4 vorher" "Ethernet am Geraet vorher AUS (z.B. nach dem Einschalten nicht eingeschaltet) (j/n)?"
        [void](Send-Cmd "#WC 011 1")
        Note "W4 nachher" "Ist Ethernet jetzt an (Symbol, ping 192.168.1.50 in einem zweiten Fenster) (j/n)?"
    }
}

# X: Uhr per Befehl stellen (THCOM08 #WC 007). Typ 02 manuell mit Uhrzeit, Typ 03 Synchro auf Null.
if (Ask "X  Uhr per Befehl: #WC 007 02 (manuell, naechste Minute) und #WC 007 03 (auf Null). Verstellt die Uhr!") {
    $n = (Get-Date).AddMinutes(2)
    # Schraegstriche fest (die deutsche Einstellung machte aus / sonst Punkte, CP: AK F)
    $cmd = "#WC 007 02 " + $n.ToString("HH:mm", [Globalization.CultureInfo]::InvariantCulture) + " " + $n.ToString("dd'/'MM'/'yy", [Globalization.CultureInfo]::InvariantCulture)
    [void](Send-Cmd $cmd)
    [void](Observe "X1 manuell" ("Display beobachten bis " + $n.ToString("HH:mm") + " Uhr (Aufforderung? Wartet es auf einen Impuls? Dann Impuls auf Buchse 1 genau um " + $n.ToString("HH:mm:00") + ")") 150)
    Note "X1 Display" "Was hat das Geraet gezeigt, und welche Uhrzeit zeigt es jetzt?"
    [void](Send-Cmd "#WC 007 03")
    [void](Observe "X2 Null" "Display beobachten; falls es auf einen Impuls wartet: Impuls auf Buchse 1" 60)
    Note "X2 Display" "Was hat das Geraet gezeigt, und welche Uhrzeit zeigt es jetzt?"
    [void](Observe "X3 Impulse" "Start auf E1 und Ziel auf E4 ausloesen (Zeitformat)" 30)
    Note "X Ende" "Uhr am Geraet danach wieder auf die richtige Zeit stellen (Synchronisation). Erledigt (j/n)?"
}

# Y: Synchronisation Master/Slave RS232. Der PC spielt den Master: THCOM08 «!T HH:MM:SS DD/XX/YY» (Zeit + 1 s).
function Watch-Offset([string]$label, [int]$Sec) {
    # Zeitzeilen mit Empfangszeit am PC: Versatz Geraeteuhr minus PC-Uhr in Sekunden
    $end = (Get-Date).AddSeconds($Sec); $buf = ""
    while ((Get-Date) -lt $end) {
        $chunk = Read-Raw
        if ($chunk) {
            $rx = Get-Date
            $buf += $chunk
            while ($buf -match "^(.*?)\n") {
                $line = $Matches[1].TrimEnd("`r"); $buf = $buf.Substring($Matches[0].Length)
                if (-not $line.Trim()) { continue }
                Log ("   <- " + (Visible $line))
                if ($line -match "^T[N+=]\s.*?\s((\d{1,2}):(\d{2}):(\d{2}\.\d+))\s") {
                    $dev = [double]$Matches[2] * 3600 + [double]$Matches[3] * 60 + [double]::Parse($Matches[4], [Globalization.CultureInfo]::InvariantCulture)
                    $pc = $rx.TimeOfDay.TotalSeconds
                    $off = $dev - $pc
                    Log ("   Versatz Geraet - PC: {0:0.000} s" -f $off)
                    $script:summary += ("{0,-22} {1}" -f $label, ("Versatz Geraet - PC {0:0.000} s" -f $off))
                }
            }
        }
        Start-Sleep -Milliseconds 5
    }
}
if ($Device -eq "cp545" -and $Com -and (Ask "Y  RS232 Master/Slave: PC sendet !T jede Sekunde, Versatz messen; CP als Master beobachten")) {
    Log "--- Y0 Versatz vorher ---"
    Write-Host "Y0: EINEN Impuls ueber Buchse 1 ausloesen (misst den Versatz vor dem Sync)" -ForegroundColor Yellow
    [void](Read-Host "Enter, dann 20 s Zeit")
    Watch-Offset "Y0 vorher" 20
    Note "Y1 Menue" "Am CP F > Synchronisation > Master/Slave RS232 oeffnen: welche Auswahl gibt es (Master, Slave, Baudrate)? Slave waehlen und bestaetigen. Was zeigt der CP?"
    Log "--- Y1 PC als Master: 30 s lang zu jeder vollen Sekunde !T <Sekunde+1> ---"
    Write-Host "Y1: 30 s lang sendet der PC die Uhrzeit. Am CP beobachten (Meldung, Uhr)." -ForegroundColor Yellow
    [void](Read-Host "Enter druecken zum Start")
    $end = (Get-Date).AddSeconds(30); $buf = ""
    while ((Get-Date) -lt $end) {
        $now = Get-Date
        $next = $now.Date.AddSeconds([Math]::Floor($now.TimeOfDay.TotalSeconds) + 1)
        $ms = ($next - (Get-Date)).TotalMilliseconds
        if ($ms -gt 0) { Start-Sleep -Milliseconds ([int]$ms) }
        $t = $next.AddSeconds(1)
        $msg = "!T " + $t.ToString("HH:mm:ss", [Globalization.CultureInfo]::InvariantCulture) + " " + $t.ToString("dd'/'MM'/'yy", [Globalization.CultureInfo]::InvariantCulture)
        $frame = $(if ($UseCs) { $msg + "`t" + (Cs16 $msg) + "`r`n" } else { $msg + "`r`n" })
        Write-Raw $frame
        Log ("-> " + (Visible $frame.TrimEnd()))
        $chunk = Read-Raw
        if ($chunk) { foreach ($l in ($chunk -split "`n")) { if ($l.Trim()) { Log ("   <- " + (Visible $l.TrimEnd("`r"))) } } }
    }
    Note "Y1 Display" "Hat der CP synchronisiert (Meldung, Uhr springt auf PC-Zeit)? Was zeigt er jetzt?"
    Write-Host "Y2: Lauf oeffnen falls noetig, dann EINEN Impuls ueber Buchse 1 (misst den Versatz nach dem Sync)" -ForegroundColor Yellow
    [void](Read-Host "Enter, dann 60 s Zeit")
    Watch-Offset "Y2 nachher" 60
    Note "Y3 Master" "Am CP F > Synchronisation > Master/Slave RS232 als MASTER waehlen (falls es geht), j wenn gewaehlt"
    [void](Send-Cmd "#!T")
    Write-Host "Y3: 30 s zuhoeren, ob der CP als Master !T-Zeilen schickt" -ForegroundColor Yellow
    Watch-Offset "Y3 Master" 30
    Note "Y Ende" "Uhr am CP wieder richtig (sonst F > Synchronisation von Hand) (j/n)?"
}

# Z: CP 545 als Slave fragt jede Sekunde «#!T». Antwort sofort, Sekunden-Top als Puls auf DTR/RTS.
if ($Device -eq "cp545" -and $Com -and (Ask "Z  RS232 Slave: auf #!T antworten (mit/ohne Pruefsumme), Puls auf DTR/RTS zur vollen Sekunde")) {
    Note "Z0 Menue" "Am CP F > Synchronisation > Master/Slave RS232 waehlen, bis er 'warten auf Synchro' zeigt (j)"
    Write-Host "Z1: 40 s lang beantwortet der PC jede Anfrage. Display beobachten." -ForegroundColor Yellow
    [void](Read-Host "Enter druecken zum Start")
    $end = (Get-Date).AddSeconds(40); $buf = ""; $n = 0
    while ((Get-Date) -lt $end) {
        $chunk = Read-Raw
        if ($chunk) { $buf += $chunk }
        while ($buf -match "^(.*?)\n") {
            $line = $Matches[1].TrimEnd("`r"); $buf = $buf.Substring($Matches[0].Length)
            if (-not $line.Trim()) { continue }
            Log ("   <- " + (Visible $line))
            if ($line -match "^#!T") {
                $now = Get-Date
                $top = $now.Date.AddSeconds([Math]::Floor($now.TimeOfDay.TotalSeconds) + 1)
                $msg = "!T " + $top.ToString("HH:mm:ss", [Globalization.CultureInfo]::InvariantCulture) + " " + $top.ToString("dd'/'MM'/'yy", [Globalization.CultureInfo]::InvariantCulture)
                $cs = ($n % 2 -eq 0); $n++
                $frame = $(if ($cs) { $msg + "`t" + (Cs16 $msg) + "`r`n" } else { $msg + "`r`n" })
                Write-Raw $frame
                Log ("-> " + (Visible $frame.TrimEnd()) + $(if ($cs) { "  (mit Pruefsumme)" } else { "  (ohne)" }))
                $ms = ($top - (Get-Date)).TotalMilliseconds
                if ($ms -gt 0) { Start-Sleep -Milliseconds ([int]$ms) }
                if ($script:sp) {
                    $script:sp.DtrEnable = $false; $script:sp.RtsEnable = $false
                    Start-Sleep -Milliseconds 20
                    $script:sp.DtrEnable = $true; $script:sp.RtsEnable = $true
                    Log "   Puls DTR/RTS zur Sekunde $($top.ToString('HH:mm:ss'))"
                }
            } elseif ($line -match "^T[N+=]\s") {
                Log "   (Zeitzeile)"
            }
        }
        Start-Sleep -Milliseconds 5
    }
    Note "Z1 Display" "Hat der CP synchronisiert? Was zeigt er (Uhrzeit)?"
    Write-Host "Z2: Lauf oeffnen falls noetig, dann EINEN Impuls ueber Buchse 1 (misst den Versatz)" -ForegroundColor Yellow
    [void](Read-Host "Enter, dann 60 s Zeit")
    Watch-Offset "Z2 nachher" 60
    Note "Z Ende" "Falls der CP noch auf Synchro wartet: abbrechen und Uhr von Hand stellen. Erledigt (j/n)?"
}

# F: Zeilen ohne Stunden (nur Info): letzte Impulse mit #RT anfordern, Format pruefen
if (Ask "F  Format: 10 s Impulse beobachten (Start und Ziel ausloesen), Zeitformat und Zusatzfelder pruefen") {
    [void](Collect 10000 10000)
}

Write-Host ""
Log "=== Zusammenfassung ==="
foreach ($s in $script:summary) { Log $s }
Log "Logdatei: $log"
if ($script:sp) { $script:sp.Close() } else { $script:tcp.Close() }
