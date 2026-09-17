@echo off
REM EA Bot - single button start semua service.
REM Double-click file ini, atau jalankan: start.bat
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-all.ps1" %*
pause
