@echo off
setlocal
schtasks /Run /TN "BCJUS - Daily Court Lists"
schtasks /Run /TN "BCJUS - Weekly Catalogue"
schtasks /Run /TN "BCJUS - Monthly Statistics"
echo.
echo Start requests sent. Check reports\scheduler for results.
pause
