# teams-ollama-bridge

Dateibasierte Brücke zwischen Microsoft Teams (via OneDrive und Power Automate) und einem lokal laufenden Ollama-Modell.

## Zweck und Architektur

```
Microsoft Teams
    ↓
Power Automate Flow 1
    ↓
OneDrive for Business
    ↓
lokal synchronisierter Inputordner
    ↓
teams-ollama-bridge
    ↓
Ollama oder Mock-Prozessor
    ↓
lokal synchronisierter Outputordner
    ↓
OneDrive for Business
    ↓
Power Automate Flow 2
    ↓
Microsoft Teams
```

Die Python-Anwendung kommuniziert **nicht** direkt mit Microsoft Teams, Microsoft Graph oder Power Automate. Sie arbeitet ausschließlich dateibasiert über lokale, von OneDrive synchronisierte Ordner.

## Verbindung zu den Power-Automate-Flows

| Flow | Rolle |
|------|-------|
| **Flow 1** | Erzeugt bei `/ai`-Nachrichten im Teams-Chat eine JSON-Datei im OneDrive-Inputordner |
| **Flow 2** | Reagiert auf neue `response_*.json` im Outputordner und veröffentlicht bei `status: completed` die Antwort in Teams |

## Inputformat

```json
{
  "requestId": "75d434c8-d025-4afb-a767-9a0b62d18c3b",
  "messageId": "1783415721396",
  "chatId": "19:meeting_...@thread.v2",
  "sender": "Christian Nuernberger",
  "message": "Dies ist ein Test.",
  "createdAt": "2026-07-07T09:15:22.6932048Z"
}
```

Pflichtfelder: `requestId`, `messageId`, `chatId`, `message`

## Outputformat

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

Nur Dateien mit `"status": "completed"` werden von Flow 2 als Teams-Nachricht veröffentlicht.

## Voraussetzungen

- Windows 11
- Python 3.12
- OneDrive for Business (Synchronisierung der Input-/Outputordner)
- Keine Administratorrechte erforderlich
- Ollama optional (Mock-Modus für Tests ohne Ollama)

## Installation

```powershell
cd teams-ollama-bridge
.\scripts\setup.ps1
```

Das Skript erstellt eine virtuelle Umgebung, installiert Abhängigkeiten und kopiert `.env.example` nach `.env`.

## Konfiguration

Bearbeiten Sie `.env` und setzen Sie mindestens `TEAMS_LLM_ROOT`:

```
TEAMS_LLM_ROOT=C:\Users\<BENUTZER>\OneDrive - <ORGANISATION>\TeamsLLM
PROCESSOR_MODE=mock
```

Pfade werden automatisch abgeleitet:

| Variable | Standard |
|----------|----------|
| `INPUT_DIR` | `<TEAMS_LLM_ROOT>\input` |
| `OUTPUT_DIR` | `<TEAMS_LLM_ROOT>\output` |
| `PROCESSED_INPUT_DIR` | `<TEAMS_LLM_ROOT>\processed\input` |
| `FAILED_INPUT_DIR` | `<TEAMS_LLM_ROOT>\error\input` |

OneDrive-Pfade ermitteln:

```powershell
.\.venv\Scripts\python.exe -m teams_ollama_bridge discover-onedrive
```

## Mock-Modus (ohne Ollama)

Standardmäßig ist `PROCESSOR_MODE=mock` gesetzt. Die Anwendung erzeugt Antworten wie:

> PoC erfolgreich. Die lokale Python-Anwendung hat folgende Nachricht verarbeitet: \<Nachricht\>

## Vollständiger Teams-End-to-End-Test

1. `.env` erstellen (via `setup.ps1`)
2. `PROCESSOR_MODE=mock` setzen
3. Anwendung starten: `.\scripts\start.ps1`
4. In Teams schreiben: `/ai Dies ist ein Test.`
5. Flow 1 erzeugt eine JSON-Datei im OneDrive-Inputordner
6. OneDrive synchronisiert die Datei lokal
7. Python erkennt und verarbeitet die Datei
8. Python erzeugt `response_<requestId>.json` im Outputordner
9. OneDrive synchronisiert die Outputdatei
10. Flow 2 erkennt die Datei
11. Flow 2 veröffentlicht die Mock-Antwort im Teams-Chat
12. Flow 2 verschiebt die Response-Datei nach `processed`
13. Python archiviert die Inputdatei unter `processed/input`

## Umstellung auf Ollama

