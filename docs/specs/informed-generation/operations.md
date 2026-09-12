# Preparing and enabling informed generation

The default build needs no simulator. Facts compile from current public card
text; missing disk caches fall back to normal computation. All new artifacts
are separate from the application database. Existing schema, ownership checks,
job locking and model usage accounting remain active.

Use the same immutable model commit and configured model name during preparation
and serving. An unset revision disables persistent embedding reuse. Preparation
is an operator job after card ingestion, never a startup migration or request job.

```sh
export SABER_EMBEDDING_REVISION=<immutable-model-commit>
export SABER_EMBEDDING_CACHE=/data/prepared/embeddings.sqlite
export SABER_CARD_FACTS=/data/prepared/card-facts.json
python -m sabermetrics.runtime.prepare_embeddings \
  --db /data/sabermetrics.db --cache "$SABER_EMBEDDING_CACHE" --batch-size 128
python -m sabermetrics.runtime.prepare_card_facts \
  --db /data/sabermetrics.db --output "$SABER_CARD_FACTS"
```

Facts snapshots are atomically published and keyed by parser version and exact
name/Oracle/type text. Stale or corrupt facts recompute. Embeddings use a separate
SQLite store with model/revision/text keys and validated finite vector shapes.
Preparation receipts contain public-card counts and artifact hashes, not users.
Ensure the service account can read facts and write its embedding cache.

Build the accompanying simulator branch with its existing release preset:

```sh
cmake --preset release
cmake --build --preset release
export SABER_RESOURCE_PROBE_BIN=/absolute/path/to/build/release/src/cli/cs
```

For a separate worker, configure `SIM_RESOURCE_TOKEN` privately on the simulator
and the same value as `SABER_RESOURCE_PROBE_TOKEN` on the generator. Set
`SABER_RESOURCE_PROBE_URL` to the private service base URL and leave the binary
variable unset. `/capabilities` advertises configuration and `/resource-simulate`
requires authentication. TLS or a trusted private network protects the token.
Do not expose this endpoint as an unauthenticated public simulator.

The generator limits a comparison to 15 seconds, with at most 3 seconds per
probe; the worker also caps games, concurrency and subprocess time. Busy,
timeout, incompatible schema, invalid hashes and unsupported land shapes produce
explicit evidence. Generation can finish without simulation, with no invented
measurement. Only basic-land colors change in this experiment; interaction and
all other spells are retained. Fresh confirmation seeds guard against choosing
a lucky screening result.

For release, build and test both revisions, enable the private worker first,
prepare artifacts, then exercise an isolated generator candidate. Record exact
image revisions and test owner access before routing traffic. Roll back the
generator image independently; the simulator endpoint is additive and can be
disabled by removing its token. Main and QA Deck Lab services require no changes.
