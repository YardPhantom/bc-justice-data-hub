@echo off
setlocal
cd /d "%~dp0.."
py tools\system_health.py
if errorlevel 1 exit /b %errorlevel%
echo System health report refreshed: data\system-health.json
pause
