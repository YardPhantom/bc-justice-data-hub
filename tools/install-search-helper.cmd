@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "TASK_NAME=BC Justice Data Hub Search Helper"
for /f "usebackq delims=" %%P in (`py -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE exit /b 1
set "PYTHONW_EXE=%PYTHON_EXE:python.exe=pythonw.exe%"
if not exist "%PYTHONW_EXE%" set "PYTHONW_EXE=%PYTHON_EXE%"
set "TASK_CMD=\"%PYTHONW_EXE%\" \"%CD%\tools\search_supervisor.py\""
schtasks /Create /F /TN "%TASK_NAME%" /SC ONLOGON /RL LIMITED /TR "%TASK_CMD%" >nul 2>&1
if errorlevel 1 (
  echo Automatic search helper could not be installed.
  exit /b 1
)
schtasks /Run /TN "%TASK_NAME%" >nul 2>&1
echo Automatic search helper installed.
exit /b 0
