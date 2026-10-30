# 실험 1 — 메타데이터 기반 매핑정의서 초안 생성: 규칙·유사도 Python 기준선

- 알고리즘 버전: `exp1-baseline-1.0.0` (동일 판정 로직)
- 공개 배포 정리: `r1` (주석·도움말·합성 테스트의 출력 계약 파일명 일반화, 환경 차이 검증 안내 보정)
- 상태: 구현, 합성 단위 테스트, 출력 구조 검증 완료. **기존 승인 매핑과의 정답 대조는 미실시.**
- 이 디렉터리는 신규 실험 코드이며 저장소의 기존 MAPS 실험을 대체하거나 통합하지 않는다.

## 1. 연구 목적

기존에 승인된 매핑정의서를 참조하지 않고, Source 컬럼 메타데이터와 Target 스키마만으로 매핑정의서 초안을 생성할 수 있는 범위와 한계를 확인한다. 이 실험은 이후 논문 기반 방법(LLM·SQL 생성 등)과 같은 출력 형식으로 비교할 수 있는 **재현 가능한 기준선**을 만드는 것이 목적이다.

연구 질문:
- RQ1. 매핑정의서의 필수 항목을 Python 알고리즘이 얼마나 작성할 수 있는가?
- RQ2. 후보 검색을 넘어 이관 결정과 변환 연산을 얼마나 확정할 수 있는가?
- RQ3. 근거가 부족할 때 REVIEW로 판단을 보류하는가?
- RQ4. 기존 승인 결과와 비교했을 때 연결·이관 판단은 얼마나 일치하는가? (아직 측정하지 않음)

## 2. 연구적 구분

- **추론 엔진은 이 디렉터리의 Python 규칙·유사도 알고리즘이다.** LLM을 호출하지 않으며 네트워크·외부 API·DB 접속 코드가 없다.
- Claude(Anthropic)는 코드·테스트·문서 작성을 도운 **개발 보조 도구**다. Claude가 매핑 정답을 골라 출력에 기입한 것이 아니며, 이 실험은 LLM 직접 매핑 생성 실험이 아니다.
- 개별 Source–Target 정답을 코드에 하드코딩하지 않는다. `validate_output.py`가 입력 식별자 문자열 리터럴이 알고리즘 소스에 없는지 정적으로 검사한다.
- 합성 테스트 통과와 구조 검증 통과는 **출력 규격 충족**을 뜻하며 업무 정확도 검증이 아니다.
- 자동 MIGRATE 결과는 **승인 전 초안**이다. REVIEW 결과도 정답으로 간주하지 않는다.
- SQLMorpher·DataMorpher 등 선행 연구의 원형 재현이 아니다.

## 3. 알고리즘

### 3.1 후보 점수
Source 컬럼 1개와 Target 컬럼 1개의 쌍마다 다음을 계산한다.

```
텍스트 점수 = 가중평균(이름 문자 n-gram TF-IDF 코사인 0.35,
                      약어 부분수열 매칭 0.25,
                      설명 문자 n-gram TF-IDF 코사인 0.40)
              (어느 한쪽 설명이 비어 있으면 설명 성분을 빼고 재정규화)
최종 점수   = 텍스트 점수 × 자료형 계수 × (0.6 + 0.4 × 테이블 친화도)
```

| 성분 | 내용 |
|---|---|
| 이름 정규화 | CamelCase·언더스코어·특수문자로 분해, 소문자화, 1글자 토큰 제거. 원본 식별자는 출력에서 변경하지 않음 |
| 이름 n-gram | `char_wb` 2–4 gram TF-IDF (Source·Target 이름 전체로 비지도 학습) |
| 약어 매칭 | 동일 토큰 1.0, 짧은 토큰이 긴 토큰의 부분수열이고 첫 글자가 같으며 길이 비 ≥ 0.3이면 0.8. 대칭 soft-Dice로 집계. 사전(약어집)은 사용하지 않음 |
| 설명 n-gram | 구두점·공백 제거 후 `char` 2–3 gram TF-IDF (한국어 띄어쓰기 차이 흡수) |
| 자료형 계수 | 안전 변환 1.0 / 규칙 필요 0.9 / 비호환 0.7 / 미확인 1.0 |
| 테이블 친화도 | Source 테이블별로, 각 Target 테이블에 대해 "Source 컬럼별 최대 텍스트 점수"의 평균을 구하고 최댓값으로 정규화. 라벨을 사용하지 않음 |

