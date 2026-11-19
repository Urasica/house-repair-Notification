@echo off
call "%~dp0stop-test-deploy.bat" %*
exit /b %ERRORLEVEL%
