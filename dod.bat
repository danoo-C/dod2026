@echo off
rem The dev wrapper on Windows: the same commands as ./dod in WSL.
rem   dod --help     every command, one line each
rem   dod --manual   how to use each command
rem It only runs windows\dod.ps1 (a .ps1 can't be run by name from cmd).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\dod.ps1" %*
exit /b %ERRORLEVEL%
