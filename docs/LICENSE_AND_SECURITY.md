# 라이선스와 민감정보 확인

2026-10-29 로컬 통합 범위 확인 결과다. 원본 삭제·비식별화·이력 정리는 수행하지 않았다. 원본 산출물의 보존과 공개 가능 여부는 별개이며, 공개·재배포 승인을 뜻하지 않는다.

## 라이선스

| 대상 | 확인 근거 | 상태 |
|---|---|---|
| 자체 실험 코드·보고서·평가 결과 | 두 저장소 HEAD 및 이력의 파일 트리 | 루트 LICENSE/재배포 허가 없음. 임의 라이선스 부여 안 함 |
| Magneto 코드·이름 비교 함수 | 각 third_party/LICENSE.txt와 magneto_full/LICENSE.txt, PROVENANCE.json | Apache-2.0 문서와 commit `6620623265fc7feac0f053996e62b68a13a72a57` 보존 |
| all-mpnet-base-v2 | 기존 실행 metadata 및 고정 revision 모델 카드 | Apache-2.0 표기 확인 |
| multilingual-e5-small | 기존 실행 metadata·로컬 고정 체크포인트 README | MIT 표기 확인 |
| ko-sroberta-multitask | 기존 실행 metadata license=null, 고정 revision 카드 | 명시 라이선스 미확인; 사용/배포 권한 추가 확인 필요 |
| fuzzywuzzy 0.18.0 | 설치된 METADATA의 License 및 classifier | GPLv2. 전체가 Apache/MIT라고 표시할 수 없음 |
| 기타 직접 의존성 | provenance/dependency-license-inventory.json | 기존 두 환경에서 23개 metadata 기록. pypdf 기록 미확보, jellyfish license 필드 등 추가 확인 필요. 전이 의존성 전체 검토는 아님 |
| 프로젝트 원천·매핑정의서·문서·프로파일·임베딩 | snapshot/manifest·phase2_original·phase2_bundle·graph DB | 별도 데이터 이용/재배포 허가 미확인. 내부 연구용으로 보존 |
| AI-Hub 등 외부 원자료 | 이번 Git 통합 트리에서 특정 데이터셋의 이용허락 근거 확보 못함 | 데이터셋 ID/다운로드 계정/약관 확인 전 임의 재배포 판단 불가 |

자체 코드·실험 결과·데이터가 같은 라이선스라는 가정을 하지 않았다. 오픈소스 코드의 라이선스가 프로젝트 자료·문서 본문·캐시 임베딩에 자동 적용된다고 보지 않는다. 가중치와 설치된 라이브러리는 가져오지 않고 기존 revision·해시·설치기록을 보존했다. benchmark 기본 환경과 모델 환경은 pandas/scikit-learn 등의 버전이 달라 requirements를 합치지 않았다.

고정 모델 카드: [MPNet](https://huggingface.co/sentence-transformers/all-mpnet-base-v2/blob/e8c3b32edf5434bc2275fc9bab85f82640a19130/README.md), [E5](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md), [SRoBERTa](https://huggingface.co/jhgan/ko-sroberta-multitask/blob/8fca7c9c98c26599be0e14b9916b11a756a26f19/README.md). 외부 웹에서는 MPNet의 Apache 표기와 SRoBERTa의 라이선스 미표기를 재확인했고, E5는 보관된 로컬 자료를 근거로 했다.

## 민감정보

두 mirror의 모든 도달 가능한 과거 blob **69개 + 247개 = 316개**를 검사했다. private key, GitHub/Hugging Face/OpenAI/AWS 토큰 형태, 문자열 자격증명 할당, 전화번호·주민번호 형태, 이메일, 내부 Azure/Databricks 경로를 탐지했다. 값은 결과에 복제하지 않고 blob·파일·행 번호만 기록했다.

- 인증키·비밀키·주민번호 형태 패턴은 발견되지 않았다. 이 결과는 모든 민감정보의 부재를 보증하지 않는다.
- graph `results/knowledge.sqlite` 문서 본문에서 전화번호 형태가 10회 발견됐다. `chunks` 5회와 FTS 검색 인덱스 5회로 중복 저장되어 있다. 주변 문맥은 phone_number/HP_NO 등 스키마·마스킹 설명의 예시지만, 실제 값인지 가상 값인지는 확정하지 않았다. 문서 본문의 주소 예시도 수동 검토 대상이다.
- benchmark 이력의 이메일 형태 3건은 profiles, DQ 지식, 원본 운영 코드에서 발견됐다. 예시·정규식인지 실제 개인정보인지 별도 검토 대상이다.
- Azure 관련 경로 형태 2건은 notebook_common.py의 원본/과거 스냅샷에 있다. 인증키 탐지와는 구분한다. 내부 인프라 이름·소스 경로·작성자 이름도 조직 정보일 수 있다.
- graph DB에는 문서 본문과 승인 매핑 68쌍이 있다. metadata-only라고 취급하면 안 된다. 과거 .npz 임베딩·프로파일도 내부 파생 자산으로 분류했다.
- 무시된 브론즈 원천 레코드, 모델, 라이브러리, 로컬 설정은 가져오지 않았다. 원본 체크아웃의 ignored 파일 목록은 별도 보관본에만 남겼다.

정규식은 한글 실명, 자유 서술 상담문, 바이너리/압축 내부 전체, 의미상 개인정보를 완전히 식별할 수 없다. SQLite는 read-only로 열어 위 탐지 항목의 저장 위치와 문맥을 추가 확인했다. 원본/이력을 그대로 보관하는 대신, 업로드·공개 전에는 해당 자료의 공유 범위와 허가를 확인해야 한다. 검토 결과 파일은 `provenance/security-scan.json`이다.

이번 로컬 통합을 완료하는 데 삭제·덮어쓰기·이력 재작성이 필요하지 않아 그런 승인은 요청하지 않았다. 민감정보 삭제나 이력 정리가 필요해지면 변경 대상·영향을 구체화한 뒤 그 조치만 별도 승인받는다.
