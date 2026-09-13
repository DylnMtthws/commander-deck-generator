"""Tests for creature_resources.creature_resources.

Oracle strings that are not a well-known vanilla/keyword-only body are
synthetic (or quoted fragments) so this file never invents a real card's
Oracle. Grizzly Bears, Runeclaw Bear, and Wind Drake use the simple printed
bodies those cards actually have.
"""

from __future__ import annotations

import copy
import math

from sabermetrics.intelligence.creature_resources import (
    RESULT_KEYS,
    creature_resources,
)

# --- real simple bodies -------------------------------------------------------

GRIZZLY_BEARS = {
    "name": "Grizzly Bears",
    "mana_cost": "{1}{G}",
    "cmc": 2.0,
    "type_line": "Creature — Bear",
    "oracle_text": "",
    "power": "2",
    "toughness": "2",
}

RUNECLAW_BEAR = {
    "name": "Runeclaw Bear",
    "mana_cost": "{1}{G}",
    "cmc": 2.0,
    "type_line": "Creature — Bear",
    "oracle_text": "",
    "power": "2",
    "toughness": "2",
}

WIND_DRAKE = {
    "name": "Wind Drake",
    "mana_cost": "{2}{U}",
    "cmc": 3.0,
    "type_line": "Creature — Drake",
    "oracle_text": "Flying",
    "power": "2",
    "toughness": "2",
}

# Llanowar-style 1/1 {G} Elf Druid vanilla *stat line*, not Llanowar Elves.
GROVE_SCOUT = {
    "name": "Grove Scout",
    "mana_cost": "{G}",
    "cmc": 1,
    "type_line": "Creature — Elf Druid",
    "oracle_text": "",
    "power": "1",
    "toughness": "1",
}


def _creature(**overrides: object) -> dict:
    card: dict = {
        "name": "Test Bear",
        "mana_cost": "{1}{G}",
        "cmc": 2,
        "type_line": "Creature — Bear",
        "oracle_text": "",
        "power": "2",
        "toughness": "2",
    }
    card.update(overrides)
    return card


def _assert_resource_shape(result: dict) -> None:
    assert tuple(result) == RESULT_KEYS
    assert isinstance(result["power"], int) and not isinstance(result["power"], bool)
    assert isinstance(result["toughness"], int) and not isinstance(
        result["toughness"], bool
    )
    assert isinstance(result["mana_value"], int) and not isinstance(
        result["mana_value"], bool
    )
    assert isinstance(result["mana_cost"], str)
    assert isinstance(result["pips"], dict)
    assert isinstance(result["types"], list)
    assert isinstance(result["supertypes"], list)
    assert isinstance(result["subtypes"], list)
    assert isinstance(result["keywords"], list)
    assert isinstance(result["evidence"], list)
    assert all(isinstance(item, str) for item in result["evidence"])


# --- positive: real and synthetic vanilla / keyword-only ----------------------


def test_grizzly_bears_vanilla_stat_line() -> None:
    result = creature_resources(GRIZZLY_BEARS)
    assert result is not None
    _assert_resource_shape(result)
    assert result["power"] == 2
    assert result["toughness"] == 2
    assert result["mana_value"] == 2
    assert result["mana_cost"] == "{1}{G}"
    assert result["pips"] == {"G": 1}
    assert result["types"] == ["creature"]
    assert result["supertypes"] == []
    assert result["subtypes"] == ["bear"]
    assert result["keywords"] == []
    assert GRIZZLY_BEARS["mana_cost"] in result["evidence"]
    assert GRIZZLY_BEARS["type_line"] in result["evidence"]


def test_runeclaw_bear_same_vanilla_body() -> None:
    result = creature_resources(RUNECLAW_BEAR)
    assert result is not None
    assert result["power"] == 2
    assert result["toughness"] == 2
    assert result["mana_cost"] == "{1}{G}"
    assert result["subtypes"] == ["bear"]
    assert result["keywords"] == []


def test_wind_drake_flying_only() -> None:
    result = creature_resources(WIND_DRAKE)
    assert result is not None
    _assert_resource_shape(result)
    assert result["power"] == 2
    assert result["toughness"] == 2
    assert result["mana_value"] == 3
    assert result["mana_cost"] == "{2}{U}"
    assert result["pips"] == {"U": 1}
    assert result["subtypes"] == ["drake"]
    assert result["keywords"] == ["flying"]
    assert WIND_DRAKE["oracle_text"] in result["evidence"]


def test_llanowar_style_vanilla_stat_line_is_synthetic() -> None:
    result = creature_resources(GROVE_SCOUT)
    assert result is not None
    assert result["power"] == 1
    assert result["toughness"] == 1
    assert result["mana_value"] == 1
    assert result["mana_cost"] == "{G}"
    assert result["pips"] == {"G": 1}
    assert result["subtypes"] == ["elf", "druid"]
    assert result["keywords"] == []
    assert GROVE_SCOUT["name"] != "Llanowar Elves"


