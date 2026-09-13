"""Unit tests for configured game-changer name extraction.

The helper is a pure projection over already-parsed YAML. Tests use in-memory
documents plus the public ``config/game_changers.yaml`` checked into this
repository. They do not fetch official rules, open private files, or mutate
the published config.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path

import yaml

from sabermetrics.intelligence.power_policy import configured_game_changer_names

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "game_changers.yaml"


def test_none_returns_empty_set() -> None:
    assert configured_game_changer_names(None) == set()


def test_canonical_card_name_mapping() -> None:
    data = {
        "game_changers": [
            {"card_name": "Mana Vault", "bracket_threshold": 4},
            {"card_name": "Thassa's Oracle"},
        ]
    }
    assert configured_game_changer_names(data) == {
        "mana vault",
        "thassa's oracle",
    }


def test_legacy_top_level_string_list() -> None:
    data = ["  Mana Vault  ", "Rhystic Study"]
    assert configured_game_changer_names(data) == {"mana vault", "rhystic study"}


def test_legacy_name_mapping() -> None:
    data = {
        "game_changers": [
            {"name": "Sol Ring"},
            {"name": "  Rhystic Study "},
        ]
    }
    assert configured_game_changer_names(data) == {"sol ring", "rhystic study"}


def test_legacy_top_level_name_mappings() -> None:
    data = [{"name": "Mana Vault"}, {"name": "Cyclonic Rift"}]
    assert configured_game_changer_names(data) == {"mana vault", "cyclonic rift"}


def test_mixed_canonical_legacy_and_strings() -> None:
    data = {
        "game_changers": [
            {"card_name": "Mana Vault"},
            {"name": "Rhystic Study"},
            "Thassa's Oracle",
        ]
    }
    assert configured_game_changer_names(data) == {
        "mana vault",
        "rhystic study",
        "thassa's oracle",
    }


def test_malformed_entries_ignored_without_stringifying() -> None:
    data = [
        None,
        42,
        3.14,
        True,
        False,
        "",
        "   ",
        {"card_name": None},
        {"card_name": 7},
        {"card_name": ""},
        {"card_name": "  "},
        {"name": None},
        {"name": 9},
        {"name": ""},
        {"foo": "bar"},
        {"card_name": {"nested": "Mana Vault"}},
        ["nested list"],
        "Mana Vault",
    ]
    names = configured_game_changer_names(data)
    assert names == {"mana vault"}
    assert "none" not in names
    assert "42" not in names
    assert "true" not in names
    assert "false" not in names
    assert "7" not in names


def test_card_name_precedence_over_legacy_name() -> None:
    data = {
        "game_changers": [
            {"card_name": "Mana Vault", "name": "Wrong Name"},
            {"card_name": "  Thassa's Oracle  ", "name": "Thoracle"},
        ]
    }
    assert configured_game_changer_names(data) == {
        "mana vault",
        "thassa's oracle",
    }


def test_invalid_card_name_falls_back_to_legacy_name() -> None:
    data = {
        "game_changers": [
            {"card_name": "", "name": "Sol Ring"},
            {"card_name": "   ", "name": "Rhystic Study"},
            {"card_name": None, "name": "Mana Vault"},
            {"card_name": 1, "name": "Cyclonic Rift"},
            {"name": "Demonic Tutor"},
        ]
    }
    assert configured_game_changer_names(data) == {
        "sol ring",
        "rhystic study",
        "mana vault",
        "cyclonic rift",
        "demonic tutor",
    }


def test_deduplicates_normalized_names() -> None:
    data = [
        "Mana Vault",
        "  mana vault  ",
        "MANA VAULT",
        {"card_name": "Mana Vault"},
        {"name": "mana vault"},
    ]
    assert configured_game_changer_names(data) == {"mana vault"}


def test_unrelated_root_metadata_ignored() -> None:
    data = {
        "last_updated": date(2025, 2, 14),
        "notes": ["not a card", "Sol Ring"],
        "aliases": {"Thoracle": "Thassa's Oracle"},
        "game_changers": [{"card_name": "Mana Vault", "rationale": "fast mana"}],
    }
    assert configured_game_changer_names(data) == {"mana vault"}


def test_unsupported_root_and_collection_shapes_return_empty() -> None:
    assert configured_game_changer_names("Mana Vault") == set()
    assert configured_game_changer_names(0) == set()
    assert configured_game_changer_names(True) == set()
    assert configured_game_changer_names({"card_name": "Mana Vault"}) == set()
    assert configured_game_changer_names({"game_changers": None}) == set()
    assert configured_game_changer_names({"game_changers": "Mana Vault"}) == set()
    assert (
        configured_game_changer_names({"game_changers": {"card_name": "Mana Vault"}})
        == set()
    )
    assert configured_game_changer_names(("Mana Vault",)) == set()
    assert configured_game_changer_names({"Mana Vault", "Sol Ring"}) == set()
    assert configured_game_changer_names({"notes": ["Mana Vault"]}) == set()


def test_empty_supported_collections_return_empty() -> None:
    assert configured_game_changer_names([]) == set()
    assert configured_game_changer_names({}) == set()
    assert configured_game_changer_names({"game_changers": []}) == set()


def test_does_not_mutate_input() -> None:
    payload: dict[str, object] = {
        "last_updated": "2025-02-14",
        "game_changers": [
            {"card_name": "Mana Vault", "name": "other", "tags": ["fast"]},
            "Rhystic Study",
        ],
    }
    snapshot = deepcopy(payload)
    result = configured_game_changer_names(payload)
    assert result == {"mana vault", "rhystic study"}
    assert payload == snapshot

    legacy = [{"name": "Sol Ring"}, "Mana Vault"]
    legacy_snapshot = deepcopy(legacy)
    assert configured_game_changer_names(legacy) == {"sol ring", "mana vault"}
    assert legacy == legacy_snapshot


def test_sol_ring_is_included_when_configured() -> None:
    data = {"game_changers": [{"card_name": "Sol Ring"}]}
    names = configured_game_changer_names(data)
    assert "sol ring" in names
    names.discard("sol ring")
    assert "sol ring" not in names
    assert configured_game_changer_names(data) == {"sol ring"}


def _literal_card_names(data: object) -> set[str]:
    """Normalized ``card_name`` strings from a canonical parsed document."""
    if not isinstance(data, dict):
        return set()
    entries = data.get("game_changers")
    if not isinstance(entries, list):
        return set()
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("card_name")
        if isinstance(raw, str) and raw.strip():
            names.add(raw.strip().lower())
    return names


def test_local_config_matches_literal_card_names() -> None:
    assert CONFIG_PATH.is_file()
    parsed = yaml.safe_load(CONFIG_PATH.read_text())
    expected = _literal_card_names(parsed)
    names = configured_game_changer_names(parsed)
    assert names == expected

    for label in ("Mana Vault", "Thassa's Oracle", "Rhystic Study"):
        key = label.strip().lower()
        if key in expected:
            assert key in names

    assert "sol ring" in names
    assert "sol ring" in expected
