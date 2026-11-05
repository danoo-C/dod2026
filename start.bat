@echo off
rem The DOD 2026 stand: double-click this on the notebook (tech-spec 6.3).
rem It only runs windows\start.ps1; a double-clicked .ps1 would open in Notepad.
rem Options go through, e.g.  start.bat -Simulated  or  start.bat -Port COM5
title DOD 2026
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\start.ps1" %*
if errorlevel 1 pause
