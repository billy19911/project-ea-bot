@echo off
REM EA Bot - restart semua service dengan SATU KLIK.
REM Double-click file ini untuk stop + start ulang semua service.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restart-all.ps1" %*
pause
