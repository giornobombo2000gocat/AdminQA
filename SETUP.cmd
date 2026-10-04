@echo off
cd /d "%~dp0"
set PLAYWRIGHT_BROWSERS_PATH=0
py -3.12 -m venv .venv
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m pip install -r requirements-desktop.txt
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto failure
echo Setup completed. Run START.cmd.
pause
exit /b 0
:failure
echo Setup failed. See the error above.
pause
exit /b 1
