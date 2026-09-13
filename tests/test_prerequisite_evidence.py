"""Tests for prerequisite_evidence, driven by public-fixtures.json only."""

import json

import pytest

from sabermetrics.intelligence.prerequisite_evidence import (
    card_colors,
    evaluate_prerequisites,
)

FIXTURES = [
    {
        "name": "Dragon's Herald",
        "oracle_text": "{2}{R}, {T}, Sacrifice a black creature, a red creature, and a green creature: Search your library for a card named Hellkite Overlord, put it onto the battlefield, then shuffle.",
        "type_line": "Creature — Goblin Shaman",
        "mana_cost": "{R}",
        "cmc": 1.0,
        "color_identity": '["R"]',
    },
    {
        "name": "Courier of Comestibles",
        "oracle_text": "When this creature enters, you may search your library for a Food card, reveal it, put it into your hand, then shuffle. If you don't put a card into your hand this way, create a Food token. (It's an artifact with \"{2}, {T}, Sacrifice this token: You gain 3 life.\")",
        "type_line": "Creature — Human Citizen",
        "mana_cost": "{1}{G}",
        "cmc": 2.0,
        "color_identity": '["G"]',
    },
    {
        "name": "Hellkite Overlord",
        "oracle_text": "Flying, trample, haste\n{R}: This creature gets +1/+0 until end of turn.\n{B}{G}: Regenerate this creature.",
        "type_line": "Creature — Dragon",
        "mana_cost": "{4}{B}{R}{R}{G}",
        "cmc": 8.0,
        "color_identity": '["B", "G", "R"]',
    },
    {
        "name": "Dizzy Spell",
        "oracle_text": "Target creature gets -3/-0 until end of turn.\nTransmute {1}{U}{U} ({1}{U}{U}, Discard this card: Search your library for a card with the same mana value as this card, reveal it, put it into your hand, then shuffle. Transmute only as a sorcery.)",
        "type_line": "Instant",
        "mana_cost": "{U}",
        "cmc": 1.0,
        "color_identity": '["U"]',
    },
    {
        "name": "Gitaxian Probe",
        "oracle_text": "({U/P} can be paid with either {U} or 2 life.)\nLook at target player's hand.\nDraw a card.",
        "type_line": "Sorcery",
        "mana_cost": "{U/P}",
        "cmc": 1.0,
        "color_identity": '["U"]',
    },
    {
        "name": "Ophidian Eye",
        "oracle_text": "Flash (You may cast this spell any time you could cast an instant.)\nEnchant creature\nWhenever enchanted creature deals damage to an opponent, you may draw a card.",
        "type_line": "Enchantment — Aura",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "color_identity": '["U"]',
    },
    {
        "name": "Springleaf Drum",
        "oracle_text": "{T}, Tap an untapped creature you control: Add one mana of any color.",
        "type_line": "Artifact",
        "mana_cost": "{1}",
        "cmc": 1.0,
        "color_identity": "[]",
    },
    {
        "name": "Painter's Servant",
        "oracle_text": "As this creature enters, choose a color.\nAll cards that aren't on the battlefield, spells, and permanents are the chosen color in addition to their other colors.",
        "type_line": "Artifact Creature — Scarecrow",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "color_identity": "[]",
    },
    {
        "name": "Young Pyromancer",
        "oracle_text": "Whenever you cast an instant or sorcery spell, create a 1/1 red Elemental creature token.",
        "type_line": "Creature — Human Shaman",
        "mana_cost": "{1}{R}",
        "cmc": 2.0,
        "color_identity": '["R"]',
    },
    {
        "name": "Llanowar Elves",
        "oracle_text": "{T}: Add {G}.",
        "type_line": "Creature — Elf Druid",
        "mana_cost": "{G}",
        "cmc": 1.0,
        "color_identity": '["G"]',
    },
    {
        "name": "Sol Ring",
        "oracle_text": "{T}: Add {C}{C}.",
        "type_line": "Artifact",
        "mana_cost": "{1}",
        "cmc": 1.0,
        "color_identity": "[]",
    },
]
BY_NAME = {c["name"]: c for c in FIXTURES}
STATUSES = {"supported", "unsupported", "unknown"}


