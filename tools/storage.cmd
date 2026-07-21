@echo off
setlocal
cd /d "%~dp0\.."
if /i "%~1"=="cleanup" (
  echo Storage cleanup is now included in tools\maintenance.cmd.
  call tools\maintenance.cmd
  exit /b %ERRORLEVEL%
)
py tools\storage_manager.py report
if errorlevel 1 python tools\storage_manager.py report
pause
