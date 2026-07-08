@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

if not exist ".venv" (
    echo FEHLER: Virtuelle Umgebung nicht gefunden.
    exit /b 1
)

".venv\Scripts\python.exe" -m teams_ollama_bridge once
exit /b %ERRORLEVEL%
