@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\verify_local_ai.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo LOCAL AI VERIFY FAILED with exit code %RC%.
  pause
)
exit /b %RC%
