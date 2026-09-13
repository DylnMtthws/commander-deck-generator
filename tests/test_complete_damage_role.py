"""Complete damage-family role helper and initial slot classification."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sabermetrics.pipeline.slot_assigner import (
    _classify_card_role,
    complete_damage_role,
)

PUBLIC_SPELLS = (
    Path(__file__).resolve().parents[1]
    / "docs/experiments/commander-substitutions/public-spells.json"
)
CARDS = {c["name"]: dict(c) for c in json.loads(PUBLIC_SPELLS.read_text())["cards"]}
BURN = ("Shock", "Burst Lightning", "Play with Fire")
INCOMPLETE_FACTS = (None, {"roles": []}, {"roles": ["utility"]})


def _with_facts(card: dict, facts: dict | None) -> dict:
    card = deepcopy(card)
    if facts is not None:
        card["_facts"] = facts
    return card


@pytest.mark.parametrize("name", BURN)
@pytest.mark.parametrize("facts", INCOMPLETE_FACTS)
def test_complete_burn_is_removal_despite_incomplete_facts(
    name: str, facts: dict | None
) -> None:
    card = _with_facts(CARDS[name], facts)
    assert complete_damage_role(card) == "removal"
    assert _classify_card_role(card) == "removal"


@pytest.mark.parametrize("facts", INCOMPLETE_FACTS)
def test_player_only_damage_is_not_complete_removal(facts: dict | None) -> None:
    card = _with_facts(
        {
            **CARDS["Shock"],
            "oracle_text": "This spell deals 2 damage to target player.",
        },
        facts,
    )
    assert complete_damage_role(card) is None
    assert _classify_card_role(card) == "utility"


def test_unknown_trailing_oracle_clause_is_not_complete_removal() -> None:
    card = deepcopy(CARDS["Shock"])
    card["oracle_text"] = "Shock deals 2 damage to any target. Skip your next turn."
    assert complete_damage_role(card) is None
    assert _classify_card_role(card) == "utility"
    if "Galvanic Blast" in CARDS:
        extra = CARDS["Galvanic Blast"]
        assert complete_damage_role(extra) is None
        assert _classify_card_role(extra) == "utility"


@pytest.mark.parametrize("name", BURN)
@pytest.mark.parametrize("llm_role", ["draw", "utility", "ramp", "wincon"])
def test_explicit_valid_llm_role_overrides_complete_damage(
    name: str, llm_role: str
) -> None:
    card = CARDS[name]
    assert complete_damage_role(card) == "removal"
    assert _classify_card_role(card, llm_role=llm_role) == llm_role


def test_invalid_or_empty_llm_role_does_not_override_complete_damage() -> None:
    card = CARDS["Shock"]
    assert _classify_card_role(card, llm_role="protection") == "removal"
    assert _classify_card_role(card, llm_role="not-a-role") == "removal"
    assert _classify_card_role(card, llm_role="") == "removal"


@pytest.mark.parametrize(
    "change",
    [
        {"mana_cost": ""},
        {"mana_cost": "{X}{R}"},
        {"mana_cost": None},
    ],
)
def test_malformed_or_absent_cost_fails_complete_helper(change: dict) -> None:
    card = {**CARDS["Shock"], **change}
    if change.get("mana_cost") is None:
        card.pop("mana_cost", None)
    assert complete_damage_role(card) is None
    assert _classify_card_role(card) == "utility"


def test_helper_none_leaves_generic_fallback_unchanged() -> None:
    draw = {"type_line": "Sorcery", "oracle_text": "Draw three cards."}
    ramp = {"type_line": "Artifact", "oracle_text": "Add {G} to your mana pool."}
    removal = {"type_line": "Instant", "oracle_text": "Destroy target creature."}
    land = {"type_line": "Land", "oracle_text": ""}
    utility = {"type_line": "Creature", "oracle_text": "Flying"}
    assert complete_damage_role(draw) is None
    assert complete_damage_role(ramp) is None
    assert complete_damage_role(removal) is None
    assert complete_damage_role(land) is None
    assert complete_damage_role(utility) is None
    assert _classify_card_role(draw) == "draw"
    assert _classify_card_role(ramp) == "ramp"
    assert _classify_card_role(removal) == "removal"
    assert _classify_card_role(land) == "land"
    assert _classify_card_role(utility) == "utility"


@pytest.mark.parametrize("name", BURN)
@pytest.mark.parametrize("facts", INCOMPLETE_FACTS)
def test_heuristic_role_cross_path_matches_complete_helper(
    name: str, facts: dict | None
) -> None:
    from sabermetrics.pipeline.deck_builder import _heuristic_role

    card = _with_facts(CARDS[name], facts)
    assert _heuristic_role(card) == complete_damage_role(card) == "removal"
