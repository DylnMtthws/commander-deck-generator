# Generator quality and observability contract

Owner requested: specify the observed Aang failures, implement with Cursor agents,
review independently, then deploy the passing result to generate.decklab.studio.
Scope: this standalone generator only. Preserve Deck Lab Main/QA URLs and images,
owner-only access, HF router/provider, private credentials, and cost accounting.
Baseline: 07d90f263af940877120897b9cf2a85c75140821.

Observed regression: a $1000, power-4 Aang build requesting four-mana copy
creatures returned 99 cards, 35 basics, a reported bracket of 2, and omitted
Spark Double and Sakashima despite both being legal and affordable. Narrative
claimed absent cards, invented abilities, and the profiler accepted invented
identity/time/set metadata. Installed configuration and schema mismatches disabled
several scoring signals. A timer masqueraded as progress. These observations are
requirements examples; do not include production records, private user identity,
credentials, or copied production databases in fixtures.

## Work packages and ownership

1. runtime.md: config resource resolution, migrations, readiness, packaged smoke.
2. grounding.md: profiler metadata/cache and grounded final narrative.
3. engine.md: builder selection/validation, intent contract and stage events.
4. jobs.md: durable owner-scoped job state and actual UI progress.

Agents each own their listed files and new focused modules/tests; do not edit
another package's files. Coordinator integrates shared contracts and resolves
conflicts. Do not commit/deploy/fetch external source/install dependencies. Use
only supplied source, test doubles and public synthetic fixtures. Report tests
that cannot run; never claim unrun checks passed.

## Shared interfaces

- Runtime exposes sabermetrics.config.config_path(name: str) -> Path, resolving
  explicit SABER_CONFIG_DIR first, packaged resources next, with checked required
  files. Existing load_settings(explicit_path) remains usable. Agent 1 updates
  ALL config consumers including builder ONLY its config-path expressions.
- Builder accepts optional progress_callback in DeckBuilder.__init__; callback
  receives (stage: str, progress: int). Stages: validate, profile, filter, score,
  template, infrastructure, optimize, review, narrative, persist, completed.
  Only emit completion AFTER persistence. No fake time-based progress.
- Builder feeds DeckSynthesizer actual FINAL card dictionaries with name, mana
  value, oracle text, type, role; existing name-only callers remain supported
  with conservative factual fallback. Agent 2 owns synthesis API; Agent 3 owns
  supplying facts from builder. Never fabricate facts for missing evidence.
- Builder persists `quality_warnings` in rationale JSON alongside narrative,
  composition and signals. Warnings include unmet target, missing signals,
  unavailable engine, failed final review. Agent 4 displays them for old/new decks.
- New jobs module accepts a callable work(progress_callback)->deck_id. It persists
  queued/running/completed/failed state, stage/progress/time, owner, safe error,
  deck_id. Routes own quota/login/CSRF and cost attribution inside worker.

## Acceptance and release gate

- Existing tests plus regression tests pass; touched code lint passes. Do not
  remove assertions or merely change expected failures into success.
- Wheel/container with arbitrary cwd loads real scoring config, initializes a
  fresh DB and upgrades legacy DB idempotently without destroying accounts,
  decks, prices, profiles, costs, or traces. Required config/schema checked before
  generation; optional absent corpus is distinctly reported.
- Aang clone-intent regression uses authoritative public card facts/synthetic
  records, mocked model responses and embeddings: reaches exactly 99+commander,
  legal singleton/color constraints, budget compliance and meaningful clone
  package that survives every swap/review. Also test another commander/no-intent
  case, impossible budget/engine, and adversarial model metadata/narrative.
- Final text cannot assert absent cards or unsupported mechanical interactions.
  Facts-only deterministic fallback is preferable to plausible fabricated advice.
- Job POST returns promptly; status is real, persistent, owner scoped, handles
  failure/restart and duplicate submissions; no repeated billed build on polling.
- Test exact installed CI artifact without network or production credentials;
  bounded live Aang evaluation only by coordinator in isolated generator data.
- Deploy only exact passing main image after coordinator acceptance, with backup,
  generator-only migration/restart and rollback compatible with additive schema.
  Preserve existing generator decks and sole enabled owner; preserve Main/QA.

## Performance and limitations

Persist stage timing and candidate/review counters where available. Keep the
existing CPU/memory bounds. Avoid a new queue server or paid service. Do not
promise a runtime SLO or claim bracket 4 achieved merely because it was requested.
Measure before optimizing embeddings; durable embedding cache is optional only
if supported by actual measurements and safe invalidation, not a release blocker.
