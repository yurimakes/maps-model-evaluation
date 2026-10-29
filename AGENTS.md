# MAPS phase-2 upgrade work

- The goal is to improve the existing phase-2 MAPS RAG/mapping workflow while retaining its datasets and target schema.
- Commit code, tests, policies, evaluation input snapshots, predictions, metrics and execution logs to https://github.com/yurimakes/maps-local-model-benchmark . The repository must stay PRIVATE. The human explicitly requested snapshots for all experiments.
- Use `python record_run.py --label <name> --commit --push` for a complete recorded experiment. Preserve failed test logs as well as successful runs.
- Keep source ZIPs, original project references, and raw source datasets unchanged. Track metadata-only evaluation snapshots and hashes; omit installed libraries, caches and credentials.
- Distinguish old-output replay, approved-mapping lookup, cross-source evaluation, and independent unseen-data evaluation. Do not label replay gains as confirmed phase-2 production improvement.
- Preserve original AI predictions. Additional proposals go to Human Review and must not create approval or migration state automatically.
- The original phase-2 RAG execution code was requested from a teammate and has not yet been supplied. Do not claim to have rerun it.
