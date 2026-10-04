@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm QA_Manager.spec
if errorlevel 1 pause
