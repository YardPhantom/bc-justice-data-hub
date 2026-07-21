@echo off
setlocal
cd /d "%~dp0.."
py tools\workflow_cache.py current requirements-install requirements.txt
if errorlevel 10 (
  echo Python requirements are already current; skipping package installation.
) else (
  py -m pip install -r requirements.txt
  if errorlevel 1 exit /b %errorlevel%
  py tools\workflow_cache.py mark requirements-install requirements.txt
)
py tools\data_pipeline.py setup
if errorlevel 1 exit /b %errorlevel%
py tools\workflow_cache.py current setup-export database\bc_justice.db tools\data_pipeline.py
if errorlevel 10 (
  echo Initial exports are already current.
) else (
  py tools\data_pipeline.py export
  if errorlevel 1 exit /b %errorlevel%
  py tools\workflow_cache.py mark setup-export database\bc_justice.db tools\data_pipeline.py
)
pause
