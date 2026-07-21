@echo off
cd /d "%~dp0.."
choice /C YN /N /M "Create a database backup before continuing? Press Y for Yes or N for No: "
if errorlevel 2 goto skip_backup
if errorlevel 1 goto run_backup

:run_backup
echo Creating pre-collection database backup...
py tools\backup_database.py --keep 1 --reason "sync-catalogue"
if errorlevel 1 (
  echo Collection stopped because the database backup failed.
  exit /b 1
)
goto backup_done

:skip_backup
echo Continuing without creating a database backup.

:backup_done
py -u tools\sync_bc_catalogue.py --verbose %*
pause
