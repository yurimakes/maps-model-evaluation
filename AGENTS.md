# MAPS phase-2 upgrade work

- The goal is to improve the existing phase-2 MAPS RAG/mapping workflow while retaining its datasets and target schema.
- Commit code, tests, policies, evaluation input snapshots, predictions, metrics and execution logs to https://github.com/yurimakes/maps-local-model-benchmark . The repository must stay PRIVATE. The human explicitly requested snapshots for all experiments.
- Use `python record_run.py --label <name> --commit --push` for a complete recorded experiment. Preserve failed test logs as well as successful runs.
- Keep source ZIPs, original project references, and raw source datasets unchanged. Track metadata-only evaluation snapshots and hashes; omit installed libraries, caches and credentials.
- Distinguish old-output replay, approved-mapping lookup, cross-source evaluation, and independent unseen-data evaluation. Do not label replay gains as confirmed phase-2 production improvement.
- Preserve original AI predictions. Additional proposals go to Human Review and must not create approval or migration state automatically.
- RAG.zip and maps_ai_demo_bundle.dat_(원본압축) were supplied on 2026-10-29. Original code, original corpus, source profiles and cached embeddings are available. Cached retrieval and validation code can be executed locally. Azure chat was not rerun; do not claim new end-to-end accuracy/precision/F1 from retrieval diagnostics or scripted contract tests.
- Phase-2 already uses hybrid BM25/embedding retrieval and channel-to-target rules. Its original candidate scope is COUNSEL/COMPLAINT (25 columns). Earlier 78-candidate explorations are a separate experiment and must not be reported as the phase-2 baseline.
- Keep original sources under phase2_original and actual knowledge under phase2_bundle. Changes are opt-in under phase2_upgrade. RRF+abbreviation expansion remains experimental because ranking diagnostics regressed at top-1; keep weighted fusion as the default.
