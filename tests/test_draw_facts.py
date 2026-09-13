"""Tests for draw_facts.draw_profile.

Fixture names are used only to look up test cases in public-fixtures.json; the
parser itself never sees an advantage from them, which the name-invariance tests
below assert directly.

Run with: pytest test_draw_facts.py
"""

from __future__ import annotations

import json
import re

import pytest

from sabermetrics.intelligence.draw_facts import PROFILE_KEYS, draw_profile

FIXTURES = [
    {
        "name": "Rhystic Study",
        "oracle_text": "Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Enchantment",
    },
    {
        "name": "Phyrexian Arena",
        "oracle_text": "At the beginning of your upkeep, you draw a card and you lose 1 life.",
        "mana_cost": "{1}{B}{B}",
        "cmc": 3.0,
        "type_line": "Enchantment",
    },
    {
        "name": "The Unagi of Kyoshi Island",
        "oracle_text": "Flash\nWard—Waterbend {4}. (Whenever this creature becomes the target of a spell or ability an opponent controls, counter it unless that player pays {4}. They can tap their artifacts and creatures to help. Each one pays for {1}.)\nWhenever an opponent draws their second card each turn, you draw two cards.",
        "mana_cost": "{3}{U}{U}",
        "cmc": 5.0,
        "type_line": "Legendary Creature — Serpent",
    },
    {
        "name": "Notion Thief",
        "oracle_text": "Flash\nIf an opponent would draw a card except the first one they draw in each of their draw steps, instead that player skips that draw and you draw a card.",
        "mana_cost": "{2}{U}{B}",
        "cmc": 4.0,
        "type_line": "Creature — Human Rogue",
    },
    {
        "name": "Insight Engine",
        "oracle_text": "{2}, {T}: Put a charge counter on this artifact, then draw a card for each charge counter on it.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Artifact",
    },
    {
        "name": "Beast Whisperer",
        "oracle_text": "Whenever you cast a creature spell, draw a card.",
        "mana_cost": "{2}{G}{G}",
        "cmc": 4.0,
        "type_line": "Creature — Elf Druid",
    },
    {
        "name": "Guardian Project",
        "oracle_text": "Whenever a nontoken creature you control enters, if it doesn't have the same name as another creature you control or a creature card in your graveyard, draw a card.",
        "mana_cost": "{3}{G}",
        "cmc": 4.0,
        "type_line": "Enchantment",
    },
    {
        "name": "Skullclamp",
        "oracle_text": "Equipped creature gets +1/-1.\nWhenever equipped creature dies, draw two cards.\nEquip {1}",
        "mana_cost": "{1}",
        "cmc": 1.0,
        "type_line": "Artifact — Equipment",
    },
    {
        "name": "Faithless Looting",
        "oracle_text": "Draw two cards, then discard two cards.\nFlashback {2}{R} (You may cast this card from your graveyard for its flashback cost. Then exile it.)",
        "mana_cost": "{R}",
        "cmc": 1.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Harmonize",
        "oracle_text": "Draw three cards.",
        "mana_cost": "{2}{G}{G}",
        "cmc": 4.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Sign in Blood",
        "oracle_text": "Target player draws two cards and loses 2 life.",
        "mana_cost": "{B}{B}",
        "cmc": 2.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Bident of Thassa",
        "oracle_text": "Whenever a creature you control deals combat damage to a player, you may draw a card.\n{1}{U}, {T}: Creatures your opponents control attack this turn if able.",
        "mana_cost": "{2}{U}{U}",
        "cmc": 4.0,
        "type_line": "Legendary Enchantment Artifact",
    },
    {
        "name": "Morbid Opportunist",
        "oracle_text": "Whenever one or more other creatures die, draw a card. This ability triggers only once each turn.",
        "mana_cost": "{2}{B}",
        "cmc": 3.0,
        "type_line": "Creature — Human Rogue",
    },
    {
        "name": "Village Rites",
        "oracle_text": "As an additional cost to cast this spell, sacrifice a creature.\nDraw two cards.",
        "mana_cost": "{B}",
        "cmc": 1.0,
        "type_line": "Instant",
    },
]
BY_NAME = {card["name"]: card for card in FIXTURES}


