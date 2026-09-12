"""Public synthetic fixtures for installed-runtime smoke and tests.

Names and oracle text are invented for detector/schema exercise. They are
not production records.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

# Synthetic public fixtures — original names/text, not copied from a live DB.
SYNTHETIC_CARDS: tuple[dict[str, Any], ...] = (
    {
        "id": "syn-ramp-rock",
        "oracle_id": "oid-syn-ramp-rock",
        "name": "Synthetic Mana Rock",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact",
        "oracle_text": "{T}: Add {G}{G}.",
        "color_identity": "[]",
        "keywords": "[]",
        "is_legal_commander": 0,
        "is_legal_in_99": 1,
        "set_code": "SYN",
        "rarity": "uncommon",
    },
    {
        "id": "syn-removal-bolt",
        "oracle_id": "oid-syn-removal-bolt",
        "name": "Synthetic Removal Spell",
        "mana_cost": "{1}{R}",
        "cmc": 2.0,
        "type_line": "Instant",
        "oracle_text": "Destroy target creature.",
        "color_identity": '["R"]',
        "keywords": "[]",
        "is_legal_commander": 0,
        "is_legal_in_99": 1,
        "set_code": "SYN",
        "rarity": "common",
    },
    {
        "id": "syn-hexproof-aura",
        "oracle_id": "oid-syn-hexproof-aura",
        "name": "Synthetic Hexproof Aura",
        "mana_cost": "{W}",
        "cmc": 1.0,
        "type_line": "Enchantment — Aura",
        "oracle_text": "Enchant creature. Enchanted creature has hexproof.",
        "color_identity": '["W"]',
        "keywords": '["Hexproof"]',
        "is_legal_commander": 0,
        "is_legal_in_99": 1,
        "set_code": "SYN",
        "rarity": "common",
    },
    {
        "id": "syn-test-commander",
        "oracle_id": "oid-syn-test-commander",
        "name": "Synthetic Test Commander",
        "mana_cost": "{2}{G}{W}",
        "cmc": 4.0,
        "type_line": "Legendary Creature — Test Avatar",
        "oracle_text": "Whenever a land enters the battlefield under your control, draw a card.",
        "color_identity": '["G","W"]',
        "keywords": "[]",
        "is_legal_commander": 1,
        "is_legal_in_99": 1,
        "set_code": "SYN",
        "rarity": "mythic",
    },
)

_CARD_INSERT_SQL = """
INSERT OR REPLACE INTO cards (
    id, oracle_id, name, mana_cost, cmc, type_line, oracle_text,
    color_identity, keywords, is_legal_commander, is_legal_in_99,
    set_code, rarity
) VALUES (
    :id, :oracle_id, :name, :mana_cost, :cmc, :type_line, :oracle_text,
    :color_identity, :keywords, :is_legal_commander, :is_legal_in_99,
    :set_code, :rarity
)
"""

# Queries used by clustering / generators that must succeed on an empty corpus.
EMPTY_CORPUS_SQL: tuple[str, ...] = (
    "SELECT id, popularity_rank, archetype_tags FROM decks ORDER BY popularity_rank",
    "SELECT COUNT(*) FROM decks",
    "SELECT id, role_tags, functional_categories FROM cards LIMIT 1",
    "SELECT card_id, produced_colors, ramp_score FROM ramp_candidates LIMIT 1",
    "SELECT card_id, removal_score, flexibility_score FROM removal_candidates LIMIT 1",
    "SELECT card_id, protection_score, coverage_score FROM protection_candidates LIMIT 1",
)


def insert_synthetic_cards(conn: sqlite3.Connection) -> int:
    """Insert the public synthetic card set. Returns the number of rows written."""
    conn.executemany(_CARD_INSERT_SQL, SYNTHETIC_CARDS)
    conn.commit()
    return len(SYNTHETIC_CARDS)


def insert_synthetic_cards_at(db_path: Path) -> int:
    """Open ``db_path`` and insert synthetic cards."""
    conn = sqlite3.connect(str(db_path))
    try:
        return insert_synthetic_cards(conn)
    finally:
        conn.close()


def query_empty_corpus_safe(conn: sqlite3.Connection) -> dict[str, int]:
    """Run generator/clustering SQL shapes; raise on schema errors, not emptiness.

    Returns row counts per statement (0 is success for an empty corpus).
    """
    counts: dict[str, int] = {}
    for sql in EMPTY_CORPUS_SQL:
        rows = conn.execute(sql).fetchall()
        counts[sql] = len(rows)
    return counts


def query_empty_corpus_safe_at(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    try:
        return query_empty_corpus_safe(conn)
    finally:
        conn.close()
