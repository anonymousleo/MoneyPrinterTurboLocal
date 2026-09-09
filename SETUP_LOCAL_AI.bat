@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\setup_local_ai.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo LOCAL AI SETUP FAILED with exit code %RC%.
  pause
)
exit /b %RC%