후보는 Source마다 최종 점수 상위 3개(최소 0.05)를 `candidates.csv`에 기록한다. **점수는 유사도이며 정답 확률이 아니다.**

### 3.2 Target 확정 게이트
아래를 **모두** 만족해야 Target을 식별한 것으로 본다. 하나라도 어긋나면 `decision=REVIEW`, `targets=[]`.
- 1위 점수 ≥ 0.45, 1·2위 점수 차 ≥ 0.08
- Source 설명과 Source 자료형이 존재
- 설명 유사도 ≥ 0.20, 이름 근거(max(이름 n-gram, 약어)) ≥ 0.20

### 3.3 연산 결정 (Target 식별 후)
| 조건 | 결과 |
|---|---|
| 명시적 제외 규칙 입력(`--exclusion-rules`)에 해당 | `EXCLUDE` (게이트보다 먼저 적용) |
| Target이 PK 또는 FK | `REVIEW` / operation `REVIEW` (식별자 생성·참조 매칭 규칙이 입력에 없음) |
| 코드성 컬럼(Source `CODE_YN=Y`, 또는 Target 이름 `_CD`/`_YN` 접미, 설명의 "코드", 닫힌 허용값 목록) | Source 코드값 목록이 Target 설명의 닫힌 허용값 목록(예: `Y/N`)의 부분집합이면 `COPY`, 아니면 `REVIEW` (코드 대응표 없이 LOOKUP을 추측하지 않음) |
| 동일 자료형 계열, 길이·정밀도 수용 | `COPY` |
| 문자열 → DATE/TIMESTAMP, `FORMAT_HINT`가 `YYYYMMDD`·`YYYY-MM-DD HH:MM:SS` 등으로 명시되고 정밀도 일치 | `FORMAT` (parse_pattern 기록) |
| 그 밖의 변환, 길이 초과, 형식 미상 | `REVIEW` |

`decision=MIGRATE`는 연산이 `COPY` 또는 `FORMAT`일 때만 나온다. 이 기준선은 `LOOKUP`, `EXPLODE`, `CONSTANT`, `CUSTOMER_MATCH`, `GENERATE_ID`를 생성하지 않는다(근거가 되는 입력이 없음). 1:N 매핑도 자동 확정하지 않는다.

### 3.4 설정값 (v1.0.0, 실제 입력 실행 전에 고정)
`maps_exp1_baseline.py`의 `Config` 데이터클래스에 있다. 성능 개선을 위해 변경한 이력은 없다. 값을 바꾸면 `ALGORITHM_VERSION`을 올리고 새 실험 조건으로 구분해야 한다.

## 4. 구현 언어와 의존성

- Python 3.12 (검증: CPython 3.12.3, Linux). Windows PowerShell 실행 절차는 아래에 있으나 Windows에서는 아직 실행 검증하지 않았다.
- 직접 의존성: `requirements.txt` (numpy, scikit-learn). 검증 환경의 전이 의존성까지 고정한 목록: `requirements-lock.txt`.
- 테스트: 표준 라이브러리 `unittest` (pytest 불필요).

