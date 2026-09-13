# Reproducing an offline paired study

Before launching a batch, freeze `src/`, `scripts/`, `config/` and the study wrapper; hash every file. Copy the original study database whose SHA256 is `3592bf8f2c5ef7a51b602b118e32b08d7da2375f29e6b620bba2a3d7462fee52` separately for each job, then run `sabermetrics.runtime.schema.apply_schema_migrations` on each copy. These migrations add nullable printed fields; do not backfill or mutate the original.

Freeze the existing selection-evidence directory and set `SABER_SELECTION_EVIDENCE` to that copy. Cached profiles use an evidence retrieval timestamp in their key, so a refreshed evidence cache can miss an otherwise unchanged profile. Preflight all commanders before generation. This study explicitly replays each commander’s exact original persisted `CommanderProfile`, checks identity, and records the raw profile hash and stored key; this bypass is confined to the offline wrapper. It does not restamp old metadata or regenerate a profile. Apply the identical profile bytes to both arms, and record request power separately from the commander-keyed cached profile.

Use the production-derived `ProductionReplay` class from `scripts/run_function_study.py`, with generation calls forbidden and credentials absent from the child environment. Required environment:

```sh
export PYTHONPATH="$FROZEN_SOURCE/src"
export SABER_CONFIG_DIR="$FROZEN_SOURCE/config"
export SABER_SELECTION_EVIDENCE="$FROZEN_EVIDENCE"
export SABER_EMBEDDING_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONHASHSEED=0
```

Pin the exact cached embedding revision; a cached snapshot without `refs/main` cannot resolve an unpinned model offline. Record the local model files’ hashes. These offline flags prevent embedding-loader cache freshness requests. They do not establish that embedding weights exist. Preflight the model cache and report any zero-embedding fallback explicitly; paired results with this fallback do not establish full production behavior.

First validate identity/cache/schema/evidence preconditions without building. Then run at most two jobs concurrently and stop after unexpected failures. Keep failed and interrupted artifacts separately; report completed builds independently from preflight attempts. Preserve rows, final decks, full intelligence, old draw audit, transition receipts, source/data/evidence/profile/harness hashes and elapsed times. Compare actual card and DRAW-slot changes, unchanged legacy credible/independent counts, final route receipts and known function opportunities. Never sum route counts and legacy card counts, or promote unknown/conditional diagnostics to guaranteed output.