# --------------------------------------------------------------------------------
# Expected profiles for the 14 public fixtures.
# Each entry lists the structural fields; caveats are checked separately because
# their wording is prose rather than an interface.
# --------------------------------------------------------------------------------

EXPECTED = {
    "Rhystic Study": {
        "status": "supported",
        "mechanism": "recurring_opponent",
        "net_cards": 1,
        "mana_value": 3,
        "activation_mana": None,
        "prerequisites": [
            "opponent_may_pay:{1}",
            "optional:controller_may",
            "trigger:opponent_casts_spell",
        ],
        "confidence": "supported",
    },
    "Phyrexian Arena": {
        "status": "supported",
        "mechanism": "recurring_self",
        "net_cards": 1,
        "mana_value": 3,
        "activation_mana": None,
        "prerequisites": ["trigger:your_upkeep"],
        "confidence": "supported",
    },
    "The Unagi of Kyoshi Island": {
        "status": "supported",
        "mechanism": "recurring_opponent",
        "net_cards": 2,
        "mana_value": 5,
        "activation_mana": None,
        "prerequisites": ["trigger:opponent_draws_extra_card"],
        "confidence": "supported",
    },
    "Notion Thief": {
        "status": "supported",
        "mechanism": "conditional",
        "net_cards": 1,
        "mana_value": 4,
        "activation_mana": None,
        "prerequisites": [
            "excludes:first_draw_step_card",
            "trigger:opponent_draws_extra_card",
        ],
        "confidence": "supported",
    },
    "Insight Engine": {
        "status": "supported",
        "mechanism": "activated",
        "net_cards": None,
        "mana_value": 3,
        "activation_mana": 2,
        "prerequisites": [
            "cost:mana:2",
            "cost:tap_self",
            "scaling:charge_counters",
            "scaling:variable",
        ],
        "confidence": "supported",
    },
    "Beast Whisperer": {
        "status": "supported",
        "mechanism": "recurring_self",
        "net_cards": 1,
        "mana_value": 4,
        "activation_mana": None,
        "prerequisites": ["trigger:you_cast_spell", "typal:creature"],
        "confidence": "supported",
    },
    "Guardian Project": {
        "status": "supported",
        "mechanism": "recurring_self",
        "net_cards": 1,
        "mana_value": 4,
        "activation_mana": None,
        "prerequisites": [
            "condition:unique_name",
            "restriction:nontoken",
            "trigger:creature_you_control_enters",
        ],
        "confidence": "supported",
    },
    "Skullclamp": {
        "status": "supported",
        "mechanism": "recurring_self",
        "net_cards": 2,
        "mana_value": 1,
        "activation_mana": None,
        "prerequisites": [
            "requires:attached_to_creature",
            "trigger:equipped_creature_dies",
        ],
        "confidence": "supported",
    },
    "Faithless Looting": {
        "status": "supported",
        "mechanism": "immediate",
        "net_cards": -1,
        "mana_value": 1,
        "activation_mana": None,
        "prerequisites": [],
        "confidence": "supported",
    },
    "Harmonize": {
        "status": "supported",
        "mechanism": "immediate",
        "net_cards": 2,
        "mana_value": 4,
        "activation_mana": None,
        "prerequisites": [],
        "confidence": "supported",
    },
    "Sign in Blood": {
        "status": "supported",
        "mechanism": "immediate",
        "net_cards": 1,
        "mana_value": 2,
        "activation_mana": None,
        "prerequisites": ["target:player"],
        "confidence": "supported",
    },
    "Bident of Thassa": {
        "status": "supported",
        "mechanism": "recurring_self",
        "net_cards": 1,
        "mana_value": 4,
        "activation_mana": None,
        "prerequisites": [
            "optional:controller_may",
            "requires:creature_you_control",
            "trigger:combat_damage_to_player",
        ],
        "confidence": "supported",
    },
    "Morbid Opportunist": {
        "status": "supported",
        "mechanism": "recurring_self",
        "net_cards": 1,
        "mana_value": 3,
        "activation_mana": None,
        "prerequisites": [
            "limit:once_each_turn",
            "restriction:other_creatures",
            "trigger:creature_dies",
        ],
        "confidence": "supported",
    },
    "Village Rites": {
        "status": "supported",
        "mechanism": "immediate",
        "net_cards": None,
        "mana_value": 1,
        "activation_mana": None,
        "prerequisites": ["cost:sacrifice_creature"],
        "confidence": "supported",
    },
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_profile_fields(name):
    profile = draw_profile(BY_NAME[name])
    for key, value in EXPECTED[name].items():
        assert profile[key] == value, f"{name}: {key}"


def test_all_fixtures_are_covered():
    assert sorted(EXPECTED) == sorted(BY_NAME)
    assert len(FIXTURES) == 14


# --------------------------------------------------------------------------------
# Structural invariants
# --------------------------------------------------------------------------------

ALL_CARDS = FIXTURES + [
    {
        "name": "Neg Vanilla",
        "oracle_text": "Flying",
        "type_line": "Creature — Bird",
        "mana_cost": "{1}{U}",
        "cmc": 2.0,
    },
    {"name": "Neg Empty", "oracle_text": "", "type_line": "Land"},
    {"name": "Neg No Text Field", "type_line": "Land"},
]


@pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.get("name", "?"))
def test_profile_shape(card):
    profile = draw_profile(card)
    assert tuple(profile) == PROFILE_KEYS
    assert profile["status"] in {"supported", "unknown", "none"}
    assert profile["mechanism"] in {
        None,
        "immediate",
        "recurring_self",
        "recurring_opponent",
        "activated",
        "conditional",
    }
    assert profile["confidence"] in {"supported", "partial"}
    assert isinstance(profile["prerequisites"], list)
    assert all(isinstance(item, str) for item in profile["prerequisites"])
    assert profile["prerequisites"] == sorted(profile["prerequisites"])
    assert isinstance(profile["evidence"], list)
    assert all(isinstance(item, str) for item in profile["evidence"])
    assert isinstance(profile["caveats"], list)
    assert all(isinstance(item, str) for item in profile["caveats"])
    for numeric in ("net_cards", "mana_value", "activation_mana"):
        assert profile[numeric] is None or isinstance(profile[numeric], (int, float))
    json.dumps(profile)  # must be serialisable


