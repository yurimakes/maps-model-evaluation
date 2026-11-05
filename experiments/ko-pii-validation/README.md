# 06 ko-pii 개인정보 탐지와 마스킹 검증

기존 라이브러리 검토에 이어, 상담 구어체와 CSV·JSON의 개인정보 처리 결과를 직접 확인한 후속 실험입니다.
**정형 데이터는 컬럼을 명시하면 조건부 적용 가능하고, 상담 자유문장은 보완 후 재검증이 필요합니다.**

검증일은 2026-11-05입니다. 모든 시험값은 이 실험을 위해 작성한 합성 데이터이며 실제 MAPS 고객 원문이 아닙니다.
전체 파이프라인 통합, 별도 모델 개발·학습, 논문 구현은 포함하지 않았습니다.

## 저장된 결과

[결과 보고서](../../results/ko-pii/20261105-synthetic-v1/report.md) · [브라우저용 보고서](../../results/ko-pii/20261105-synthetic-v1/report.html) · [사례별 결과 CSV](../../results/ko-pii/20261105-synthetic-v1/case_review.csv)

| 시험 | 범위 | 확인한 결과 |
|---|---|---|
| 텍스트 STRICT | 53건·정답 53구간·13개 라벨 | 정탐 39, 미탐 14, 오탐 5, 원문 전체 잔존 15구간 |
| 그중 상담 구어체 | 10건·정답 18구간 | 정탐 10, 미탐 8, 오탐 2, 원문 전체 잔존 8구간 |
| CSV 헤더 자동 매핑 | 8행·개인정보 46셀 | 원문 잔존 22셀 |
| JSON 문자열 자동 탐지 | 같은 8행·46셀 | 원문 잔존 27셀 |
| CSV·JSON 개인정보 필드 명시 | 같은 6개 컬럼·46셀 | 각 방식에서 해당 46셀의 원문 잔존 0 |

정탐/미탐은 라벨·문자 시작·끝 위치가 같은 구간 기준입니다. 오탐은 정답에 없는 탐지 후보이며 실제 치환 여부와 구분합니다.
텍스트 시험은 PHONE, EMAIL, RRN, FRN, CARD, ACCOUNT, PERSON, ADDRESS, DT_BIRTH, PASSPORT, VEHICLE, DRIVER_LICENSE, IP의 13개 라벨만 선택했습니다. 패키지 전체 라벨의 성능평가가 아닙니다.
명시 필드의 잔존 0은 자동 탐지 정확도 100%가 아닙니다. policy_id와 상담 메모 등 비매핑 값에는 원문이 남습니다.
PARANOID에서 주소 일부만 치환된 사례도 있으므로, 전체 문자열이 사라졌다는 이유만으로 보호 성공으로 판정하지 않습니다.
숫자형 식별자, null, 잘못된 필드 경로·bool·float 입력 및 입력 객체·파일 보존도 별도로 확인했습니다.

## 재현

Python 3.10 이상이 필요하며 실제 로컬 측정은 Python 3.12.14와 ko-pii 1.22.17로 수행했습니다.
저장소 루트에서 실행합니다. 의존성 버전과 배포 파일 해시는 requirements.txt에 고정했습니다.

```sh
python -m pip install --require-hashes -r experiments/ko-pii-validation/requirements.txt
python experiments/ko-pii-validation/run.py --out results/ko-pii/my-new-run
python experiments/ko-pii-validation/verify_results.py --results results/ko-pii/my-new-run
```

`--out`은 저장소의 results/ko-pii 아래 새 폴더만 허용하며 기존 폴더를 덮어쓰지 않습니다.
코드·입력 해시는 각 실행의 provenance.json에 기록됩니다. verify_results.py는 고정 합성 입력의 회귀 검사이며 독립 실데이터 성능평가가 아닙니다.
출력 일부가 준비된 뒤 실행이 실패할 수 있으므로 완료 여부는 종료 코드와 summary.json으로 확인하고 실패 폴더는 재사용하지 않습니다.
새 실행에는 새 폴더명을 사용합니다. 원문·정답 fixture 파일은 실행 중 수정하지 않습니다.

외부 API·모델을 호출하지 않습니다. 설치된 라이브러리의 규칙을 실제로 실행하며 저장된 기존 예측의 단순 재채점과 구분합니다.
기존 매핑 실험의 comparison_key나 매핑 정확도 표에 개인정보 탐지 지표를 합치지 않습니다.

## 파일

- fixtures/text_cases.jsonl: 위치 정답이 표시된 합성 텍스트 53건
- fixtures/synthetic_input.csv 및 .json: 같은 합성 상담 레코드 8행
- probe.py: STRICT/PARANOID 탐지와 마스킹 후 전체·부분 잔존 확인
- structured.py: CSV/JSON 자동 처리와 명시 필드 마스킹 비교
- run.py: 고정 입력을 읽어 새 실행 폴더에 기록
- verify_results.py: 고정 기대 결과와 입력 보존·오류 거부 확인
- results/ko-pii/20261105-synthetic-v1: 최초 검증의 보존 결과(저장소 루트 기준)

상담 예제는 텍스트이며 음성 녹음이나 STT 정확도를 평가하지 않았습니다.
소규모 합성 입력이며 이름·번호가 반복돼 독립 표본으로 해석할 수 없습니다. 실제 MAPS 고객 데이터의 일반 성능이나 운영 배포 완료를 뜻하지 않습니다.

## 출처와 사용 고지

- [ko-pii 1.22.17](https://github.com/Marker-Inc-Korea/ko-pii/releases/tag/v1.22.17), upstream commit 8957e8bc9f0ade3d21381734523b18920330c159
- [구조화 처리](https://github.com/Marker-Inc-Korea/ko-pii/blob/8957e8bc9f0ade3d21381734523b18920330c159/docs/STRUCTURED_PROCESSING.md)
- [평가 안내](https://github.com/Marker-Inc-Korea/ko-pii/blob/8957e8bc9f0ade3d21381734523b18920330c159/docs/DOMAIN_EVALUATION.md)

ko-pii의 MIT 고지는 [LICENSE.ko-pii.txt](LICENSE.ko-pii.txt)에 보존했습니다. 프로젝트의 다른 코드·데이터에 일괄 라이선스를 부여하지 않습니다.
공개 파일은 합성 입력과 그 결과, 검증 코드·집계 보고서로 제한했습니다. 실제 고객 행·내부 원천 데이터·실행환경·wheel·캐시는 포함하지 않습니다.