1. [Ollama installieren](https://ollama.com)
2. Modell laden: `ollama pull qwen3:14b`
3. Ollama starten (läuft standardmäßig als Dienst)
4. API prüfen: `http://127.0.0.1:11434/api/tags`
5. In `.env` ändern: `PROCESSOR_MODE=ollama`
6. Konfiguration prüfen: `.\scripts\check.ps1`
7. Worker starten: `.\scripts\start.ps1`

## CLI-Befehle

| Befehl | Beschreibung |
|--------|--------------|
| `run` | Dauerhafte Ordnerüberwachung |
| `once` | Alle ausstehenden Dateien einmal verarbeiten |
| `check` | Konfiguration und Umgebung prüfen |
| `process-file <pfad>` | Einzelne Datei verarbeiten |
| `list-pending` | Offene/fehlgeschlagene Requests auflisten |
| `retry-failed` | Fehlgeschlagene Requests erneut versuchen |
| `discover-onedrive` | Mögliche OneDrive-Pfade anzeigen |

## Logging

- Konsole und rotierende Datei unter `logs/teams-ollama-bridge.log`
- Standardmäßig werden keine vollständigen Nachrichteninhalte protokolliert
- `LOG_MESSAGE_CONTENT=true` für lokale Entwicklung

## SQLite-Status

Datenbank: `data/state.db`

| Status | Bedeutung |
|--------|-----------|
| `discovered` | Datei erkannt |
| `processing` | In Bearbeitung |
| `completed` | Erfolgreich verarbeitet |
| `failed` | Fehlgeschlagen |
| `archived` | Input archiviert |

## Archivierung

- Erfolg: Input nach `<TEAMS_LLM_ROOT>\processed\input`
- Fehler: Input nach `<TEAMS_LLM_ROOT>\error\input`
- Outputordner enthält nur finale `response_*.json`-Dateien

## Fehlerbehandlung

Bei temporären Fehlern bleibt die Datei im Inputordner. Nach `MAX_PROCESS_RETRIES` wird eine `status: failed`-Response erzeugt und die Inputdatei in den Fehlerordner verschoben.

## Neustartverhalten

- Bereits abgeschlossene Requests werden nicht erneut verarbeitet
- Vorhandene Outputdateien werden nicht überschrieben
- SQLite verhindert doppelte Verarbeitung

## Vermeidung doppelter Antworten

- `requestId` als Primärschlüssel in SQLite
- Atomares `processing`-Flag
- Exklusives Erstellen von Outputdateien (`O_CREAT | O_EXCL`)
- Instanzsperre via `data/worker.lock`

## Windows-Autostart (ohne Admin)

1. Anwendung manuell testen mit `.\scripts\start.ps1`
2. Windows-Aufgabenplanung öffnen
3. Neue Aufgabe erstellen:
   - Trigger: **Bei Anmeldung**
   - Aktion: `C:\Pfad\zum\teams-ollama-bridge\.venv\Scripts\python.exe -m teams_ollama_bridge run`
   - Arbeitsverzeichnis: Projektordner
   - **Nicht** „Mit höchsten Privilegien ausführen"
   - Bedingung: OneDrive-Verzeichnis verfügbar
4. Optional: Ausgabe in Logdatei umleiten

## Tests ausführen

```powershell
.\scripts\test.ps1
```

Oder manuell:

```bash
ruff check src tests
mypy src/teams_ollama_bridge
pytest -v
```

## Typische OneDrive-Probleme

- Dateien erscheinen verzögert → `FILE_STABLE_SECONDS` erhöhen
- Temporäre `.tmp`-Dateien → werden automatisch ignoriert
- Sync-Konflikte → eindeutige Dateinamen verwenden

## Typische Ollama-Fehler

| Fehler | Lösung |
|--------|--------|
| Nicht erreichbar | Ollama-Dienst starten |
| Timeout | `OLLAMA_TIMEOUT_SECONDS` erhöhen |
| Modell fehlt | `ollama pull <modell>` |

## Datenschutz

- Nachrichteninhalte werden standardmäßig nicht geloggt
- Keine Cloud-Übertragung außer OneDrive-Sync und Teams (via Flows)
- Lokale Verarbeitung auf dem Windows-PC

## Zukünftige Erweiterungen

- Gesprächskontext über mehrere Nachrichten
- RAG mit lokalen Dokumenten
- Mehrere Modelle je nach Anfragetyp
- Webhook-Modus als Alternative zum Dateipolling

## Lizenz

MIT