@pytest.mark.parametrize("card", FIXTURES, ids=lambda c: c["name"])
def test_evidence_is_exact_original_substring(card):
    profile = draw_profile(card)
    assert profile["evidence"], "every supported fixture should cite evidence"
    for snippet in profile["evidence"]:
        assert snippet in card["oracle_text"]
        assert snippet == snippet.strip()


@pytest.mark.parametrize("card", FIXTURES, ids=lambda c: c["name"])
def test_evidence_first_item_mentions_drawing(card):
    profile = draw_profile(card)
    assert re.search(r"\bdraws?\b", profile["evidence"][0], re.IGNORECASE)


@pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.get("name", "?"))
def test_deterministic_repeated_calls(card):
    assert draw_profile(card) == draw_profile(card)


@pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.get("name", "?"))
def test_input_is_not_mutated(card):
    before = json.dumps(card, sort_keys=True)
    draw_profile(card)
    assert json.dumps(card, sort_keys=True) == before


# --------------------------------------------------------------------------------
# Name invariance: the parser must read only printed text, never the card name.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("card", FIXTURES, ids=lambda c: c["name"])
@pytest.mark.parametrize("replacement", ["", "Xyzzy", "Rhystic Study", "Harmonize"])
def test_name_invariance(card, replacement):
    baseline = draw_profile(card)
    renamed = dict(card, name=replacement)
    assert draw_profile(renamed) == baseline


@pytest.mark.parametrize("card", FIXTURES, ids=lambda c: c["name"])
def test_name_absent_is_invariant(card):
    baseline = draw_profile(card)
    without = {k: v for k, v in card.items() if k != "name"}
    assert draw_profile(without) == baseline


