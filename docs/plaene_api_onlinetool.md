# Pläne: API und Anbindung ans Onlinetool

Stand 22.11.2026, App v1.12.0. Was hier unter «geplant» steht, ist noch nicht gebaut.

## Grundsätze (gelten für alles hier)

- Der Speaker-PC ist von aussen nicht erreichbar. Die App baut nur ausgehende Verbindungen auf
  (Onlinetool, Update-Prüfung auf GitHub). Einzige Ausnahme ist die Browser-Anzeige im lokalen Netz,
  nur lesend und nur mit Schlüssel, standardmässig aus.
- Keine Zugangsdaten in der .exe. Der API-Schlüssel des Onlinetools wird pro Wettkampf in der App
  eingegeben und liegt nur in den Einstellungen im Datenordner.
- Nur `https://`, Zertifikat wird geprüft. Die App spricht nur mit der eingetragenen Adresse.
- Fehlerberichte gehen nie automatisch weg. Upload nur auf Knopfdruck.
- Das Onlinetool ist Master für Startliste und Strafpunkte. Die App liefert nur gefahrene Zeiten.
- Ein Ausfall des Onlinetools oder des Internets darf die Zeitmessung und die Speakeranzeige nie
  stören. Alles läuft weiter offline, Uploads warten in der Warteschlange.

## 1. Lokale API (Browser-Anzeige)

### Stand

Nur lesen, nur im lokalen Netz, jede Abfrage mit `?key=…`, Antworten in JSON (UTF-8).

| Endpunkt | Inhalt |
| --- | --- |
| `GET /api/v1/live` | laufendes Boot, Laufzeit, letzter Zieleinlauf, Wettkampf |
| `GET /api/v1/results` | Ranglisten pro Kategorie, Rang, Zeit, Strafpunkte, nicht klassiert (DNS, DNF, DSQ) |
| `GET /api/v1/course` | Boote auf der Fahrstrecke mit Startzeit und Laufzeit |
| `GET /api/v1/startlist` | nächste Starter in Startreihenfolge |
| `GET /api/v1/events` | die letzten 30 Ereignisse des Tickers |
| `WS /ws` | bei jeder Änderung der Stand der Anzeige, mit `&stream=all` alles in einer Nachricht |

Übersicht im Browser unter `/api?key=…`.

### Geplant

- `GET /api/v1/device`: verbundenes Haupt- und Reservegerät, Verbindungsart, Uhrversatz, letzte Zeile.
  Für eine zweite Anzeige beim Zeitmesser.
- `GET /api/v1/results?kategorie=…` und `?verein=…`: gefiltert, für Vereinsbildschirme.
- Versionsangabe `api_version` in jeder Antwort. Änderungen, die bestehende Felder brechen, nur mit `/api/v2/`.
- Kein Schreibzugriff über die lokale API. Bedienung bleibt in der App.

## 2. Onlinetool

### Stand

- Einstellungen vorhanden: Betriebsart Offline (Startliste aus Excel) oder Online (Onlinetool ist Master),
  API-Adresse (`https://`), Wettkampf-ID, API-Schlüssel, Senden sofort oder nach Bestätigung,
  Startliste automatisch aktualisieren bei Vereins- oder Startblockwechsel.
- Upload-Warteschlange mit Status pro Resultat, Nutzlast vorbereitet (`build_upload_payload`).
- Klasse `OnlineClient` als Platzhalter (`fetch_startlist`, `send_result`).
- Es fehlt die API-Dokumentation des Onlinetools. Die Endpunkte unten sind ein Vorschlag und werden an
  die echte API angepasst.

### Datenfluss

```
Onlinetool  --Startliste, Strafpunkte, Kategorien-->  App
App         --gefahrene Zeiten (nach Bestätigung oder sofort)-->  Onlinetool
App         --Fehlerberichte (nur auf Knopfdruck)-->  Onlinetool
```

### Vorschlag Endpunkte

| Richtung | Aufruf | Inhalt |
| --- | --- | --- |
| lesen | `GET /wettkaempfe/{id}` | Name, Datum, Ort, Kategorien mit Nummernbereich |
| lesen | `GET /wettkaempfe/{id}/startliste?seit=…` | Teilnehmer, Startreihenfolge, Startblöcke, Strafpunkte, DNS; mit `seit` nur Änderungen |
| schreiben | `POST /wettkaempfe/{id}/zeiten` | eine oder mehrere Zeiten |
| schreiben | `POST /wettkaempfe/{id}/fehlerberichte` | ZIP eines Fehlerberichts |

Authentifizierung: `Authorization: Bearer <API-Schlüssel>`, Schlüssel nur für diesen Wettkampf gültig
und mit Ablaufdatum.

### Nutzlast einer Zeit

```json
{
  "wettkampf_id": "…",
  "startnummer": 207,
  "lauf": 1,
  "zeit": "5:27.90",
  "zeit_sekunden": 327.9,
  "quelle": "CP 545",
  "erfasst_um": "2026-06-13T14:05:22",
  "upload_id": "5f3c…"
}
```

- `upload_id` ist pro Resultat fest. Sendet die App nach einem Abbruch erneut, legt das Onlinetool
  keinen zweiten Eintrag an.
- Korrigiert der Zeitmesser eine Zeit, schickt die App dieselbe `upload_id` mit neuer Zeit und
  `korrektur: true`. Storno als `status: "DNF" | "DSQ"` ohne Zeit.
- Keine Strafpunkte, keine Rangliste. Die rechnet das Onlinetool.

### Ablauf in der App

1. Online-Modus, Adresse, Wettkampf-ID und Schlüssel eintragen, «Verbindung testen» ruft
   `GET /wettkaempfe/{id}` auf und zeigt Name und Datum.
2. «Startliste vom Onlinetool laden» ersetzt den Excel-Import. Änderungen gegenüber dem Stand in der
   App werden vor dem Übernehmen angezeigt. Bereits gefahrene Boote bleiben unverändert.
3. Automatische Aktualisierung bei Vereins- oder Startblockwechsel holt nur Änderungen (`seit`).
   Neue Strafpunkte erscheinen sofort im Speaker-Ranking.
4. Jede Zielzeit kommt in die Warteschlange. Modus «sofort»: senden ohne Rückfrage. Modus
   «nach Bestätigung»: Zeitmesser bestätigt einzeln oder alle.
5. Fehlgeschlagene Uploads wiederholt die App mit wachsender Pause (5 s, 15 s, 60 s, dann jede Minute).
   Status pro Zeile: offen, gesendet, Fehler mit Meldung.
6. Die Warteschlange liegt im Autosave. Nach einem Absturz oder Neustart geht nichts verloren.

### Netzwerk

- Für das Onlinetool braucht der PC Internet, getrennt vom Zeitmessnetz (192.168.1.x). Empfohlen:
  WLAN oder Handy-Hotspot für Internet, Kabel für CP 545 bzw. TM550. Die App setzt keine Route ins
  Internet über die Netzwerkkarte des Zeitmessgeräts.
- Ohne Internet läuft alles offline weiter. Die Anzeige «Upload: n offen» zeigt den Rückstand.

## 3. Offene Punkte

- API-Dokumentation des Onlinetools (Adressen, Felder, Authentifizierung, Fehlercodes).
- Wer stellt den API-Schlüssel pro Wettkampf aus, wie lange gilt er.
- Darf das Onlinetool Zeiten des Speaker-PCs überschreiben, oder nur der Zeitmesser im Onlinetool.
- Format für mehrere Läufe pro Boot (Lauf 1 und 2, beste oder Summe).
- Testumgebung des Onlinetools für Probeläufe mit dem Simulator.
