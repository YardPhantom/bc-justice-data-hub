@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title BC Justice Data Hub Command Menu

:menu
cls
echo ============================================================
echo              BC Justice Data Hub Command Menu
echo ============================================================
echo Run location: %CD%
echo.
echo  1. Setup project and database
echo  2. Collect new or changed data
echo  3. Collect all data - full refresh
echo  4. Run maintenance and storage cleanup
echo  5. Collect justice sources
echo  6. Sync BC Data Catalogue metadata
echo  7. Sync Catalogue and download resources
echo  8. Import downloaded and local data
echo  9. Queue local files for indexing
echo 10. Import CSO case-index CSV
echo 11. Retry failed imports and stale resources
echo 12. Apply review-actions.csv
echo 13. Apply note-actions.csv
echo 14. Run advanced features and exports
echo 15. Run system health check
echo 16. Validate official source links
echo 17. Generate storage report
echo 18. Setup or migrate data database
echo 19. Setup Windows scheduled tasks
echo 20. Run scheduled tasks now
echo 21. Remove Windows scheduled tasks
echo 22. Run daily court-list scheduled target
echo 23. Run weekly Catalogue scheduled target
echo 24. Run monthly statistics scheduled target
echo 25. Create a database backup - keep newest only
echo 26. Rebuild person identity and repeat-offender data
echo 27. Backfill historical BC judgments and rebuild identities
echo 28. Run person-search regression tests
echo 29. Run search-quality regression tests
echo 30. Run data-retention regression tests
echo 31. Prepare CSO charge lookup queue - maximum 250
echo 32. Import and link saved CSO charge records
echo 33. Prepare CSO disposition refresh queue - maximum 250
echo 34. Install and start automatic Search API helper
echo 35. Start local Search API in a new console
echo 36. Start Search API supervisor in a new console
echo 37. Refresh the large Statistics Canada crime table
echo 38. Rebuild dashboard and search exports only
echo 39. Run full maintenance and SQLite compaction
echo  0. Exit
echo.
set "choice="
set /p "choice=Enter command number: "

if "%choice%"=="0" exit /b 0
if "%choice%"=="1" call tools\setup.cmd
if "%choice%"=="2" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File tools\collect-new.ps1
if "%choice%"=="3" call tools\collect-all.cmd
if "%choice%"=="4" call tools\maintenance.cmd
if "%choice%"=="5" call tools\collect-justice.cmd
if "%choice%"=="6" call tools\sync-catalogue.cmd
if "%choice%"=="7" call tools\sync-catalogue.cmd --download
if "%choice%"=="8" call tools\import-data.cmd
if "%choice%"=="9" call tools\queue-files.cmd
if "%choice%"=="10" call tools\import-cso.cmd
if "%choice%"=="11" call tools\retry-failed.cmd
if "%choice%"=="12" call tools\apply-reviews.cmd review-actions.csv
if "%choice%"=="13" call tools\notes.cmd apply note-actions.csv
if "%choice%"=="14" call tools\advanced-features.cmd
if "%choice%"=="15" call tools\system-health.cmd
if "%choice%"=="16" call tools\validate-sources.cmd
if "%choice%"=="17" call tools\storage.cmd report
if "%choice%"=="18" call tools\setup-data.cmd
if "%choice%"=="19" call tools\setup-scheduled-tasks.cmd
if "%choice%"=="20" call tools\run-scheduled-tasks-now.cmd
if "%choice%"=="21" call tools\remove-scheduled-tasks.cmd
if "%choice%"=="22" call tools\scheduled-daily-courts.cmd
if "%choice%"=="23" call tools\scheduled-weekly-catalogue.cmd
if "%choice%"=="24" call tools\scheduled-monthly-statistics.cmd
if "%choice%"=="25" call tools\backup-db.cmd --keep 1 --reason "manual command menu"
if "%choice%"=="26" call tools\person-identity.cmd
if "%choice%"=="27" call tools\collect-historical-judgments.cmd
if "%choice%"=="28" call tools\test-person-search.cmd
if "%choice%"=="29" call tools\test-search-quality.cmd
if "%choice%"=="30" call tools\test-data-retention.cmd
if "%choice%"=="31" py -u tools\cso_charge_pipeline.py queue --cap 250
if "%choice%"=="32" py -u tools\cso_charge_pipeline.py import
if "%choice%"=="32" py -u tools\cso_charge_pipeline.py link
if "%choice%"=="33" py -u tools\cso_charge_pipeline.py queue --cap 250 --refresh-dispositions
if "%choice%"=="34" call tools\install-search-helper.cmd
if "%choice%"=="35" start "BCJUS Search API" py -u tools\search_api.py
if "%choice%"=="36" start "BCJUS Search Supervisor" py -u tools\search_supervisor.py
if "%choice%"=="37" call tools\backup-db.cmd --keep 1 --reason "large-statcan-refresh" && py -u tools\collect_statcan_crime.py --refresh-large
if "%choice%"=="38" py -u tools\data_pipeline.py export
if "%choice%"=="39" call tools\maintenance.cmd --full

for %%N in (0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39) do if "%choice%"=="%%N" goto completed
echo.
echo Invalid number: %choice%
pause
goto menu

:completed
echo.
echo ------------------------------------------------------------
echo Command finished with exit code %ERRORLEVEL%.
echo ------------------------------------------------------------
pause
goto menu
