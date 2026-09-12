"""Runtime package: config_path, migrations, readiness, and synthetic prepare."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sabermetrics.config import (
    REQUIRED_CONFIG_FILES,
    ConfigError,
    config_path,
    load_settings,
)
from sabermetrics.runtime import (
    SCHEMA_VERSION,
    apply_schema_migrations,
    assert_installed_scoring_values,
    assert_readiness,
    check_readiness,
    insert_synthetic_cards_at,
    prepare_public_corpus,
    query_empty_corpus_safe_at,
    setup_database,
)
from sabermetrics.runtime.readiness import ReadinessError


def _packaged_config_dir() -> Path:
    return config_path("settings.yaml").parent


def _copy_required_config(dest: Path) -> None:
    src = _packaged_config_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_CONFIG_FILES:
        (dest / name).write_bytes((src / name).read_bytes())


# --- config_path ---------------------------------------------------------


def test_config_path_returns_real_settings_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Packaged settings.yaml is used even when cwd has a decoy config/."""
    decoy = tmp_path / "config"
    decoy.mkdir()
    (decoy / "settings.yaml").write_text(
        "user:\n  default_budget_usd: 1\nllm:\n  monthly_cost_ceiling_usd: 0.01\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SABER_CONFIG_DIR", raising=False)
    path = config_path("settings.yaml")
    assert path.is_file()
    assert path.resolve() != (decoy / "settings.yaml").resolve()
    settings = load_settings(path)
    assert settings.user.default_budget_usd == 200
    assert settings.llm.monthly_cost_ceiling_usd == 15.0
    assert settings.llm.profile_model == "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"


def test_config_path_rejects_traversal() -> None:
    with pytest.raises(ConfigError):
        config_path("../settings.yaml")
    with pytest.raises(ConfigError):
        config_path("foo/settings.yaml")
    with pytest.raises(ConfigError):
        config_path("/etc/passwd")
    with pytest.raises(ConfigError):
        config_path("settings.txt")
    with pytest.raises(ConfigError):
        config_path("")


def test_saber_config_dir_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _copy_required_config(tmp_path)
    patched = yaml.safe_load((tmp_path / "settings.yaml").read_text())
    patched["user"]["default_budget_usd"] = 42
    (tmp_path / "settings.yaml").write_text(yaml.safe_dump(patched))
    monkeypatch.setenv("SABER_CONFIG_DIR", str(tmp_path))
    path = config_path("settings.yaml")
    assert path.parent.resolve() == tmp_path.resolve()
    assert load_settings(path).user.default_budget_usd == 42