| 패키지 | 검증 버전 | 라이선스 (패키지 메타데이터 기준) |
|---|---|---|
| numpy | 2.4.4 | BSD-3-Clause (번들 구성요소 0BSD, MIT, Zlib, CC0-1.0 포함) |
| scikit-learn | 1.8.0 | BSD-3-Clause |
| scipy | 1.17.1 | BSD License |
| joblib | 1.5.3 | BSD-3-Clause |
| threadpoolctl | 3.6.0 | BSD-3-Clause |

이 디렉터리는 위 패키지의 코드를 포함하거나 재배포하지 않는다. 외부 연구의 코드도 복사하지 않았다.

## 5. 입력·출력 규격

### 5.1 입력
| 파일 | 필수 헤더 |
|---|---|
| Source 메타데이터 CSV (UTF-8, BOM 허용) | `SOURCE_SYSTEM, SOURCE_TABLE, TABLE_NAME_ASSUMED, SOURCE_COLUMN, DATA_TYPE, COLUMN_DESCRIPTION, NULLABLE_YN, PK_YN, BUSINESS_KEY_YN, CODE_YN, PII_YN, FORMAT_HINT, SOURCE_CODE_HINT` |
| Target 스키마 CSV | `TABLE_NAME, COLUMN_NAME, DATA_TYPE, KEY, NULLABLE, DESCRIPTION` |
| 출력 계약 텍스트 | 아래 출력 필드명과 결정값·연산값이 모두 포함되어야 함 (프로그램이 일치 여부를 검사) |
| (선택) 제외 규칙 CSV | `SOURCE_SYSTEM, SOURCE_TABLE, SOURCE_COLUMN, EXCLUDE_REASON` |

- Source 식별자는 (`SOURCE_SYSTEM`, `SOURCE_TABLE`, `SOURCE_COLUMN`), Target 식별자는 (`TABLE_NAME`, `COLUMN_NAME`). 중복이면 중단한다.
- Y/N 플래그는 `Y`, `N`, 빈값만 허용한다. 빈 `DATA_TYPE`·`COLUMN_DESCRIPTION`은 미확인으로 취급하며 추측으로 채우지 않는다.
- `SOURCE_CODE_HINT`는 `A|B|C` 형식의 코드값 목록이다.

### 5.2 출력 (`--out-dir`)
| 파일 | 내용 |
|---|---|
| `mapping_draft.json` | Source 1행당 객체 1개(입력 순서 유지). 필드: `source_system, source_table, source_column, decision, targets[{target_table, target_column, operation, parameters, exception_policy}], reason, missing_information` |
| `candidates.csv` | Source별 후보 최대 3개와 점수 성분. **확정 매핑이 아님** |
| `decision_trace.csv` | Source별 결정·연산·규칙 코드 (보류 사유 분류용) |
| `report.txt` | 집계, 보류 사유, 추가 정보 필요 항목, 검증 결과, 미검증 범위 |
| `validation_result.json` | 독립 검증기 결과 |
| `run_manifest.json` | 설정·라이브러리 버전·입출력 SHA-256·실행 시각 (파일 경로는 기록하지 않음) |

출력 관례 (평가 전에 고정):
- `MIGRATE`: 단일 Target과 `COPY`/`FORMAT`이 메타데이터 근거로 결정된 초안.
- `REVIEW` + `targets=[]`: Target 미확정. 후보는 `candidates.csv`에만 있다.
- `REVIEW` + Target 1개(operation `REVIEW`): Target 단일 후보는 식별했으나 변환 규칙(키 정책, 코드 대응표, 길이·형식)이 미확정. **매핑 쌍 평가 시 이 범주를 포함할지 평가 전에 정해야 한다.**

> 주의: 실제 입력으로 실행한 출력에는 실제 Source·Target 식별자와 입력 파일 해시가 들어간다. 이 디렉터리의 `.gitignore`는 `output/`, `input/`, `data/`를 제외하지만, 다른 이름의 폴더에 출력했다면 커밋 전에 반드시 직접 확인해야 한다.

## 6. 실행 방법

