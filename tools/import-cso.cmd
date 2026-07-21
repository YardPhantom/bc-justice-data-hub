@echo off
setlocal
cd /d "%~dp0.."
choice /C YN /N /M "Create a database backup before continuing? Press Y for Yes or N for No: "
if errorlevel 2 goto skip_backup
if errorlevel 1 goto run_backup
:run_backup
py tools\backup_database.py --keep 1 --reason "import-cso"
if errorlevel 1 exit /b 1
goto backup_done
:skip_backup
echo Continuing without creating a database backup.
:backup_done
py tools\data_pipeline.py setup
py tools\workflow_cache.py snapshot import-cso-db database\bc_justice.db
py tools\collect_justice_sources.py cso %*
if errorlevel 1 exit /b 1
py tools\workflow_cache.py changed import-cso-db database\bc_justice.db
if errorlevel 10 (
  echo No new CSO records were imported; skipping export.
) else (
  py tools\data_pipeline.py export
)
pause