# --------------------------------------------------------------------------------
# Synthetic negatives and boundary shapes (invented text, not printed cards).
# --------------------------------------------------------------------------------


def _synthetic(text, type_line="Enchantment", cmc=2.0, cost="{1}{U}"):
    return {
        "name": "Synthetic",
        "oracle_text": text,
        "type_line": type_line,
        "mana_cost": cost,
        "cmc": cmc,
    }


def test_no_draw_text_reports_none():
    profile = draw_profile(_synthetic("Flying\nVigilance", "Creature — Bird"))
    assert profile["status"] == "none"
    assert profile["mechanism"] is None
    assert profile["net_cards"] is None
    assert profile["evidence"] == []
    assert profile["confidence"] == "supported"


def test_static_draw_restriction_is_unknown():
    profile = draw_profile(
        _synthetic("Players can't draw more than one card each turn.")
    )
    assert profile["status"] == "unknown"
    assert profile["mechanism"] is None
    assert profile["net_cards"] is None
    assert profile["confidence"] == "partial"
    assert profile["caveats"]


def test_unsupported_two_sentence_payment_shape_is_unknown():
    profile = draw_profile(
        _synthetic(
            "Whenever a creature dies, you may pay {1}. If you do, draw a card.",
            "Creature — Human Rogue",
        )
    )
    assert profile["status"] == "unknown"
    assert profile["net_cards"] is None


def test_opponent_only_draw_claims_no_gain_for_you():
    profile = draw_profile(
        _synthetic("Each opponent draws a card.", "Sorcery", 1.0, "{U}")
    )
    assert profile["status"] == "none"
    assert profile["mechanism"] is None
    assert profile["net_cards"] is None


def test_variable_draw_is_not_quantified():
    profile = draw_profile(_synthetic("Draw X cards.", "Sorcery", 3.0, "{X}{1}{U}"))
    assert profile["net_cards"] is None
    assert "scaling:variable" in profile["prerequisites"]
    assert profile["confidence"] == "partial"


def test_counter_scaling_is_not_quantified():
    profile = draw_profile(
        _synthetic(
            "At the beginning of your upkeep, draw a card for each charge counter on this artifact.",
            "Artifact",
            4.0,
            "{4}",
        )
    )
    assert profile["mechanism"] == "recurring_self"
    assert profile["net_cards"] is None
    assert "scaling:variable" in profile["prerequisites"]


def test_immediate_spell_consumes_itself():
    profile = draw_profile(_synthetic("Draw a card.", "Instant", 1.0, "{U}"))
    assert profile["mechanism"] == "immediate"
    assert profile["net_cards"] == 0


def test_mandatory_discard_is_subtracted_but_optional_is_not():
    mandatory = draw_profile(
        _synthetic("Draw three cards, then discard a card.", "Sorcery", 3.0, "{2}{U}")
    )
    optional = draw_profile(
        _synthetic(
            "Draw three cards, then you may discard a card.", "Sorcery", 3.0, "{2}{U}"
        )
    )
    assert mandatory["net_cards"] == 1
    assert optional["net_cards"] == 2


def test_recurring_ability_is_per_event_not_amortized():
    profile = draw_profile(
        _synthetic(
            "At the beginning of your upkeep, draw two cards.",
            "Enchantment",
            6.0,
            "{4}{U}{U}",
        )
    )
    assert profile["mechanism"] == "recurring_self"
    assert profile["net_cards"] == 2  # not reduced by the 6-mana casting cost
    assert profile["mana_value"] == 6


def test_activated_ability_reports_activation_mana():
    profile = draw_profile(_synthetic("{3}, {T}: Draw a card.", "Artifact", 2.0, "{2}"))
    assert profile["mechanism"] == "activated"
    assert profile["activation_mana"] == 3
    assert profile["net_cards"] == 1
    assert "cost:tap_self" in profile["prerequisites"]


