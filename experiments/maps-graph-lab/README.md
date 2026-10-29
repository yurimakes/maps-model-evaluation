# MAPS 경량 온톨로지·그래프 실험

2026-10-29 로컬 CPU 실측. SQLite 속성 그래프와 표준용어·단어·도메인 관계를 이용한 컬럼 매핑 탐색 실험입니다.

## 결과

| 방법 | Top-1 | Top-5 | 매핑 F1 |
|---|---:|---:|---:|
| 메타데이터 TF-IDF | 41.5% | 75.4% | 36.6% |
| 사전·BM25·자료형 | 60.0% | 86.2% | 43.8% |
| 기존 승인 이력 결합 | 64.6% | 89.2% | **54.0%** |
| 용어·단어·도메인 그래프 | 66.2% | 83.1% | 42.9% |
| 그래프 + 다른 원천 승인 이력 | **69.2%** | **92.3%** | 51.8% |

그래프+이력은 후보 순위에서 개선됐지만 매핑 F1은 기존 이력 방식보다 2.2%p 낮았습니다. 동일 65개 양성 컬럼 중 Top-1 적중은 42→45개, Top-5는 58→60개입니다. 자동 이관 승인 개선을 입증한 결과는 아닙니다. F1 차이의 탐색적 질문 단위 bootstrap 95% 구간은 -10.6~+5.7%p로 0을 포함하며, 원천 간 의존성은 반영하지 않았습니다.

## 입력·반영 범위

- 원본 폴더 50파일과 백업 ZIP 1개를 읽고, 압축 내부 포함 131항목을 SHA-256으로 추적했습니다. 72개 고유 내용입니다.
- 18개 텍스트 문서 본문을 색인했습니다. PDF는 텍스트만 추출해 레이아웃 의미는 보장하지 않습니다.
- 49개 CSV·XLSX·JSON은 구조를 프로파일링했습니다. XLSX 전체 셀 값을 문서화하거나 상담 원문을 행 단위 그래프로 복제한 것은 아닙니다.
- 중복 59항목은 같은 내용과 연결했습니다. 압축 4개를 순회했습니다. 동영상 1개는 파일 정보만 기록했습니다.
- 표준단어 59, 표준용어 66, 도메인 16, 표준코드 80, 코드매핑 116, Target 78, Source 144개를 구조화했습니다.
- 원본은 읽기만 했습니다. `sources/`는 당시 비어 있어 이전 실험의 입력 해시 목록에 기록된 접근 가능한 원본 폴더를 사용했습니다.

전체 그래프는 노드 1,147개, 관계 1,921개입니다. `results/inventory.json`에 항목별 처리 상태가 있습니다. 근거 문서 검색은 SQLite FTS5 단어 검색이며 한국어 형태소·의미 검색은 아닙니다.

## 평가

114개 원천 컬럼, 5개 시스템, Target 후보 78개. 양성 컬럼 65개·정답 쌍 68개, 이관 제외 49개입니다. 정답 없는 메타데이터 컬럼 30개와 생성값 행 6개는 점수에서 제외했습니다. 출처를 정확히 연결하지 못한 4개 평가 컬럼은 이름만 사용했습니다.

원천별 outer leave-one-system-out으로 평가했습니다. 임계값은 나머지 원천 안에서 inner leave-one-system-out으로 고르며, F1·정밀도·더 낮은 임계값 순으로 선택합니다. 각 컬럼에 최대 하나를 추천합니다. 복수 Target 정답을 완전히 회수하지 못하면 재현율에서 감점됩니다. Top-k는 양성 65개, 매핑 F1은 제외 49개까지 포함합니다.

정적 그래프에는 Target→용어→단어·도메인을 사용합니다. 매핑 이력 그래프에는 학습 원천 컬럼과 그 승인 Target 연결만 추가합니다. 24회 확산, restart 0.65, 기존 점수 0.75 + 정규화 그래프 점수 0.25로 고정했습니다. 문서 본문·원천별 코드변환·변환규칙·검토 코멘트·고객 행 값은 점수에 넣지 않습니다.

