# Package 1 — installed resources and schema readiness

Own config.py, config consumers' path expressions ONLY, pyproject.toml,
scripts/setup_db.py, server.py, scripts/smoke_container.py, and new runtime tests.
Do not alter builder behavior, profiles, jobs or UI.

Implement central config_path with packaged configuration files, optional explicit
SABER_CONFIG_DIR, safe filename validation and required-file errors. Avoid divergent
copied configuration versions. All loaders (rules, signatures, role templates,
Karsten, auto-includes, game changers etc.) must work from an installed wheel with
unrelated cwd. Test real expected values, not merely file existence. Essential
missing/malformed files fail readiness; optional corpus absence remains graceful.

Audit actual consumers against initial schema. Add idempotent, additive migration
for cards.role_tags, functional_categories and decks.popularity_rank and every
required field used by ramp/removal/protection readers. Ensure public card role
initialization and candidate detectors have an explicit idempotent preparation
path for both fresh and existing public corpus. Do not seed/reseed user data or
run heavy updates per request. Wire required migration/readiness at startup and
provide operator preparation if corpus work is heavy. No automatic external fetch.
Ensure optional empty historical deck corpus is not a SQL error.

Extend installed offline smoke to run real scoring loaders, empty-corpus SQL paths
and migrated synthetic card generation helpers. Preserve existing DB records and
verify repeated migration and old-schema upgrade. Include migration versioning.
