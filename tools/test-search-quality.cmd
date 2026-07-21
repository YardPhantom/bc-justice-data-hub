@echo off
setlocal
cd /d "%~dp0.."
python tests\search_quality_tests.py
exit /b %errorlevel%
