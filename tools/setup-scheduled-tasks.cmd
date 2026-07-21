@echo off
setlocal EnableExtensions
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

echo Creating BC Justice Data Hub scheduled tasks...

schtasks /Create /TN "BCJUS - Daily Court Lists" /TR "\"%ROOT%\tools\scheduled-daily-courts.cmd\"" /SC DAILY /ST 06:30 /RL LIMITED /F
if errorlevel 1 goto :failed

schtasks /Create /TN "BCJUS - Weekly Catalogue" /TR "\"%ROOT%\tools\scheduled-weekly-catalogue.cmd\"" /SC WEEKLY /D SUN /ST 07:00 /RL LIMITED /F
if errorlevel 1 goto :failed

schtasks /Create /TN "BCJUS - Monthly Statistics" /TR "\"%ROOT%\tools\scheduled-monthly-statistics.cmd\"" /SC MONTHLY /D 1 /ST 08:00 /RL LIMITED /F
if errorlevel 1 goto :failed

echo.
echo Scheduled tasks created:
echo  Daily court lists: every day at 6:30 AM
echo  Catalogue update: Sundays at 7:00 AM
echo  Statistics refresh: first day of each month at 8:00 AM
echo.
echo Logs will be written to reports\scheduler.
pause
exit /b 0

:failed
echo.
echo A task could not be created. Run this file as Administrator if Task Scheduler denied access.
pause
exit /b 1
