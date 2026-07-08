@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

if not exist ".venv" (
    echo FEHLER: Virtuelle Umgebung nicht gefunden. Fuehren Sie zuerst scripts\setup.cmd aus.
    exit /b 1
)

".venv\Scripts\python.exe" -m teams_ollama_bridge check
exit /b %ERRORLEVEL%
