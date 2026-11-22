# TM550-Verhaltenstest fuer SWV Live-Ranking
# Prueft, wie der TM550 mit dem PC spricht: Netz, Ports, wer die Verbindung aufbaut, Antworten auf Befehle,
# USB/RS232. Alles wird in tm550_test_<Datum>.txt neben diesem Skript geschrieben.
#
# Start: PowerShell im Ordner dieses Skripts oeffnen, dann
#   powershell -ExecutionPolicy Bypass -File .\tm550_test.ps1
# Optional: -Ip 192.168.0.101 -Port 2101 -Com COM5 -Listen 30
param(
    [string]$Ip = "192.168.0.101",
    [int]$Port = 2101,
    [string]$Com = "",
    [int]$Listen = 30
)

$log = Join-Path $PSScriptRoot ("tm550_test_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".txt")
function Log($text) {
    $line = (Get-Date -Format "HH:mm:ss.fff") + "  " + $text
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}
function Show($bytes, $n) {
    $s = ""
    for ($i = 0; $i -lt $n; $i++) {
        $b = $bytes[$i]
        if ($b -ge 32 -and $b -lt 127) { $s += [char]$b }
        elseif ($b -eq 13) { $s += "<CR>" } elseif ($b -eq 10) { $s += "<LF>`n" }
        elseif ($b -eq 9) { $s += "<TAB>" } else { $s += ("<{0:X2}>" -f $b) }
    }
    return $s
}
function Cs16($text) {
    $sum = 0
    foreach ($b in [Text.Encoding]::ASCII.GetBytes($text)) { if ($b -ne 0x23) { $sum += $b } }
    return ("{0:X4}" -f ($sum -band 0xFFFF))
}
$commands = @("#SN", "#RP 003", "#RP 026 01", "#RP 026 04", "#RT 0001 01")

Log "=== TM550-Test, Ziel $Ip Port $Port ==="

# 1. Netzwerkkarten
Log "--- 1. Netzwerkkarten ---"
Get-NetAdapter | ForEach-Object { Log ("{0}: {1} {2}" -f $_.Name, $_.Status, $_.LinkSpeed) }
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" } |
    ForEach-Object { Log ("IP {0}/{1} auf {2}" -f $_.IPAddress, $_.PrefixLength, $_.InterfaceAlias) }

# 2. Erreichbarkeit
Log "--- 2. Ping und ARP ---"
$ping = Test-Connection -ComputerName $Ip -Count 3 -Quiet
Log "Ping $Ip : $ping"
arp -a | Select-String "192.168." | ForEach-Object { Log ("ARP " + $_.Line.Trim()) }

# 3. Offene Ports am Geraet (der PC verbindet sich)
Log "--- 3. TCP-Ports am Geraet ---"
foreach ($p in @($Port, 7000, 13500, 23, 80)) {
    $c = New-Object System.Net.Sockets.TcpClient
    $ok = $c.ConnectAsync($Ip, $p).Wait(2000)
    Log ("TCP {0}:{1} offen: {2}" -f $Ip, $p, ($ok -and $c.Connected))
    $c.Close()
}

# 4. Befehle ueber TCP (ohne und mit Pruefsumme)
Log "--- 4. Befehle ueber TCP ---"
foreach ($p in @($Port, 7000, 13500)) {
    $c = New-Object System.Net.Sockets.TcpClient
    if (-not ($c.ConnectAsync($Ip, $p).Wait(2000) -and $c.Connected)) { $c.Close(); continue }
    $s = $c.GetStream(); $s.ReadTimeout = 1500
    Start-Sleep -Milliseconds 800
    $buf = New-Object byte[] 8192
    if ($s.DataAvailable) { $n = $s.Read($buf, 0, $buf.Length); Log ("Port $p sendet beim Verbinden: " + (Show $buf $n)) }
    foreach ($cmd in $commands) {
        foreach ($variant in @("plain", "cs")) {
            if ($variant -eq "plain") { $frame = $cmd + "`r`n" } else { $frame = $cmd + "`t" + (Cs16 $cmd) + "`r`n" }
            $b = [Text.Encoding]::ASCII.GetBytes($frame)
            $s.Write($b, 0, $b.Length)
            Start-Sleep -Milliseconds 900
            $out = ""
            while ($s.DataAvailable) { $n = $s.Read($buf, 0, $buf.Length); $out += (Show $buf $n) }
            Log ("Port $p  $cmd ($variant)  ->  " + ($(if ($out) { $out } else { "(keine Antwort)" })))
        }
    }
    $c.Close()
}

# 5. Baut der TM550 selbst eine Verbindung auf? (TCP- und UDP-Empfang auf dem PC)
Log "--- 5. Empfang auf dem PC, $Listen s: jetzt am TM550 einige Impulse ausloesen (E1..E4) ---"
$tcp = $null; $udp = $null
try { $tcp = New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Any, $Port); $tcp.Start(); Log "TCP-Empfang auf Port $Port bereit" }
catch { Log "TCP-Empfang auf Port $Port nicht moeglich: $_" }
try { $udp = New-Object System.Net.Sockets.UdpClient($Port); $udp.Client.ReceiveTimeout = 500; Log "UDP-Empfang auf Port $Port bereit" }
catch { Log "UDP-Empfang auf Port $Port nicht moeglich: $_" }
$end = (Get-Date).AddSeconds($Listen)
$conn = $null
while ((Get-Date) -lt $end) {
    if ($tcp -and $tcp.Pending()) { $conn = $tcp.AcceptTcpClient(); Log ("TCP-Verbindung VOM Geraet: " + $conn.Client.RemoteEndPoint) }
    if ($conn -and $conn.GetStream().DataAvailable) {
        $buf = New-Object byte[] 8192; $n = $conn.GetStream().Read($buf, 0, $buf.Length); Log ("TCP empfangen: " + (Show $buf $n))
    }
    if ($udp -and $udp.Available -gt 0) {
        $ep = New-Object System.Net.IPEndPoint([Net.IPAddress]::Any, 0)
        $d = $udp.Receive([ref]$ep); Log ("UDP von " + $ep + ": " + (Show $d $d.Length))
    }
    Start-Sleep -Milliseconds 100
}
if ($conn) { $conn.Close() }; if ($tcp) { $tcp.Stop() }; if ($udp) { $udp.Close() }