def abilities_of(result, kind):
    return [a for a in result["abilities"] if a["kind"] == kind]


@pytest.mark.parametrize("card", FIXTURES, ids=[c["name"] for c in FIXTURES])
def test_fixture_invariants(card):
    result = evaluate_prerequisites(card, FIXTURES)
    assert result["coverage"] == "incomplete"
    assert result["cut_authorized"] is False
    paragraphs = card["oracle_text"].split("\n")
    for text in result["fallback_text"] + result["remaining_text"]:
        assert text in paragraphs
    assert not set(result["fallback_text"]) & set(result["remaining_text"])
    for ability in result["abilities"]:
        assert ability["status"] in STATUSES
        assert isinstance(ability["requirements"], dict) and ability["reason"]
        for evidence in ability["evidence"]:
            assert evidence in card["oracle_text"]


def test_all_eleven_fixtures_present():
    assert len(FIXTURES) == 11


def test_dragons_herald_named_search_supported_by_deck_presence():
    result = evaluate_prerequisites(
        BY_NAME["Dragon's Herald"], FIXTURES, catalog_complete=True
    )
    named = abilities_of(result, "named_search")[0]
    assert named["status"] == "supported"
    assert named["requirements"]["searched_card_name"] == "Hellkite Overlord"
    assert named["supporting_cards"] == ["Hellkite Overlord"]
    assert "battlefield" in named["reason"]
    assert "then shuffle" not in "".join(named["evidence"])


def test_dragons_herald_sacrifice_is_unknown_with_observed_matches():
    deck = [
        BY_NAME[n] for n in ("Llanowar Elves", "Young Pyromancer", "Hellkite Overlord")
    ]
    sac = abilities_of(
        evaluate_prerequisites(BY_NAME["Dragon's Herald"], deck, catalog_complete=True),
        "sacrifice_colored_creatures",
    )[0]
    assert sac["status"] == "unknown"
    assert sac["requirements"]["sacrifice_colored_creatures"] == {
        "black": 1,
        "red": 1,
        "green": 1,
    }
    assert sac["requirements"]["distinct_creatures_required"] == 3
    assert sac["requirements"]["observed_matches"]["black"] == ["Hellkite Overlord"]
    assert sac["requirements"]["distinct_assignment_found"] is True


def test_one_multicolor_creature_cannot_pay_three_sacrifices():
    sac = abilities_of(
        evaluate_prerequisites(
            BY_NAME["Dragon's Herald"],
            [BY_NAME["Hellkite Overlord"]],
            catalog_complete=True,
        ),
        "sacrifice_colored_creatures",
    )[0]
    assert sac["requirements"]["distinct_assignment_found"] is False
    assert sac["status"] == "unknown"


def test_token_and_color_changing_sources_yield_explicit_caveat():
    deck = [BY_NAME["Young Pyromancer"], BY_NAME["Painter's Servant"]]
    sac = abilities_of(
        evaluate_prerequisites(BY_NAME["Dragon's Herald"], deck, catalog_complete=True),
        "sacrifice_colored_creatures",
    )[0]
    assert sac["requirements"]["token_sources"] == ["Young Pyromancer"]
    assert sac["requirements"]["color_changing_sources"] == ["Painter's Servant"]
    assert "caveat" in sac["reason"].lower() and sac["status"] == "unknown"


def test_color_identity_is_not_used_for_colored_costs():
    fake = {
        "name": "Dull Golem",
        "mana_cost": "{2}",
        "type_line": "Artifact Creature — Golem",
        "oracle_text": "",
        "cmc": 2.0,
        "color_identity": '["B"]',
    }
    assert card_colors(fake) == []
    assert card_colors({"name": "x", "colors": ["B"], "mana_cost": "{2}"}) == ["B"]
    sac = abilities_of(
        evaluate_prerequisites(
            BY_NAME["Dragon's Herald"], [fake], catalog_complete=True
        ),
        "sacrifice_colored_creatures",
    )[0]
    assert sac["requirements"]["observed_matches"]["black"] == []