### 6.1 Windows PowerShell (이 디렉터리에서)
```powershell
$env:PYTHONUTF8 = "1"
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt

# 1) 합성 단위 테스트
python -m unittest discover -s tests -v

# 2) 합성 예시 실행
python .\maps_exp1_baseline.py `
  --source .\examples\synthetic\input\source_metadata.csv `
  --target .\examples\synthetic\input\target_schema.csv `
  --protocol .\examples\synthetic\input\OUTPUT_CONTRACT.txt `
  --exclusion-rules .\examples\synthetic\input\exclusion_rules.csv `
  --out-dir .\output\synthetic `
  --expect-source-rows 10 --expect-target-rows 8

# 3) 환경 비의존 출력 4개를 바이트 단위 비교
# report.txt에는 Python·라이브러리 버전이 기록되므로 버전이 다르면 그 줄이 달라질 수 있다.
# run_manifest.json은 실행 시각이 들어가므로 비교 대상에서 제외한다.
python -c "import filecmp; n=['mapping_draft.json','candidates.csv','decision_trace.csv','validation_result.json']; m,d,e=filecmp.cmpfiles('output/synthetic','examples/synthetic/expected_output',n,shallow=False); print('일치:',m,'불일치:',d,'오류:',e); assert not d and not e"
```

### 6.2 Linux / macOS
```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m unittest discover -s tests -v
I=examples/synthetic/input
python maps_exp1_baseline.py --source $I/source_metadata.csv --target $I/target_schema.csv \
  --protocol $I/OUTPUT_CONTRACT.txt --exclusion-rules $I/exclusion_rules.csv \
  --out-dir output/synthetic --expect-source-rows 10 --expect-target-rows 8
```

### 6.3 비공개 실제 입력
실제 입력은 이 저장소에 포함하지 않는다. 권한이 있는 로컬 환경에서 입력 파일을 저장소 밖(또는 `.gitignore`된 `input/`)에 두고, 출력은 `output/` 아래에 쓴다. 출력 폴더는 입력 파일 폴더와 달라야 한다(프로그램이 검사).
```powershell
python .\maps_exp1_baseline.py --source <Source CSV> --target <Target CSV> --protocol <출력 계약 파일> `
  --out-dir .\output\real --expect-source-rows <행 수> --expect-target-rows <행 수>
```

### 6.4 독립 검증만 다시 실행
```powershell
python .\validate_output.py --source <Source CSV> --target <Target CSV> `
  --mapping <out>\mapping_draft.json --candidates <out>\candidates.csv --algorithm .\maps_exp1_baseline.py
```

종료 코드: `0` 생성·검증 통과 / `1` 검증 실패 또는 입력 파일 해시 변경 / `2` 입력 오류로 중단.

## 7. 기존 실험에서 관찰된 결과

요약만 적는다. 상세 집계와 재현 확인 기록은 [`RESULTS.md`](RESULTS.md).

- 비공개 입력 Source 140행, Target 78행 → 출력 140건
- MIGRATE 4 (COPY 3, FORMAT 1) / REVIEW 136 / EXCLUDE 0 (제외 규칙 입력 없음)
- 합성 단위 테스트 28개 통과, 출력 구조 검증 21개 항목 통과

## 8. 수행한 검증과 수행하지 않은 검증

수행:
- 합성 단위 테스트 28개: 입력 검사, 정규화·약어·자료형·형식·허용값 해석, 판정 경로별 결과, 결정성, 원본 해시 불변, 검증기의 오류 탐지
- 독립 구조 검증 21개 항목: JSON 구조, 결정·연산 값, Source 1:1 대응, Target 참조 유효성, 결정·연산 일관성, 후보 파일, 하드코딩·네트워크 import 정적 검사
- 실행 전후 입력 파일 SHA-256 동일 여부

