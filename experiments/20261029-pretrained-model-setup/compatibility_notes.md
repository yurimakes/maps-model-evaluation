# Runtime compatibility record

- Initial actual MPNet inference completed on 118 common texts. Official Magneto's bipartite stage then failed because Valentine 1.1.0 MatcherResults has no pop method. This full experiment failure is preserved in commit 19d5a59 and its actual_neural_model_comparison.log.
- Pinning Valentine 0.5.0 without dependencies initially raised ModuleNotFoundError: jellyfish during an import preflight. This was an environment dependency failure, not a scored model prediction.
- Installing latest jellyfish exposed its <1.3 constraint and PuLP's <4.0 constraint. The proper resolver installed jellyfish 1.2.1 and PuLP 3.3.2.
- The final environment has Valentine 0.5.0 with dict-compatible pop/update methods. Official Magneto source files were not modified. The complete actual three-model inference and matching run then succeeded; its package lock and outputs are preserved.
- Model download code now pins the exact three checkpoint revisions used in this run, including for a fresh environment.
