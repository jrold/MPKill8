@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_mpkill8.ps1"
if errorlevel 1 (
  echo.
  echo MPKill8 installer failed.
  pause
)
