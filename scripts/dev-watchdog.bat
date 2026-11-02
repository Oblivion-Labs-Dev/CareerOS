@echo off
echo.
echo   Starting CareerOS Dev Watchdog...
echo   This window monitors both Backend API and Web Frontend.
echo   If either crashes, it will be automatically restarted.
echo   Press Ctrl+C to stop everything.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev-watchdog.ps1" %*
