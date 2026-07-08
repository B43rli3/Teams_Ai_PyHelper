@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

if not exist ".venv" (
    echo FEHLER: Virtuelle Umgebung nicht gefunden.
    exit /b 1
)

echo === Ruff ===
".venv\Scripts\ruff.exe" check src tests
if errorlevel 1 exit /b 1

echo === mypy ===
".venv\Scripts\mypy.exe" src/teams_ollama_bridge
if errorlevel 1 exit /b 1

echo === pytest ===
".venv\Scripts\pytest.exe" -v
exit /b %ERRORLEVEL%
