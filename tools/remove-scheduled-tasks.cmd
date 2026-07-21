@echo off
setlocal
schtasks /Delete /TN "BCJUS - Daily Court Lists" /F
schtasks /Delete /TN "BCJUS - Weekly Catalogue" /F
schtasks /Delete /TN "BCJUS - Monthly Statistics" /F
schtasks /Delete /TN "BC Justice Data Hub Search Helper" /F
echo.
echo BC Justice Data Hub scheduled tasks removed.
pause
