"""Opt-in public-card embedding preparation (operator CLI).

Writes a separate SQLite cache. Never runs on the request path, never
alters the application database schema, and never reads user tables.

Usage:
    python -m sabermetrics.runtime.prepare_embeddings --db PATH --cache PATH [--batch-size 64]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from sabermetrics.analytics.embeddings import EmbeddingService

# Canonical public-card identity only. Do not expand this query to user tables.
_PUBLIC_CARD_SQL = """
SELECT oracle_id, MIN(oracle_text) AS oracle_text
FROM cards
WHERE oracle_id IS NOT NULL
  AND TRIM(oracle_id) != ''
  AND oracle_text IS NOT NULL
  AND TRIM(oracle_text) != ''
GROUP BY oracle_id
ORDER BY oracle_id
"""


def load_canonical_oracle_texts(db_path: Path) -> list[tuple[str, str]]:
    """Load distinct oracle_id / oracle_text pairs from the public cards table."""
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = conn.execute(_PUBLIC_CARD_SQL).fetchall()
    finally:
        conn.close()
    return [(str(oracle_id), str(oracle_text)) for oracle_id, oracle_text in rows]


def prepare_public_card_embeddings(
    db_path: Path,
    cache_path: Path,
    *,
    batch_size: int = 64,
    service: EmbeddingService | None = None,
) -> dict[str, Any]:
    """Incrementally embed canonical public-card oracle texts into ``cache_path``.

    Args:
        db_path: Application SQLite database (read-only cards query).
        cache_path: Separate embedding cache file; created if missing.
        batch_size: Texts per ``embed_batch`` call.
        service: Optional preconfigured EmbeddingService (tests).

    Returns:
        Count summary: oracle_ids, unique_texts, cache_hits, newly_encoded, batch_size.
    """
    if batch_size < 1:
        raise ValueError("batch-size must be >= 1")

    db_path = Path(db_path)
    cache_path = Path(cache_path)
    if db_path.resolve() == cache_path.resolve():
        raise ValueError("cache must be separate from application database")
    pairs = load_canonical_oracle_texts(db_path)

    if service is None:
        service = EmbeddingService(cache_path=cache_path)

    unique_texts: list[str] = []
    seen_texts: set[str] = set()
    for _oracle_id, text in pairs:
        if text in seen_texts:
            continue
        seen_texts.add(text)
        unique_texts.append(text)

    cache_hits = 0
    missing: list[str] = []
    for text in unique_texts:
        if service._lookup_cached(text) is not None:
            cache_hits += 1
        else:
            missing.append(text)

    for offset in range(0, len(missing), batch_size):
        service.embed_batch(missing[offset : offset + batch_size])

    return {
        "oracle_ids": len(pairs),
        "unique_texts": len(unique_texts),
        "cache_hits": cache_hits,
        "newly_encoded": len(missing),
        "batch_size": batch_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare public-card embeddings into a separate SQLite cache. "
            "Reads canonical oracle_id/oracle_text only; does not modify the "
            "application database."
        )
    )
    parser.add_argument(
        "--db", type=Path, required=True, help="Application SQLite database"
    )
    parser.add_argument(
        "--cache",
        type=Path,
        required=True,
        help="Embedding cache SQLite path (created if missing)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Texts per embedding batch (default 64)",
    )
    args = parser.parse_args(argv)
    stats = prepare_public_card_embeddings(
        args.db, args.cache, batch_size=args.batch_size
    )
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