def test_sacrifice_additional_cost_makes_net_unknown():
    profile = draw_profile(
        _synthetic(
            "As an additional cost to cast this spell, sacrifice an artifact.\nDraw two cards.",
            "Instant",
            1.0,
            "{B}",
        )
    )
    assert profile["net_cards"] is None
    assert "cost:sacrifice_artifact" in profile["prerequisites"]


def test_missing_cmc_falls_back_to_mana_cost():
    card = {
        "oracle_text": "Draw two cards.",
        "type_line": "Sorcery",
        "mana_cost": "{2}{U}",
    }
    assert draw_profile(card)["mana_value"] == 3


def test_unvaluable_mana_cost_yields_none_mana_value():
    card = {
        "oracle_text": "Draw two cards.",
        "type_line": "Sorcery",
        "mana_cost": "{X}{U}",
    }
    assert draw_profile(card)["mana_value"] is None


def test_reminder_text_is_ignored_for_classification():
    plain = draw_profile(
        _synthetic(
            "Whenever you cast a creature spell, draw a card.",
            "Creature — Elf Druid",
            4.0,
            "{2}{G}{G}",
        )
    )
    with_reminder = draw_profile(
        _synthetic(
            "Ward {2} (Whenever this creature becomes the target of a spell an opponent "
            "controls, counter it unless that player pays {2}.)\n"
            "Whenever you cast a creature spell, draw a card.",
            "Creature — Elf Druid",
            4.0,
            "{2}{G}{G}",
        )
    )
    assert with_reminder["mechanism"] == plain["mechanism"]
    assert with_reminder["net_cards"] == plain["net_cards"]
    assert with_reminder["prerequisites"] == plain["prerequisites"]


@pytest.mark.parametrize(
    "text",
    [
        "Whenever an artifact you control enters, draw a card.",
        "Whenever you cast your second spell each turn, draw a card.",
        "Whenever a creature with power 4 or greater dies, draw a card.",
        "Whenever a creature you control enters, if you control a Dragon, draw a card.",
        "At the beginning of your upkeep, draw a card if you have no cards in hand.",
        "{T}, Sacrifice a creature: Draw two cards.",
    ],
)
def test_unknown_gates_are_not_verified(text):
    p = draw_profile(_synthetic(text))
    assert p["status"] != "supported" or p["confidence"] == "partial"


def test_typal_cast_is_not_generic_creature_cast():
    p = draw_profile(_synthetic("Whenever you cast a Dragon spell, draw a card."))
    assert "typal:dragon" in p["prerequisites"]
    assert "typal:creature" not in p["prerequisites"]


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), -2, True])
def test_bad_numeric_mana_value_uses_printed_cost(bad):
    p = draw_profile(_synthetic("Draw two cards.", "Sorcery", bad, "{2}{U}"))
    assert p["mana_value"] == 3
    json.dumps(p, allow_nan=False)


