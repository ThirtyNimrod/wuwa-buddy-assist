@echo off
setlocal
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges for Wuthering Waves input automation...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================================
echo   wuwa-buddy-assist // Elevated Capture Launcher (1600x900)
echo ================================================================
echo Ensure Wuthering Waves (1600x900 Windowed) is open at the Terminal (ESC) menu!
echo Press F12 at any time to abort capture immediately.
echo.

C:\Python314\python.exe -m src.main --scan-from-terminal --include-bag
echo.
pause
