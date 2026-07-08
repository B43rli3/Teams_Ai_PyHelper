@echo off
REM Fuehrt ein PowerShell-Skript mit Process-Bypass aus (fuer Firmen-PCs mit AllSigned).
REM Verwendung: scripts\run-ps1.cmd setup.ps1
setlocal EnableExtensions

if "%~1"=="" (
    echo Verwendung: scripts\run-ps1.cmd ^<skript.ps1^> [argumente...]
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%%~1"

if not exist "%PS_SCRIPT%" (
    echo FEHLER: Skript nicht gefunden: %PS_SCRIPT%
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%
