@echo off
setlocal
cd /d "%~dp0.."
python tests\data_retention_tests.py
endlocal