REGRESSION_FIXTURES = [
    {
        "name": "Brainstorm",
        "oracle_text": "Draw three cards, then put two cards from your hand on top of your library in any order.",
        "mana_cost": "{U}",
        "cmc": 1.0,
        "type_line": "Instant",
    },
    {
        "name": "Humble Defector",
        "oracle_text": "{T}: Draw two cards. Target opponent gains control of this creature. Activate only during your turn.",
        "mana_cost": "{1}{R}",
        "cmc": 2.0,
        "type_line": "Creature — Human Rogue",
    },
    {
        "name": "Edgewall Innkeeper",
        "oracle_text": "Whenever you cast a creature spell that has an Adventure, draw a card. (It doesn't need to have gone on the adventure first.)",
        "mana_cost": "{G}",
        "cmc": 1.0,
        "type_line": "Creature — Human Peasant",
    },
    {
        "name": "Undead Augur",
        "oracle_text": "Whenever this creature or another Zombie you control dies, you draw a card and you lose 1 life.",
        "mana_cost": "{B}{B}",
        "cmc": 2.0,
        "type_line": "Creature — Zombie Wizard",
    },
    {
        "name": "Mindstorm Crown",
        "oracle_text": "At the beginning of your upkeep, draw a card if you had no cards in hand at the beginning of this turn. If you had a card in hand, this artifact deals 1 damage to you.",
        "mana_cost": "{3}",
        "cmc": 3.0,
        "type_line": "Artifact",
    },
    {
        "name": "Ancestral Vision",
        "oracle_text": "Suspend 4—{U} (Rather than cast this card from your hand, pay {U} and exile it with four time counters on it. At the beginning of your upkeep, remove a time counter. When the last is removed, you may cast it without paying its mana cost.)\nTarget player draws three cards.",
        "mana_cost": "",
        "cmc": 0.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Glimpse of Nature",
        "oracle_text": "Whenever you cast a creature spell this turn, draw a card.",
        "mana_cost": "{G}",
        "cmc": 1.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Idol of Oblivion",
        "oracle_text": "{T}: Draw a card. Activate only if you created a token this turn.\n{8}, {T}, Sacrifice this artifact: Create a 10/10 colorless Eldrazi creature token.",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact",
    },
    {
        "name": "Endless Atlas",
        "oracle_text": "{2}, {T}: Draw a card. Activate only if you control three or more lands with the same name.",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact",
    },
    {
        "name": "Mazemind Tome",
        "oracle_text": "{T}, Put a page counter on this artifact: Scry 1. (Look at the top card of your library. You may put that card on the bottom.)\n{2}, {T}, Put a page counter on this artifact: Draw a card.\nWhen there are four or more page counters on this artifact, exile it. If you do, you gain 4 life.",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact — Book",
    },
    {
        "name": "Sunset Pyramid",
        "oracle_text": "This artifact enters with three brick counters on it.\n{2}, {T}, Remove a brick counter from this artifact: Draw a card.\n{2}, {T}: Scry 1.",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact",
    },
    {
        "name": "Mask of Memory",
        "oracle_text": "Whenever equipped creature deals combat damage to a player, you may draw two cards. If you do, discard a card.\nEquip {1} ({1}: Attach to target creature you control. Equip only as a sorcery.)",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact — Equipment",
    },
    {
        "name": "Phyrexian Arena",
        "oracle_text": "At the beginning of your upkeep, you draw a card and you lose 1 life.",
        "mana_cost": "{1}{B}{B}",
        "cmc": 3.0,
        "type_line": "Enchantment",
    },
    {
        "name": "Moldervine Reclamation",
        "oracle_text": "Whenever a creature you control dies, you gain 1 life and draw a card.",
        "mana_cost": "{3}{B}{G}",
        "cmc": 5.0,
        "type_line": "Enchantment",
    },
    {
        "name": "Skullclamp",
        "oracle_text": "Equipped creature gets +1/-1.\nWhenever equipped creature dies, draw two cards.\nEquip {1}",
        "mana_cost": "{1}",
        "cmc": 1.0,
        "type_line": "Artifact — Equipment",
    },
    {
        "name": "Night's Whisper",
        "oracle_text": "You draw two cards and lose 2 life.",
        "mana_cost": "{1}{B}",
        "cmc": 2.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Read the Bones",
        "oracle_text": "Scry 2, then draw two cards. You lose 2 life. (To scry 2, look at the top two cards of your library, then put any number of them on the bottom and the rest on top in any order.)",
        "mana_cost": "{2}{B}",
        "cmc": 3.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Mind's Eye",
        "oracle_text": "Whenever an opponent draws a card, you may pay {1}. If you do, draw a card.",
        "mana_cost": "{5}",
        "cmc": 5.0,
        "type_line": "Artifact",
    },
    {
        "name": "Staff of Nin",
        "oracle_text": "At the beginning of your upkeep, draw a card.\n{T}: This artifact deals 1 damage to any target.",
        "mana_cost": "{6}",
        "cmc": 6.0,
        "type_line": "Artifact",
    },
]


@pytest.mark.parametrize(
    "card",
    REGRESSION_FIXTURES[:7] + REGRESSION_FIXTURES[11:12],
    ids=lambda c: c["name"],
)
def test_public_unparsed_restrictions_are_never_verified(card):
    p = draw_profile(card)
    assert p["status"] != "supported" or p["confidence"] == "partial"
    assert p["prerequisites"]


