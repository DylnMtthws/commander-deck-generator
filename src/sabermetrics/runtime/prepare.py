"""Idempotent public-corpus preparation (role tags + candidate detectors).

Heavy work is opt-in via :func:`prepare_public_corpus` / ``setup_db.py
--prepare-corpus``. Startup applies schema only and must not re-tag the
corpus on every request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROLE_TAG_VERSION = "1.0.0"


def prepare_public_corpus(db_path: Path, *, tag_version: str = ROLE_TAG_VERSION) -> dict[str, Any]:
    """Prepare role tags and ramp/removal/protection candidate tables.

    Safe on a fresh public corpus, an existing tagged corpus, and an empty
    cards table. Does not fetch external sources or seed user data.

    Args:
        db_path: SQLite database path.
        tag_version: Role-tag extraction version (skip cards already tagged).

    Returns:
        Dict of per-step statistics.
    """
    from sabermetrics.analytics.protection_detector import (
        populate_protection_candidates,
    )
    from sabermetrics.analytics.ramp_detector import populate_ramp_candidates
    from sabermetrics.analytics.removal_detector import populate_removal_candidates
    from sabermetrics.analytics.role_tagger import tag_all_cards
    from sabermetrics.runtime.schema import apply_schema_migrations

    db_path = Path(db_path)
    schema_version = apply_schema_migrations(db_path)

    tag_stats = tag_all_cards(db_path, tag_version)
    ramp_stats = populate_ramp_candidates(db_path)
    removal_stats = populate_removal_candidates(db_path)
    protection_stats = populate_protection_candidates(db_path)

    return {
        "schema_version": schema_version,
        "role_tags": {
            "total_cards": tag_stats.total_cards,
            "tagged_cards": tag_stats.tagged_cards,
            "version": tag_stats.version,
        },
        "ramp_candidates": ramp_stats,
        "removal_candidates": removal_stats,
        "protection_candidates": protection_stats,
    }
