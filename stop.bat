@echo off
REM EA Bot - stop semua service (port 8000/3001/3200).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-all.ps1" %*
pause
