@echo off
setlocal
"%~dp0.venv\Scripts\python.exe" -B -u "%~dp0installer\install_facial_head.py" install
if errorlevel 1 (
  echo Installation interrompue. Les fichiers du module peuvent etre retires avec le desinstalleur.
  pause
  exit /b 1
)
pause
