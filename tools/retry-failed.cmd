@echo off
setlocal
cd /d "%~dp0.."
choice /C YN /N /M "Create a database backup before continuing? Press Y for Yes or N for No: "
if errorlevel 2 goto skip_backup
if errorlevel 1 goto run_backup
:run_backup
py tools\backup_database.py --keep 1 --reason "retry-failed"
if errorlevel 1 exit /b 1
goto backup_done
:skip_backup
echo Continuing without creating a database backup.
:backup_done
echo Retrying previously failed or pending imports...
py tools\workflow_cache.py snapshot retry-failed-db database\bc_justice.db
py tools\data_pipeline.py import
if errorlevel 1 exit /b 1
py tools\workflow_cache.py changed retry-failed-db database\bc_justice.db
if errorlevel 10 (
  echo No failed or pending imports changed the database; skipping full report rebuild.
) else (
  py tools\collection_summary.py
  py tools\collection_alerts.py
  py tools\system_health.py
)
echo Retry complete. Open retry-centre.html or collection-alerts.html.
pause
