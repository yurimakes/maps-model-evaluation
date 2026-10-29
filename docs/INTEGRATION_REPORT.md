# MAPS 두 실험 저장소 로컬 통합 결과

2026-10-29, Asia/Seoul. GitHub 원격 조회와 `C:/choiyuri/msdt-team-project-03/`의 실제 체크아웃을 함께 확인했다. 원격 조회 시점의 HEAD를 아래에 고정했으며, 작업 종료 전 GitHub에서 같은 HEAD임을 다시 확인했다.

## 대상 확정과 최신 상태

이전 프로젝트 대화 **「레포지토리 이름 확정」** (`6ae2e57c-3588-83ee-8e25-6bb736c8a49a`)에서 두 이름이 확정됐다. 이어지는 **「실험 레포 운영 비교」** (`6ae350ea-6d70-83ec-afc5-5429e79c6120`)의 `maps-model-evaluation`은 통합 구조의 제안 이름이다. 이번에는 그 이름으로 새 로컬 작업본만 만들었다.

| 항목 | maps-ontology-graph | maps-local-model-benchmark |
|---|---|---|
| GitHub | yurimakes/maps-ontology-graph | yurimakes/maps-local-model-benchmark |
| 공개 범위 | private | private |
| 원격/로컬 브랜치 | main만 존재 | main만 존재 |
| 원격·로컬 HEAD | 740bca59ebbd8c2bae9275a2d97e8c8631d14dc5 | 3bf941ebf81e717fe3cefcb040d2a564642b9500 |
| 기존 커밋 수 | 2 | 8 |
| HEAD 추적 파일 수 | 72 | 369 |
| 추적 파일 바이트 | 5,630,726 | 15,672,303 |
| 실제 체크아웃 미커밋·미추적 | 없음 | 없음 |
| 로컬 제외 파일 | 설치 환경 등은 별도 상태 목록으로 보관 | 모델·설치 환경·브론즈 원천·로컬 설정 등 존재, 통합 제외 |

각 저장소 전체 파일 트리와 blob ID·크기는 `provenance/source-trees.json`에, 브랜치·HEAD·커밋 목록·로컬 상태는 `provenance/repository-state.json`에 있다. 원격 기본 브랜치와 모든 원격 refs는 mirror/bundle에도 보존했다. 숨겨진 GitHub 내부 refs나 접근 불가능한 다른 사용자의 작업 공간은 점검 범위가 아니다.

## 실제 적용한 변경

기존 benchmark를 새 로컬 Git 작업본의 기반으로 복제하고, 파일을 `experiments/local-model-benchmark/`로 이동했다. ontology의 `experiments/maps-graph-lab/`, `experiments/maps-local-lab/`, `research_support/`를 함께 가져왔다. 그래프의 형제 폴더 import 관계와 각 실험 내부 상대 경로를 유지했다. 기존에 동명 코드가 있어도 당시 버전·예측·실패 로그를 각각 보존하며 중복 삭제하지 않았다.

공통 `evaluation/`과 `configs/suites.json`으로 지표 산식과 평가 범위 검증을 새로 추가했다. 기존 코드의 생성 방식·보류 임계값·예측은 바꾸지 않았다. 공통 결과는 새 `results/common/` 아래에 기록한다. 기존 스크립트·과거 성능표는 당시 기록으로 남겼다.

원본 파일별 이전/이후 경로, Git blob, SHA-256을 `provenance/import-manifest.json`에 기록했다. 자체 검증에서 원본 **441개 모두 byte 일치**를 확인했다. Windows 체크아웃의 줄바꿈 변환이 개입하지 않도록 최종 보관 파일은 원래 Git blob 바이트로 맞췄다. 기존 AGENTS의 자동 commit/push 지시는 원문을 `provenance/benchmark-root/AGENTS.md`에 보관하고 현재 작업 지침으로 교체했다. 새 루트 문서와 실행기는 로컬 검토 범위만 안내한다.