`results/knowledge.sqlite`의 전체 저장 그래프는 조회 목적으로 정답 연결 68쌍을 포함합니다. 평가는 이 DB의 정답 연결을 검색하지 않고 학습 원천만 사용해 별도 그래프를 구성합니다. 보류 원천의 모든 정답을 바꿔도 점수·임계값이 같은지 5원천×2모델=10개 조건을 검사했습니다.

이미 프로젝트 자료를 보고 만든 표준사전과 알고리즘을 쓰므로 완전한 외부 독립 검증은 아닙니다. Fabric 서비스, 임베딩 모델, LLM RAG 재실행, 실제 토큰 절감은 측정하지 않았습니다.

## 실행

저장소의 `experiments/maps-local-lab`와 `experiments/maps-graph-lab`는 서로 형제 폴더로 유지합니다. Python 3.13과 `requirements.txt` 환경을 사용합니다.

```powershell
python -m pip install -r experiments/maps-graph-lab/requirements.txt
python experiments/maps-graph-lab/benchmark.py
python experiments/maps-graph-lab/verify.py
python experiments/maps-graph-lab/query.py recommend --column customer_name --description "고객 이름" --dtype "VARCHAR(100)"
python experiments/maps-graph-lab/query.py neighbors target:CUSTOMER.CUST_NM
python experiments/maps-graph-lab/query.py search 매핑
```

벤치마크는 저장한 메타데이터 스냅샷만으로 다시 실행할 수 있습니다. 전체 그래프 원본 재구축에는 별도 원본 폴더와 백업 ZIP이 필요합니다.

```powershell
python experiments/maps-graph-lab/build_graph.py --backup "원본 백업.zip" --source-root "원본 폴더"
python experiments/maps-graph-lab/benchmark.py
python experiments/maps-graph-lab/verify.py --require-source-files
python experiments/maps-graph-lab/measure_queries.py
```

`verify.py`는 원본이 없을 때 해당 해시 재검사를 건너뛰고 누락 경로를 기록합니다. `--require-source-files`는 원본 부재 시 실패합니다. 저장된 `verification.json`은 당시 51개 원본 해시까지 확인한 결과입니다.

신규 추천 CLI는 요청마다 공통 특징도 다시 준비하는 초기 구현입니다. `query_latency.json`은 실제 전체 추천 요청 시간, `costs.csv`는 전처리 후 배치 점수 계산·정렬 시간입니다. 둘을 전체 응답시간으로 혼동하지 않아야 합니다. 유료 API 호출은 0회이며 장비·전력 비용과 LLM 대비 비용 절감은 계산하지 않았습니다.

도메인·물리모델 비교로 자료형 차이 21개, 표준용어 연결 누락 8개, NULL 조건 차이 1개를 검토 대상으로 기록했습니다. 업무상 예외일 수 있어 오류로 확정하지 않았습니다. 도메인 검증기준의 원문은 보존했으나 모든 업무 규칙을 자동 실행하는 엔진은 아닙니다.

## 주요 산출물

- `results/report.html`: 서버 없이 열 수 있는 결과 보고서·관계 탐색
- `results/knowledge.sqlite`, `results/graph.json`: 전체 그래프와 근거 검색
- `results/metrics.csv`, `results/metrics_by_system.csv`: 전체·원천별 성능
- `results/predictions.csv`, `results/errors.csv`: 예측·오답
- `results/run_manifest.json`, `results/fold_graph_audit.json`: 실험 조건·평가 그래프 이력 범위
- `results/inventory.json`, `results/build_summary.json`: 파일 범위·해시·구축 시간
- `results/verification.json`: 유출 방지·독립 지표 계산·DB·원본 보존 검사

기존 이름 비교 함수의 출처와 라이선스는 형제 폴더 `maps-local-lab/third_party/`에 보존했습니다. Magneto 전체 신경망·LLM 파이프라인을 재현한 것은 아닙니다.
