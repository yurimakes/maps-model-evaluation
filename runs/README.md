# 실행별 기록

새 기록은 `python -m adapters.record`로 생성한다. 실행시각과 고유 ID로 폴더를 만들며 기존 실행 폴더를 재사용하지 않는다.

각 폴더에는 config.json, manifest.json, predictions.jsonl, metrics.json, execution.log를 기록한다. 실패한 실행은 manifest.status=failed와 로그를 남기고 성공 지표를 만들지 않는다. 모델 추론을 실행하지 않고 저장 예측을 다시 채점한 경우 manifest에 명시한다.

과거 원본 실행 기록은 experiments/ 아래 원래 경로에 보존되어 있다. 이 폴더의 평가 입력·예측은 내부 파생 자산이며 공개 가능 여부를 별도로 확인한다.