def test_int_power_toughness_and_mana_value_field() -> None:
    card = _creature(power=2, toughness=2)
    del card["cmc"]
    card["mana_value"] = 2
    result = creature_resources(card)
    assert result is not None
    assert result["power"] == 2
    assert result["toughness"] == 2
    assert result["mana_value"] == 2


def test_comma_and_newline_separated_supported_keywords() -> None:
    comma = creature_resources(
        _creature(oracle_text="Flying, vigilance", name="Keyword Bear")
    )
    newline = creature_resources(
        _creature(oracle_text="Flying\nFirst strike", name="Strike Bear")
    )
    assert comma is not None and comma["keywords"] == ["flying", "vigilance"]
    assert newline is not None and newline["keywords"] == ["flying", "first strike"]


def test_mapped_flying_reminder_is_consumed() -> None:
    card = _creature(
        oracle_text=(
            "Flying (This creature can't be blocked except by creatures "
            "with flying or reach.)"
        )
    )
    result = creature_resources(card)
    assert result is not None
    assert result["keywords"] == ["flying"]


def test_legendary_snow_creature_type_line() -> None:
    card = _creature(type_line="Legendary Snow Creature — Human Wizard")
    result = creature_resources(card)
    assert result is not None
    assert result["supertypes"] == ["legendary", "snow"]
    assert result["types"] == ["creature"]
    assert result["subtypes"] == ["human", "wizard"]


def test_artifact_creature_is_official_creature_type_line() -> None:
    card = _creature(
        mana_cost="{1}",
        cmc=1,
        type_line="Artifact Creature — Construct",
        oracle_text="",
        power="1",
        toughness="1",
    )
    result = creature_resources(card)
    assert result is not None
    assert result["types"] == ["artifact", "creature"]
    assert result["subtypes"] == ["construct"]


# --- subtypes retained, no equivalence ----------------------------------------


def test_subtype_differences_are_preserved_and_not_equated() -> None:
    elf = _creature(name="Grove Elf", type_line="Creature — Elf")
    human = _creature(name="Town Human", type_line="Creature — Human")
    elf_result = creature_resources(elf)
    human_result = creature_resources(human)
    assert elf_result is not None and human_result is not None
    assert elf_result["subtypes"] == ["elf"]
    assert human_result["subtypes"] == ["human"]
    assert elf_result["subtypes"] != human_result["subtypes"]
    assert elf_result["power"] == human_result["power"]
    assert elf_result["toughness"] == human_result["toughness"]
    assert elf_result["mana_value"] == human_result["mana_value"]


# --- self-name prefix ---------------------------------------------------------


def test_self_name_has_keyword_with_and_without_period() -> None:
    named = _creature(
        name="Wind Drake",
        mana_cost="{2}{U}",
        cmc=3,
        type_line="Creature — Drake",
        oracle_text="Wind Drake has flying.",
        power="2",
        toughness="2",
    )
    no_period = dict(named)
    no_period["oracle_text"] = "Wind Drake has flying"
    for card in (named, no_period):
        result = creature_resources(card)
        assert result is not None
        assert result["keywords"] == ["flying"]


def test_self_name_prefix_is_case_insensitive() -> None:
    card = _creature(
        name="Wind Drake",
        mana_cost="{2}{U}",
        cmc=3,
        type_line="Creature — Drake",
        oracle_text="wind drake has Flying, vigilance.",
        power="2",
        toughness="2",
    )
    result = creature_resources(card)
    assert result is not None
    assert result["keywords"] == ["flying", "vigilance"]


def test_foreign_name_has_keyword_is_not_normalized() -> None:
    card = _creature(
        name="Wind Drake",
        mana_cost="{2}{U}",
        cmc=3,
        type_line="Creature — Drake",
        oracle_text="Some Other Drake has flying.",
        power="2",
        toughness="2",
    )
    assert creature_resources(card) is None


def test_this_creature_has_keyword_is_not_normalized() -> None:
    card = _creature(oracle_text="This creature has flying.")
    assert creature_resources(card) is None


def test_self_name_has_without_keyword_is_rejected() -> None:
    card = _creature(name="Test Bear", oracle_text="Test Bear has")
    assert creature_resources(card) is None


# --- metadata cannot conceal effects ------------------------------------------


def test_keywords_metadata_cannot_conceal_activated_mana() -> None:
    card = _creature(oracle_text="{T}: Add {G}.", keywords=["flying"])
    assert creature_resources(card) is None


def test_keywords_metadata_cannot_salvage_triggered_etb() -> None:
    card = _creature(
        oracle_text="When this creature enters, draw a card.",
        keywords=[],
    )
    assert creature_resources(card) is None


def test_oracle_empty_ignores_lying_keywords_metadata() -> None:
    card = _creature(oracle_text="", keywords=["flying", "trample"])
    result = creature_resources(card)
    assert result is not None
    assert result["keywords"] == []


# --- negative restriction / extra clauses -------------------------------------


