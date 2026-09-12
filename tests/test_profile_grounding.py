"""Tests for profiler identity override, cache provenance, and oracle facts."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sabermetrics.models.card import Card
from sabermetrics.models.evidence import EvidencePackage, ReferenceChunk
from sabermetrics.models.profile import CommanderProfile
from sabermetrics.reasoning.profile_grounding import (
    CACHE_PROVENANCE_KEY,
    CACHE_PROVENANCE_VERSION,
    apply_canonical_profile_metadata,
    derive_card_analysis,
    profile_cache_is_valid,
    stamp_cache_provenance,
)
from sabermetrics.reasoning.profiler import ProfileManager, ProfileRequest
from sabermetrics.reasoning.prompts import _CACHE as _PROMPT_CACHE
from sabermetrics.reasoning.prompts import load_prompt
from scripts.setup_db import setup_database
from tests.fixtures.grounding.public_card_facts import AANG_COMMANDER


def _card() -> Card:
    return Card(**AANG_COMMANDER)


def _strategic_fields() -> dict:
    return {
        "behavioral_signals": {
            "total_decks_tracked": 0,
            "edhrec_themes": [],
            "most_included_cards": [],
            "average_deck_price_usd": 0.0,
            "average_cmc": 0.0,
            "tournament_win_rate": None,
            "tournament_sample_size": 0,
        },
        "community_signals": {
            "reddit_thread_count": 0,
            "named_archetypes": [],
            "primer_articles_referenced": [],
            "emerging_strategies": [],
        },
        "strategic_profile": {
            "primary_archetype": "midrange",
            "game_plan_summary": "Cheat a cheap creature into play with Aang.",
            "win_conditions": [
                {
                    "description": "Combat damage",
                    "key_cards": [AANG_COMMANDER["name"]],
                    "reliability": "primary",
                }
            ],
            "build_paths": [],
            "synergy_priorities": {},
            "anti_synergies": [],
            "strategic_constraints": {
                "mana_base_requirements": "Bant",
                "interaction_density": "medium",
                "speed_tier": "midrange",
            },
            "power_indicators": {
                "estimated_ceiling_bracket": 3,
                "estimated_floor_bracket": 2,
                "notes": "Synthetic fixture",
            },
        },
        "schema_version": "1.0",
    }


def _hostile_model_payload(commander: Card) -> dict:
    """Wrong ID, old date, wrong set, fabricated source, wrong mana/color."""
    data = _strategic_fields()
    data.update(
        {
            "commander_id": "aang-airbending-hero",
            "commander_name": "Invented Aang",
            "generated_at": "2020-01-01T00:00:00",
            "set_version": "LEA",
            "card_analysis": {
                "mana_cost": "{0}",
                "color_identity": ["B"],
                "core_mechanic": "You get extra combats and make tokens.",
                "triggered_abilities": ["Invented trigger"],
                "activated_abilities": [],
                "static_abilities": [],
                "evasion_or_protection": "shadow",
            },
            "user_intent": {
                "provided": True,
                "description": "model-invented intent",
                "divergence_from_consensus": "invented",
            },
            "sources": {
                "rules_chunks_referenced": [
                    "CR 702.2",
                    "https://example.invalid/fabricated",
                    "chunk-retrieved-1",
                ],
                "articles_referenced": ["not-a-real-article"],
                "evidence_freshness": {
                    "edhrec_last_updated": "2010-01-01T00:00:00",
                    "topdeck_last_updated": "2010-01-01T00:00:00",
                    "reddit_last_searched": "2010-01-01T00:00:00",
                },
            },
        }
    )
    assert data["commander_id"] != commander.id
    return data


def _evidence(commander: Card) -> EvidencePackage:
    return EvidencePackage(
        commander=commander,
        rulings=[],
        reddit_threads=[],
        primer_articles=[],
        reference_chunks=[
            ReferenceChunk(
                id="chunk-retrieved-1",
                document="CR",
                section="702.8",
                tier=1,
                content="Flash is a static ability.",
            )
        ],
        user_intent="four-mana copy creatures",
    )


def _insert_commander(db_path: Path, commander: Card) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO cards ("
            "id, oracle_id, name, mana_cost, cmc, type_line, oracle_text, "
            "color_identity, keywords, is_legal_commander, is_legal_in_99, "
            "set_code, rarity, last_updated"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                commander.id,
                commander.oracle_id,
                commander.name,
                commander.mana_cost,
                commander.cmc,
                commander.type_line,
                commander.oracle_text,
                json.dumps(commander.color_identity),
                json.dumps(commander.keywords),
                int(commander.is_legal_commander),
                int(commander.is_legal_in_99),
                commander.set_code,
                commander.rarity,
                commander.last_updated.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _profile_from_canonical(
    commander: Card, user_intent: str | None = None
) -> CommanderProfile:
    data = _strategic_fields()
    data["card_analysis"] = derive_card_analysis(commander)
    data = apply_canonical_profile_metadata(
        data,
        commander=commander,
        user_intent=user_intent,
        evidence=(
            _evidence(commander)
            if user_intent
            else EvidencePackage(
                commander=commander,
                rulings=[],
                reddit_threads=[],
                primer_articles=[],
                reference_chunks=[],
                user_intent=user_intent,
            )
        ),
        generated_at=datetime(2026, 9, 12, 18, 0, tzinfo=UTC),
    )
    return CommanderProfile(**data)


def _stamped_payload(profile: CommanderProfile) -> dict:
    return stamp_cache_provenance(json.loads(profile.model_dump_json()))


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "grounding.db"
    setup_database(path)
    _insert_commander(path, _card())
    return path


def test_profile_prompt_removes_erroneous_flash_cr_example() -> None:
    _PROMPT_CACHE.pop("profile_synthesis", None)
    template = load_prompt("profile_synthesis")
    assert "CR 702.2 confirms flash" not in template
    assert "flash creatures count as cast" not in template
    assert "do not invent Comprehensive Rules numbers" in template


def test_aang_card_analysis_uses_public_printed_text() -> None:
    commander = _card()
    analysis = derive_card_analysis(commander)
    oracle = (commander.oracle_text or "").lower()
    assert "look at the top five cards" in oracle
    assert "earthbend" in oracle
    assert "deals combat damage to a player, draw a card" not in oracle
    assert "look at the top five cards" in analysis["core_mechanic"].lower()
    assert analysis["mana_cost"] == "{2}{G}{W}{U}"
    assert "flying" in (analysis["evasion_or_protection"] or "").lower()


def test_hostile_model_metadata_loses_to_canonical_inputs() -> None:
    commander = _card()
    grounded = apply_canonical_profile_metadata(
        _hostile_model_payload(commander),
        commander=commander,
        user_intent="four-mana copy creatures",
        evidence=_evidence(commander),
        generated_at=datetime(2026, 9, 12, 18, 30, tzinfo=UTC),
    )
    profile = CommanderProfile(**grounded)
    assert profile.commander_id == commander.id
    assert profile.commander_name == commander.name
    assert profile.set_version == commander.set_code
    assert profile.generated_at == datetime(2026, 9, 12, 18, 30, tzinfo=UTC)
    assert profile.user_intent.provided is True
    assert profile.user_intent.description == "four-mana copy creatures"
    assert profile.card_analysis.mana_cost == commander.mana_cost
    assert profile.card_analysis.color_identity == commander.color_identity
    assert profile.sources.rules_chunks_referenced == ["chunk-retrieved-1"]
    assert "CR 702.2" not in profile.sources.rules_chunks_referenced
    assert profile.sources.articles_referenced == []
    assert profile.sources.evidence_freshness.edhrec_last_updated is None
    assert "extra combats" not in profile.card_analysis.core_mechanic.lower()
    assert "shadow" not in (profile.card_analysis.evasion_or_protection or "").lower()
    assert "flying" in (profile.card_analysis.evasion_or_protection or "").lower()
    assert CACHE_PROVENANCE_KEY not in grounded


def test_unmarked_profile_is_never_a_valid_cache() -> None:
    commander = _card()
    profile = _profile_from_canonical(commander)
    unmarked = json.loads(profile.model_dump_json())
    assert CACHE_PROVENANCE_KEY not in unmarked
    assert (
        profile_cache_is_valid(unmarked, commander=commander, user_intent=None) is False
    )
    assert (
        profile_cache_is_valid(profile, commander=commander, user_intent=None) is False
    )


def test_stamped_cache_requires_identity_set_intent_and_aware_time() -> None:
    commander = _card()
    now = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)
    good = _stamped_payload(_profile_from_canonical(commander))
    assert (
        profile_cache_is_valid(good, commander=commander, user_intent=None, now=now)
        is True
    )

    wrong_id = dict(good)
    wrong_id["commander_id"] = "not-the-commander"
    wrong_id[CACHE_PROVENANCE_KEY] = dict(good[CACHE_PROVENANCE_KEY])
    wrong_id[CACHE_PROVENANCE_KEY]["commander_id"] = "not-the-commander"
    assert (
        profile_cache_is_valid(wrong_id, commander=commander, user_intent=None, now=now)
        is False
    )

    wrong_set = dict(good)
    wrong_set["set_version"] = "LEA"
    wrong_set[CACHE_PROVENANCE_KEY] = dict(good[CACHE_PROVENANCE_KEY])
    wrong_set[CACHE_PROVENANCE_KEY]["set_version"] = "LEA"
    assert (
        profile_cache_is_valid(
            wrong_set, commander=commander, user_intent=None, now=now
        )
        is False
    )

    wrong_intent = _stamped_payload(
        _profile_from_canonical(commander, user_intent="four-mana copy creatures")
    )
    assert (
        profile_cache_is_valid(
            wrong_intent, commander=commander, user_intent=None, now=now
        )
        is False
    )
    assert (
        profile_cache_is_valid(
            wrong_intent,
            commander=commander,
            user_intent="four-mana copy creatures",
            now=now,
        )
        is True
    )

    naive = dict(good)
    naive["generated_at"] = "2026-09-12T18:00:00"
    assert (
        profile_cache_is_valid(naive, commander=commander, user_intent=None, now=now)
        is False
    )

    future = dict(good)
    future["generated_at"] = "2027-01-01T00:00:00+00:00"
    assert (
        profile_cache_is_valid(future, commander=commander, user_intent=None, now=now)
        is False
    )


def test_unmarked_legacy_date_is_rejected_without_date_blacklist() -> None:
    commander = _card()
    now = datetime(2026, 9, 12, tzinfo=UTC)
    unmarked = json.loads(_profile_from_canonical(commander).model_dump_json())
    unmarked["generated_at"] = "2025-04-09T12:00:00+00:00"
    assert (
        profile_cache_is_valid(unmarked, commander=commander, user_intent=None, now=now)
        is False
    )

    stamped = _stamped_payload(_profile_from_canonical(commander))
    stamped["generated_at"] = "2025-04-09T12:00:00+00:00"
    assert (
        profile_cache_is_valid(stamped, commander=commander, user_intent=None, now=now)
        is True
    )


def test_cached_malformed_legacy_profile_misses(db_path: Path) -> None:
    commander = _card()
    mgr = ProfileManager(db_path)
    unmarked = json.loads(_profile_from_canonical(commander).model_dump_json())
    unmarked["generated_at"] = "2025-04-09T12:00:00+00:00"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO commander_profiles "
            "(commander_id, profile_json, user_intent, user_intent_hash, "
            "set_version, generated_at, is_stale, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (
                commander.id,
                json.dumps(unmarked),
                None,
                None,
                commander.set_code,
                "2025-04-09T12:00:00+00:00",
                "1.0",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert mgr._get_cached_profile(commander.id, None) is None
    stale = (
        sqlite3.connect(str(db_path))
        .execute(
            "SELECT is_stale FROM commander_profiles WHERE commander_id = ?",
            (commander.id,),
        )
        .fetchone()[0]
    )
    assert stale in (1, True)


def test_stamped_row_with_wrong_set_is_invalidated(db_path: Path) -> None:
    commander = _card()
    mgr = ProfileManager(db_path)
    profile = _profile_from_canonical(commander)
    payload = _stamped_payload(profile)
    payload["set_version"] = "LEA"
    payload[CACHE_PROVENANCE_KEY]["set_version"] = "LEA"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO commander_profiles "
            "(commander_id, profile_json, user_intent, user_intent_hash, "
            "set_version, generated_at, is_stale, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (
                commander.id,
                json.dumps(payload),
                None,
                None,
                "LEA",
                profile.generated_at.isoformat(),
                CACHE_PROVENANCE_VERSION,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert mgr._get_cached_profile(commander.id, None) is None
    stale = (
        sqlite3.connect(str(db_path))
        .execute(
            "SELECT is_stale FROM commander_profiles WHERE commander_id = ?",
            (commander.id,),
        )
        .fetchone()[0]
    )
    assert stale in (1, True)


def test_valid_cache_hit_does_not_bill(db_path: Path) -> None:
    commander = _card()
    mgr = ProfileManager(db_path)
    profile = _profile_from_canonical(commander, user_intent=None)
    mgr._store_profile(profile, None, None)

    fake = MagicMock()
    fake.call_with_cache.side_effect = AssertionError(
        "cache hit must not call the model"
    )
    with patch(
        "sabermetrics.reasoning.client.AnthropicClient.get_instance",
        return_value=fake,
    ):
        result = mgr.generate_profile(ProfileRequest(commander_id=commander.id))
    assert result.cache_hit is True
    assert result.generation_cost_usd == 0.0
    assert result.profile.commander_id == commander.id
    assert result.profile.commander_name == commander.name
    fake.call_with_cache.assert_not_called()


def test_generate_profile_overrides_hostile_model(db_path: Path) -> None:
    commander = _card()
    mgr = ProfileManager(db_path)
    evidence = _evidence(commander)
    payload = _hostile_model_payload(commander)
    fake_result = MagicMock()
    fake_result.content = json.dumps(payload)
    fake_result.cost_usd = 0.04
    fake_client = MagicMock()
    fake_client.call_with_cache.return_value = fake_result

    before = datetime.now(UTC)
    with (
        patch.object(mgr._evidence_aggregator, "aggregate", return_value=evidence),
        patch(
            "sabermetrics.reasoning.client.AnthropicClient.get_instance",
            return_value=fake_client,
        ),
    ):
        result = mgr.generate_profile(
            ProfileRequest(
                commander_id=commander.id,
                user_intent="four-mana copy creatures",
            )
        )
    after = datetime.now(UTC)

    assert result.cache_hit is False
    assert result.generation_cost_usd == 0.04
    profile = result.profile
    assert profile.commander_id == commander.id
    assert profile.commander_name == commander.name
    assert profile.set_version == commander.set_code
    assert profile.generated_at.tzinfo is not None
    assert before <= profile.generated_at <= after
    assert profile.user_intent.description == "four-mana copy creatures"
    assert profile.card_analysis.mana_cost == "{2}{G}{W}{U}"
    assert profile.card_analysis.color_identity == commander.color_identity
    assert profile.sources.rules_chunks_referenced == ["chunk-retrieved-1"]
    fake_client.call_with_cache.assert_called_once()

    conn = sqlite3.connect(str(db_path))
    try:
        stored_json, row_version = conn.execute(
            "SELECT profile_json, schema_version FROM commander_profiles "
            "WHERE commander_id = ?",
            (commander.id,),
        ).fetchone()
    finally:
        conn.close()
    stored = json.loads(stored_json)
    assert stored[CACHE_PROVENANCE_KEY]["version"] == CACHE_PROVENANCE_VERSION
    assert row_version == CACHE_PROVENANCE_VERSION

    fake_client.call_with_cache.reset_mock()
    with patch(
        "sabermetrics.reasoning.client.AnthropicClient.get_instance",
        return_value=fake_client,
    ):
        hit = mgr.generate_profile(
            ProfileRequest(
                commander_id=commander.id,
                user_intent="four-mana copy creatures",
            )
        )
    assert hit.cache_hit is True
    assert hit.generation_cost_usd == 0.0
    fake_client.call_with_cache.assert_not_called()
