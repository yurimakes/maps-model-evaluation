# 표준화 CSV 자동 성능평가

AI 팀원의 CSV·ZIP과 한 번 확정한 정답 CSV를 비교하는 로컬 평가 도구입니다.
Python 3.10 이상, 추가 패키지·LLM API 없이 실행합니다. 기존 저장소의 평가 모듈과 별도로 동작합니다.

## 가상 예제로 확인

이 폴더에서 실행하세요.

```sh
python evaluate.py run --ai examples/predictions.csv --gold examples/gold.csv --out results/example --dataset-id 가상예제_실제프로젝트아님
python -m unittest discover -s . -p "test_evaluate.py" -v
```

`results/example/보고서.html`을 엽니다. 예제 점수는 실제 프로젝트 성능이 아닙니다.

## 실제 평가

1. 실제 파일은 로컬 `inputs/`에 보관합니다. 정답 형식은 `examples/gold.csv`를 참고하세요.
2. 아래 명령을 실행합니다. Windows에서는 AI 파일을 `실행.cmd` 위로 끌어다 놓아도 됩니다. 이때 같은 폴더에 `정답.csv`를 준비하세요.
3. 보고서와 `틀린항목.csv`, `확인필요.csv`를 확인합니다. 매번 전체를 수작업 채점할 필요는 없습니다.

```sh
python evaluate.py run --ai inputs/ai.zip --gold inputs/gold.csv --out results/baseline --dataset-id source-v1
```

입력은 표준화 CSV 6개가 있는 ZIP·폴더 또는 `examples/predictions.csv`와 같은 공통 CSV입니다.
정답상태=확정, 독립성=확인, 정답버전·근거·검토자가 있어야 채점합니다. 정답은 최초 한 번 확인해 재사용합니다.
`prepare --ai inputs/ai.zip --out inputs/template`으로 빈 정답 양식을 만들 수 있습니다.

영역별 일치율·오류율·커버리지·미결정률과 분자·분모를 기록합니다. 정답 미확정은 오답이나 정확도 0%로 처리하지 않습니다.
의미상 일치는 정답지의 `의미상허용값`에 미리 승인한 표현만 인정합니다. 자동 수용률은 이번 출력에 대한 사람의 직접 승인율과 다릅니다.
앞자리 0·대소문자는 보존하고, 중복 키는 중단하며, 정답이 있는 AI 누락은 불일치로 셉니다.
컬럼 연결은 선택한 표준용어를, 도메인은 명세를 비교합니다. 실제 원천값 변환 품질은 별도 검증 대상입니다.

## 개선 전후 비교

```sh
python evaluate.py run --ai inputs/improved.zip --gold inputs/gold.csv --out results/improved --dataset-id source-v1
python evaluate.py compare --before results/baseline --after results/improved --out results/comparison
```

정답·범위·평가 방법·원천 버전 표시가 같아야 비교합니다. 실제 원천 내용의 동일성은 담당자가 확인합니다.
단어는 구성단어 순번으로 비교하므로 분해 개수가 바뀌면 단어 비교를 중단합니다. 기존 결과 폴더는 덮어쓰지 않습니다.
실제 CSV·ZIP·정답·평가 결과는 커밋하지 않습니다. 포함된 CSV는 가상 예제뿐입니다.
