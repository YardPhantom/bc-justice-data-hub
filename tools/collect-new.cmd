@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

rem Run the workflow outside cmd.exe's batch control path so Ctrl+C does not
rem display the built-in "Terminate batch job (Y/N)?" prompt.
set "PS_ARGS="
for %%A in (%*) do (
  if /I "%%~A"=="--force" set "PS_ARGS=!PS_ARGS! -Force"
  if /I "%%~A"=="--quick" set "PS_ARGS=!PS_ARGS! -Quick"
  if /I "%%~A"=="--skip" set "PS_ARGS=!PS_ARGS! -SkipBackup"
  if /I "%%~A"=="--wait" set "PS_ARGS=!PS_ARGS! -Wait"
)

start "" /wait /b powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect-new.ps1" %PS_ARGS%
exit /b %ERRORLEVEL%
