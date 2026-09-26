@echo off
REM EA Bot - stop semua service (port dari .env.runtime; default 8787/3789/4321).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-all.ps1" %*
pause
