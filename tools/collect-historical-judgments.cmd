@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

set "STARTYEAR=%~1"
set "ENDYEAR=%~2"
if not defined STARTYEAR set "STARTYEAR=1990"
if not defined ENDYEAR set "ENDYEAR=%DATE:~-4%"

echo Historical judgment backfill: %STARTYEAR% to %ENDYEAR%
echo This collector keeps all outcomes in review status until manually verified.
echo.
py tools\workflow_cache.py snapshot historical-judgments-db database\bc_justice.db
python tools\collect_historical_judgments.py --start-year %STARTYEAR% --end-year %ENDYEAR% --official --canlii-api
if errorlevel 1 exit /b %ERRORLEVEL%
py tools\workflow_cache.py changed historical-judgments-db database\bc_justice.db
if errorlevel 10 (
  echo No new historical judgments were imported; skipping identity and export rebuilds.
  exit /b 0
)
python tools\collect_justice_sources.py export
if errorlevel 1 exit /b %ERRORLEVEL%
python tools\person_identity.py
if errorlevel 1 exit /b %ERRORLEVEL%
python tools\data_pipeline.py export
exit /b %ERRORLEVEL%
