@echo off
setlocal
cd /d "%~dp0.."
title BC Justice Data Hub - Local Search API
py tools\search_api.py %*
if errorlevel 1 pause
