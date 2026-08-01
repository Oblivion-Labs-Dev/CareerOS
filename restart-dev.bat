@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restart-dev.ps1" %*
