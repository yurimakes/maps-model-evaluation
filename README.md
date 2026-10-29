# MAPS 2차 고도화 실험

목표는 기존 2차 MAPS의 RAG·매핑 추천 성능을 개선하는 것이다. 기존 데이터와 Target 표준체계를 유지하며 검색, 업무관계 검사, 승인 이력 활용을 추가한다.

## 지금 실행할 수 있는 것

- `open_report.cmd`: 저장된 실험 보고서 열기.
- `run_local.cmd`: 테스트·실험·2차 로그 재생을 실행하고 결과를 고유 스냅샷 폴더에 저장한 뒤 지정한 비공개 저장소에 커밋·업로드한다. Python 3.13과 폴더 내 `.packages`를 사용한다.
- `python test_evaluation.py`: 지표와 테스트 정답 누출 검사.
- `python run_experiments.py --out experiments/새실험명`: 원천 시스템 5개를 번갈아 보류하는 평가.
- `python record_run.py --label 실험명 --commit --push`: 검사 로그·전체 예측·실행 정보를 함께 기록하고 커밋한다. 실험명에는 영문·숫자·하이픈을 사용한다.

새 환경에서는 `python -m pip install -r requirements.txt`로 설치한다. 기존 로컬 환경의 라이브러리는 `.packages`에 있으며 Git에는 실행 환경 버전만 기록한다.

## 데이터와 평가

백업 매핑정의서 123행 중 생성 값 6행을 분리하고, 동일 원천·테이블·컬럼을 합친 114질문을 평가한다. 65질문에 68개 정답 쌍이 있고 49질문은 이관 제외다. Target은 테이블을 구분한 78개 후보이다. 이름이 같아도 다른 Target 테이블이면 다른 정답이다.

승인 이력 모델은 테스트 원천의 매핑을 사용하지 않는다. 추천 보류 기준은 테스트 원천을 제외한 데이터 내부에서 다시 원천별로 나누어 결정한다. 정답표에 없는 메타데이터 컬럼은 제외 정답으로 만들지 않는다. `data/snapshot.json`은 메타데이터·표준사전·정답·기존 반복 로그를 고정한 재현 입력이며, 원천 고객 레코드는 담지 않는다. 입력 원본 해시는 `data/manifest.csv`에 남긴다.

`maps_policy.json`은 2차 확정 논리모델·업무관계 Gate의 적용 범위를 별도 관리한다. 이 정책을 사용하는 실험과 사용하지 않는 실험을 구분한다. 현재 규칙과 방법은 이 프로젝트를 검토하며 설계했으므로 독립적인 외부 검증 결과로 주장하지 않는다.

## 2차와 비교할 때 주의할 점

2차 핵심 RAG 코드·프롬프트·검색 인덱스는 팀원에게 요청한 상태다. 현재는 홈페이지 18질문 × 30회 반복 로그만 기존 출력으로 재채점할 수 있다. 540회를 독립 데이터 540건으로 세지 않는다. 최빈 출력은 30회 집계 결과이고 단일 실행과 비용이 다르다. 승인 매핑을 그대로 찾는 점수를 새로운 매핑의 예측 성능으로 제시하지 않는다.

전체 114질문의 로컬 이름 비교보다 성능이 올랐다는 사실은 기존 2차 전체보다 좋아졌다는 증거가 아니다. 기존 코드 수령 후 동일 입력·모델·정답·데이터 분할로 A/B 재실행해야 한다.

## 기존 2차 코드에 붙일 모듈

`upgrade_adapter.py`의 `UpgradeEngine.recommend(source, legacy_target)`를 기존 RAG 추천 직후에 호출한다. source에는 `system`, `table`, `column`, `description`, `dtype`를 전달한다. 기존 Target 출력은 `legacy_target_original`로 보존하고, 재검토 후보를 `v3_target_proposal`로 따로 반환한다.

기존 결과가 매핑이면 이를 유지한다. 기존 결과가 EXCLUDE이면 기존 하이브리드·업무관계 검사 후 하이브리드의 두 기준 중 더 엄격한 기준을 충족하는 후보만 추가한다. 두 기준은 현재 원천을 제외한 데이터에서 선택한다. 모든 추가 후보는 `requires_human_review=true`, `execution_allowed=false`이며 최종 승인이나 Gold 이관 규칙을 직접 만들지 않는다. 점수는 검색 점수이고 성공 확률·기존 7항목 Confidence가 아니다.

`replay_predictions.csv`와 `replay_metrics.csv`는 저장된 기존 출력에 이 모듈을 붙인 탐색 결과다. 오류를 확인한 같은 18질문을 다시 사용한 것이므로 독립 검증·일반화 성능으로 주장하지 않는다. 기존 RAG 자체를 다시 실행한 결과도 아니다.

## 오픈소스

Magneto 공식 저장소 commit `6620623265fc7feac0f053996e62b68a13a72a57`의 문자열 비교 함수를 분리해 실제 실행한다. `third_party/magneto_name.py`에 변경 표시와 출처를, `third_party/LICENSE.txt`에 Apache-2.0 라이선스를 보존했다. 전체 Magneto 신경망 검색·LLM 재정렬이나 LLMatch 전체의 재현은 아니다.

- https://github.com/VIDA-NYU/magneto-matcher
- https://github.com/knowledge-fusion/LLMatch

## 스냅샷 원칙

이 저장소는 비공개를 유지한다. 코드, 테스트, 정책, 평가 입력 스냅샷, 예측, 지표, 실행 시간, 테스트 로그를 함께 커밋한다. 실행 바이너리·라이브러리·캐시·인증키는 커밋하지 않고 버전과 설치 방법을 기록한다. 실제 원천 데이터·첨부 원본은 읽기만 한다.
