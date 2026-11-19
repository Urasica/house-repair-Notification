@echo off
call "%~dp0test-deploy.bat" %*
exit /b %ERRORLEVEL%
