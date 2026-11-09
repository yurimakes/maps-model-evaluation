# AI 입력·출력 연계규칙 로컬 검증

WBS 07.1.1의 첫 공유용 검토본 **v0.1**과 합성 입출력 예시를 검증한다. 문서 기준일은 2026-11-05이며, 이후 회의 결정이나 G1 승인 상태를 갱신한 자료는 아니다.

Python **3.10 이상**과 표준 라이브러리만 필요하다. 패키지 설치, API 키, 모델 다운로드, Azure 연결이 필요하지 않다.

## VS Code에서 실행

저장소 최상위 폴더를 VS Code로 열고 `Python: Select Interpreter`에서 사용할 Python을 선택한다. 터미널에서 다음 명령을 실행한다.

```powershell
python -X utf8 experiments/ai-contract-validation/validate.py
```

`PASS: offline artifact checks`와 결과 폴더가 표시되면 구조 검증에 통과한 것이다. 검증 대상 파일은 수정하지 않으며, 보고서는 매번 새 `results/ai-contract-validation/<실행시각-식별자>/validation.json`에 저장된다. 실패 시 오류 코드·대상 위치가 표시되고 종료 코드 1을 반환한다. 보고서 저장 실패·기존 폴더 재사용은 종료 코드 2다.

VS Code의 `Tasks: Run Task`에서도 실행할 수 있다.

- **MAPS: 연계규칙 검증** — 문서·합성 예시 검사
- **MAPS: 연계규칙 테스트** — 오류를 넣었을 때 검증기가 잡는지 확인
- **MAPS: 연계규칙 HTML 갱신** — Markdown 수정 후 HTML 본문을 다시 생성하는 명시적 편집 작업

VS Code 작업은 Microsoft Python 확장의 선택된 인터프리터를 사용한다. 확장이 없어도 위 터미널 명령으로 실행할 수 있다.

## 포함 파일

| 파일 | 용도 |
|---|---|
| `artifacts/MAPS_AI_입출력_연계규칙_v0.1.md` | 수정 기준 원문 |
| `artifacts/MAPS_AI_입출력_연계규칙_v0.1.html` | 같은 내용의 열람본 |
| `artifacts/MAPS_AI_연계예시_v0.1.json` | 합성 입력·추천·보류·Mapping·실패 예시 |
| `artifacts/bundle.json` | 검증 파일과 문서/계약 버전 연결 |
| `validate.py` | 오프라인 구조 검증 및 새 보고서 생성 |
| `test_validate.py` | 정상 입력·오류 입력에 대한 회귀 검사 |
| `render_html.py` | 기존 디자인을 보존하며 Markdown에서 HTML 본문 갱신 |

원천 데이터, 팀 대화, 개인 로컬 경로, 내부 원본 대응표는 포함하지 않는다. 문서 버전 `0.1`과 JSON의 계약 버전 `0.1-draft`는 첫 공유본 표시이며 정식 승인을 뜻하지 않는다.

## 검사하는 내용

- 요청·응답 ID, 접근 범위, 입력 스냅샷과 스키마 버전 연결
- 원천 복합키, 대상·Evidence·자산·사전 항목의 참조와 판본
- 요청한 대상/유형의 결과 누락, 기술 실패와 추천의 모순
- 입력 대상 수·처리 대상 수·실패 대상 수·추천 수와 판정별 집계
- 시간대와 실행 시각 순서, 관측 표본/전체 구분과 관측 건수
- AI 적용·제외 제안과 사람의 최종값 분리, 제외 사유
- Confidence 범위와 산출 방법 표기, 미산출 점수의 이유
- 제공된 참조 자산의 사용/미사용 기록
- Markdown·HTML 본문 일치, 문서 버전·절 참조, 사용자별 로컬 경로 포함 여부

대상 5개나 특정 예시 ID를 정답으로 고정하지 않는다. 한 대상의 여러 추천과 여러 유형 요청을 허용하며, 같은 대상/유형의 성공과 실패는 모순으로 처리한다. `processed_subjects`에는 추천·보류가 생성된 고유 대상 수를, `failed_subjects`에는 기술 실패가 발생한 고유 대상 수를 센다. 한 대상의 일부 유형만 실패하면 두 집합이 겹칠 수 있어 두 수를 무조건 더해 입력 수로 보지 않는다.

이 도구는 **현재 초안의 AI 추천 교환 형식**을 검사한다. 사람이 확정한 승인 결과를 입력하는 도구가 아니며, 임의 JSON 전체에 적용되는 범용 스키마 검증기도 아니다. 새 계약 구조로 바꿀 때는 문서·예시·검증기·테스트를 함께 검토한다. 가중치 계산의 타당성, 실제 업무 의미, 개인정보 탐지 성능, 서버 권한, 승인 규칙 발행, Fabric 동작은 확인하지 않는다. 모든 문법의 CommonMark를 처리하는 도구도 아니다.

## 다른 로컬 예시 검사

기존 예시와 같은 계약 형태의 파일을 지정할 수 있다. 파일 내용은 로컬에서 읽고 외부로 전송하지 않는다. 보고서에는 원문 값 대신 오류 분류·필드 위치·입력 해시를 기록한다.

```powershell
python -X utf8 experiments/ai-contract-validation/validate.py --example "C:\my-work\exchange.json"
```

## 원문을 수정했을 때

Markdown의 내용을 수정한 뒤 HTML을 갱신하고 다시 검증한다. 버전이 바뀌면 파일명, 문서 머리말·제목·꼬리말, JSON 요청·응답의 계약 버전, `bundle.json`을 함께 맞춘다. HTML 갱신기는 **본문만** 갱신하며 버전을 임의로 바꾸지 않는다. 제목·본문·표·순서 목록·강조·인라인 코드 형식을 지원한다.

```powershell
python -X utf8 experiments/ai-contract-validation/render_html.py
python -X utf8 experiments/ai-contract-validation/validate.py
python -X utf8 -m unittest discover -s experiments/ai-contract-validation -p test_validate.py -v
```

검증 통과는 실제 API 연결, 모델 성능 또는 Gate 승인 증적과 별개다. 이 도구는 기존 공통 모델 평가(`python -m evaluation`)와 독립적으로 실행한다.