def test_saber_config_dir_missing_required_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_required_config(tmp_path)
    (tmp_path / "synergy_rules.yaml").unlink()
    monkeypatch.setenv("SABER_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match="synergy_rules.yaml"):
        config_path("synergy_rules.yaml")


def test_installed_scoring_loaders_real_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SABER_CONFIG_DIR", raising=False)
    values = assert_installed_scoring_values()
    assert values["first_synergy_rule_id"] == "tokens_with_sacrifice_payoff"
    assert values["karsten_one_pip_turn_1"] == 22
    assert values["sol_ring_auto_include"] is True


# --- readiness -----------------------------------------------------------


def test_readiness_ok_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SABER_CONFIG_DIR", raising=False)
    report = check_readiness(db_path=None)
    assert report.ok
    assert "settings.yaml" in report.config_files


def test_readiness_fails_on_malformed_required_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_required_config(tmp_path)
    (tmp_path / "synergy_rules.yaml").write_text("not: valid_rules_structure: true\n")
    monkeypatch.setenv("SABER_CONFIG_DIR", str(tmp_path))
    report = check_readiness(db_path=None)
    assert not report.ok
    assert any("synergy_rules.yaml" in e for e in report.errors)
    with pytest.raises(ReadinessError):
        assert_readiness(db_path=None)


def test_readiness_optional_corpus_empty_is_warning(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    setup_database(db_path, quiet=True)
    report = check_readiness(db_path)
    assert report.ok
    assert report.schema_version == SCHEMA_VERSION
    assert report.corpus["cards"] == 0
    assert report.corpus["decks"] == 0
    assert any("deck corpus is empty" in w for w in report.warnings)
    assert any("card corpus is empty" in w for w in report.warnings)


# --- schema migrations ---------------------------------------------------


def test_fresh_setup_has_required_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    version = apply_schema_migrations(db_path)
    assert version == SCHEMA_VERSION
    conn = sqlite3.connect(str(db_path))
    try:
        card_cols = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
        deck_cols = {row[1] for row in conn.execute("PRAGMA table_info(decks)")}
        ramp_cols = {row[1] for row in conn.execute("PRAGMA table_info(ramp_candidates)")}
        versions = {
            row[0] for row in conn.execute("SELECT version FROM _schema_version")
        }
    finally:
        conn.close()
    assert {"role_tags", "functional_categories"} <= card_cols
    assert {"popularity_rank", "archetype_tags"} <= deck_cols
    assert "produced_colors" in ramp_cols
    assert SCHEMA_VERSION in versions
    query_empty_corpus_safe_at(db_path)


def test_repeated_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "idemp.db"
    apply_schema_migrations(db_path)
    apply_schema_migrations(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        versions = [
            row[0] for row in conn.execute("SELECT version FROM _schema_version")
        ]
    finally:
        conn.close()
    assert versions.count(SCHEMA_VERSION) == 1


def _build_legacy_v1_db(path: Path) -> None:
    """Pre-1.1.0 schema: original tables without role_tags / popularity_rank / produced_colors."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE cards (
            id TEXT PRIMARY KEY,
            oracle_id TEXT NOT NULL,
            name TEXT NOT NULL,
            mana_cost TEXT,
            cmc REAL,
            type_line TEXT,
            oracle_text TEXT,
            color_identity TEXT,
            keywords TEXT,
            is_legal_commander BOOLEAN,
            is_legal_in_99 BOOLEAN,
            set_code TEXT,
            rarity TEXT,
            image_uri TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE card_prices (
            card_id TEXT,
            price_usd REAL,
            price_usd_foil REAL,
            snapshot_date DATE,
            source TEXT DEFAULT 'scryfall',
            PRIMARY KEY (card_id, snapshot_date)
        );
        CREATE TABLE decks (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            commander_id TEXT NOT NULL,
            deck_name TEXT,
            creator TEXT,
            estimated_price_usd REAL,
            power_tier INTEGER,
            raw_data TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, source_id)
        );
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            display_name TEXT,
            avatar_emoji TEXT,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            monthly_deck_quota INTEGER,
            invited_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP
        );
        CREATE TABLE generated_decks (
            id TEXT PRIMARY KEY,
            commander_id TEXT NOT NULL,
            profile_id TEXT,
            owner_id TEXT,
            deck_name TEXT,
            budget_usd REAL,
            power_target INTEGER,
            strategy TEXT,
            cards_json TEXT,
            rationale TEXT,
            cvar_score REAL,
            estimated_bracket INTEGER,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE commander_profiles (
            commander_id TEXT PRIMARY KEY,
            profile_json TEXT NOT NULL,
            user_intent TEXT,
            user_intent_hash TEXT,
            set_version TEXT NOT NULL,
            evidence_sources TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_validated_at TIMESTAMP,
            is_stale BOOLEAN DEFAULT FALSE,
            schema_version TEXT DEFAULT '1.0'
        );
        CREATE TABLE cost_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            call_type TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER,
            cached_input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd REAL,
            request_id TEXT,
            user_id TEXT,
            deck_id TEXT,
            metadata TEXT
        );
        CREATE TABLE generation_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id TEXT NOT NULL,
            card_name TEXT NOT NULL,
            card_id TEXT,
            stage TEXT NOT NULL,
            action TEXT NOT NULL,
            score REAL,
            score_components_json TEXT,
            reason TEXT,
            timestamp REAL
        );
        CREATE TABLE ramp_candidates (
            card_id TEXT PRIMARY KEY,
            ramp_type TEXT NOT NULL,
            net_mana_rate REAL,
            mana_output REAL,
            produces_colored BOOLEAN,
            is_conditional BOOLEAN,
            is_restricted BOOLEAN,
            resilience_tier INTEGER,
            ramp_score REAL,
            detection_version TEXT,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE _schema_version (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        );
        INSERT INTO _schema_version VALUES ('1.0', CURRENT_TIMESTAMP, 'Initial schema');
        INSERT INTO cards (id, oracle_id, name, cmc, type_line, color_identity, keywords,
            is_legal_commander, is_legal_in_99, set_code, rarity)
            VALUES ('keep-card', 'oid-keep', 'Legacy Keep Card', 1.0, 'Artifact', '[]', '[]',
            0, 1, 'LEG', 'common');
        INSERT INTO card_prices (card_id, price_usd, snapshot_date) VALUES ('keep-card', 0.25, '2020-01-01');
        INSERT INTO decks (id, source, source_id, commander_id, deck_name)
            VALUES ('keep-deck', 'test', 'src-1', 'keep-card', 'Legacy Deck');
        INSERT INTO users (id, email, display_name, role, status)
            VALUES ('u1', 'owner@example.com', 'Owner', 'admin', 'active');
        INSERT INTO generated_decks (id, commander_id, owner_id, cards_json, rationale)
            VALUES ('gd1', 'keep-card', 'u1', '[]', '{"narrative": "keep me"}');
        INSERT INTO commander_profiles (commander_id, profile_json, set_version)
            VALUES ('keep-card', '{"identity": "legacy"}', '1');
        INSERT INTO cost_log (call_type, model, cost_usd) VALUES ('profile', 'test-model', 0.01);
        INSERT INTO generation_traces (generation_id, card_name, stage, action)
            VALUES ('g1', 'Legacy Keep Card', 'filter', 'kept');
        INSERT INTO ramp_candidates (card_id, ramp_type, ramp_score, detection_version)
            VALUES ('keep-card', 'rock', 0.5, '0.0.0');
        """
    )
    conn.commit()
    conn.close()


def test_old_schema_upgrade_preserves_records(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _build_legacy_v1_db(db_path)
    apply_schema_migrations(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        card_cols = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
        deck_cols = {row[1] for row in conn.execute("PRAGMA table_info(decks)")}
        ramp_cols = {row[1] for row in conn.execute("PRAGMA table_info(ramp_candidates)")}
        assert "role_tags" in card_cols
        assert "functional_categories" in card_cols
        assert "popularity_rank" in deck_cols
        assert "produced_colors" in ramp_cols

        assert conn.execute("SELECT email FROM users WHERE id='u1'").fetchone()[0] == (
            "owner@example.com"
        )
        assert conn.execute("SELECT name FROM cards WHERE id='keep-card'").fetchone()[0] == (
            "Legacy Keep Card"
        )
        assert conn.execute(
            "SELECT price_usd FROM card_prices WHERE card_id='keep-card'"
        ).fetchone()[0] == 0.25
        assert conn.execute("SELECT deck_name FROM decks WHERE id='keep-deck'").fetchone()[0] == (
            "Legacy Deck"
        )
        rationale = conn.execute(
            "SELECT rationale FROM generated_decks WHERE id='gd1'"
        ).fetchone()[0]
        assert "keep me" in rationale
        assert conn.execute(
            "SELECT profile_json FROM commander_profiles WHERE commander_id='keep-card'"
        ).fetchone()[0] == '{"identity": "legacy"}'
        assert conn.execute("SELECT cost_usd FROM cost_log").fetchone()[0] == 0.01
        assert conn.execute(
            "SELECT action FROM generation_traces WHERE generation_id='g1'"
        ).fetchone()[0] == "kept"
        versions = {
            row[0] for row in conn.execute("SELECT version FROM _schema_version")
        }
        assert "1.0" in versions and SCHEMA_VERSION in versions
        # Empty-corpus-shaped query must not raise after the upgrade.
        conn.execute(
            "SELECT id, popularity_rank, archetype_tags FROM decks ORDER BY popularity_rank"
        ).fetchall()
    finally:
        conn.close()


# --- public corpus preparation -------------------------------------------


def test_prepare_public_corpus_tags_and_detects_synthetic_cards(tmp_path: Path) -> None:
    db_path = tmp_path / "syn.db"
    setup_database(db_path, quiet=True)
    query_empty_corpus_safe_at(db_path)
    insert_synthetic_cards_at(db_path)
    stats = prepare_public_corpus(db_path)
    assert stats["role_tags"]["tagged_cards"] >= 4
    assert stats["ramp_candidates"]["rows"] >= 1
    assert stats["removal_candidates"]["rows"] >= 1
    assert stats["protection_candidates"]["rows"] >= 1

    conn = sqlite3.connect(str(db_path))
    try:
        ramp_tags = conn.execute(
            "SELECT role_tags FROM cards WHERE id='syn-ramp-rock'"
        ).fetchone()[0]
        assert "ramp" in ramp_tags
        produced = conn.execute(
            "SELECT produced_colors FROM ramp_candidates WHERE card_id='syn-ramp-rock'"
        ).fetchone()
        assert produced is not None
        removal = conn.execute(
            "SELECT removal_score FROM removal_candidates WHERE card_id='syn-removal-bolt'"
        ).fetchone()
        assert removal is not None
        prot = conn.execute(
            "SELECT protection_type FROM protection_candidates WHERE card_id='syn-hexproof-aura'"
        ).fetchone()
        assert prot is not None
    finally:
        conn.close()

    again = prepare_public_corpus(db_path)
    assert again["role_tags"]["tagged_cards"] == 0
    assert again["ramp_candidates"].get("skipped") is True


def test_smoke_scoring_and_schema_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The installed-smoke helper runs against a temp DB (no /data required)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SABER_CONFIG_DIR", raising=False)
    db_path = tmp_path / "smoke.db"
    setup_database(db_path, quiet=True)
    from sabermetrics import db as saber_db

    saber_db.UsersRepo(db_path).create(
        email="owner@example.com",
        display_name="Owner",
        role="admin",
        status="active",
        password_hash=saber_db.hash_password("offline-password"),
    )
    assert_installed_scoring_values()
    query_empty_corpus_safe_at(db_path)
    insert_synthetic_cards_at(db_path)
    prepare_public_corpus(db_path)
    apply_schema_migrations(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute("SELECT email FROM users").fetchone()[0] == "owner@example.com"
    finally:
        conn.close()


def test_scripts_setup_db_reexports_setup_database(tmp_path: Path) -> None:
    from scripts.setup_db import setup_database as script_setup

    db_path = tmp_path / "from-script.db"
    script_setup(db_path, quiet=True)
    assert db_path.exists()
