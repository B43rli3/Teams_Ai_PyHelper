#Requires -Version 5.1
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    Write-Host "FEHLER: Virtuelle Umgebung nicht gefunden." -ForegroundColor Red
    exit 1
}

Write-Host "=== Ruff ===" -ForegroundColor Cyan
& .\.venv\Scripts\ruff.exe check src tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== mypy ===" -ForegroundColor Cyan
& .\.venv\Scripts\mypy.exe src/teams_ollama_bridge
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== pytest ===" -ForegroundColor Cyan
& .\.venv\Scripts\pytest.exe -v
exit $LASTEXITCODE
