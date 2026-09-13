"""Independent selection regressions using frozen public Oracle negatives."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sabermetrics.intelligence.draw_selection import (
    context,
    evaluate,
    repair,
    select_package,
)

DOCS = Path(__file__).parents[1] / "docs/experiments/draw-selection"
NEGATIVES = json.loads((DOCS / "public-negative-fixtures.v1.json").read_text())["cards"]
POSITIVES = json.loads((DOCS / "public-fixtures.json").read_text())["cards"]


def fixture(name, **updates):
    card = deepcopy(POSITIVES[name])
    if isinstance(card.get("color_identity"), str):
        card["color_identity"] = json.loads(card["color_identity"])
    card.update(price_usd=1, role_tags=["draw"])
    card.update(updates)
    return card


def synthetic(name, text="", typ="Creature — Elf", **updates):
    card = {
        "name": name,
        "oracle_text": text,
        "type_line": typ,
        "mana_cost": "{2}",
        "cmc": 2,
        "color_identity": [],
        "price_usd": 1,
        "role_tags": ["utility"],
    }
    card.update(updates)
    return card


def idol():
    return synthetic(
        "Idol of Oblivion",
        "{T}: Draw a card. Activate only if you created a token this turn.\n"
        "{8}, {T}, Sacrifice this artifact: Create a 10/10 colorless Eldrazi creature token.",
        "Artifact",
        role_tags=["draw"],
    )


def atlas():
    return synthetic(
        "Endless Atlas",
        "{2}, {T}: Draw a card. Activate only if you control three or more lands with the same name.",
        "Artifact",
        role_tags=["draw"],
    )


@pytest.mark.parametrize("card", NEGATIVES, ids=lambda c: c["name"])
def test_known_unmodeled_effects_do_not_receive_draw_credit(card):
    # A creature-rich shell must not erase Adventure, Zombie, suspend, exile,
    # transformation, opponent benefit, or extra-payment restrictions.
    deck = [synthetic(f"Elf {i}") for i in range(30)]
    assert not evaluate(card, context(deck, {"color_identity": ["B", "G"]}))["credible"]


def test_highest_power_does_not_upgrade_to_generic_three_mana_draw():
    divination = synthetic(
        "Divination", "Draw two cards.", "Sorcery", mana_cost="{2}{U}", cmc=3
    )
    assert not evaluate(divination, context([], {}), power=5)["credible"]


def test_idol_cannot_supply_its_own_token_after_sacrificing_itself():
    card = idol()
    assert not evaluate(card, context([card], {}))["credible"]


def test_idol_accepts_external_treasure_creation_not_only_creature_tokens():
    card = idol()
    # Printed front-face effect; flashback not needed to demonstrate token type.
    treasure = synthetic(
        "Synthetic treasure creation", "Create a Treasure token.", "Sorcery"
    )
    assert evaluate(card, context([treasure], {}))["credible"]


def test_treasure_creation_does_not_supply_creature_deaths():
    treasure = synthetic(
        "Synthetic treasure creation", "Create a Treasure token.", "Sorcery"
    )
    assert not evaluate(fixture("Morbid Opportunist"), context([treasure], {}))[
        "credible"
    ]


def test_atlas_requires_repeated_land_names_not_total_land_count():
    unique_lands = [synthetic(f"Unique land {i}", typ="Land") for i in range(35)]
    repeated_basics = [
        synthetic("Island", typ="Basic Land — Island") for _ in range(20)
    ]
    assert not evaluate(atlas(), context(unique_lands, {}))["credible"]
    assert evaluate(atlas(), context(repeated_basics, {}))["credible"]


def test_unknown_custom_engine_is_not_permission_to_cut():
    engine = synthetic(
        "Synthetic unmodeled engine", "Double a resource counter.", role_tags=["engine"]
    )
    commander = {"name": "Synthetic commander", "color_identity": ["B"]}
    deck, receipt = repair([engine], [fixture("Sign in Blood")], commander, 10)
    assert deck == [engine]
    assert not receipt["decisions"]


def test_empirically_supported_utility_is_not_automatic_draw_filler():
    engine = synthetic(
        "Synthetic supported utility",
        "Untap another target permanent.",
        _selection_inclusion=0.7,
    )
    commander = {"name": "Synthetic commander", "color_identity": ["B"]}
    deck, receipt = repair([engine], [fixture("Sign in Blood")], commander, 10)
    assert deck == [engine]
    assert not receipt["decisions"]


def test_package_respects_identity_budget_and_unique_card_names():
    commander = {"name": "Synthetic commander", "color_identity": ["B"]}
    candidates = [
        fixture("Sign in Blood"),
        fixture("Sign in Blood"),
        fixture("Harmonize"),
    ]
    package = select_package(candidates, [], commander, budget=10, count=3)
    assert len({card["name"] for card in package}) == len(package)
    assert all(set(card["color_identity"]) <= {"B"} for card in package)
    assert sum(card["price_usd"] for card in package) <= 10


@pytest.mark.parametrize(
    "card",
    json.loads((DOCS / "public-negative-fixtures.v2.json").read_text())["cards"],
    ids=lambda c: c["name"],
)
def test_full_card_restrictions_cannot_hide_behind_a_draw_clause(card):
    assert not evaluate(card, context([synthetic(f"body{i}") for i in range(30)], {}))[
        "credible"
    ]


def test_premium_draw_unavailable_still_retains_actual_budget_alternatives():
    pool = [fixture("Rhystic Study", price_usd=100)] + [
        fixture(n, price_usd=1)
        for n in [
            "Phyrexian Arena",
            "The Unagi of Kyoshi Island",
            "Notion Thief",
            "Insight Engine",
        ]
    ]
    selected = select_package(pool, [], {"color_identity": ["U", "B"]}, 4, 4, 3)
    assert {c["name"] for c in selected} == {
        "Phyrexian Arena",
        "The Unagi of Kyoshi Island",
        "Notion Thief",
        "Insight Engine",
    }
    assert sum(c["price_usd"] for c in selected) <= 4
    blue = select_package(pool, [], {"color_identity": ["U"]}, 4, 4, 3)
    assert {c["name"] for c in blue} == {"The Unagi of Kyoshi Island", "Insight Engine"}
