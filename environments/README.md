# 실행 환경

공통 재채점·run 기록은 Python 3.13 표준 라이브러리만 필요하다.

기존 알고리즘 환경은 다음 파일을 원문으로 유지한다. 서로 다른 환경의 requirements를 한 번에 합쳐 설치하지 않는다.

- 그래프: experiments/maps-graph-lab/requirements.txt
- 기존 기본 비교: experiments/local-model-benchmark/requirements.txt
- 실제 임베딩 모델: experiments/local-model-benchmark/requirements-models.txt
- 당시 실제 설치 잠금 기록: experiments/local-model-benchmark/results/latest/requirements-models.lock.txt

새 모델은 필요하면 별도 가상환경과 환경별 requirements/lock 파일을 추가한다. 가중치·캐시·가상환경은 Git에 넣지 않고 모델 revision과 파일 해시를 실행 기록에 남긴다. 모델 다운로드/새 추론은 현재 공통 recorder가 수행하지 않는다.
