@echo off
cd /d "%~dp0"
python -X utf8 record_run.py --label local --commit --push
if errorlevel 1 (
  echo Experiment failed. Please read the error above.
  pause
  exit /b 1
)
start "" "%~dp0results\latest\phase2_report.html"
pause
