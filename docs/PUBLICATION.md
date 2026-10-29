# 통합 저장소 게시

사용자가 새 저장소 https://github.com/yurimakes/maps-model-evaluation 에 커밋하도록 승인했다. 게시 직전 이 저장소가 private이며 브랜치가 없는 빈 저장소임을 확인했다.

- main: 기존 benchmark 이력에서 이어지는 통합 커밋
- archive/maps-local-model-benchmark: 원본 benchmark의 main (8개 커밋)
- archive/maps-ontology-graph: 원본 ontology의 main (2개 커밋)

원본 두 저장소에는 쓰지 않는다. merge commit, 강제 push, 기존 커밋 재작성, 삭제, 공개 전환은 수행하지 않는다. 두 이력은 독립 보관 브랜치로도 게시하므로 일반 clone 후 원격 보관 브랜치에서 조회할 수 있다.

INTEGRATION_REPORT.md와 provenance/final-verification.json의 미커밋·게시 전 상태는 해당 시점의 점검 기록이다. 게시 이후 상태와 구분한다. 원본 자산 바이트 검증은 provenance/import-manifest.json을 기준으로 수행한다.