# 6. USB / RS232
Log "--- 6. COM-Ports ---"
[System.IO.Ports.SerialPort]::GetPortNames() | ForEach-Object { Log "COM-Port vorhanden: $_" }
Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match "\(COM\d+\)" } | ForEach-Object { Log ("  " + $_.Name + "  " + $_.DeviceID) }
if ($Com) {
    foreach ($baud in @(9600, 19200, 38400, 57600, 115200)) {
        try {
            $sp = New-Object System.IO.Ports.SerialPort $Com, $baud, None, 8, One
            $sp.ReadTimeout = 1500; $sp.Open()
            Start-Sleep -Milliseconds 500
            $pre = $sp.ReadExisting()
            if ($pre) { Log ("$Com $baud Bd beim Oeffnen: " + (Show ([Text.Encoding]::ASCII.GetBytes($pre)) $pre.Length)) }
            foreach ($cmd in @("#SN", "#RP 003")) {
                $sp.Write($cmd + "`t" + (Cs16 $cmd) + "`r`n"); Start-Sleep -Milliseconds 1200
                $r = $sp.ReadExisting()
                Log ("$Com $baud Bd  $cmd  ->  " + $(if ($r) { Show ([Text.Encoding]::ASCII.GetBytes($r)) $r.Length } else { "(keine Antwort)" }))
            }
            $sp.Close()
        } catch { Log "$Com $baud Bd: $_" }
    }
}
Log "=== Ende. Datei: $log ==="
