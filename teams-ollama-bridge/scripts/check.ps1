#Requires -Version 5.1
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    Write-Host "FEHLER: Virtuelle Umgebung nicht gefunden." -ForegroundColor Red
    exit 1
}

& .\.venv\Scripts\python.exe -m teams_ollama_bridge check
