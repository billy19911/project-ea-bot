@echo off
REM EA Bot - mint dev token dashboard & copy ke clipboard.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\get-token.ps1" %*
pause
