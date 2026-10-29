# 실제 모델 간 비교

이 실험은 코드 테스트나 모의 응답 평가가 아니다. 아래 사전학습 가중치를 로드해 CPU에서 실제 추론한다.

| 모델 | 공개 가중치 |
|---|---|
| MPNet | sentence-transformers/all-mpnet-base-v2 |
| 다국어 E5 | intfloat/multilingual-e5-small |
| 한국어 SRoBERTa | jhgan/ko-sroberta-multitask |

모델 리비전과 다운로드 파일의 SHA-256을 고정한다. 세 모델을 순서대로 로드하며 파인튜닝은 하지 않는다. 유료 추론 API를 호출하지 않고 입력은 외부에 전송하지 않는다. 모델 다운로드에 필요한 공개 저장소 요청은 별도다.

## 통제한 임베딩 모델 비교

원래 질문 문자열 `query_text(row)`와 Target 카드 문자열 `chunk_text(card)`를 그대로 재사용한다. 원본 캐시와 문자열 해시가 일치해야 실행한다. 기존 2차 임베딩 캐시와 새 모델 3개의 실제 추론 벡터에 동일한 코사인 분류기와 평가를 적용한다. E5는 공식 모델 카드의 대칭 유사도 사용법에 따라 양쪽에 `query: `를 붙인다.

이 표의 2차 임베딩 기준선은 기존 RAG 전체의 최종 LLM 추천이 아니다. 모델 백본의 성능을 같은 입력·같은 결정 방식에서 비교하는 실험이다.

## 공식 Magneto 매핑 실행

`third_party/magneto_full`에 보존한 공식 소스 commit `6620623265fc7feac0f053996e62b68a13a72a57`의 `Magneto.get_matches`를 실행한다. 실제 신경망 `EmbeddingMatcher`, 동일명 매칭, 공식 이분 매칭 재정렬을 모두 실행한다. 모델을 원천별로 다시 로드하는 비용만 줄이는 리소스 어댑터를 사용하며, 공식 소스는 수정하지 않는다.

Target의 실제 값 테이블이 제공되지 않아 공식 지원 설정 `header_only`를 사용한다. null 한 행은 타입·샘플링 도우미의 입력 형태를 맞추기 위한 것이며, 이 설정에서는 값이 모델 입력에 사용되지 않는다.

- 논문 설정 범위의 스키마 전용 조건: MPNet + 실제 컬럼명.
- MAPS 메타데이터 적용 조건: 각 모델 + 컬럼명·한글 설명·자료형.
- E5의 컬럼 인코더에는 query 접두사를 추가한다. 없는 EOS 토큰이 문자열 None으로 들어가지 않도록 인코더용 토크나이저의 빈 EOS를 빈 문자열로 처리한다.

Magneto 기본 비LLM 모드이며 GPT 재정렬·GDC 파인튜닝과 원논문 데이터셋 실험 전체를 재현한 것은 아니다. 원천을 기준으로 다른 4개 원천에서 선택한 문턱을 적용해 이관 제외도 평가한다.

최초 실행은 Valentine 1.1.0의 MatcherResults API 변경 때문에 이분 매칭 단계에서 실패했다. 실제 MPNet 추론은 끝난 상태였으며 실패 로그와 벡터를 보존했다. 공식 알고리즘을 수정하지 않고 사전형 API와 호환되는 Valentine 0.5.0 및 그 의존성 범위로 맞췄다.

## 평가 범위

- 원천 93질문: 매핑 정답 44개, 이관 제외 49개.
- 원래 2차 범위인 COUNSEL·COMPLAINT 25개 Target. 실제 채널별로 후보를 고정한다.
- 질문 하나당 Target 1개 또는 보류를 반환한다. 매핑 쌍의 Precision·Recall·F1과 제외 포함 정확도를 구분한다.
- 테스트 원천의 정답은 추천 문턱 선택에 사용하지 않는다. 문턱은 나머지 원천에서 F1을 기준으로 고정 그리드로 선택한다.
- 기존 2차 최종 출력은 홈페이지 18질문만 있어 동일 18질문 표에서만 직접 비교한다. rep=1과 30회 최빈 출력을 구분한다.
- 개발 과정에서 본 평가셋이다. 독립 평가셋 검증은 별도로 필요하다.

## 실행과 스냅샷

현재 환경: `python record_run.py --label pretrained-model-comparison --local-models --commit --push`

새 환경은 `setup_model_runtime.ps1 -DownloadModels`로 전용 CPU 환경과 모델을 준비한다. 모델 가중치·가상환경·로컬 런타임 경로는 Git에서 제외하고 모델 리비전·파일 해시·전체 패키지 버전·실행 로그·예측은 커밋한다.

보고서: `results/latest/neural_model_report.html`

## 출처

- https://github.com/VIDA-NYU/magneto-matcher
- https://huggingface.co/sentence-transformers/all-mpnet-base-v2
- https://huggingface.co/intfloat/multilingual-e5-small
- https://huggingface.co/jhgan/ko-sroberta-multitask