수행하지 않음:
- 기존 승인 매핑정의서와의 매핑 쌍 Precision·Recall·F1
- 이관 여부(이관·제외·판단 불가) 일치도
- 실제 값 샘플·기대 출력 기반 변환 실행 정확도
- 전문가 수용률, 검토 시간 절감 효과
- Windows 환경 실행, 다른 라이브러리 버전에서의 결과 동일성

## 9. 알려진 한계

- 보류율이 매우 높다(실제 입력에서 97.1%). 게이트가 보수적이며 설명이 짧거나 이름 체계가 다른 시스템에서 점수가 낮다.
- 이름·설명 문자열 유사도는 의미적 정답을 보장하지 않는다. "Target 식별·변환 보류" 범주에 Source와 다른 업무 엔터티의 Target이 연결된 사례가 있는 것으로 보인다(설계자 관찰, 정답 대조로 확인되지 않음).
- 동일 컬럼명이 여러 Target 테이블에 있으면 1·2위 차이가 작아 REVIEW가 된다. 1:N 매핑은 자동 생성하지 않는다.
- 코드 대응표, 키 생성·고객 매칭 규칙, NULL·형식 불일치 처리 기준이 입력에 없어 해당 연산은 모두 REVIEW다.
- 설명이나 자료형이 비어 있는 Source는 이름만으로 확정하지 않는다.
- 규칙 설계 과정에서 구현 보조자가 실제 입력의 메타데이터 구조를 열람했다. 개별 컬럼 예외 규칙은 없지만, 임계값·가중치가 그 입력에 우연히 유리하거나 불리할 수 있어 독립 입력 검증이 필요하다.
- 실험 결과는 Python 3.12.3, numpy 2.4.4, scikit-learn 1.8.0에서 얻었다. 다른 버전에서 점수의 미세한 차이가 날 수 있다.

## 10. 후속 평가 계획

1. 별도 평가 환경에서 생성 결과와 기존 승인 매핑을 Source 식별자로 정렬한다. 평가 집합에 대응하지 않는 행의 수와 선정 기준을 함께 보고한다.
2. 매핑 쌍 Precision·Recall·F1을 계산한다. "Target 식별·변환 보류" 범주를 포함한 경우와 제외한 경우를 모두 보고한다.
3. 이관 여부 일치도, 확정률, 보류율을 보고한다.
4. 참조 규칙이 있는 사례에서만 연산·인자 일치도를 계산하고, 기대 출력이 확보된 경우에만 변환 실행 정확도를 계산한다.
5. 평가 결과를 보고 규칙을 고친 버전은 새 버전으로 분리하고, 동일 블라인드 점수로 취급하지 않는다.
6. 표준사전 추가, 논문 기반 LLM/SQL 생성 방법과의 비교는 별도 조건으로 수행한다.

## 11. 파일 구성

```
exp1-rule-baseline/
├── README.md                    이 문서
├── RESULTS.md                   기존 실험 집계 결과와 재현 확인 기록
├── maps_exp1_baseline.py        생성기 (입력 검사·점수화·판정·출력·보고서)
├── validate_output.py           독립 검증기 (생성기를 import하지 않음)
├── tests/test_baseline.py       합성 단위 테스트 28개
├── requirements.txt             직접 의존성
├── requirements-lock.txt        검증 환경 전이 의존성 고정
├── examples/synthetic/input/    합성 입력 (가상 식별자) + 공개용 출력 계약
├── examples/synthetic/expected_output/  합성 입력의 기대 출력
├── .gitignore                   output/, input/, data/, 캐시 등 제외
└── .gitattributes               예시 파일의 줄바꿈 변환 방지
```

## 12. 저장소에 포함하지 않는 자료

실제 Source·Target 메타데이터와 원본 데이터, 기존 승인 매핑정의서와 정답 데이터, 실제 입력으로 생성한 출력·로그, 원본 파일 해시, 내부 업무 문서는 저장소에 포함하지 않는다. 저장소가 비공개여도 같은 원칙을 적용한다.
