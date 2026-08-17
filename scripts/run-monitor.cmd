@echo off
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Create it before running the monitor.
  exit /b 1
)
".venv\Scripts\python.exe" main.py