def test_named_search_unknown_unless_decklist_declared_complete():
    deck = [BY_NAME["Sol Ring"]]
    open_named = abilities_of(
        evaluate_prerequisites(BY_NAME["Dragon's Herald"], deck), "named_search"
    )[0]
    assert open_named["status"] == "unknown"
    closed = abilities_of(
        evaluate_prerequisites(BY_NAME["Dragon's Herald"], deck, catalog_complete=True),
        "named_search",
    )[0]
    assert closed["status"] == "unsupported"
    assert "useless" in closed["reason"]


def test_courier_typed_search_and_untouched_food_fallback():
    card = BY_NAME["Courier of Comestibles"]
    result = evaluate_prerequisites(card, [BY_NAME["Sol Ring"]], catalog_complete=True)
    typed = abilities_of(result, "typed_search")[0]
    assert typed["status"] == "unsupported"
    assert typed["requirements"]["searched_card_type"] == "Food"
    assert result["fallback_text"] == [card["oracle_text"]]
    assert "create a Food token" in result["fallback_text"][0]
    assert result["cut_authorized"] is False


def test_quoted_token_reminder_text_is_not_a_named_search_or_sacrifice():
    result = evaluate_prerequisites(BY_NAME["Courier of Comestibles"], FIXTURES)
    assert abilities_of(result, "named_search") == []
    assert abilities_of(result, "sacrifice_colored_creatures") == []
    synthetic = {
        "name": "Token Maker",
        "cmc": 2.0,
        "mana_cost": "{2}",
        "type_line": "Artifact",
        "oracle_text": 'Create a Treasure token. ("{T}, Sacrifice this token: '
        'Add one mana of any color.")',
    }
    out = evaluate_prerequisites(synthetic, FIXTURES, catalog_complete=True)
    assert out["abilities"] == []
    assert out["remaining_text"] == [synthetic["oracle_text"]]


def test_transmute_uses_printed_source_mana_value():
    dizzy = BY_NAME["Dizzy Spell"]
    valid = abilities_of(
        evaluate_prerequisites(
            dizzy, [BY_NAME["Gitaxian Probe"]], catalog_complete=True
        ),
        "same_mana_value_search",
    )[0]
    assert valid["status"] == "supported"
    assert valid["requirements"]["same_mana_value_as_source"] == 1.0
    assert valid["supporting_cards"] == ["Gitaxian Probe"]
    assert "Transmute {1}{U}{U}" in valid["evidence"]
    invalid = abilities_of(
        evaluate_prerequisites(dizzy, [BY_NAME["Ophidian Eye"]], catalog_complete=True),
        "same_mana_value_search",
    )[0]
    assert invalid["status"] == "unsupported"
    assert invalid["supporting_cards"] == []


def test_incomplete_type_color_and_mana_value_are_distinguished():
    no_type = [{"name": "Mystery", "cmc": 1.0, "mana_cost": "{1}"}]
    typed = abilities_of(
        evaluate_prerequisites(
            BY_NAME["Courier of Comestibles"], no_type, catalog_complete=True
        ),
        "typed_search",
    )[0]
    assert typed["status"] == "unknown" and typed["requirements"][
        "incomplete_data"
    ] == ["Mystery"]
    no_cmc = [{"name": "Mystery", "type_line": "Instant", "mana_cost": "{1}"}]
    mv = abilities_of(
        evaluate_prerequisites(BY_NAME["Dizzy Spell"], no_cmc, catalog_complete=True),
        "same_mana_value_search",
    )[0]
    assert mv["status"] == "unknown" and mv["requirements"]["incomplete_data"] == [
        "Mystery"
    ]
    no_cost = [{"name": "Mystery", "type_line": "Creature — Golem", "oracle_text": ""}]
    sac = abilities_of(
        evaluate_prerequisites(
            BY_NAME["Dragon's Herald"], no_cost, catalog_complete=True
        ),
        "sacrifice_colored_creatures",
    )[0]
    assert sac["requirements"]["colorless_or_unknown_color_entries"] == ["Mystery"]


