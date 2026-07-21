@echo off
setlocal
set "ACTION_FILE=%~1"
cd /d "%~dp0.."
py tools\workflow_cache.py snapshot apply-reviews-db database\bc_justice.db
if "%ACTION_FILE%"=="" (
  py tools\apply_review_actions.py
) else (
  py tools\apply_review_actions.py "%ACTION_FILE%"
)
if errorlevel 1 pause & exit /b 1
py tools\workflow_cache.py changed apply-reviews-db database\bc_justice.db
if errorlevel 10 (
  echo No review changes were applied; skipping export and feature rebuilds.
  pause
  exit /b 0
)
py tools\collect_justice_sources.py export
py tools\advanced_features.py
py tools\data_pipeline.py export
pause
