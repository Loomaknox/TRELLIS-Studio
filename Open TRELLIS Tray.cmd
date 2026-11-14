@echo off
setlocal
if not exist "%~dp0TRELLIS Studio Tray.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\windows\Build-Tray.ps1"
  if errorlevel 1 exit /b 1
)
if "%~1"=="" (
  start "" "%~dp0TRELLIS Studio Tray.exe" --mode desktop
) else (
  start "" "%~dp0TRELLIS Studio Tray.exe" %*
)
