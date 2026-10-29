@echo off
cd /d "%~dp0"
python -X utf8 record_run.py --label pretrained-model-comparison --local-models --commit --push
if errorlevel 1 (
  echo Comparison failed. See the saved experiment log.
  pause
  exit /b 1
)
start "" "%~dp0results\latest\neural_model_report.html"
pause
