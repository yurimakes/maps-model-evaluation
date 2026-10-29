@echo off
cd /d "%~dp0"
python -X utf8 run_experiments.py
if errorlevel 1 (
  echo Experiment failed. Please read the error above.
  pause
  exit /b 1
)
start "" "%~dp0results\latest\report.html"
pause
