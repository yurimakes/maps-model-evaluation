# MAPS 통합 실험 작업본

`maps-ontology-graph`와 `maps-local-model-benchmark`를 공통 평가체계를 중심으로 정리한 통합 실험 저장소다. 사용자가 만든 비공개 저장소 https://github.com/yurimakes/maps-model-evaluation 에 게시한다. 기존 benchmark 커밋 `3bf941ebf81e717fe3cefcb040d2a564642b9500`에서 이어지는 통합 커밋이며, 원본 두 저장소는 그대로 유지한다.

원본 체크아웃, 원격 저장소, 기존 결과와 Git 이력을 보존했다. 원본 추적 파일 **441개**는 Git blob 바이트와 일치하며, `provenance/import-manifest.json`에 이전·현재 경로와 해시가 있다. 두 이력은 `refs/archive/`에 따로 보존했고, 독립 Git bundle과 mirror는 형제 폴더 `../maps-integration-preservation-20261029/`에 있다.

## 시작

여러 모델의 장기 실험을 위해 `configs/models/`, `configs/experiments/`, `adapters/`, `environments/`, `runs/`를 추가했다. [모델 추가·실행 기록 방법](docs/MULTI_MODEL_WORKFLOW.md)을 참고한다. 기존 결과를 run 형식으로 기록하는 기능을 제공하며, 새 모델의 자동 추론 실행기는 별도 구현 대상이다.

Python 3.13 표준 라이브러리만으로 저장 예측을 다시 채점한다.

```powershell
python -X utf8 -m evaluation
python -X utf8 -m unittest discover -s tests -v
```

매번 `results/common/<새 실행시각>/`에 성능표·정규화 예측·입력 해시·기존 성능표 대조 결과를 만든다. `--out results/common/새이름`으로 경로를 지정할 수 있다. 기존 폴더 덮어쓰기는 거부한다. 모델 추론이나 유료 API 호출은 없다.

검증 결과: **37개 성능표·2,898개 예측 재채점 일치**, 테스트 **43개 통과**, 그래프 10조건 정답 누출 검사·SQLite 무결성·원본 51파일 해시 확인 통과. [상세 작업 보고서](docs/INTEGRATION_REPORT.md), [평가 기준](docs/EVALUATION.md), [라이선스·민감정보](docs/LICENSE_AND_SECURITY.md)를 참고한다.

## 구조

```text
evaluation/                       공통 지표·평가 입력 검증·오프라인 채점
configs/suites.json                평가셋·프로토콜·예측·기존 성능표 연결
tests/                            공통 평가 계약 검사
tools/validate_local.py            원본 보존·기존 코드 검증
experiments/local-model-benchmark/ 최신 benchmark 전체 코드·실험·결과
experiments/maps-graph-lab/         그래프 실험 전체 코드·입력·결과
experiments/maps-local-lab/         그래프가 참조하는 당시 로컬 실험
research_support/                 기존 연구 보고서 생성·검사 코드
provenance/                        출처·파일 트리·경로 이동·보안·라이선스 기록
results/common/                    새 공통 재채점 결과
results/validation/                새 검증 로그
```

그래프와 당시 로컬 실험은 형제 경로를 유지하여 기존 import가 작동한다. 최신 benchmark는 별도 디렉터리에 두어 동명 파일·과거 산출물을 덮어쓰지 않는다. 두 requirements 환경은 버전이 다르므로 별도 환경을 사용한다. 설치 라이브러리·모델 가중치·인증정보·브론즈 원천 레코드는 가져오지 않았다. 기존에 Git으로 관리하던 임베딩·지식 문서·DB는 출처를 보존한 내부 자산이다.

## 기존 보고서

- [그래프 보고서](experiments/maps-graph-lab/results/report.html)
- [최신 모델 비교 보고서](experiments/local-model-benchmark/results/latest/neural_model_report.html)
- [2차 RAG 검색 진단](experiments/local-model-benchmark/results/latest/phase2_report.html)
- [실제 모델 비교 해석](experiments/local-model-benchmark/MODEL_FINDINGS.md)
- [공통 성능표](results/common/integration-check/metrics.csv)

이전 실행 스크립트와 사용법은 당시 기록을 그대로 담고 있다. 특히 legacy `run_local.cmd`, `run_model_comparison.cmd`, `record_run.py --commit --push`는 자동 커밋·업로드 기능이 있으므로 이번 작업의 실행 경로로 사용하지 않는다. 루트 `run_evaluation.cmd`와 `python -m evaluation`은 로컬 채점만 한다. 원래 AGENTS 지침은 `provenance/benchmark-root/AGENTS.md`에 보존하고 현재 지침으로 교체했다.

커밋·푸시·PR·merge·이력 재작성·기존 저장소 삭제·공개 전환은 별도 명시적 승인 대상이다. 자체 코드·데이터와 일부 모델의 라이선스가 미확정이므로 통합 저장소 전체에 임의의 오픈소스 라이선스를 부여하지 않았다.
