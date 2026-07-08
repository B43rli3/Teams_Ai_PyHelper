@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

echo === teams-ollama-bridge Setup ===

where python >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python wurde nicht gefunden. Bitte Python 3.12 installieren.
    exit /b 1
)

python --version
if errorlevel 1 exit /b 1

if not exist ".venv" (
    echo Erstelle virtuelle Umgebung...
    python -m venv .venv
    if errorlevel 1 exit /b 1
)

echo Installiere Abhaengigkeiten...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

".venv\Scripts\pip.exe" install -e ".[dev]"
if errorlevel 1 exit /b 1

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo .env aus .env.example erstellt.
) else (
    echo .env existiert bereits, wird nicht ueberschrieben.
)

echo.
echo === Naechste Schritte ===
echo 1. Bearbeiten Sie .env und setzen Sie TEAMS_LLM_ROOT auf Ihren OneDrive-Pfad.
echo 2. Konfigurationspruefung: scripts\check.cmd
echo 3. Worker starten: scripts\start.cmd
echo 4. Testen Sie mit einer Input-JSON im Inputordner.

endlocal
