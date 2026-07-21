@echo off
setlocal
cd /d "%~dp0.."
choice /C YN /N /M "Create a database backup before continuing? Press Y for Yes or N for No: "
if errorlevel 2 goto skip_backup
if errorlevel 1 goto run_backup
:run_backup
echo Creating pre-collection database backup...
py tools\backup_database.py --keep 1 --reason "collect-justice"
if errorlevel 1 exit /b 1
goto backup_done
:skip_backup
echo Continuing without creating a database backup.
:backup_done
py -c "import certifi" >nul 2>&1
if errorlevel 1 (
  echo Installing trusted certificate bundle for verified HTTPS...
  py -m pip install certifi
  if errorlevel 1 exit /b 1
)
py tools\data_pipeline.py setup
if errorlevel 1 exit /b 1
py tools\workflow_cache.py snapshot collect-justice-db database\bc_justice.db
py -u tools\collect_justice_sources.py all %*
if errorlevel 1 exit /b 1
py tools\workflow_cache.py changed collect-justice-db database\bc_justice.db
if errorlevel 10 (
  echo Justice data is unchanged; skipping dashboard export.
) else (
  py tools\data_pipeline.py export
)
pause
