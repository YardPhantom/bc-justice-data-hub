@echo off
setlocal
cd /d "%~dp0.."
echo Creating pre-collection database backup...
py tools\backup_database.py --keep 1 --reason "scheduled-monthly-statistics"
if errorlevel 1 exit /b 1
if not exist reports\scheduler mkdir reports\scheduler
set "LOG=reports\scheduler\monthly-statistics-latest.log"
echo [%date% %time%] Monthly statistics refresh started.> "%LOG%"
set "RC=0"
py tools\workflow_cache.py snapshot scheduled-statistics-db database\bc_justice.db
py tools\collect_corrections_oversight.py >> "%LOG%" 2>&1 || set "RC=1"
py tools\collect_police_data.py >> "%LOG%" 2>&1 || set "RC=1"
py -u tools\collect_statcan_crime.py --quick >> "%LOG%" 2>&1 || set "RC=1"
py tools\workflow_cache.py changed scheduled-statistics-db database\bc_justice.db
if errorlevel 10 (
  echo Statistics data unchanged; identity, advanced features and exports skipped.>> "%LOG%"
) else (
  py tools\person_identity.py >> "%LOG%" 2>&1 || set "RC=1"
  py -u tools\advanced_features.py >> "%LOG%" 2>&1 || set "RC=1"
  py tools\data_pipeline.py export >> "%LOG%" 2>&1 || set "RC=1"
)
if "%RC%"=="0" (py tools\collection_summary.py success 0 >> "%LOG%" 2>&1) else (py tools\collection_summary.py failed 1 >> "%LOG%" 2>&1)
if "%RC%"=="0" (py tools\collection_alerts.py success >> "%LOG%" 2>&1) else (py tools\collection_alerts.py failed >> "%LOG%" 2>&1)
echo [%date% %time%] Finished with exit code %RC%.>> "%LOG%"
exit /b %RC%
