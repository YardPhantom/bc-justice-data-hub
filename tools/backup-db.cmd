@echo off
setlocal
cd /d "%~dp0.."
py tools\backup_database.py %*
if errorlevel 1 exit /b %errorlevel%
