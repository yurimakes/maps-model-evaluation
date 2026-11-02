@echo off
chcp 65001 >nul
setlocal
set "TASK_BASE=%~dp0"
set "AI_SOURCE=%~1"
if not defined AI_SOURCE set "AI_SOURCE=%TASK_BASE%AI결과.zip"
set "GOLD_SOURCE=%~2"
if not defined GOLD_SOURCE set "GOLD_SOURCE=%TASK_BASE%정답.csv"
set "DATASET_LABEL=%~3"
if not exist "%AI_SOURCE%" (
  echo AI 결과 ZIP 또는 폴더를 이 실행 파일 위로 끌어다 놓으세요.
  pause
  exit /b 2
)
if not exist "%GOLD_SOURCE%" (
  echo 정답.csv를 찾을 수 없습니다. README를 확인하세요.
  pause
  exit /b 2
)
set "PYTHON_LAUNCH=python"
where python >nul 2>nul
if errorlevel 1 (
  set "PYTHON_LAUNCH=py -3"
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10 이상이 필요합니다. 설치 후 다시 실행하세요.
    pause
    exit /b 2
  )
)
set "TASK_OUTPUT=%TASK_BASE%결과\run_%RANDOM%_%RANDOM%"
%PYTHON_LAUNCH% "%TASK_BASE%evaluate.py" run --ai "%AI_SOURCE%" --gold "%GOLD_SOURCE%" --out "%TASK_OUTPUT%" --dataset-id "%DATASET_LABEL%"
if errorlevel 1 (
  echo 위 오류를 확인하세요. 입력 파일은 변경하지 않았습니다.
  pause
  exit /b 2
)
start "" "%TASK_OUTPUT%\보고서.html"
echo 평가가 끝났습니다. 보고서가 열렸습니다.
pause
endlocal
