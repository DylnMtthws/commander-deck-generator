"""Tests over the 18 public fixtures plus synthetic negatives.

Fixtures are looked up by name here only for test readability; the parser under
test never reads the 'name' field (see test_name_invariance).
"""

import pytest

from sabermetrics.intelligence import commander_contracts as cc

FIXTURES = [
    {
        "name": "Lathril, Blade of the Elves",
        "oracle_text": "Menace (This creature can't be blocked except by two or more creatures.)\nWhenever Lathril deals combat damage to a player, create that many 1/1 green Elf Warrior creature tokens.\n{T}, Tap ten untapped Elves you control: Each opponent loses 10 life and you gain 10 life.",
        "mana_cost": "{2}{B}{G}",
        "cmc": 4.0,
        "type_line": "Legendary Creature — Elf Noble",
    },
    {
        "name": "Krenko, Mob Boss",
        "oracle_text": "{T}: Create X 1/1 red Goblin creature tokens, where X is the number of Goblins you control.",
        "mana_cost": "{2}{R}{R}",
        "cmc": 4.0,
        "type_line": "Legendary Creature — Goblin Warrior",
    },
    {
        "name": "Giada, Font of Hope",
        "oracle_text": "Flying, vigilance\nEach other Angel you control enters with an additional +1/+1 counter on it for each Angel you already control.\n{T}: Add {W}. Spend this mana only to cast an Angel spell.",
        "mana_cost": "{1}{W}",
        "cmc": 2.0,
        "type_line": "Legendary Creature — Angel",
    },
    {
        "name": "Vivi Ornitier",
        "oracle_text": "{0}: Add X mana in any combination of {U} and/or {R}, where X is Vivi Ornitier's power. Activate only during your turn and only once each turn.\nWhenever you cast a noncreature spell, put a +1/+1 counter on Vivi Ornitier and it deals 1 damage to each opponent.",
        "mana_cost": "{1}{U}{R}",
        "cmc": 3.0,
        "type_line": "Legendary Creature — Wizard",
    },
    {
        "name": "Arcades, the Strategist",
        "oracle_text": "Flying, vigilance\nWhenever a creature you control with defender enters, draw a card.\nEach creature you control with defender assigns combat damage equal to its toughness rather than its power and can attack as though it didn't have defender.",
        "mana_cost": "{1}{G}{W}{U}",
        "cmc": 4.0,
        "type_line": "Legendary Creature — Elder Dragon",
    },
    {
        "name": "Beast Whisperer",
        "oracle_text": "Whenever you cast a creature spell, draw a card.",
        "mana_cost": "{2}{G}{G}",
        "cmc": 4.0,
        "type_line": "Creature — Elf Druid",
    },
    {
        "name": "Llanowar Elves",
        "oracle_text": "{T}: Add {G}.",
        "mana_cost": "{G}",
        "cmc": 1.0,
        "type_line": "Creature — Elf Druid",
    },
    {
        "name": "Elvish Visionary",
        "oracle_text": "When this creature enters, draw a card.",
        "mana_cost": "{1}{G}",
        "cmc": 2.0,
        "type_line": "Creature — Elf Shaman",
    },
    {
        "name": "Wall of Omens",
        "oracle_text": "Defender\nWhen this creature enters, draw a card.",
        "mana_cost": "{1}{W}",
        "cmc": 2.0,
        "type_line": "Creature — Wall",
    },
    {
        "name": "Wall of Blossoms",
        "oracle_text": "Defender\nWhen this creature enters, draw a card.",
        "mana_cost": "{1}{G}",
        "cmc": 2.0,
        "type_line": "Creature — Plant Wall",
    },
    {
        "name": "Spirited Companion",
        "oracle_text": "When this creature enters, draw a card.",
        "mana_cost": "{1}{W}",
        "cmc": 2.0,
        "type_line": "Enchantment Creature — Dog",
    },
    {
        "name": "Inspiring Overseer",
        "oracle_text": "Flying\nWhen this creature enters, you gain 1 life and draw a card.",
        "mana_cost": "{2}{W}",
        "cmc": 3.0,
        "type_line": "Creature — Angel Cleric",
    },
    {
        "name": "Young Pyromancer",
        "oracle_text": "Whenever you cast an instant or sorcery spell, create a 1/1 red Elemental creature token.",
        "mana_cost": "{1}{R}",
        "cmc": 2.0,
        "type_line": "Creature — Human Shaman",
    },
    {
        "name": "Elven Ambush",
        "oracle_text": "Create a 1/1 green Elf Warrior creature token for each Elf you control.",
        "mana_cost": "{3}{G}",
        "cmc": 4.0,
        "type_line": "Instant",
    },
    {
        "name": "Harmonize",
        "oracle_text": "Draw three cards.",
        "mana_cost": "{2}{G}{G}",
        "cmc": 4.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Divination",
        "oracle_text": "Draw two cards.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Sorcery",
    },
    {
        "name": "Opt",
        "oracle_text": "Scry 1. (Look at the top card of your library. You may put that card on the bottom.)\nDraw a card.",
        "mana_cost": "{U}",
        "cmc": 1.0,
        "type_line": "Instant",
    },
    {
        "name": "Goblin Matron",
        "oracle_text": "When this creature enters, you may search your library for a Goblin card, reveal that card, put it into your hand, then shuffle.",
        "mana_cost": "{2}{R}",
        "cmc": 3.0,
        "type_line": "Creature — Goblin",
    },
]
BY_NAME = {card["name"]: card for card in FIXTURES}
COMMANDERS = [
    "Lathril, Blade of the Elves",
    "Krenko, Mob Boss",
    "Giada, Font of Hope",
    "Vivi Ornitier",
    "Arcades, the Strategist",
]


