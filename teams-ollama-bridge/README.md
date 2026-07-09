# teams-ollama-bridge

Dateibasierte Brücke zwischen Microsoft Teams (via OneDrive und Power Automate) und einem lokal laufenden Ollama-Modell.

Die Anwendung läuft dauerhaft auf einem Windows-PC, überwacht einen lokal synchronisierten OneDrive-Ordner und verarbeitet JSON-Anfragen aus Microsoft Teams. Antworten werden als JSON-Dateien zurück in einen synchronisierten Outputordner geschrieben.

**Wichtig:** Die Anwendung kommuniziert nicht direkt mit Teams, Microsoft Graph oder Power Automate. Der gesamte Datenaustausch erfolgt ausschließlich über lokale Dateien, die von OneDrive synchronisiert werden.

---

## Inhaltsverzeichnis

1. [Zweck und Architektur](#zweck-und-architektur)
2. [Voraussetzungen](#voraussetzungen)
3. [Schritt-für-Schritt: Installation](#schritt-für-schritt-installation)
4. [Schritt-für-Schritt: OneDrive-Ordner einrichten](#schritt-für-schritt-onedrive-ordner-einrichten)
5. [Schritt-für-Schritt: Konfiguration (.env)](#schritt-für-schritt-konfiguration-env)
6. [Schritt-für-Schritt: Erste Prüfung](#schritt-für-schritt-erste-prüfung)
7. [Schritt-für-Schritt: Mock-Modus testen](#schritt-für-schritt-mock-modus-testen)
8. [Schritt-für-Schritt: Teams-End-to-End-Test](#schritt-für-schritt-teams-end-to-end-test)
9. [Schritt-für-Schritt: Umstellung auf Ollama](#schritt-für-schritt-umstellung-auf-ollama)
10. [Schritt-für-Schritt: Windows-Autostart](#schritt-für-schritt-windows-autostart)
11. [Verbindung zu den Power-Automate-Flows](#verbindung-zu-den-power-automate-flows)
12. [Dateianhänge aus dem aktuellen Power-Automate-PoC](#dateianhänge-aus-dem-aktuellen-power-automate-poc)
13. [Input- und Outputformat](#input--und-outputformat)
14. [CLI-Befehle](#cli-befehle)
15. [Konfigurationsreferenz](#konfigurationsreferenz)
16. [Logging](#logging)
17. [SQLite-Status und Archivierung](#sqlite-status-und-archivierung)
18. [Fehlerbehandlung und Neustartverhalten](#fehlerbehandlung-und-neustartverhalten)
19. [Typische Probleme](#typische-probleme)
20. [Datenschutz](#datenschutz)
21. [Tests ausführen](#tests-ausführen)
22. [Zukünftige Erweiterungen](#zukünftige-erweiterungen)

---

## Zweck und Architektur

```
Microsoft Teams
    ↓
Power Automate Flow 1          ← erzeugt Input-JSON bei /ai-Nachrichten
    ↓
OneDrive for Business
    ↓
lokal synchronisierter Inputordner   (z. B. …\TeamsLLM\input)
    ↓
teams-ollama-bridge              ← diese Python-Anwendung
    ↓
Ollama oder Mock-Prozessor
    ↓
lokal synchronisierter Outputordner  (z. B. …\TeamsLLM\output)
    ↓
OneDrive for Business
    ↓
Power Automate Flow 2          ← veröffentlicht Antwort bei status=completed
    ↓
Microsoft Teams
```

| Komponente | Aufgabe |
|------------|---------|
| **Flow 1** | Schreibt pro Teams-Anfrage eine JSON-Datei in den OneDrive-Inputordner |
| **OneDrive-Client** | Synchronisiert Input- und Outputordner auf den lokalen PC |
| **teams-ollama-bridge** | Liest Input, verarbeitet Nachricht, schreibt Response, archiviert Input |
| **Flow 2** | Erkennt neue `response_*.json`, postet Antwort in Teams, räumt auf |

---

## Voraussetzungen

### Hardware und Betriebssystem

| Anforderung | Details |
|-------------|---------|
| Betriebssystem | Windows 11 |
| Rechte | **Keine** Administratorrechte erforderlich |
| Netzwerk | Internet für initiale Paketinstallation; danach lokaler Betrieb möglich |

### Software

| Software | Version | Pflicht | Hinweis |
|----------|---------|---------|---------|
| Python | 3.12 | Ja | [python.org/downloads](https://www.python.org/downloads/) — bei Installation **„Add python.exe to PATH"** aktivieren |
| OneDrive for Business | aktuell | Ja | Synchronisiert Input-/Outputordner |
| Power Automate Flows | — | Ja | Flow 1 und Flow 2 müssen bereits eingerichtet sein |
| Ollama | aktuell | Nein | Erst später nötig; Mock-Modus reicht für den Ersttest |
| Git | beliebig | Nein | Nur zum Klonen des Repositories |

### Bereits vorhandene Infrastruktur

Bevor Sie starten, sollten folgende Komponenten **bereits funktionieren**:

1. Ein Teams-Chat, in dem Nachrichten mit dem Prefix `/ai` an Flow 1 weitergeleitet werden
2. Flow 1 legt JSON-Dateien im OneDrive-Ordner `TeamsLLM\input` ab
3. Flow 2 überwacht `TeamsLLM\output` und veröffentlicht Antworten bei `status: completed`
4. OneDrive synchronisiert den `TeamsLLM`-Ordner auf Ihren Windows-PC

---

## Schritt-für-Schritt: Installation

### Schritt 1 — Repository bereitstellen

**Option A: Git Clone**

```powershell
git clone https://github.com/B43rli3/Teams_Ai_PyHelper.git
cd Teams_Ai_PyHelper
```

**Struktur prüfen** — der Projektordner muss vorhanden sein:

```powershell
dir teams-ollama-bridge
```

Erwartung: Ordner `teams-ollama-bridge` mit Unterordnern `src`, `scripts`, `tests` usw.

Falls der Ordner **fehlt**, Repository aktualisieren:

```powershell
git pull origin main
```

Danach in den Projektordner wechseln:

```powershell
cd teams-ollama-bridge
```

**Option B: ZIP-Archiv**

1. Repository als ZIP herunterladen und entpacken
2. PowerShell öffnen und in den Projektordner wechseln:

```powershell
cd C:\Pfad\zum\teams-ollama-bridge
```

### Schritt 2 — Python 3.12 prüfen

```powershell
python --version
```

Erwartete Ausgabe: `Python 3.12.x`

Falls Python nicht gefunden wird:

1. [Python 3.12 herunterladen](https://www.python.org/downloads/)
2. Installer starten
3. **„Add python.exe to PATH"** aktivieren
4. **„Install Now"** wählen (keine Admin-Rechte nötig bei Benutzerinstallation)
5. PowerShell **neu öffnen** und erneut `python --version` prüfen

### Schritt 3 — Automatisches Setup ausführen

Im Projektordner `teams-ollama-bridge`:

**Empfohlen auf Firmen-PCs (Arbeitsrechner):** `.cmd`-Dateien — keine PowerShell-Signatur nötig:

```powershell
.\scripts\setup.cmd
```

**Alternativ:** PowerShell-Skripte (auf privaten PCs oder wenn Ausführungsrichtlinie es erlaubt):

```powershell
.\scripts\setup.ps1
```

Das Setup führt automatisch aus:

| Schritt | Aktion |
|---------|--------|
| 1 | Prüft Python 3.12 |
| 2 | Erstellt virtuelle Umgebung unter `.venv\` |
| 3 | Installiert alle Python-Abhängigkeiten |
| 4 | Kopiert `.env.example` → `.env` (falls noch nicht vorhanden) |

**Erwartete Ausgabe am Ende:**

```
=== Naechste Schritte ===
1. Bearbeiten Sie .env und setzen Sie TEAMS_LLM_ROOT auf Ihren OneDrive-Pfad.
2. Konfigurationspruefung: scripts\check.cmd
3. Worker starten: scripts\start.cmd
4. Testen Sie mit einer Input-JSON im Inputordner.
```

### Schritt 4 — PowerShell blockiert? (Firmen-PC / AllSigned)

Auf vielen **Arbeitsrechnern** gilt eine strenge Ausführungsrichtlinie (`AllSigned`). Dann erscheint:

```
Die Datei ... setup.ps1 ist nicht digital signiert. Sie können dieses Skript im aktuellen System nicht ausführen.
```

**Lösung 1 — `.cmd` verwenden (empfohlen, keine Admin-Rechte):**

```powershell
.\scripts\setup.cmd
.\scripts\check.cmd
.\scripts\start.cmd
```

`.cmd`-Dateien unterliegen **nicht** der PowerShell-Ausführungsrichtlinie.

**Lösung 2 — PowerShell einmalig mit Bypass:**

```powershell
.\scripts\run-ps1.cmd setup.ps1
```

**Lösung 3 — Ausführungsrichtlinie nur für Ihr Konto lockern** (falls IT das erlaubt):

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Danach `.\scripts\setup.ps1` erneut ausführen.

> **Hinweis:** Die `.ps1`-Skripte im Repository sind absichtlich **nicht digital signiert**. Eine Signatur würde ein firmeninternes Code-Signing-Zertifikat erfordern. Für den Produktivbetrieb auf Firmen-PCs sind die `.cmd`-Alternativen vorgesehen.

---

## Schritt-für-Schritt: OneDrive-Ordner einrichten

### Schritt 1 — OneDrive-Pfad ermitteln

```powershell
.\.venv\Scripts\python.exe -m teams_ollama_bridge discover-onedrive
```

Beispielausgabe:

```
=== OneDrive-Pfad-Erkennung ===

  C:\Users\Max.Mustermann\OneDrive - MeineFirma GmbH
    -> C:\Users\Max.Mustermann\OneDrive - MeineFirma GmbH\TeamsLLM
```

Notieren Sie den vollständigen Pfad zu `TeamsLLM`.

### Schritt 2 — Ordnerstruktur anlegen

Erstellen Sie unter Ihrem OneDrive-Hauptverzeichnis folgende Struktur (falls noch nicht durch Flow 1/2 vorhanden):

```
TeamsLLM\
├── input\              ← Flow 1 schreibt hierhin
├── output\             ← teams-ollama-bridge schreibt Antworten hierhin
├── processed\
│   └── input\          ← teams-ollama-bridge archiviert verarbeitete Inputs
└── error\
    └── input\          ← teams-ollama-bridge verschiebt fehlerhafte Inputs
```

**PowerShell-Befehl** (Pfad anpassen):

```powershell
$root = "C:\Users\Max.Mustermann\OneDrive - MeineFirma GmbH\TeamsLLM"
New-Item -ItemType Directory -Force -Path "$root\input"
New-Item -ItemType Directory -Force -Path "$root\output"
New-Item -ItemType Directory -Force -Path "$root\processed\input"
New-Item -ItemType Directory -Force -Path "$root\error\input"
```

### Schritt 3 — Synchronisierung prüfen

1. Erstellen Sie eine Testdatei im OneDrive-Ordner (z. B. `TeamsLLM\input\sync-test.txt`)
2. Prüfen Sie, ob die Datei auch **lokal** am gleichen Pfad erscheint
3. Warten Sie ggf., bis das OneDrive-Symbol „Auf dem neuesten Stand" anzeigt

> **Hinweis:** Die Python-Anwendung arbeitet mit dem **lokal synchronisierten** Pfad, nicht mit der OneDrive-Weboberfläche.

---

## Schritt-für-Schritt: Konfiguration (.env)

### Schritt 1 — .env-Datei öffnen

Die Datei `.env` liegt im Projektordner `teams-ollama-bridge\`. Öffnen Sie sie mit einem Texteditor (Notepad, VS Code, Notepad++).

### Schritt 2 — Pflichtwerte setzen

Mindestens diese Zeile **muss** angepasst werden:

```ini
TEAMS_LLM_ROOT=C:\Users\Max.Mustermann\OneDrive - MeineFirma GmbH\TeamsLLM
```

Ersetzen Sie den Pfad durch Ihren tatsächlichen OneDrive-Pfad aus dem Schritt [OneDrive-Pfad ermitteln](#schritt-1--onedrive-pfad-ermitteln).

### Schritt 3 — Mock-Modus bestätigen

Für den Ersttest ohne Ollama:

```ini
PROCESSOR_MODE=mock
```

### Schritt 4 — Vollständige Beispielkonfiguration

```ini
APP_ENV=development
LOG_LEVEL=INFO
LOG_MESSAGE_CONTENT=false

# Pflicht: Ihr lokaler OneDrive-Pfad
TEAMS_LLM_ROOT=C:\Users\Max.Mustermann\OneDrive - MeineFirma GmbH\TeamsLLM

# Leer lassen = automatisch aus TEAMS_LLM_ROOT ableiten
INPUT_DIR=
OUTPUT_DIR=
PROCESSED_INPUT_DIR=
FAILED_INPUT_DIR=

# Ersttest ohne Ollama
PROCESSOR_MODE=mock

POLL_INTERVAL_SECONDS=2
FILE_STABLE_SECONDS=2
MAX_PROCESS_RETRIES=3
RETRY_DELAY_SECONDS=5
STALE_PROCESSING_MINUTES=10

# Ollama-Einstellungen (erst relevant bei PROCESSOR_MODE=ollama)
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:14b
OLLAMA_TIMEOUT_SECONDS=180
OLLAMA_KEEP_ALIVE=10m
OLLAMA_TEMPERATURE=0.2

LLM_SYSTEM_PROMPT=Du bist ein hilfreicher interner Assistent in Microsoft Teams. Antworte präzise, sachlich und auf Deutsch. Gib nur die eigentliche Antwort aus.
LLM_MAX_INPUT_CHARACTERS=12000
LLM_MAX_OUTPUT_CHARACTERS=20000

# Lokale Projektdateien (relativ zum Projektordner)
DATABASE_PATH=data\state.db
LOCK_FILE_PATH=data\worker.lock
LOG_FILE_PATH=logs\teams-ollama-bridge.log
LOG_MAX_BYTES=5000000
LOG_BACKUP_COUNT=5
```

### Schritt 5 — Abgeleitete Pfade verstehen

Wenn `INPUT_DIR`, `OUTPUT_DIR` usw. leer bleiben, leitet die Anwendung sie automatisch ab:

| Umgebungsvariable | Abgeleiteter Pfad |
|-------------------|-------------------|
| `INPUT_DIR` | `<TEAMS_LLM_ROOT>\input` |
| `OUTPUT_DIR` | `<TEAMS_LLM_ROOT>\output` |
| `PROCESSED_INPUT_DIR` | `<TEAMS_LLM_ROOT>\processed\input` |
| `FAILED_INPUT_DIR` | `<TEAMS_LLM_ROOT>\error\input` |

Einzelpfade in `.env` überschreiben die abgeleiteten Werte.

### Schritt 6 — .env speichern

Datei speichern und schließen. Die `.env` wird **nicht** in Git versioniert.

---

## Schritt-für-Schritt: Erste Prüfung

### Schritt 1 — Konfigurationscheck ausführen

```powershell
.\scripts\check.ps1
```

### Schritt 2 — Erwartete Ausgabe prüfen

```
=== teams-ollama-bridge check ===

Processor-Modus: mock
Umgebung: development
  Input: C:\...\TeamsLLM\input [OK]
  Output: C:\...\TeamsLLM\output [OK]
  Archiv: C:\...\TeamsLLM\processed\input [OK]
  Fehler: C:\...\TeamsLLM\error\input [OK]
  Schreibrechte Output: OK
  SQLite: data\state.db [OK]
  Ollama: nicht geprüft (Mock-Modus aktiv)

Zusammenfassung: Alle Prüfungen bestanden.
```

### Schritt 3 — Fehler beheben (falls nötig)

| Meldung | Lösung |
|---------|--------|
| `TEAMS_LLM_ROOT muss gesetzt sein` | `.env` öffnen und `TEAMS_LLM_ROOT` setzen |
| `Input: … [FEHLER]` | Ordner manuell anlegen (siehe [Ordnerstruktur](#schritt-2--ordnerstruktur-anlegen)) |
| `Schreibrechte Output: FEHLER` | Schreibberechtigung im Outputordner prüfen |
| `Konfigurationsfehler` | `.env`-Syntax prüfen, keine Anführungszeichen um Pfade nötig |

---

## Schritt-für-Schritt: Mock-Modus testen

Der Mock-Modus testet den **gesamten Datei-Workflow** ohne installiertes Ollama.

### Schritt 1 — Worker starten

```powershell
.\scripts\start.ps1
```

Erwartete Konsolenausgabe:

```
Starte teams-ollama-bridge Worker...
2026-07-07 14:00:00 [INFO] teams_ollama_bridge.worker: teams-ollama-bridge v1.0.0 gestartet
2026-07-07 14:00:00 [INFO] teams_ollama_bridge.worker: Konfiguration: {...}
2026-07-07 14:00:00 [INFO] teams_ollama_bridge.worker: Instanzsperre erworben: data\worker.lock
2026-07-07 14:00:00 [INFO] teams_ollama_bridge.worker: Worker gestartet (Modus=mock, Intervall=2.0s)
```

Der Worker läuft jetzt dauerhaft. **Fenster offen lassen.**

### Schritt 2 — Test-Inputdatei erstellen

Öffnen Sie ein **zweites** PowerShell-Fenster.

> **Wichtig — richtiger Ordner:** Die JSON-Datei muss in den Unterordner **`input`** gelegt werden, **nicht** direkt in `TeamsLLM`!
>
> | Falsch | Richtig |
> |--------|---------|
> | `...\TeamsLLM\request_test-001.json` | `...\TeamsLLM\input\request_test-001.json` |
>
> Der Worker überwacht ausschließlich den `input`-Ordner (siehe `input_dir` in der Worker-Konfiguration).

Pfade an Ihre Umgebung anpassen und Testdatei erstellen:

```powershell
# Basisordner (entspricht TEAMS_LLM_ROOT in .env)
$teamsRoot = "C:\Users\nuern\OneDrive - Strabag BRVZ GmbH\TeamsLLM"

# WICHTIG: immer den input-Unterordner verwenden!
$inputDir = "$teamsRoot\input"
$outputDir = "$teamsRoot\output"

# Input-Ordner anlegen, falls noch nicht vorhanden
New-Item -ItemType Directory -Force -Path $inputDir | Out-Null

# Für jeden neuen Test eine neue requestId verwenden (z. B. test-002, test-003)
@'
{
  "requestId": "test-002",
  "messageId": "1783415721396",
  "chatId": "19:meeting_test@thread.v2",
  "sender": "Lokaler Test",
  "message": "Dies ist ein Test.",
  "createdAt": "2026-07-07T09:15:22.6932048Z"
}
'@ | Out-File -FilePath "$inputDir\request_test-002.json" -Encoding utf8

# Kurz prüfen, ob die Datei am richtigen Ort liegt
Get-Item "$inputDir\request_test-002.json"
```

> **Häufiger Fehler:** `$inputDir = "...\TeamsLLM"` ohne `\input` — dann passiert im Worker **nichts**.

> **Alternativ:** Datei manuell im Explorer erstellen und in den Ordner `TeamsLLM\input\` kopieren.

### Schritt 3 — Verarbeitung beobachten

Im Worker-Fenster sollten nach wenigen Sekunden Meldungen erscheinen:

```
[INFO] ... Verarbeite Datei: request_test-002.json
[INFO] ... Outputdatei erstellt: C:\...\TeamsLLM\output\response_test-002.json
[INFO] ... Request test-002 erfolgreich verarbeitet (10ms, Modus=mock)
[INFO] ... Datei archiviert: request_test-002.json -> C:\...\TeamsLLM\processed\input\...
```

Wenn diese Meldungen erscheinen, war die Verarbeitung **erfolgreich** — auch wenn die Outputdatei im Explorer kurz danach nicht mehr sichtbar ist (siehe Schritt 4).

### Schritt 4 — Ergebnis prüfen

**Sofort nach der Verarbeitung** (am besten innerhalb weniger Sekunden):

```powershell
$teamsRoot = "C:\Users\nuern\OneDrive - Strabag BRVZ GmbH\TeamsLLM"
Get-ChildItem "$teamsRoot\output\"
Get-Content "$teamsRoot\output\response_test-002.json"
```

Erwarteter Inhalt:

```json
{
  "requestId": "test-002",
  "messageId": "1783415721396",
  "chatId": "19:meeting_test@thread.v2",
  "answer": "PoC erfolgreich. Die lokale Python-Anwendung hat folgende Nachricht verarbeitet: Dies ist ein Test.",
  "status": "completed",
  "processedAt": "2026-07-07T14:05:00Z",
  "model": "mock",
  "processingDurationMs": 10
}
```

#### Output-Ordner ist leer — trotzdem Erfolg?

Wenn der Worker Meldungen wie `Outputdatei erstellt` und `erfolgreich verarbeitet` zeigt, die Datei aber **nirgends** auffindbar ist, unterscheiden Sie zwei Fälle:

##### Fall A — Flow 2 hat die Datei übernommen

Flow 2 verschiebt Response-Dateien **nicht** nach `processed\input\` — dort landen nur **Input**-Dateien (archiviert von Python).

| Ordner | Inhalt |
|--------|--------|
| `processed\input\` | Archivierte **Input**-JSONs (von Python) |
| `processed\` (anderer Unterordner) | Archivierte **Response**-JSONs (von Flow 2, je nach Flow-Konfiguration) |
| `output\` | Aktuelle Response-Dateien (kurzzeitig, bis Flow 2 sie holt) |

Flow 2 kann Response-Dateien an einen **anderen Ort** verschieben als Python Input-Dateien archiviert. Prüfen Sie:

```powershell
# Gesamten TeamsLLM-Baum durchsuchen
Get-ChildItem "C:\Users\nuern\OneDrive - Strabag BRVZ GmbH\TeamsLLM" -Recurse -Filter "response_test-002.json"

# Power Automate: Flow-2-Ausführungsverlauf prüfen (Portal)
# Hat Flow 2 die Datei verarbeitet? Erfolg oder Fehlerzweig?
```

##### Fall B — Lokaler Test mit erfundener chatId

Die Testdatei aus der README enthält eine **erfundene** `chatId` (`19:meeting_test@thread.v2`). Wenn Flow 2 aktiv ist, kann er die Response-Datei zwar erkennen, aber **nicht in Teams posten** — und die Datei in einen **Fehlerzweig** verschieben oder löschen.

**Empfehlung für rein lokalen Mock-Test ohne Flow-2-Eingriff:**

1. Flow 2 vorübergehend **deaktivieren**, oder
2. Sofort nach Worker-Meldung den Output prüfen, oder
3. Echten Teams-Test mit `/ai`-Nachricht durchführen (echte `chatId` von Flow 1)

##### Diagnose-Befehl

```powershell
.\.venv\Scripts\python.exe -m teams_ollama_bridge show-request test-001
```

Zeigt SQLite-Status, erwarteten Output-Pfad und sucht die Datei rekursiv unter `TeamsLLM`.

**Erfolg prüfen, wenn Flow 2 aktiv ist:**

1. **Teams-Chat prüfen** — Mock-Antwort sollte dort erscheinen:
   > PoC erfolgreich. Die lokale Python-Anwendung hat folgende Nachricht verarbeitet: …

2. **Archivierte Inputdatei prüfen** (wird von Python verschoben):

```powershell
Get-ChildItem "C:\Users\nuern\OneDrive - Strabag BRVZ GmbH\TeamsLLM\processed\input\"
```

3. **Response-Archiv von Flow 2 prüfen** — je nach Flow-Konfiguration z. B.:

```powershell
Get-ChildItem "C:\Users\nuern\OneDrive - Strabag BRVZ GmbH\TeamsLLM\processed\" -Recurse
```

4. **Logdatei prüfen** (zeigt den vollständigen Output-Pfad):

```powershell
Get-Content .\logs\teams-ollama-bridge.log -Tail 20
```

**Erfolg ohne Flow 2:** Die Datei `response_<requestId>.json` bleibt im `output`-Ordner liegen, bis Flow 2 oder Sie sie manuell entfernen.

Die Originaldatei sollte **nicht mehr** im `input`-Ordner liegen.

### Schritt 5 — Einmalverarbeitung (Alternative zu dauerhaftem Worker)

Statt `start.ps1` können Sie auch einmalig alle vorhandenen Dateien verarbeiten:

```powershell
.\scripts\run_once.ps1
```

### Schritt 6 — Worker beenden

Im Worker-Fenster: **Strg+C** drücken. Die Anwendung beendet sich sauber und gibt die Instanzsperre frei.

---

## Schritt-für-Schritt: Teams-End-to-End-Test

Dieser Test prüft die vollständige Kette von Teams über Power Automate, OneDrive und zurück.

### Voraussetzungen

- [ ] Installation abgeschlossen (`setup.ps1`)
- [ ] `.env` konfiguriert und `check.ps1` bestanden
- [ ] Flow 1 und Flow 2 sind aktiv
- [ ] OneDrive synchronisiert den `TeamsLLM`-Ordner
- [ ] `PROCESSOR_MODE=mock` in `.env`

### Ablauf

| Nr. | Schritt | Wer | Was passiert |
|-----|---------|-----|--------------|
| 1 | Worker starten | Sie | `.\scripts\start.ps1` |
| 2 | Teams-Nachricht senden | Sie | `/ai Dies ist ein Test.` im konfigurierten Chat |
| 3 | Input-JSON erzeugen | Flow 1 | Schreibt JSON in OneDrive `TeamsLLM\input\` |
| 4 | Datei synchronisieren | OneDrive | JSON erscheint lokal im `input`-Ordner |
| 5 | Datei erkennen | teams-ollama-bridge | Polling erkennt stabile JSON-Datei |
| 6 | Nachricht verarbeiten | teams-ollama-bridge | Mock-Antwort erzeugen |
| 7 | Response schreiben | teams-ollama-bridge | `response_<requestId>.json` in `output\` |
| 8 | Response synchronisieren | OneDrive | Datei erscheint in OneDrive Cloud |
| 9 | Response erkennen | Flow 2 | Trigger auf neue Datei im Outputordner |
| 10 | Antwort posten | Flow 2 | Mock-Antwort erscheint im Teams-Chat |
| 11 | Response aufräumen | Flow 2 | Verschiebt Response nach `processed` |
| 12 | Input archivieren | teams-ollama-bridge | Input nach `processed\input\` |

### Erfolgskriterien

- [ ] Mock-Antwort erscheint im Teams-Chat
- [ ] `response_<requestId>.json` wurde im lokalen `output`-Ordner erstellt
- [ ] `status` in der Response-Datei ist exakt `"completed"`
- [ ] Inputdatei wurde nach `processed\input\` verschoben
- [ ] Keine Fehlermeldung in `logs\teams-ollama-bridge.log`

### Bei Problemen

1. Logdatei prüfen: `logs\teams-ollama-bridge.log`
2. Offene Requests anzeigen: `.\.venv\Scripts\python.exe -m teams_ollama_bridge list-pending`
3. OneDrive-Sync-Status prüfen (grünes Häkchen am `TeamsLLM`-Ordner)
4. `FILE_STABLE_SECONDS` in `.env` auf `5` erhöhen, falls Dateien zu früh gelesen werden

---

## Schritt-für-Schritt: Umstellung auf Ollama

Erst nach erfolgreichem Mock-Test durchführen.

### Schritt 1 — Ollama installieren

1. [https://ollama.com](https://ollama.com) öffnen
2. Windows-Installer herunterladen und ausführen
3. Keine Administratorrechte nötig (Benutzerinstallation)

### Schritt 2 — Modell laden

```powershell
ollama pull qwen3:14b
```

> Modellname muss mit `OLLAMA_MODEL` in `.env` übereinstimmen.

### Schritt 3 — Ollama-API prüfen

Im Browser öffnen: [http://127.0.0.1:11434/api/tags](http://127.0.0.1:11434/api/tags)

Erwartung: JSON-Antwort mit installierten Modellen.

### Schritt 4 — .env anpassen

```ini
PROCESSOR_MODE=ollama
OLLAMA_MODEL=qwen3:14b
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_TIMEOUT_SECONDS=180
```

### Schritt 5 — Konfiguration prüfen

```powershell
.\scripts\check.ps1
```

Erwartete zusätzliche Zeile:

```
  Ollama: http://127.0.0.1:11434 [OK]
  Modell: qwen3:14b
```

### Schritt 6 — Worker starten und testen

```powershell
.\scripts\start.ps1
```

In Teams: `/ai Erkläre mir kurz, was Ollama ist.`

Die Antwort sollte nun vom lokalen Modell stammen (nicht mehr die Mock-Nachricht).

---

## Schritt-für-Schritt: Windows-Autostart

Damit die Anwendung nach jedem PC-Start automatisch läuft — **ohne Administratorrechte**.

### Schritt 1 — Manuellen Betrieb bestätigen

Stellen Sie sicher, dass `.\scripts\start.ps1` zuverlässig funktioniert.

### Schritt 2 — Aufgabenplanung öffnen

1. **Win+R** → `taskschd.msc` → Enter
2. Oder: Startmenü → „Aufgabenplanung" suchen

### Schritt 3 — Neue Aufgabe erstellen

| Registerkarte | Einstellung |
|---------------|-------------|
| **Allgemein** | Name: `teams-ollama-bridge` |
| **Allgemein** | „Nur ausführen, wenn Benutzer angemeldet ist" |
| **Allgemein** | **Nicht** „Mit höchsten Privilegien ausführen" |
| **Trigger** | Neu → „Bei Anmeldung" → OK |
| **Aktionen** | Neu → Programm starten |

**Programm/Skript:**

```
C:\Pfad\zum\teams-ollama-bridge\.venv\Scripts\python.exe
```

**Argumente:**

```
-m teams_ollama_bridge run
```

**Starten in:**

```
C:\Pfad\zum\teams-ollama-bridge
```

### Schritt 4 — Bedingungen setzen

- Optional: Aufgabe nur starten, wenn Netzwerk verfügbar
- Optional: Aufgabe beenden, falls länger als X Stunden läuft → **deaktiviert** lassen

### Schritt 5 — Aufgabe testen

Rechtsklick auf die Aufgabe → **Ausführen**

Prüfen:

```powershell
Get-Content C:\Pfad\zum\teams-ollama-bridge\logs\teams-ollama-bridge.log -Tail 20
```

### Schritt 6 — OneDrive-Verfügbarkeit beachten

Die Aufgabe sollte erst starten, wenn OneDrive den `TeamsLLM`-Ordner synchronisiert hat. Falls nötig:

- Trigger-Verzögerung von 1–2 Minuten nach Anmeldung einstellen
- Oder Bedingung: „Aufgabe erst starten, wenn folgende Netzwerkverbindung verfügbar ist"

---

## Verbindung zu den Power-Automate-Flows

| Flow | Trigger | Aktion |
|------|---------|--------|
| **Flow 1** | Neue Nachricht in Teams-Chat mit Prefix `/ai` | JSON-Datei in `TeamsLLM\input\` erstellen |
| **Flow 2** | Neue Datei in `TeamsLLM\output\` | Bei `status=completed`: Antwort in Teams posten; Datei nach `processed` verschieben; bei `status=failed`: Error-Zweig |

Die Python-Anwendung kennt diese Flows nicht — sie arbeitet nur mit lokalen Dateien.

---

## Dateianhänge aus dem aktuellen Power-Automate-PoC

Neben reinen Textnachrichten kann Flow 1 Dateianhänge in den lokal synchronisierten Inputordner kopieren. Die Python-Anwendung liest diese Dateien **ausschließlich lokal** — es gibt keine Microsoft-Graph-Anbindung und keinen Download aus Teams, SharePoint oder fremden OneDrives.

### Unterstützter aktueller PoC

1. Flow 1 kopiert Dateien nach `TeamsLLM\input\files\`
2. Die Request-JSON enthält `attachments[].localPath` (relativer Pfad unterhalb des Inputordners)
3. Python löst den Pfad sicher auf, extrahiert den Inhalt und übergibt ihn zusammen mit der Teams-Frage an das LLM (oder den Mock-Modus)
4. Nach erfolgreicher Verarbeitung werden Request-JSON und zugehörige Dateien archiviert

### Einschränkung im aktuellen PoC

Im aktuellen PoC funktioniert das zuverlässig nur für Dateien, die **vom Flow-Konto selbst in Teams hochgeladen** wurden. Dateien anderer Kollegen liegen häufig in deren OneDrive und können durch Flow 1 nicht zuverlässig kopiert werden. Dafür ist später Microsoft Graph vorgesehen.

### Unterstützte Dateitypen

| Typ | Endungen | Verarbeitung |
|-----|----------|--------------|
| Text | `.txt`, `.md`, `.csv` | Direktes Einlesen (UTF-8, UTF-8-BOM, Fallback cp1252) |
| PDF | `.pdf` | Textextraktion mit PyMuPDF (kein OCR) |
| Word | `.docx` | Absätze und Tabellen |
| Excel | `.xlsx` | Zellwerte (keine Formelausführung) |
| Bilder | `.png`, `.jpg`, `.jpeg`, `.webp` | Metadaten (Standard) oder optional Ollama-Vision |

### Beispiel-Input-JSON mit Attachments

```json
{
  "requestId": "75d434c8-d025-4afb-a767-9a0b62d18c3b",
  "messageId": "1783415721396",
  "chatId": "19:meeting_...@thread.v2",
  "sender": "Christian Nuernberger",
  "message": "Bitte fasse die angehängte Datei kurz zusammen.",
  "createdAt": "2026-07-07T09:15:22.6932048Z",
  "attachments": [
    {
      "name": "Test-pdf_4.pdf",
      "contentType": "reference",
      "contentUrl": "https://...",
      "localPath": "files/75d434c8-d025-4afb-a767-9a0b62d18c3b_Test-pdf_4.pdf"
    }
  ]
}
```

Wenn Flow 1 eine Datei nicht kopieren konnte:

```json
{
  "name": "Test-pdf_4.pdf",
  "localPath": "",
  "status": "not_copied",
  "error": "Die Datei konnte vom Flow nicht aus OneDrive gelesen werden."
}
```

### Beispiel-OneDrive-Ordnerstruktur

```
TeamsLLM\
  input\
    request_75d434c8-d025-4afb-a767-9a0b62d18c3b.json
    files\
      75d434c8-d025-4afb-a767-9a0b62d18c3b_Test-pdf_4.pdf
  output\
    response_75d434c8-d025-4afb-a767-9a0b62d18c3b.json
  processed\
    input\
      request_75d434c8-d025-4afb-a767-9a0b62d18c3b.json
      files\
        75d434c8-d025-4afb-a767-9a0b62d18c3b_Test-pdf_4.pdf
```

### Beispiel-Testablauf in Teams

1. Datei selbst in Teams hochladen
2. `/ai Bitte fasse die angehängte Datei zusammen` senden
3. Flow 1 kopiert die Datei nach `input\files\` und erzeugt die Request-JSON
4. Python extrahiert den Dateiinhalt und beantwortet die Frage
5. Flow 2 veröffentlicht die Antwort in Teams

### Debug-Befehl

Attachments ohne LLM-Aufruf und ohne Archivierung prüfen:

```powershell
.\.venv\Scripts\python.exe -m teams_ollama_bridge inspect-attachments "C:\Pfad\zu\request_test.json"
```

Der Befehl listet Attachments auf, löst lokale Pfade auf, prüft Dateigröße und Stabilität und führt eine Testextraktion aus.

### Typische Fehler bei Attachments

| Symptom | Ursache | Hinweis |
|---------|---------|---------|
| Request wird wiederholt übersprungen | Datei noch nicht lokal synchronisiert | OneDrive-Sync abwarten; `FILE_STABLE_SECONDS` prüfen |
| `localPath` leer | Flow konnte Datei nicht kopieren | Nur selbst hochgeladene Dateien im aktuellen PoC |
| Datei zu groß | `ATTACHMENTS_MAX_FILE_SIZE_MB` überschritten | Grenzwert in `.env` anpassen oder Datei verkleinern |
| Dateityp nicht erlaubt | Endung nicht in `ATTACHMENTS_ALLOWED_EXTENSIONS` | Erlaubte Endungen prüfen |
| PDF ohne Text | Gescanntes PDF ohne extrahierbaren Text | Kein OCR — anderes Format verwenden |
| Bildbeschreibung fehlgeschlagen | Vision-Modell nicht verfügbar | `IMAGE_PROCESSING_MODE=metadata` oder passendes Modell installieren |
| Kollegen-Datei | Datei liegt in fremdem OneDrive | Aktueller PoC unterstützt das nicht — Graph geplant |

---

## Input- und Outputformat

### Input (von Flow 1)

```json
{
  "requestId": "75d434c8-d025-4afb-a767-9a0b62d18c3b",
  "messageId": "1783415721396",
  "chatId": "19:meeting_ZjE0YTM5N2UtNzUyOC00ODg2LWI2MWQtZGRmYmE3OTRmMjEy@thread.v2",
  "sender": "Christian Nuernberger",
  "message": "Dies ist ein Test.",
  "createdAt": "2026-07-07T09:15:22.6932048Z"
}
```

| Feld | Pflicht | Beschreibung |
|------|---------|--------------|
| `requestId` | Ja | Eindeutige ID (UUID oder z. B. `test-001`) |
| `messageId` | Ja | Teams-Nachrichten-ID |
| `chatId` | Ja | Teams-Chat-ID |
| `message` | Ja | Nachrichtentext (ohne `/ai`-Prefix) |
| `sender` | Nein | Absendername |
| `createdAt` | Nein | ISO-8601-Zeitstempel |
| `attachments` | Nein | Liste angehängter Dateien (siehe [Dateianhänge](#dateianhänge-aus-dem-aktuellen-power-automate-poc)) |

Jedes Attachment-Objekt kann folgende Felder enthalten:

| Feld | Beschreibung |
|------|--------------|
| `name` | Dateiname |
| `contentType` | Optional, z. B. `reference` |
| `contentUrl` | Optional, Teams-Referenz-URL |
| `localPath` | Relativer Pfad unterhalb des Inputordners, z. B. `files/<requestId>_datei.pdf` |
| `status` | Optional, z. B. `not_copied` wenn Flow die Datei nicht kopieren konnte |
| `error` | Optional, Fehlermeldung vom Flow |

### Output (für Flow 2)

Dateiname: `response_<requestId>.json`

```json
{
  "requestId": "75d434c8-d025-4afb-a767-9a0b62d18c3b",
  "messageId": "1783415721396",
  "chatId": "19:meeting_...@thread.v2",
  "answer": "Die vom lokalen Modell erzeugte Antwort.",
  "status": "completed",
  "processedAt": "2026-07-07T09:30:00Z",
  "model": "qwen3:14b",
  "processingDurationMs": 2450
}
```

| Feld | Pflicht | Beschreibung |
|------|---------|--------------|
| `requestId` | Ja | Aus Input übernommen |
| `messageId` | Ja | Aus Input übernommen |
| `chatId` | Ja | Aus Input übernommen |
| `answer` | Ja | Antworttext |
| `status` | Ja | `completed` oder `failed` |
| `processedAt` | Ja | UTC-Zeitstempel (ISO-8601 mit Z) |
| `model` | Nein | Verwendetes Modell |
| `processingDurationMs` | Nein | Verarbeitungsdauer in ms |
| `error` | Nein | Nur bei `status: failed` |
| `attachmentsProcessed` | Nein | Optional: Verarbeitungsstatus je Attachment (Flow 2 ignoriert dieses Feld) |

Beispiel mit `attachmentsProcessed`:

```json
{
  "requestId": "75d434c8-d025-4afb-a767-9a0b62d18c3b",
  "messageId": "1783415721396",
  "chatId": "19:meeting_...@thread.v2",
  "answer": "Kurze Zusammenfassung der PDF …",
  "status": "completed",
  "processedAt": "2026-07-07T09:30:00Z",
  "attachmentsProcessed": [
    {
      "name": "Test-pdf_4.pdf",
      "status": "processed",
      "kind": "document",
      "extractedCharacters": 12345
    }
  ]
}
```

> **Wichtig:** Nur `status: completed` wird von Flow 2 als Teams-Nachricht veröffentlicht.

---

## CLI-Befehle

Alle Befehle über die virtuelle Umgebung:

```powershell
.\.venv\Scripts\python.exe -m teams_ollama_bridge <befehl>
```

| Befehl | Beschreibung | Typischer Anwendungsfall |
|--------|--------------|--------------------------|
| `run` | Dauerhafte Ordnerüberwachung (bis Strg+C) | Produktivbetrieb |
| `once` | Alle ausstehenden Dateien einmal verarbeiten | Manueller Batch-Lauf |
| `check` | Konfiguration, Verzeichnisse, Rechte, SQLite, Ollama prüfen | Nach Einrichtung oder Änderungen |
| `process-file "C:\Pfad\datei.json"` | Einzelne Datei verarbeiten | Debugging |
| `list-pending` | Offene und fehlgeschlagene Requests auflisten | Statusprüfung |
| `show-request <requestId>` | Request-Status und Output-Dateisuche | Wenn Output-Datei fehlt |
| `inspect-attachments "C:\Pfad\request.json"` | Attachments debuggen (ohne LLM/Archivierung) | PoC-Debugging für Dateianhänge |
| `retry-failed` | Fehlgeschlagene Requests zurücksetzen | Nach Fehlerbehebung |
| `discover-onedrive` | OneDrive-Pfade aus Umgebungsvariablen anzeigen | Ersteinrichtung |

**Skript-Shortcuts** (im Projektordner):

| Aufgabe | Firmen-PC (`.cmd`) | PowerShell (`.ps1`) | CLI-Befehl |
|---------|-------------------|---------------------|------------|
| Setup | `.\scripts\setup.cmd` | `.\scripts\setup.ps1` | — |
| Worker starten | `.\scripts\start.cmd` | `.\scripts\start.ps1` | `run` |
| Einmal verarbeiten | `.\scripts\run_once.cmd` | `.\scripts\run_once.ps1` | `once` |
| Konfiguration prüfen | `.\scripts\check.cmd` | `.\scripts\check.ps1` | `check` |
| Tests | `.\scripts\test.cmd` | `.\scripts\test.ps1` | — |

> Auf Arbeitsrechnern mit `AllSigned`-Richtlinie immer die **`.cmd`**-Variante verwenden.

---

## Konfigurationsreferenz

Vollständige Vorlage: `.env.example`

### Pfadkonfiguration

| Variable | Standard | Beschreibung |
|----------|----------|--------------|
| `TEAMS_LLM_ROOT` | — | Basisordner auf lokalem OneDrive |
| `INPUT_DIR` | `<ROOT>\input` | Eingangsordner |
| `OUTPUT_DIR` | `<ROOT>\output` | Ausgangsordner |
| `PROCESSED_INPUT_DIR` | `<ROOT>\processed\input` | Archiv für verarbeitete Inputs |
| `FAILED_INPUT_DIR` | `<ROOT>\error\input` | Archiv für fehlerhafte Inputs |

### Verarbeitung

| Variable | Standard | Beschreibung |
|----------|----------|--------------|
| `PROCESSOR_MODE` | `mock` | `mock` oder `ollama` |
| `POLL_INTERVAL_SECONDS` | `2` | Sekunden zwischen Ordnerabfragen |
| `FILE_STABLE_SECONDS` | `2` | Wartezeit bis Datei als synchronisiert gilt |
| `MAX_PROCESS_RETRIES` | `3` | Maximale Wiederholungen bei temporären Fehlern |
| `RETRY_DELAY_SECONDS` | `5` | Pause zwischen Wiederholungen |
| `STALE_PROCESSING_MINUTES` | `10` | Alte `processing`-Einträge freigeben |

### Ollama

| Variable | Standard | Beschreibung |
|----------|----------|--------------|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama-API-Basis-URL |
| `OLLAMA_MODEL` | `qwen3:14b` | Modellname |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | HTTP-Timeout |
| `OLLAMA_KEEP_ALIVE` | `10m` | Modell im Speicher halten |
| `OLLAMA_TEMPERATURE` | `0.2` | Antwort-Temperatur |
| `LLM_SYSTEM_PROMPT` | (siehe `.env.example`) | System-Prompt für das Modell |
| `LLM_MAX_INPUT_CHARACTERS` | `12000` | Maximale Eingabelänge |
| `LLM_MAX_OUTPUT_CHARACTERS` | `20000` | Maximale Ausgabelänge |

### Attachments und Bilder

| Variable | Standard | Beschreibung |
|----------|----------|--------------|
| `ATTACHMENTS_ENABLED` | `true` | Attachment-Verarbeitung aktivieren |
| `ATTACHMENTS_BASE_DIR` | (leer = `INPUT_DIR`) | Basisordner für `localPath`-Auflösung |
| `ATTACHMENTS_MAX_FILES` | `3` | Maximale Anzahl Attachments pro Request |
| `ATTACHMENTS_MAX_FILE_SIZE_MB` | `20` | Maximale Dateigröße je Attachment |
| `ATTACHMENTS_MAX_EXTRACTED_CHARACTERS_PER_FILE` | `30000` | Max. extrahierte Zeichen je Datei |
| `ATTACHMENTS_MAX_TOTAL_EXTRACTED_CHARACTERS` | `60000` | Max. extrahierte Zeichen gesamt |
| `ATTACHMENTS_ALLOWED_EXTENSIONS` | siehe `.env.example` | Erlaubte Dateiendungen |
| `ATTACHMENTS_INCLUDE_FILENAMES_IN_PROMPT` | `true` | Dateinamen im LLM-Kontext anzeigen |
| `IMAGE_PROCESSING_MODE` | `metadata` | `metadata` oder `ollama_vision` |
| `OLLAMA_VISION_MODEL` | `llava:latest` | Modell für Bildanalyse |
| `OLLAMA_VISION_TIMEOUT_SECONDS` | `180` | Timeout für Vision-Aufruf |
| `IMAGE_MAX_SIZE_MB` | `10` | Maximale Bildgröße |
| `IMAGE_MAX_DIMENSION_PIXELS` | `8000` | Maximale Bildbreite/-höhe |
| `IMAGE_ANALYSIS_PROMPT` | (siehe `.env.example`) | Prompt für Bildbeschreibung |

### Logging und Daten

| Variable | Standard | Beschreibung |
|----------|----------|--------------|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_MESSAGE_CONTENT` | `false` | Nachrichteninhalte loggen (nur Entwicklung) |
| `LOG_FILE_PATH` | `logs\teams-ollama-bridge.log` | Logdatei |
| `LOG_MAX_BYTES` | `5000000` | Maximale Logdateigröße |
| `LOG_BACKUP_COUNT` | `5` | Anzahl rotierender Logdateien |
| `DATABASE_PATH` | `data\state.db` | SQLite-Datenbank |
| `LOCK_FILE_PATH` | `data\worker.lock` | Instanzsperre |

---

## Logging

### Ausgabeziele

- **Konsole** — Live-Meldungen beim Worker-Betrieb
- **Datei** — `logs\teams-ollama-bridge.log` (rotierend, max. 5 MB × 5 Dateien)

### Was standardmäßig geloggt wird

- Programmstart und -ende
- Konfiguration (ohne sensible Werte)
- Gefundene Inputdateien und `requestId`
- Statusänderungen und Verarbeitungsdauer
- Verwendeter Modus und Modell
- Retry-Versuche und Archivierung
- Fehlerklassen
- Attachment-Anzahl, Dateityp, Größe und Extraktionsstatus (ohne vollständige Inhalte)

### Was standardmäßig **nicht** geloggt wird

- Vollständige Teams-Nachrichten
- Vollständige LLM-Antworten
- Vollständige Chat-IDs
- Vollständige extrahierte Dateiinhalte
- Absolute lokale Pfade und `contentUrl`-Werte

Für lokale Entwicklung: `LOG_MESSAGE_CONTENT=true` in `.env` setzen.

### Logdatei lesen

```powershell
Get-Content .\logs\teams-ollama-bridge.log -Tail 50 -Wait
```

---

## SQLite-Status und Archivierung

### Datenbank

Pfad: `data\state.db` (im Projektordner, nicht in OneDrive)

| Status | Bedeutung |
|--------|-----------|
| `discovered` | Datei erkannt, noch nicht verarbeitet |
| `processing` | Verarbeitung läuft |
| `completed` | Erfolgreich abgeschlossen |
| `failed` | Dauerhaft fehlgeschlagen |
| `archived` | Inputdatei archiviert |

### Archivierung

| Ergebnis | Zielordner |
|----------|------------|
| Erfolg | `<TEAMS_LLM_ROOT>\processed\input\` (inkl. `files\` für Attachments) |
| Fehler | `<TEAMS_LLM_ROOT>\error\input\` (inkl. `files\` für Attachments) |

Der **Outputordner** enthält ausschließlich finale `response_*.json`-Dateien. Temporäre oder archivierte Dateien werden dort **nicht** abgelegt.

### Deduplizierung

- Dieselbe `requestId` wird höchstens einmal erfolgreich verarbeitet
- Neustart erzeugt keine zweite Teams-Antwort
- Vorhandene Outputdateien werden nicht überschrieben
- Zwei gleichzeitige Worker-Instanzen werden durch `data\worker.lock` verhindert

---

## Fehlerbehandlung und Neustartverhalten

### Fehlertypen

| Fehler | Verhalten |
|--------|-----------|
| Ungültiges JSON (vorübergehend) | Retry bis `MAX_PROCESS_RETRIES` |
| Ungültiges Schema / leere Nachricht | Sofort `failed`, Input nach `error\input` |
| Ollama nicht erreichbar | Retry, danach `failed` |
| Outputdatei existiert bereits | Überspringen, kein Überschreiben |
| Doppelte `requestId` | Keine erneute Verarbeitung |

### Fehler-Response (Beispiel)

```json
{
  "requestId": "test-001",
  "messageId": "1783415721396",
  "chatId": "19:meeting_...",
  "answer": "",
  "status": "failed",
  "processedAt": "2026-07-07T09:30:00Z",
  "error": "Ollama ist nicht erreichbar."
}
```

Flow 2 veröffentlicht **keine** Teams-Nachricht bei `status: failed`.

### Neustart

Nach einem Neustart des Workers oder PCs:

- Bereits abgeschlossene Requests werden erkannt (SQLite + Outputdatei)
- Verarbeitung wird nicht wiederholt
- Offene Dateien im `input`-Ordner werden normal weiterverarbeitet

---

## Typische Probleme

### OneDrive-Synchronisierung

| Problem | Symptom | Lösung |
|---------|---------|--------|
| Datei noch nicht vollständig | JSON-Decode-Fehler im Log | `FILE_STABLE_SECONDS` auf `5` erhöhen |
| Verzögerte Synchronisierung | Datei erscheint erst nach Minuten | OneDrive-Status prüfen, ggf. „Immer auf diesem Gerät behalten" |
| Sync-Konflikte | Doppelte Dateien mit PC-Namen | Konfliktdateien manuell bereinigen |
| `.tmp`-Dateien | — | Werden automatisch ignoriert |

### Ollama-Verbindung

| Problem | Symptom | Lösung |
|---------|---------|--------|
| Ollama nicht gestartet | `Ollama ist nicht erreichbar` | Ollama-App starten |
| Modell fehlt | HTTP 404 oder leere Antwort | `ollama pull <modellname>` |
| Timeout | `Ollama-Anfrage hat das Zeitlimit überschritten` | `OLLAMA_TIMEOUT_SECONDS` erhöhen |
| Falscher Port | Verbindungsfehler | `OLLAMA_BASE_URL` prüfen |

### Anwendung

| Problem | Symptom | Lösung |
|---------|---------|--------|
| PowerShell blockiert `.ps1` | `nicht digital signiert` / `UnauthorizedAccess` | `.\scripts\setup.cmd` statt `setup.ps1` verwenden |
| Testdatei im falschen Ordner | Worker reagiert nicht | Datei muss in `TeamsLLM\input\` liegen, **nicht** direkt in `TeamsLLM\` |
| Output leer trotz Worker-Erfolg | `Outputdatei erstellt` im Log, Datei nirgends | `show-request <id>` ausführen; Flow-2-Verlauf prüfen; `processed\input` ist nur für Inputs |
| Erneuter Test klappt nicht | Gleiche `requestId` wie zuvor | Neue ID verwenden: `test-002`, `test-003`, … |
| Zweite Instanz | `Eine andere Instanz läuft bereits` | Erste Instanz beenden oder `data\worker.lock` löschen (nur wenn keine Instanz läuft) |
| Keine Verarbeitung | Worker läuft, nichts passiert | `list-pending` prüfen, Logdatei lesen |
| Fehlgeschlagene Requests | Status `failed` in SQLite | Ursache beheben, dann `retry-failed` |

---

## Datenschutz

- Nachrichteninhalte werden standardmäßig **nicht** protokolliert
- Verarbeitung erfolgt **lokal** auf dem Windows-PC
- Keine direkte Cloud-Kommunikation der Python-Anwendung
- Daten fließen nur über OneDrive-Sync und die bestehenden Power-Automate-Flows
- `.env`, `state.db`, Logs und Lockdateien sind in `.gitignore` ausgeschlossen

---

## Tests ausführen

Entwickler und CI:

```powershell
.\scripts\test.ps1
```

Führt nacheinander aus:

1. `ruff check src tests` — Code-Stil und Linting
2. `mypy src/teams_ollama_bridge` — Typprüfung
3. `pytest -v` — 37 automatisierte Tests

Tests benötigen **kein** echtes Ollama und **kein** echtes OneDrive.

---

## Zukünftige Erweiterungen

- Microsoft Graph für Dateianhänge anderer Kollegen
- Gesprächskontext über mehrere Nachrichten hinweg
- RAG (Retrieval-Augmented Generation) mit lokalen Dokumenten
- Mehrere Modelle je nach Anfragetyp oder Chat
- Webhook-Modus als Alternative zum Dateipolling
- Metriken und Dashboard für Verarbeitungsstatistiken

---

## Lizenz

MIT — siehe [LICENSE](LICENSE)
