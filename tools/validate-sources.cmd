@echo off
cd /d "%~dp0\.."
py tools\validate_sources.py
pause
