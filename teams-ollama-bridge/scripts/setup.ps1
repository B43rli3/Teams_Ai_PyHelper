#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host "=== teams-ollama-bridge Setup ===" -ForegroundColor Cyan

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "FEHLER: Python wurde nicht gefunden. Bitte Python 3.12 installieren." -ForegroundColor Red
    exit 1
}

$version = & python --version 2>&1
Write-Host "Gefunden: $version"

if ($version -notmatch "3\.12") {
    Write-Host "WARNUNG: Python 3.12 wird empfohlen. Gefunden: $version" -ForegroundColor Yellow
}

if (-not (Test-Path ".venv")) {
    Write-Host "Erstelle virtuelle Umgebung..."
    & python -m venv .venv
}

Write-Host "Installiere Abhaengigkeiten..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -e ".[dev]"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env aus .env.example erstellt." -ForegroundColor Green
} else {
    Write-Host ".env existiert bereits, wird nicht ueberschrieben."
}

Write-Host ""
Write-Host "=== Naechste Schritte ===" -ForegroundColor Cyan
Write-Host "1. Bearbeiten Sie .env und setzen Sie TEAMS_LLM_ROOT auf Ihren OneDrive-Pfad."
Write-Host "2. Fuehren Sie die Konfigurationspruefung aus: .\scripts\check.cmd  (oder check.ps1)"
Write-Host "3. Starten Sie den Worker im Mock-Modus: .\scripts\start.cmd  (oder start.ps1)"
Write-Host "4. Testen Sie mit einer Input-JSON im Inputordner."
