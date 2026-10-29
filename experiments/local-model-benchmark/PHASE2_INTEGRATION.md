# 실제 2차 RAG A/B 실행

원본 코드·지식·임베딩·마스킹 프로파일은 준비돼 있다. 현재 실행 환경에는 Azure 연결 환경변수가 없어 최종 LLM 추천은 실행하지 않았다.

## 지금 바로 실행 가능: 무료 캐시 비교

`python record_run.py --label phase2-cached --commit --push`

이 명령은 테스트, 실제 검색 재실행, 코드 검증과 유료 A/B 실행 계획을 저장한다. 기본 실행은 Azure를 호출하지 않는다. 기존 Databricks 운영 노트북은 실행하지 않으며 공유 테이블에 쓰지 않는다.

## 기존 Azure 연결 환경에서 실행

실행 프로세스의 환경변수에 기존 `MAPS_AZURE_ENDPOINT`, `MAPS_AZURE_KEY`, `MAPS_CHAT_DEPLOYMENT`가 설정돼 있어야 한다. 인증값을 코드·결과·Git에 쓰지 않는다.

5질문으로 원본과 개선판을 먼저 확인하는 명령:

`python record_run.py --label phase2-ab-smoke --model-ab-api --model-ab-questions 5 --model-ab-max-requests 24 --commit --push`

`--model-ab-api`를 명시할 때만 실제 유료 호출을 한다. 이 호출은 새 Azure 리소스를 생성하지 않고 기존 배포를 사용한다. 동일 질문·동일 배포·동일 지식·동일 캐시를 사용하고, 질문마다 원본/개선판 실행 순서를 교대로 바꾼다. 기본 가중합은 동일하며 엄격한 검증과 프롬프트 규약의 효과를 비교한다.

요청 시도는 두 방법 합계 최대 24회, 응답 한도는 요청당 2,200토큰이다. 기존 코드 내부의 빈 응답 재시도에도 이 한도가 적용되며, HTTP 오류는 자동 재시도하지 않는다. 실제 통화 비용 한도를 보장하는 것은 아니므로 단가는 배포 가격으로 별도 계산한다. 실제 사용량과 오류를 결과에 기록한다. 임베딩 API 호출은 없고 Databricks에 쓰지 않는다.

## 결과 해석

- `model_ab_metrics.csv`: 최종 매핑 Precision·Recall·F1, 추천·제외 정확도, 유효 출력 수와 오류 수.
- `model_ab_predictions.json`: 질문별 정답·예측·검증 상태·토큰 수.
- `model_ab_raw.json`: 원본 응답과 실제 검색 근거.
- `model_ab_execution.json`: 배포명, 요청 시도, 사용량, 실행 조건. 인증키는 포함하지 않는다.

오류와 INVALID/판단 보류를 정답 EXCLUDE로 세지 않는다. 기존 데이터에 대해 설계한 방법이므로 초기 개선 폭은 탐색 결과이며, 별도 검토한 새 평가셋으로 일반화를 확인해야 한다. 5질문은 실행 확인용이다. 실제 2차 범위의 전체 비교는 93질문이며 필요한 요청·토큰 한도를 별도 산정한 후 실행한다.
