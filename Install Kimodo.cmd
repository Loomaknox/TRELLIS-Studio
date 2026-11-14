@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Studio.ps1" -WorkshopOnly -WithKimodo -NoLaunch %*
set "studio_exit=%errorlevel%"
if not "%studio_exit%"=="0" echo Kimodo installation stopped. Review the message above and run this launcher again to resume.
pause
exit /b %studio_exit%
