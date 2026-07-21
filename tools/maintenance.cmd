@echo off
setlocal
cd /d "%~dp0.."

echo BC Justice maintenance starting...
echo.

set "PYTHON_CMD=py"
where py >nul 2>nul
if errorlevel 1 set "PYTHON_CMD=python"

if /i "%~1"=="full" (
  echo Running full maintenance. Database compaction may take a long time.
  %PYTHON_CMD% -u tools\maintenance.py --full
) else if /i "%~1"=="--full" (
  echo Running full maintenance. Database compaction may take a long time.
  %PYTHON_CMD% -u tools\maintenance.py --full
) else (
  %PYTHON_CMD% -u tools\maintenance.py
)

set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto failed

echo.
echo Maintenance and storage retention cleanup complete.
exit /b 0

:failed
echo.
echo Maintenance failed with exit code %RC%.
exit /b %RC%
