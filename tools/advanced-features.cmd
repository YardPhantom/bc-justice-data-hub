@echo off
setlocal
cd /d "%~dp0.."
set "FORCE_RUN=0"
set "RUN_ARGS=%*"
for %%A in (%*) do if /I "%%~A"=="--force" set "FORCE_RUN=1"
set "RUN_ARGS=%RUN_ARGS:--force=%"
if "%FORCE_RUN%"=="0" (
  py tools\workflow_cache.py current advanced-features database\bc_justice.db tools\advanced_features.py
  if errorlevel 10 (
    echo Advanced features are already current; skipping rebuild.
    exit /b 0
  )
)
py -u tools\advanced_features.py %RUN_ARGS%
if errorlevel 1 exit /b %errorlevel%
py tools\workflow_cache.py mark advanced-features database\bc_justice.db tools\advanced_features.py
