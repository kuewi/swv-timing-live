# Funkstrecke HL675 und TAG Heuer Timing Online (GPRS)

Notizen aus den ITS-Unterlagen «Liaison radio HL675 vers Modulo», «Serveur TAG Heuer Timing Online,
liaison départ / arrivée», «Chronoprinter 540 GPRS Connection» und «Connexion-paramétrage CP545 – Elite v3».
Die PDF-Dateien selbst liegen nicht im Repository.

## Funkstrecke HL675

- Sender HL675-TX und Empfänger HL675-RX übertragen eine RS232-Leitung per Funk, z.B. vom CP 545 oder TM550 zur
  Anzeigetafel (Modulo) oder zu einem PC.
- Kabel laut ITS: USB-RS232 (Stecker) am PC, RS232 Buchse/Buchse zwischen Gerät und Sender, RS232 auf
  Bananenstecker (HL675TX-F, HL675RX-M) für Impulse.
- Für die App ist die Funkstrecke ein normaler COM-Port. Sie liefert, was das Gerät auf RS232 ausgibt:
  - Anzeige-Protokoll (Laufzeit, Nummer) → Verbindungsart **RS232**, die App wertet nur aus.
  - THCOM-Zeilen → Verbindungsart **USB** mit dem COM-Port des Empfängers. Befehle gehen nur, wenn die Strecke
    in beide Richtungen überträgt; sonst meldet die App «beantwortet keine Befehle» und arbeitet nur mit den
    Zeiten weiter.
- Funk kann Zeilen verlieren. Lücken in den Zählnummern holt die App beim CP 545 mit `#RT` nach, beim TM550
  per Download des Laufs.

## TAG Heuer Timing Online (Server, GPRS)

Ablauf beim Rallye-/Bergrennen-Beispiel von ITS:

1. Auf TAG Heuer Timing Online unter MATERIAL alle Geräte erfassen (beim CP 545 die Seriennummer des CP, nicht
   die der Docking HL540-GSM), dazu jeden PC.
2. Event anlegen und festlegen, wer an wen sendet (Pools). Pro PC einen Software-Port vergeben, z.B. 9000 und
   9001.
3. CP 545 mit Docking HL540-GSM: SIM-Karte ohne PIN, Zugang mit «GPRS Settings» über den COM-Port eintragen
   (APN, Server, Port, Timer ID). Am CP: Menü › Docking › GPS ein, mit GPRS 1 verbinden. Zeitmessart
   START – FINISH; Eingang 1 empfängt vom Server, Eingang 4 sendet.
4. Auf dem PC läuft «GPRS Interface» (TAG Heuer). Es holt die Zeilen vom Server und liefert sie lokal auf
   **127.0.0.1** am Software-Port des Events. Es verbindet, sobald die Zeitmess-Software den Port öffnet.

Elite V3 (Chronelec) liest dort mit Protokoll «TAG HEUER CP540/HL440», IP 127.0.0.1, Port = Software-Port.
Direkt am CP 545 über Ethernet nimmt Elite V3 IP 192.168.1.50 und Port 7000.

## In der App

- Verbindungsart Ethernet, im Feld «Gerät» `127.0.0.1:9000` (Port des Events) eintippen, «Verbinden».
- Die App sendet über diese Verbindung **keine Befehle** (kein Vorladen, kein Nachholen, kein Drucken). Nummern
  übernimmt sie wie geliefert, fehlt eine Nummer, nimmt sie die Startreihenfolge.
- Sicherheit: Die App öffnet dafür keinen Port, sie verbindet nur ausgehend zu 127.0.0.1. Das GPRS Interface ist
  ein fremdes Programm, das selbst ins Internet verbindet und einen lokalen Port öffnet. Fragt die
  Windows-Firewall beim GPRS Interface nach, nur «Private Netzwerke» erlauben.
- Nicht getestet: Es gibt im Verband keine Docking HL540-GSM. Format der Zeilen laut ITS wie vom CP 545.
