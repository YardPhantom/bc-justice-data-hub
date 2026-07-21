@echo off
cd /d "%~dp0.."
call tools\setup-data.cmd
if errorlevel 1 exit /b %ERRORLEVEL%
call tools\install-search-helper.cmd
exit /b %ERRORLEVEL%