def scopes(result, key="contracts"):
    return [item["scope"] for item in result[key]]


def by_scope(result, scope, key="contributions"):
    return next(item for item in result[key] if item["scope"] == scope)


@pytest.mark.parametrize("card", FIXTURES, ids=lambda c: c["name"])
def test_profile_schema_and_evidence_is_exact_substring(card):
    profile = cc.commander_profile(card)
    assert profile["coverage"] == "incomplete" and profile["caveats"]
    for contract in profile["contracts"]:
        assert contract["kind"] in {
            "tribal",
            "cast",
            "token_scaling",
            "defender",
            "mana_value",
            "power",
        }
        assert contract["confidence"] in {"supported", "partial"}
        assert isinstance(contract["requirements"], dict)
        for text in contract["evidence"]:
            assert text in card["oracle_text"] or text in card["type_line"]


@pytest.mark.parametrize("card", FIXTURES, ids=lambda c: c["name"])
def test_contribution_schema_against_every_commander(card):
    for name in COMMANDERS:
        result = cc.contribution(card, BY_NAME[name])
        assert result["coverage"] == "incomplete" and result["caveats"]
        for item in result["contributions"]:
            assert item["confidence"] in {"supported", "partial"}
            assert item["value"] is None or isinstance(
                item["value"], (bool, int, float)
            )
            for text in item["evidence"]:
                assert text in card["oracle_text"] or text in card["type_line"]


def test_lathril_threshold_is_explicit_and_a_body_does_not_prove_activation():
    profile = cc.commander_profile(BY_NAME["Lathril, Blade of the Elves"])
    tribal = next(c for c in profile["contracts"] if c["scope"] == "tribal:elf")
    assert tribal["requirements"]["count_threshold"] == 10
    assert tribal["requirements"]["state"] == "untapped"
    assert "Tap ten untapped Elves you control" in tribal["evidence"]
    item = by_scope(
        cc.contribution(
            BY_NAME["Llanowar Elves"], BY_NAME["Lathril, Blade of the Elves"]
        ),
        "tribal:elf",
    )
    assert item["value"] == 1 and item["confidence"] == "partial"


def test_token_scaling_is_distinct_from_printed_subtype():
    lathril = BY_NAME["Lathril, Blade of the Elves"]
    assert "token_scaling:produced:elf_warrior" in scopes(cc.commander_profile(lathril))
    ambush = cc.contribution(BY_NAME["Elven Ambush"], lathril)
    # An instant that creates Elf tokens is not itself an Elf.
    assert ambush["creature_types"] == []
    assert by_scope(ambush, "tribal:elf")["value"] == 0
    assert (
        by_scope(ambush, "token_scaling:produced:elf_warrior:token_producer")["value"]
        is True
    )


def test_krenko_counts_permanents_not_tokens_created_by_others():
    profile = cc.commander_profile(BY_NAME["Krenko, Mob Boss"])
    token = next(c for c in profile["contracts"] if c["kind"] == "token_scaling")
    assert token["requirements"]["counted_type"] == "goblin"
    matron = cc.contribution(BY_NAME["Goblin Matron"], BY_NAME["Krenko, Mob Boss"])
    assert by_scope(matron, "tribal:goblin")["value"] is True
    assert by_scope(matron, token["scope"] + ":token_producer")["value"] is False
    assert by_scope(matron, token["scope"] + ":counted_body")["value"] == 1


def test_giada_angel_restricted_mana_requires_an_angel_creature_spell():
    giada = BY_NAME["Giada, Font of Hope"]
    assert "cast:tribal:angel" in scopes(cc.commander_profile(giada))
    assert (
        by_scope(
            cc.contribution(BY_NAME["Inspiring Overseer"], giada), "cast:tribal:angel"
        )["value"]
        is True
    )
    assert (
        by_scope(cc.contribution(BY_NAME["Harmonize"], giada), "cast:tribal:angel")[
            "value"
        ]
        is False
    )


def test_vivi_noncreature_contribution_survives_creature_draw_comparison():
    vivi = BY_NAME["Vivi Ornitier"]
    assert "cast:noncreature" in scopes(cc.commander_profile(vivi))
    assert (
        by_scope(cc.contribution(BY_NAME["Divination"], vivi), "cast:noncreature")[
            "value"
        ]
        is True
    )
    assert (
        by_scope(cc.contribution(BY_NAME["Beast Whisperer"], vivi), "cast:noncreature")[
            "value"
        ]
        is False
    )
    power = by_scope(
        cc.contribution(BY_NAME["Divination"], vivi), "power:unparsed_reference"
    )
    assert power["value"] is None and power["confidence"] == "partial"


