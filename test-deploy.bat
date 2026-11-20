@echo off
setlocal
rem Usage: test-deploy.bat [-Monitoring] [-OpenTunnel]
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\test-deploy.ps1" -Action Start %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
