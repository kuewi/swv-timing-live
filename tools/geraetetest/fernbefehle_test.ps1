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
#   Nur einzelne Gruppen: ... -Nur A,G
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
Start-Sleep -Milliseconds 500
$pre = Collect 800 2000
if ($pre.Count) { Log ("Beim Verbinden " + $pre.Count + " Zeile(n) erhalten") }

# A: nur lesen
if (Ask "A  Lesen: #SN, #ID, #!T, #RP 003 (Lauf), #RP 120 (Betriebsart)") {
    foreach ($c in @("#SN", "#ID", "#!T", "#RP 003", "#RP 120")) { [void](Send-Cmd $c) }
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

# F: Zeilen ohne Stunden (nur Info): letzte Impulse mit #RT anfordern, Format pruefen
if (Ask "F  Format: 10 s Impulse beobachten (Start und Ziel ausloesen), Zeitformat und Zusatzfelder pruefen") {
    [void](Collect 10000 10000)
}

Write-Host ""
Log "=== Zusammenfassung ==="
foreach ($s in $script:summary) { Log $s }
Log "Logdatei: $log"
if ($script:sp) { $script:sp.Close() } else { $script:tcp.Close() }
