@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\smoke_core_local_ai.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo CORE LOCAL AI SMOKE FAILED with exit code %RC%.
  pause
)
exit /b %RC%
