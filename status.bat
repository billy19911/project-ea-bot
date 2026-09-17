@echo off
REM EA Bot - cek status service.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\status.ps1" %*
pause
