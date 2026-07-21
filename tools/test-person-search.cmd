@echo off
setlocal
cd /d "%~dp0.."
python tests\person_search_tests.py
if errorlevel 1 exit /b %errorlevel%
python tests\repeat_offender_tests.py
endlocal
