"""Runtime helpers: schema migrations, readiness, and public-corpus preparation."""

from sabermetrics.runtime.prepare import ROLE_TAG_VERSION, prepare_public_corpus
from sabermetrics.runtime.readiness import (
    ReadinessError,
    ReadinessReport,
    assert_readiness,
    check_readiness,
)
from sabermetrics.runtime.schema import (
    COMMANDER_CANDIDATE_VIEW_SQL,
    DDL_STATEMENTS,
    SCHEMA_VERSION,
    apply_schema_migrations,
    current_schema_version,
    ensure_portal_schema,
    ensure_runtime_schema,
    setup_database,
)
from sabermetrics.runtime.scoring import (
    assert_installed_scoring_values,
    load_installed_scoring_values,
)
from sabermetrics.runtime.synthetic import (
    SYNTHETIC_CARDS,
    insert_synthetic_cards,
    insert_synthetic_cards_at,
    query_empty_corpus_safe,
    query_empty_corpus_safe_at,
)

__all__ = [
    "COMMANDER_CANDIDATE_VIEW_SQL",
    "DDL_STATEMENTS",
    "ROLE_TAG_VERSION",
    "SCHEMA_VERSION",
    "SYNTHETIC_CARDS",
    "ReadinessError",
    "ReadinessReport",
    "apply_schema_migrations",
    "assert_installed_scoring_values",
    "assert_readiness",
    "check_readiness",
    "current_schema_version",
    "ensure_portal_schema",
    "ensure_runtime_schema",
    "insert_synthetic_cards",
    "insert_synthetic_cards_at",
    "load_installed_scoring_values",
    "prepare_public_corpus",
    "query_empty_corpus_safe",
    "query_empty_corpus_safe_at",
    "setup_database",
]
