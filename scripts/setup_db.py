"""Create the Sabermetrics SQLite database with all tables.

Idempotent: uses CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
Run: python scripts/setup_db.py [--db-path data/sabermetrics.db]
     python scripts/setup_db.py --prepare-corpus
"""

from sabermetrics.runtime.schema import (
    COMMANDER_CANDIDATE_VIEW_SQL,
    DDL_STATEMENTS,
    ensure_portal_schema,
    ensure_runtime_schema,
    main,
    setup_database,
)

__all__ = [
    "COMMANDER_CANDIDATE_VIEW_SQL",
    "DDL_STATEMENTS",
    "ensure_portal_schema",
    "ensure_runtime_schema",
    "main",
    "setup_database",
]


if __name__ == "__main__":
    main()
