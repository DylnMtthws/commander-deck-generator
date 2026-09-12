"""Startup readiness: required config/schema vs optional corpus absence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sabermetrics.config import (
    OPTIONAL_CONFIG_FILES,
    REQUIRED_CONFIG_FILES,
    ConfigError,
    config_path,
    load_settings,
)


class ReadinessError(Exception):
    """Essential configuration or schema is missing or malformed."""

    def __init__(self, message: str, report: ReadinessReport | None = None) -> None:
        super().__init__(message)
        self.report = report


@dataclass
class ReadinessReport:
    """Outcome of :func:`check_readiness`."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    config_files: dict[str, str] = field(default_factory=dict)
    schema_version: str | None = None
    corpus: dict[str, Any] = field(default_factory=dict)


def _check_required_config(report: ReadinessReport) -> None:
    for name in REQUIRED_CONFIG_FILES:
        try:
            path = config_path(name)
        except ConfigError as exc:
            report.errors.append(str(exc))
            continue
        report.config_files[name] = str(path)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            report.errors.append(f"Malformed configuration file {name}: {exc}")
            continue
        if raw is None:
            report.errors.append(f"Malformed configuration file {name}: empty document")
            continue
        _validate_required_payload(name, raw, path, report)

    for name in OPTIONAL_CONFIG_FILES:
        try:
            path = config_path(name)
        except ConfigError:
            report.warnings.append(f"Optional configuration file {name} is absent")
            continue
        report.config_files[name] = str(path)


def _validate_required_payload(
    name: str, raw: Any, path: Path, report: ReadinessReport
) -> None:
    if name == "settings.yaml":
        if not isinstance(raw, dict):
            report.errors.append(f"{name}: expected a mapping")
            return
        try:
            settings = load_settings(path)
        except (ConfigError, TypeError, ValueError) as exc:
            report.errors.append(f"{name}: {exc}")
            return
        if not settings.llm.profile_model:
            report.errors.append(f"{name}: llm.profile_model is empty")
        return
    if name == "synergy_rules.yaml":
        rules = raw.get("rules") if isinstance(raw, dict) else None
        if not isinstance(rules, list) or not rules:
            report.errors.append(f"{name}: missing non-empty 'rules' list")
            return
        if not isinstance(rules[0], dict) or "id" not in rules[0]:
            report.errors.append(f"{name}: rules must have an 'id'")
        return
    if name == "karsten_mana_base.yaml":
        if not isinstance(raw, dict) or not raw.get("color_source_requirements"):
            report.errors.append(f"{name}: missing color_source_requirements")
        return
    if name == "auto_include_cards.yaml":
        always = raw.get("always") if isinstance(raw, dict) else None
        if not isinstance(always, list) or not always:
            report.errors.append(f"{name}: missing non-empty 'always' list")
        return
    if name == "game_changers.yaml":
        gcs = raw.get("game_changers") if isinstance(raw, dict) else None
        if not isinstance(gcs, list) or not gcs:
            report.errors.append(f"{name}: missing non-empty 'game_changers' list")
        return
    if name == "functional_categories.yaml":
        cats = raw.get("categories") if isinstance(raw, dict) else None
        if not isinstance(cats, dict) or not cats:
            report.errors.append(f"{name}: missing non-empty 'categories' mapping")
        return
    if name == "role_tag_overrides.yaml":
        overrides = raw.get("overrides") if isinstance(raw, dict) else None
        if not isinstance(overrides, dict):
            report.errors.append(f"{name}: missing 'overrides' mapping")
        return
    if name == "archetype_signatures.yaml":
        archetypes = raw.get("archetypes") if isinstance(raw, dict) else None
        if not isinstance(archetypes, dict) or not archetypes:
            report.errors.append(f"{name}: missing non-empty 'archetypes' mapping")


def _check_schema_and_corpus(db_path: Path, report: ReadinessReport) -> None:
    from sabermetrics.runtime.schema import (
        CARD_COLUMN_MIGRATIONS,
        DECK_COLUMN_MIGRATIONS,
        RAMP_COLUMN_MIGRATIONS,
        current_schema_version,
    )

    if not db_path.exists():
        report.warnings.append(f"Database not found at {db_path} (optional until created)")
        return

    conn = sqlite3.connect(str(db_path))
    try:
        report.schema_version = current_schema_version(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        required_tables = ("cards", "decks", "ramp_candidates", "removal_candidates",
                           "protection_candidates", "_schema_version")
        for table in required_tables:
            if table not in tables:
                report.errors.append(f"Required table {table!r} is missing")

        def require_columns(table: str, cols: tuple[tuple[str, str], ...]) -> None:
            if table not in tables:
                return
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for col_name, _col_type in cols:
                if col_name not in existing:
                    report.errors.append(f"Required column {table}.{col_name} is missing")

        require_columns("cards", CARD_COLUMN_MIGRATIONS)
        require_columns("decks", DECK_COLUMN_MIGRATIONS)
        require_columns("ramp_candidates", RAMP_COLUMN_MIGRATIONS)

        card_count = 0
        deck_count = 0
        tagged = 0
        if "cards" in tables:
            card_count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            existing = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
            if "role_tags" in existing:
                tagged = conn.execute(
                    "SELECT COUNT(*) FROM cards WHERE role_tags IS NOT NULL AND role_tags != ''"
                ).fetchone()[0]
        if "decks" in tables:
            # Empty historical deck corpus must be a zero-row result, not a SQL error.
            deck_count = conn.execute(
                "SELECT COUNT(*) FROM decks"
            ).fetchone()[0]
            conn.execute(
                "SELECT id, popularity_rank, archetype_tags FROM decks "
                "ORDER BY popularity_rank LIMIT 1"
            ).fetchall()

        report.corpus = {
            "cards": card_count,
            "decks": deck_count,
            "tagged_cards": tagged,
        }
        if card_count == 0:
            report.warnings.append("Optional card corpus is empty")
        if deck_count == 0:
            report.warnings.append("Optional historical deck corpus is empty")
        if report.schema_version is None and "cards" in tables:
            report.errors.append("Schema version is missing")
    finally:
        conn.close()


def check_readiness(db_path: Path | str | None = None) -> ReadinessReport:
    """Inspect required config (and optional DB) without mutating state."""
    report = ReadinessReport(ok=True)
    _check_required_config(report)
    if db_path is not None:
        _check_schema_and_corpus(Path(db_path), report)
    report.ok = not report.errors
    return report


def assert_readiness(db_path: Path | str | None = None) -> ReadinessReport:
    """Raise :class:`ReadinessError` if essential config or schema is unfit."""
    report = check_readiness(db_path)
    if not report.ok:
        details = "; ".join(report.errors)
        raise ReadinessError(f"Runtime readiness failed: {details}", report=report)
    return report
