#Requires -Version 5.1
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    Write-Host "FEHLER: Virtuelle Umgebung nicht gefunden. Fuehren Sie zuerst .\scripts\setup.ps1 aus." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host "FEHLER: .env nicht gefunden. Kopieren Sie .env.example nach .env." -ForegroundColor Red
    exit 1
}

Write-Host "Starte teams-ollama-bridge Worker..."
& .\.venv\Scripts\python.exe -m teams_ollama_bridge run
