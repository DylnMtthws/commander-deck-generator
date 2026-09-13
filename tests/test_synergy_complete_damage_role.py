"""Complete-damage cards must report removal in synergy primary roles."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sabermetrics.analytics.synergy_matrix import _get_primary_roles

DOCS = Path(__file__).parents[1] / "docs/experiments/commander-substitutions"
CARDS = {
    c["name"]: c
    for c in json.loads((DOCS / "public-spells.json").read_text())["cards"]
}

COMPLETE_DAMAGE = ("Shock", "Burst Lightning", "Play with Fire")
STALE_ROLE_TAGS = ('["utility"]', "[]", ["utility"], [])


def _card(name: str, **overrides: object) -> dict:
    card = deepcopy(CARDS[name])
    card.update(overrides)
    return card


@pytest.mark.parametrize("name", COMPLETE_DAMAGE)
@pytest.mark.parametrize("role_tags", STALE_ROLE_TAGS)
def test_complete_damage_overrides_stale_role_tags_and_empty_facts(name, role_tags):
    card = _card(name, role_tags=role_tags, _facts={"roles": []})
    supplied_tags = deepcopy(role_tags)
    supplied_facts = deepcopy(card["_facts"])

    assert _get_primary_roles([card]) == ["removal"]
    assert card["role_tags"] == supplied_tags
    assert card["_facts"] == supplied_facts


def test_complete_damage_list_reports_removal_for_each_supported_card():
    cards = [
        _card(name, role_tags='["utility"]', _facts={"roles": []})
        for name in COMPLETE_DAMAGE
    ]

    assert _get_primary_roles(cards) == ["removal"] * len(COMPLETE_DAMAGE)


def test_player_only_damage_retains_supplied_metadata():
    card = _card(
        "Shock",
        oracle_text="This spell deals 2 damage to target player.",
        role_tags='["utility"]',
        _facts={"roles": []},
    )

    assert _get_primary_roles([card]) == ["utility"]
    assert card["role_tags"] == '["utility"]'
    assert card["_facts"] == {"roles": []}


def test_unknown_tail_retains_supplied_metadata():
    card = _card(
        "Shock",
        oracle_text="Shock deals 2 damage to any target. Skip your next turn.",
        role_tags='["draw"]',
        _facts={"roles": []},
    )

    assert _get_primary_roles([card]) == ["draw"]
    assert card["role_tags"] == '["draw"]'
    assert card["_facts"] == {"roles": []}


def test_generic_nonburn_role_unchanged():
    card = _card("Thrill of Possibility", role_tags='["draw"]')

    assert _get_primary_roles([card]) == ["draw"]
    assert card["role_tags"] == '["draw"]'
