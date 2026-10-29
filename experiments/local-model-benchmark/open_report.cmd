@echo off
if exist "%~dp0results\latest\neural_model_report.html" (
  start "" "%~dp0results\latest\neural_model_report.html"
) else (
  start "" "%~dp0results\latest\phase2_report.html"
)