@pytest.mark.parametrize(
    "name, identifier",
    [
        ("Idol of Oblivion", "condition:created_token_this_turn"),
        ("Endless Atlas", "condition:three_lands_same_name"),
    ],
)
def test_activation_gate_is_explicit_and_evidenced(name, identifier):
    card = next(c for c in REGRESSION_FIXTURES if c["name"] == name)
    p = draw_profile(card)
    assert p["confidence"] == "supported"
    assert identifier in p["prerequisites"]
    assert any("Activate only" in evidence for evidence in p["evidence"])


@pytest.mark.parametrize("card", REGRESSION_FIXTURES, ids=lambda c: c["name"])
def test_regression_evidence_and_rename(card):
    p = draw_profile(card)
    assert all(e in card["oracle_text"] for e in p["evidence"])
    assert p == draw_profile(dict(card, name="Other name"))


def test_two_sentence_optional_payment_is_unknown():
    card = next(c for c in REGRESSION_FIXTURES if c["name"] == "Mind's Eye")
    assert draw_profile(card)["status"] == "unknown"


RESOURCE_FIXTURES = [
    {
        "name": "Sunset Pyramid",
        "oracle_text": "This artifact enters with three brick counters on it.\n{2}, {T}, Remove a brick counter from this artifact: Draw a card.\n{2}, {T}: Scry 1.",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact",
    },
    {
        "name": "Mazemind Tome",
        "oracle_text": "{T}, Put a page counter on this artifact: Scry 1. (Look at the top card of your library. You may put that card on the bottom.)\n{2}, {T}, Put a page counter on this artifact: Draw a card.\nWhen there are four or more page counters on this artifact, exile it. If you do, you gain 4 life.",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact — Book",
    },
    {
        "name": "Bane Alley Broker",
        "oracle_text": "{T}: Draw a card, then exile a card from your hand face down.\nYou may look at cards exiled with this creature.\n{U}{B}, {T}: Return a card exiled with this creature to its owner's hand.",
        "mana_cost": "{1}{U}{B}",
        "cmc": 3.0,
        "type_line": "Creature — Human Rogue",
    },
    {
        "name": "Loreseeker's Stone",
        "oracle_text": "{3}, {T}: Draw three cards. This ability costs {1} more to activate for each card in your hand.",
        "mana_cost": "{6}",
        "cmc": 6.0,
        "type_line": "Artifact",
    },
    {
        "name": "Inspired Idea",
        "oracle_text": "Cleave {3}{U}{U} (You may cast this spell for its cleave cost. If you do, remove the words in square brackets.)\nDraw three cards. [Your maximum hand size is reduced by three for the rest of the game.]",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Sinister Gnarlbark",
        "oracle_text": "At the beginning of your end step, draw a card and blight 1. (Put a -1/-1 counter on a creature you control.)",
        "mana_cost": "{2}{B}",
        "cmc": 3.0,
        "type_line": "Creature — Treefolk Warlock",
    },
    {
        "name": "Urza's Blueprints",
        "oracle_text": "Echo {6} (At the beginning of your upkeep, if this came under your control since the beginning of your last upkeep, sacrifice it unless you pay its echo cost.)\n{T}: Draw a card.",
        "mana_cost": "{6}",
        "cmc": 6.0,
        "type_line": "Artifact",
    },
    {
        "name": "Jacob Hauken, Inspector // Hauken's Insight",
        "oracle_text": "{T}: Draw a card, then exile a card from your hand face down. You may look at that card for as long as it remains exiled. You may pay {4}{U}{U}. If you do, transform Jacob Hauken. // At the beginning of your upkeep, exile the top card of your library face down. You may look at that card for as long as it remains exiled.\nOnce during each of your turns, you may play a land or cast a spell from among the cards exiled with this permanent without paying its mana cost.",
        "mana_cost": "{1}{U}",
        "cmc": 2.0,
        "type_line": "Legendary Creature — Human Advisor // Legendary Enchantment",
    },
]


