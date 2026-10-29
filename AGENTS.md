# MAPS integrated local evaluation

- Do not commit, push, create PRs, merge, rewrite Git history, delete repositories or change visibility without explicit user approval.
- Keep original checkouts and synced sources read-only. Legacy assets are byte-preserved according to provenance/import-manifest.json.
- Run shared evaluation from the root with `python -m evaluation`. It re-scores saved predictions; it is not a model inference run.
- New runs use new folders under results/. Never overwrite historical outputs.
- Compare only equal comparison_key values; preserve evaluation scope and distinguish stored replay, cached retrieval, scripted tests and actual model inference.
- Preserve all third-party license notices. Project code/data and ko-sroberta licensing remain unresolved; do not assign a blanket license.
- Never upload internal data, embeddings, graph document text, raw source rows or new model outputs without checking their sharing scope.
- Legacy scripts that contain --commit/--push are archival entry points. Do not execute them for this task.