def test_nonfunctional_named_search_keeps_useful_fallback_and_never_authorizes_cut():
    synthetic = {
        "name": "Hopeful Seeker",
        "cmc": 2.0,
        "mana_cost": "{1}{G}",
        "type_line": "Creature — Elf Scout",
        "oracle_text": "When this creature enters, search your library for a card named "
        "Nonexistent Behemoth, put it into your hand, then shuffle.\n"
        "{T}: Add {G}.",
    }
    result = evaluate_prerequisites(synthetic, FIXTURES, catalog_complete=True)
    named = abilities_of(result, "named_search")[0]
    assert named["status"] == "unsupported"
    assert result["remaining_text"] == ["{T}: Add {G}."]
    assert result["cut_authorized"] is False and result["coverage"] == "incomplete"


def test_missing_oracle_text_is_unknown_not_unsupported():
    result = evaluate_prerequisites({"name": "Blank"}, FIXTURES, catalog_complete=True)
    assert [a["status"] for a in result["abilities"]] == ["unknown"]
    assert result["abilities"][0]["kind"] == "incomplete_data"


def test_unnamed_deck_entry_prevents_absence_claim():
    result = evaluate_prerequisites(
        BY_NAME["Dragon's Herald"], [{}], catalog_complete=True
    )
    assert abilities_of(result, "named_search")[0]["status"] == "unknown"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -1])
def test_invalid_printed_mana_value_stays_unknown(value):
    source = dict(BY_NAME["Dizzy Spell"], cmc=value)
    result = evaluate_prerequisites(source, FIXTURES, catalog_complete=True)
    assert abilities_of(result, "same_mana_value_search")[0]["status"] == "unknown"
    json.dumps(result, allow_nan=False)


def test_devoid_or_missing_color_information_is_not_colored_from_identity():
    assert card_colors({"mana_cost": "{2}{B}", "oracle_text": "Devoid"}) is None
    assert card_colors({"colors": None, "color_identity": ["B"]}) is None
    assert card_colors({"mana_cost": "", "color_identity": ["B"]}) is None


def test_generic_and_colored_sacrifices_need_distinct_objects():
    card = {"oracle_text": "Sacrifice a black creature and a creature: Draw two cards."}
    creature = {"name": "Only body", "type_line": "Creature — Human", "colors": ["B"]}
    result = evaluate_prerequisites(card, [creature], catalog_complete=True)
    ability = abilities_of(result, "sacrifice_colored_creatures")[0]
    assert ability["requirements"]["distinct_assignment_found"] is False
    assert ability["status"] == "unknown"


def test_multicolor_single_cost_shape_is_not_misread_as_one_color():
    card = {"oracle_text": "Sacrifice a black and red creature: Draw two cards."}
    result = evaluate_prerequisites(card, [], catalog_complete=True)
    assert (
        "unparsed_cost"
        in abilities_of(result, "sacrifice_colored_creatures")[0]["requirements"]
    )


DEVOID_FIXTURE = {
    "name": "Catacomb Sifter",
    "oracle_text": 'Devoid (This card has no color.)\nWhen this creature enters, create a 1/1 colorless Eldrazi Scion creature token. It has "Sacrifice this token: Add {C}."\nWhenever another creature you control dies, scry 1. (Look at the top card of your library. You may put that card on the bottom.)',
    "mana_cost": "{1}{B}{G}",
    "type_line": "Creature — Eldrazi Drone",
    "cmc": 3.0,
}


def test_actual_devoid_card_does_not_inherit_mana_cost_colors():
    assert "Devoid" in DEVOID_FIXTURE["oracle_text"]
    assert card_colors(DEVOID_FIXTURE) is None
    assert card_colors(dict(DEVOID_FIXTURE, colors=[])) == []


def test_back_face_food_does_not_prove_front_face_library_target():
    result = evaluate_prerequisites(
        BY_NAME["Courier of Comestibles"],
        [{"name": "Front // Back", "type_line": "Creature — Human // Artifact — Food"}],
        catalog_complete=True,
    )
    assert abilities_of(result, "typed_search")[0]["status"] == "unknown"
