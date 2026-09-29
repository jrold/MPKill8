@echo off
setlocal
cd /d "%~dp0"
if not exist vendor mkdir vendor
if not exist vendor\MPKmini3_Updater_v1.26_WIN.zip (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://cdn.inmusicbrands.com/akai/mpk3mini/1_26/MPKmini3_Updater_v1.26_WIN.zip' -OutFile 'vendor\MPKmini3_Updater_v1.26_WIN.zip'"
  if errorlevel 1 exit /b 1
)
if exist dist\stock_updater rmdir /s /q dist\stock_updater
mkdir dist\stock_updater
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path 'vendor\MPKmini3_Updater_v1.26_WIN.zip' -DestinationPath 'dist\stock_updater' -Force"
for /r "dist\stock_updater" %%F in (*.exe) do (
  start "" "%%F"
  goto :done
)
echo Could not find stock updater executable.
exit /b 1
:done
echo Official Akai v1.26 updater launched.