def test_rock_jockey_cast_restriction_returns_none() -> None:
    card = _creature(
        name="Rock Jockey",
        mana_cost="{2}{R}",
        cmc=3,
        type_line="Creature — Goblin",
        oracle_text=(
            "You can't cast this spell if you've played a land this turn.\n"
            "You can't play lands this turn."
        ),
        power="3",
        toughness="3",
    )
    assert creature_resources(card) is None


def test_rock_sled_restrictions_return_none() -> None:
    card = _creature(
        name="Rock Sled",
        mana_cost="{3}{R}",
        cmc=4,
        type_line="Creature — Horse",
        oracle_text=(
            "Trample\n"
            "Rock Sled doesn't untap during your untap step if it attacked "
            "during your last turn.\n"
            "Rock Sled can't attack unless defending player controls a Mountain."
        ),
        power="3",
        toughness="4",
    )
    assert creature_resources(card) is None


def test_triggered_etb_body_returns_none() -> None:
    card = _creature(oracle_text="Whenever this creature enters, you draw a card.")
    assert creature_resources(card) is None


def test_flying_plus_cannot_block_clause_is_rejected() -> None:
    card = _creature(oracle_text="Flying. This creature cannot block.")
    assert creature_resources(card) is None


def test_unmapped_parentheses_are_not_stripped() -> None:
    card = _creature(oracle_text="Flying (This creature cannot block.)")
    assert creature_resources(card) is None


def test_protection_ward_changeling_landwalk_rejected() -> None:
    for oracle in (
        "Protection from black",
        "Ward {2}",
        "Changeling",
        "Forestwalk",
        "Islandwalk",
        "Flash",
    ):
        assert creature_resources(_creature(oracle_text=oracle)) is None


def test_activated_and_whenever_bodies_rejected() -> None:
    activated = "{T}: Target creature gets +1/+1 until end of turn."
    triggered = "Whenever this creature attacks, it gets +1/+1 until end of turn."
    assert creature_resources(_creature(oracle_text=activated)) is None
    assert creature_resources(_creature(oracle_text=triggered)) is None


# --- malformed / inconsistent printed stats -----------------------------------


def test_inconsistent_printed_mana_value_rejected() -> None:
    assert creature_resources(_creature(cmc=4)) is None
    assert creature_resources(_creature(cmc=2, mana_cost="{2}{U}")) is None
    assert creature_resources(_creature(cmc=2, mana_value=3)) is None


def test_alternative_hybrid_phyrexian_snow_x_costs_rejected() -> None:
    for cost in ("{X}{G}", "{G/W}", "{G/P}", "{2/G}", "{S}", "{W/U}", ""):
        parsed = 0
        tokens = __import__("re").findall(r"\{([^}]+)\}", cost)
        for token in tokens:
            parsed += int(token) if token.isdigit() else 1
        assert creature_resources(_creature(mana_cost=cost, cmc=parsed or 0)) is None


def test_star_x_expression_and_bool_power_toughness_rejected() -> None:
    for power, toughness in (
        ("*", "2"),
        ("2", "*"),
        ("X", "2"),
        ("1+*", "1"),
        ("2+1", "2"),
        (True, 2),
        (2, False),
        ("2.0", "2"),
        ("-1", "2"),
        ("02", "2"),
    ):
        assert creature_resources(_creature(power=power, toughness=toughness)) is None


def test_bool_and_non_finite_cmc_rejected() -> None:
    assert creature_resources(_creature(cmc=True)) is None
    assert creature_resources(_creature(cmc=math.inf)) is None
    assert creature_resources(_creature(cmc=math.nan)) is None


def test_unknown_or_multiface_type_lines_rejected() -> None:
    for type_line in (
        "Instant",
        "Sorcery",
        "Host Creature — Eldrazi",
        "Creature // Creature — Bear",
        "Foo Creature — Bear",
        "Creature",
        "Creature —",
        "Instant Creature — Wizard",
    ):
        assert creature_resources(_creature(type_line=type_line)) is None


def test_split_name_and_card_faces_rejected() -> None:
    assert creature_resources(_creature(name="Bear // Bear")) is None
    assert creature_resources(_creature(card_faces=[{"oracle_text": ""}])) is None
    assert creature_resources(_creature(layout="transform")) is None


def test_missing_oracle_or_non_dict_input_rejected() -> None:
    card = _creature()
    del card["oracle_text"]
    assert creature_resources(card) is None
    assert creature_resources(None) is None  # type: ignore[arg-type]
    assert creature_resources("Creature — Bear") is None  # type: ignore[arg-type]
    assert creature_resources({}) is None


# --- immutability -------------------------------------------------------------


def test_input_card_is_not_mutated() -> None:
    card = _creature(
        oracle_text="Flying, vigilance",
        keywords=["trample"],
        extra_list=["keep"],
    )
    snapshot = copy.deepcopy(card)
    result = creature_resources(card)
    assert result is not None
    assert card == snapshot
    result["keywords"].append("trample")
    result["subtypes"].append("elf")
    result["pips"]["G"] = 99
    result["evidence"].append("invented")
    assert card == snapshot
    assert snapshot["keywords"] == ["trample"]
    assert snapshot["extra_list"] == ["keep"]
