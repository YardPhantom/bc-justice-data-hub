@echo off
setlocal
cd /d "%~dp0.."
echo Creating pre-collection database backup...
py tools\backup_database.py --keep 1 --reason "scheduled-daily-courts"
if errorlevel 1 exit /b 1
if not exist reports\scheduler mkdir reports\scheduler
set "LOG=reports\scheduler\daily-courts-latest.log"
echo [%date% %time%] Daily court-list collection started.> "%LOG%"
py tools\workflow_cache.py snapshot scheduled-daily-db database\bc_justice.db
py tools\collect_justice_sources.py daily >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
py tools\workflow_cache.py changed scheduled-daily-db database\bc_justice.db
if errorlevel 10 (
  echo Court-list data unchanged; export skipped.>> "%LOG%"
) else (
  py tools\data_pipeline.py export >> "%LOG%" 2>&1
  if errorlevel 1 set "RC=1"
)
if "%RC%"=="0" (py tools\collection_summary.py success 0 >> "%LOG%" 2>&1) else (py tools\collection_summary.py failed 1 >> "%LOG%" 2>&1)
if "%RC%"=="0" (py tools\collection_alerts.py success >> "%LOG%" 2>&1) else (py tools\collection_alerts.py failed >> "%LOG%" 2>&1)
echo [%date% %time%] Finished with exit code %RC%.>> "%LOG%"
exit /b %RC%
