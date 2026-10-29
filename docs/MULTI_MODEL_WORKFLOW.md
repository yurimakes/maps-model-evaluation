# 모델을 계속 추가하는 실험 저장소

기존 두 저장소는 초기 실험의 출처다. 앞으로의 단위는 저장소 개수가 아니라 모델 설정 × 평가셋 × 실험 조건 × 실행 ID다.

```text
configs/models/          모델별 저장소·고정 revision·라이선스·환경
configs/experiments/     모델·평가셋·방법·seed를 묶은 실험 설정
configs/suites.json      평가셋·분할·후보 범위·지표 검증 기준
adapters/                모델 출력을 공통 계약에 연결
evaluation/              모델과 독립적인 공통 지표
environments/            실행 환경 안내·추가 환경의 의존성 관리
runs/<실행시각-ID>/      설정·버전·예측·지표·로그
experiments/             기존 두 저장소의 원본 자산 보존
```

현재 MPNet, 다국어 E5, 한국어 SRoBERTa의 기존 고정 revision을 모델 설정으로 등록했다. 모델과 Magneto 같은 매핑 방법은 구분한다. 예를 들어 같은 MPNet을 dense 방식과 Magneto 방식으로 비교할 때 모델 설정을 재사용하고 실험의 방법을 달리한다.

저장 예측을 실행별 형식으로 기록하는 예시:

```powershell
python -X utf8 -m adapters.record --experiment configs/experiments/mpnet-phase2.json --predictions results/common/integration-check/normalized_predictions.json
```

위 명령은 기존 실제 추론 결과를 가져와 새로 채점하는 작업이다. 새 모델 추론을 했다고 기록하지 않는다. 같은 명령을 반복해도 새 run ID를 만들고 이전 결과는 보존한다. 실패한 실행도 실패 상태와 로그를 남긴다. 기존 latest를 덮어쓰지 않는다.

새 모델을 추가할 때:

1. configs/models/에 고유 ID, 모델 저장소, 고정 revision, 라이선스, 환경을 등록한다. 가중치는 Git 밖에 둔다.
2. configs/experiments/에 모델 설정과 평가 suite, 방법, seed를 명시한다. 기존 저장 결과 가져오기는 saved_method로 선택한다.
3. 모델별 추론 구현은 별도 adapter로 추가한다. gold를 모델 입력/튜닝에 노출하지 않고 학습·검증·테스트 경계를 유지한다. 현재 recorder는 추론을 실행하지 않는다.
4. 새 출력은 JSON 목록 또는 JSONL로 만든다. 질문별 query_key, system, fold, gold, predicted, ranked를 갖추고 공통 계약 검사를 통과해야 한다. 오류는 status=ERROR/INVALID로 표시하며 보류 정답으로 바꾸지 않는다.
5. 같은 comparison_key의 결과끼리 비교한다. 서로 다른 평가셋·분할·후보·과거 재생 결과를 하나의 순위로 합산하지 않는다.

공통 recorder는 현재 스키마 매핑 과제용이다. 분류·텍스트 생성처럼 다른 과제가 생기면 과제별 평가 계약을 추가한다. 설정 등록만으로 임의의 새 모델을 자동 실행하는 범용 추론기는 아직 구현하지 않았다. 유료 API 실행이나 자동 commit/push 기능도 추가하지 않았다.
