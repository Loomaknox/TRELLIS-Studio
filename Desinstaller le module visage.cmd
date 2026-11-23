@echo off
setlocal
"%~dp0.venv\Scripts\python.exe" -B -u "%~dp0installer\install_facial_head.py" remove
if errorlevel 1 (
  echo Desinstallation interrompue. Verifie le message ci-dessus avant de reessayer.
  pause
  exit /b 1
)
pause