두 원본 이력은 새 작업본의 `refs/archive/maps-ontology-graph/main`, `refs/archive/maps-local-model-benchmark/main`으로 보존했다. benchmark의 8개와 ontology의 2개, 총 10개 커밋은 변경하지 않았다. 기존 main과 다른 이력을 합치는 merge commit은 만들지 않았다. 따라서 현재는 단일 작업 디렉터리 안의 통합 파일 배치와 분리된 원본 이력이 보존된 상태이며, 향후 단일 GitHub 저장소로 게시/merge하는 단계는 별도 승인 대상이다.

형제 `../maps-integration-preservation-20261029/`에는 두 저장소의 mirror, 검증한 `.bundle`, 초기 상태·전체 트리·보안 점검을 따로 보관했다. bundle은 Git 이력만 담으므로 현재 미커밋 통합 파일은 이 작업본과 함께 보관해야 한다. 새 작업본에는 origin을 설정하지 않고 원본 두 곳의 upstream URL만 기록했으며 push URL은 로컬 검토용 비활성 값으로 지정했다. 원본 저장소의 remote 설정은 건드리지 않았다.

## 검증과 차이점

| 검증 | 결과 |
|---|---|
| 원본 자산 해시 | 441개 전부 일치 |
| Git 이력 | 원본 2 + 8개, bundle verify·Git fsck 통과 |
| 공통 평가 | 6개 등록 범위, 37개 방법/성능표, 2,898개 예측 |
| 과거 지표 대조 | 37개 전부 1e-12 허용오차 안에서 일치 |
| 공통 평가 계약 테스트 | 6개 통과 |
| 최신 benchmark 테스트 | 32개 통과 |
| 당시 로컬 실험 테스트 | 5개 통과 |
| 그래프 검증 | 5원천×2방법 정답 변경 10조건에서 점수·임계값 불변 |
| DB·입력 검증 | SQLite 무결성, dangling edge 0, 원본 51파일 해시 불변 |
| 원본 체크아웃 종료 상태 | 두 곳 모두 main/기존 HEAD 유지, 미커밋·미추적 변경 없음 |

새 성능 향상 수치를 만들지 않았다. 기존의 F1·TP/FP/FN·Top-K는 그대로 재현됐다. 달라진 것은 공통 보고에서 decision accuracy와 exact set accuracy, 질문 Top-K 적중과 정답 쌍 recall을 명시적으로 구분한 점이다. 114문항/78후보 실험의 17개 성능표, 93문항 모델 8개, 18문항 모델 8개, 18문항 과거 재생 4개를 서로 다른 비교 그룹으로 관리한다. 같은 입력·프로토콜인 앞의 17개만 같은 comparison_key를 공유한다.

검증은 저장 예측 재채점과 기존 평가/누출/계약 검사를 실행한 것이다. 모델 가중치를 다시 내려받거나 사전학습 모델을 재추론하거나 Azure LLM을 호출하지 않았다. 그래프 검증 파일은 임시 복제본에 기록하여 원래 verification.json을 보존했다. 원본 데이터 재구축이나 운영 notebook의 Databricks 쓰기도 수행하지 않았다.

실행 증거는 `results/common/integration-check/`와 `results/validation/20261029T232702+0900/`에 있다. 전체 상태 재확인은 `provenance/final-verification.json`을 참고한다.

## 미확정 사항과 다음 승인 경계

라이선스·민감정보의 세부 근거는 [별도 검토 기록](LICENSE_AND_SECURITY.md)에 정리했다. 핵심 미확정 사항은 자체 코드/데이터의 재배포 허가, SRoBERTa 체크포인트 라이선스, fuzzywuzzy GPLv2 포함 의존성 검토, graph DB의 전화번호 형태 예시와 내부 문서·프로파일 공유 범위다. 해당 자산은 삭제하거나 원본 이력에서 제거하지 않고 비공개 로컬 검토본에 보존했다.

현재 통합에 사용자 판단이 필요한 삭제·덮어쓰기·이력 변경은 없어 안전한 작업을 완료했다. 이후 GitHub 대상 선택/생성, 커밋, push, PR, merge, 공개 전환, 원본 레포 삭제, 이력 정리, 데이터 삭제는 이번 작업으로 승인된 것이 아니다. 필요한 조치가 정해지면 대상·변경 내용을 구체화해 해당 조치만 승인받는다.
