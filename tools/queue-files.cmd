@echo off
cd /d "%~dp0.."
if "%~1"=="" (
  echo Drag one or more PDF, HTML, CSV, JSON or Excel files onto this command file.
  pause
  exit /b 1
)
py tools\data_pipeline.py queue %*
pause
