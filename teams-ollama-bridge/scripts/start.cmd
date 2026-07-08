@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

if not exist ".venv" (
    echo FEHLER: Virtuelle Umgebung nicht gefunden. Fuehren Sie zuerst scripts\setup.cmd aus.
    exit /b 1
)

if not exist ".env" (
    echo FEHLER: .env nicht gefunden. Kopieren Sie .env.example nach .env.
    exit /b 1
)

echo Starte teams-ollama-bridge Worker...
".venv\Scripts\python.exe" -m teams_ollama_bridge run
exit /b %ERRORLEVEL%
