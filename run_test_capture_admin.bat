@echo off
setlocal
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges for Wuthering Waves expanded test capture...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================================
echo   wuwa-buddy-assist // Expanded End-to-End Test (1600x900)
echo   Scope: Terminal -> 1 Resonator -> 2x ESC -> B -> 6 Bag Echoes
echo   Plus:  Auto-generates captures/calibration/01..07_*.png
echo ================================================================
echo Ensure Wuthering Waves (1600x900 Windowed) is open at the Terminal (ESC) menu!
echo Press F12 at any time to abort immediately.
echo.

C:\Python314\python.exe -m src.main --scan-from-terminal --roster-count 1 --include-bag --max-bag-echos 6 --test-run
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Test capture exited with code %errorlevel%.
    pause
    exit /b %errorlevel%
)

echo.
echo Generating per-menu calibration overlays (including 07_backpack.png)...
C:\Python314\python.exe -m src.main --calibrate-menus
echo.
pause
