@echo off
setlocal
cd /d "%~dp0.."
set "FORCE_RUN=0"
for %%A in (%*) do if /I "%%~A"=="--force" set "FORCE_RUN=1"
if "%FORCE_RUN%"=="0" (
  py tools\workflow_cache.py current person-identity database\bc_justice.db tools\person_identity.py tools\advanced_features.py
  if errorlevel 10 (
    echo Person identity data is already current; skipping rebuild.
    exit /b 0
  )
)
python tools\data_pipeline.py export
if errorlevel 1 exit /b %errorlevel%
python tools\person_identity.py
if errorlevel 1 exit /b %errorlevel%
python -u tools\advanced_features.py --profile identity
if errorlevel 1 exit /b %errorlevel%
py tools\workflow_cache.py mark person-identity database\bc_justice.db tools\person_identity.py tools\advanced_features.py
echo Person identity workflow complete.
endlocal