@pytest.mark.parametrize(
    "card, cap",
    [(RESOURCE_FIXTURES[0], 3), (RESOURCE_FIXTURES[1], 4)],
    ids=["brick", "page"],
)
def test_finite_counter_draw_has_explicit_cap_and_evidence(card, cap):
    p = draw_profile(card)
    assert p["confidence"] == "supported"
    assert p["net_cards"] == 1
    assert p["activation_mana"] == 2
    assert f"resource:draw_activations:{cap}" in p["prerequisites"]
    assert len(p["evidence"]) >= 2
    assert all(e in card["oracle_text"] for e in p["evidence"])
    assert p == draw_profile(dict(card, name="Unrelated name"))


@pytest.mark.parametrize("card", RESOURCE_FIXTURES[2:], ids=lambda c: c["name"])
def test_global_costs_and_drawbacks_are_unverified(card):
    p = draw_profile(card)
    assert p["status"] != "supported" or p["confidence"] == "partial"
    assert p["net_cards"] is None


@pytest.mark.parametrize("card", RESOURCE_FIXTURES[:2], ids=lambda c: c["name"])
def test_counter_cost_without_printed_source_or_cap_stays_unparsed(card):
    clone = dict(card)
    if "brick" in clone["oracle_text"]:
        clone["oracle_text"] = clone["oracle_text"].replace(
            "This artifact enters with three brick counters on it.", ""
        )
    else:
        clone["oracle_text"] = clone["oracle_text"].replace(
            "When there are four or more page counters on this artifact, exile it.", ""
        )
    p = draw_profile(clone)
    assert p["confidence"] == "partial"
    assert "cost:unparsed_activation" in p["prerequisites"]


def test_unsupported_upkeep_payment_does_not_become_free_draw():
    p = draw_profile(
        _synthetic(
            "At the beginning of your upkeep, pay {2}.\n{T}: Draw a card.", "Artifact"
        )
    )
    assert p["confidence"] == "partial"


HAND_MOVEMENT_FIXTURES = [
    {
        "name": "Sensei's Divining Top",
        "oracle_text": "{1}: Look at the top three cards of your library, then put them back in any order.\n{T}: Draw a card, then put this artifact on top of its owner's library.",
        "mana_cost": "{1}",
        "cmc": 1.0,
        "type_line": "Artifact",
    },
    {
        "name": "Azor's Gateway // Sanctum of the Sun",
        "oracle_text": "{1}, {T}: Draw a card, then exile a card from your hand. If cards with five or more different mana values are exiled with Azor's Gateway, you gain 5 life, untap Azor's Gateway, and transform it. // (Transforms from Azor's Gateway.)\n{T}: Add X mana of any one color, where X is your life total.",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Legendary Artifact // Legendary Land",
    },
    {
        "name": "See Beyond",
        "oracle_text": "Draw two cards, then shuffle a card from your hand into your library.",
        "mana_cost": "{1}{U}",
        "cmc": 2.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Insatiable Avarice",
        "oracle_text": "Spree (Choose one or more additional costs.)\n+ {2} — Search your library for a card, then shuffle and put that card on top.\n+ {B}{B} — Target player draws three cards and loses 3 life.",
        "mana_cost": "{B}",
        "cmc": 1.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Promise of Power",
        "oracle_text": "Choose one —\n• You draw five cards and you lose 5 life.\n• Create an X/X black Demon creature token with flying, where X is the number of cards in your hand.\nEntwine {4} (Choose both if you pay the entwine cost.)",
        "mana_cost": "{2}{B}{B}{B}",
        "cmc": 5.0,
        "type_line": "Sorcery",
    },
]


@pytest.mark.parametrize("card", HAND_MOVEMENT_FIXTURES, ids=lambda c: c["name"])
def test_modal_cost_and_hand_or_source_return_are_not_verified(card):
    p = draw_profile(card)
    assert p["status"] != "supported" or p["confidence"] == "partial"
    assert p["net_cards"] is None
    assert p == draw_profile(dict(card, name="Unrelated name"))
