@echo off
cd /d "%~dp0"
title Moect Build Launcher
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_all.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%
