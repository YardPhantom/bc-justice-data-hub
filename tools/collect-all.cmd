@echo off
setlocal
cd /d "%~dp0.."
choice /C YN /N /M "Create a database backup before continuing? Press Y for Yes or N for No: "
if errorlevel 2 goto skip_backup
if errorlevel 1 goto run_backup

:run_backup
echo Creating pre-collection database backup...
py tools\backup_database.py --keep 1 --reason "collect-all"
if errorlevel 1 (
  echo Collection stopped because the database backup failed.
  exit /b 1
)
goto backup_done

:skip_backup
echo Continuing without creating a database backup.

:backup_done
set RC=0
py tools\sync_bc_catalogue.py --download --import %* || set RC=1
py tools\collect_justice_sources.py all || set RC=1
py tools\collect_historical_judgments.py --official --canlii-api || set RC=1
py tools\collect_justice_sources.py export || set RC=1
py tools\collect_corrections_oversight.py || set RC=1
py tools\collect_police_data.py || set RC=1
py -u tools\collect_statcan_crime.py || set RC=1
echo Exporting dashboard snapshots...
py tools\data_pipeline.py export || set RC=1
py tools\person_identity.py || set RC=1
py tools\advanced_features.py || set RC=1
if "%RC%"=="0" (py tools\collection_summary.py success 0) else (py tools\collection_summary.py failed 1)
if "%RC%"=="0" (py tools\collection_alerts.py success) else (py tools\collection_alerts.py failed)
echo.
if "%RC%"=="0" (echo Collection finished successfully.) else (echo Collection finished with errors. Open the dashboard collection summary.)
pause
exit /b %RC%