def test_defender_requires_keyword_line_not_subtype_or_mention():
    arcades = BY_NAME["Arcades, the Strategist"]
    assert {"defender:etb", "defender:combat"} <= set(
        scopes(cc.commander_profile(arcades))
    )
    assert (
        by_scope(cc.contribution(BY_NAME["Wall of Omens"], arcades), "defender:etb")[
            "value"
        ]
        is True
    )
    assert (
        by_scope(
            cc.contribution(BY_NAME["Spirited Companion"], arcades), "defender:etb"
        )["value"]
        is False
    )
    bare_wall = {
        "name": "X",
        "oracle_text": "When this creature enters, draw a card.",
        "type_line": "Creature - Wall",
        "cmc": 2.0,
    }
    assert (
        by_scope(cc.contribution(bare_wall, arcades), "defender:etb")["value"] is False
    )
    mention = {
        "name": "X",
        "type_line": "Creature - Soldier",
        "cmc": 2.0,
        "oracle_text": "This creature can attack as though it didn't have defender.",
    }
    assert by_scope(cc.contribution(mention, arcades), "defender:etb")["value"] is False


def test_name_invariance():
    lathril = BY_NAME["Lathril, Blade of the Elves"]
    renamed = dict(lathril, name="Totally Different Card")
    assert cc.commander_profile(renamed) == cc.commander_profile(lathril)
    elves = BY_NAME["Llanowar Elves"]
    assert cc.contribution(dict(elves, name="Zzz"), renamed) == cc.contribution(
        elves, lathril
    )


def test_unknown_commander_condition_stays_partial():
    unknown = {
        "name": "X",
        "type_line": "Legendary Creature - Avatar",
        "cmc": 5.0,
        "oracle_text": "Sliver spells cost {1} less to cast as long as the moon is full.",
    }
    contract = next(
        c
        for c in cc.commander_profile(unknown)["contracts"]
        if c["scope"] == "tribal:sliver"
    )
    assert contract["confidence"] == "partial"


def test_mana_value_never_fabricates_zero():
    mv_commander = {
        "name": "X",
        "type_line": "Legendary Creature - Human",
        "cmc": 3.0,
        "oracle_text": "Whenever you cast a spell with mana value 3 or less, "
        "draw a card.",
    }
    known = cc.contribution(BY_NAME["Opt"], mv_commander)
    assert by_scope(known, "mana_value:3_or_less")["value"] == 1
    unknown = cc.contribution(
        {"name": "X", "type_line": "Instant", "oracle_text": "Draw a card."},
        mv_commander,
    )
    item = by_scope(unknown, "mana_value:3_or_less")
    assert item["value"] is None and item["confidence"] == "partial"


def test_land_is_not_a_cast_spell():
    land = {
        "name": "X",
        "type_line": "Land",
        "oracle_text": "{T}: Add {G}.",
        "cmc": 0.0,
    }
    result = cc.contribution(land, BY_NAME["Vivi Ornitier"])
    assert result["cast_categories"] == [] and result["creature_types"] == []
    assert by_scope(result, "cast:noncreature")["value"] is False


@pytest.mark.parametrize("value", [float("inf"), float("nan"), -1, True, None])
def test_invalid_mana_is_unknown(value):
    assert cc.printed_mana_value({"cmc": value}) is None


def test_creature_land_is_never_cast():
    assert cc.cast_categories({"type_line": "Land Creature — Forest Dryad"}) == []


def test_defender_reminder_and_case_preserve_exact_evidence():
    card = {
        "type_line": "Creature — Wall",
        "oracle_text": "defender (This creature can't attack.)",
    }
    p = cc.contribution(card, BY_NAME["Arcades, the Strategist"])
    assert by_scope(p, "defender:etb")["value"] is True
    assert by_scope(p, "defender:etb")["evidence"] == ["defender"]


def test_angel_kindred_spell_uses_restricted_mana_but_is_not_angel_body():
    card = {"type_line": "Kindred Instant — Angel", "oracle_text": "Draw a card."}
    p = cc.contribution(card, BY_NAME["Giada, Font of Hope"])
    assert by_scope(p, "cast:tribal:angel")["value"] is True
    assert by_scope(p, "tribal:angel")["value"] is False


def test_extra_cast_gate_does_not_become_verified_unconditional_trigger():
    commander = {
        "type_line": "Creature — Wizard",
        "oracle_text": "Whenever you cast a noncreature spell, if you control an artifact, draw a card.",
    }
    p = cc.contribution(BY_NAME["Divination"], commander)
    assert by_scope(p, "cast:noncreature")["confidence"] == "partial"


def test_arcades_toughness_replacement_is_not_source_power_mana():
    assert not any(
        c["kind"] == "power"
        for c in cc.commander_profile(BY_NAME["Arcades, the Strategist"])["contracts"]
    )


def test_front_face_does_not_acquire_back_face_subtypes():
    assert cc.creature_types(
        {"type_line": "Creature — Human Wizard // Enchantment"}
    ) == ["Human", "Wizard"]
