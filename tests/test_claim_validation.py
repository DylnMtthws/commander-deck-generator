"""Falsifiable-claim checks over synthetic model prose.

Card records carry only the printed clauses under test, abridged from public
Oracle text. The thresholded commander is a synthetic fixture rather than a
named real card: the rule under test is the printed template "whenever you cast
... with mana value N or greater", and a misremembered threshold on a real card
must not silently become the specification. No model is called here.
"""

from __future__ import annotations

from sabermetrics.intelligence.review import (
    MSG_ADD_ONE,
    MSG_CARD_TYPE,
    MSG_CAST_THRESHOLD,
    MSG_CAST_TRIGGER,
    MSG_DOUBLING,
    MSG_MANA_COST,
    MSG_MANA_VALUE,
    contradictions,
)

DISMEMBER = {
    "name": "Dismember",
    "type_line": "Instant",
    "mana_cost": "{1}{B/P}{B/P}",
    "cmc": 3.0,
    "oracle_text": "Target creature gets -5/-5 until end of turn.",
}

VEGETATION = {
    "name": "Explosive Vegetation",
    "type_line": "Sorcery",
    "mana_cost": "{3}{G}",
    "cmc": 4.0,
    "oracle_text": (
        "Search your library for up to two basic land cards, put them onto "
        "the battlefield tapped, then shuffle."
    ),
}

# Hardened Scales template: one more counter, which is not doubling.
KAMI = {
    "name": "Kami of Whispered Hopes",
    "type_line": "Creature — Spirit",
    "mana_cost": "{1}{G}",
    "cmc": 2.0,
    "oracle_text": (
        "If one or more +1/+1 counters would be put on a creature you control, "
        "that many plus one +1/+1 counters are put on it instead."
    ),
}

# Corpsejack template: actual doubling, which is not "one more".
DOUBLER = {
    "name": "Corpsejack Menace",
    "type_line": "Creature — Fungus Beast",
    "mana_cost": "{3}{B}{G}",
    "cmc": 5.0,
    "oracle_text": (
        "If one or more +1/+1 counters would be put on a creature you control, "
        "twice that many +1/+1 counters are put on it instead."
    ),
}

KATHARI_BOMBER = {
    "name": "Kathari Bomber",
    "type_line": "Creature — Bird Shaman",
    "mana_cost": "{3}{B}{R}",
    "cmc": 5.0,
    "oracle_text": (
        "Whenever this creature deals combat damage to a player, create a 1/1 "
        "red Goblin creature token.\nUnearth {1}{B}{R}"
    ),
}

THRESHOLD_COMMANDER = {
    "name": "Ysh, Threshold Fixture",
    "type_line": "Legendary Creature — Human Cleric",
    "mana_cost": "{2}{W}{B}",
    "cmc": 4.0,
    "oracle_text": (
        "Whenever you cast a noncreature spell with mana value 3 or greater, "
        "draw a card."
    ),
}

PLAIN_COMMANDER = {
    "name": "Bob, Spell Watcher",
    "type_line": "Legendary Creature — Human Wizard",
    "cmc": 3.0,
    "oracle_text": "Whenever you cast a noncreature spell, create a Treasure token.",
}

NO_TRIGGER_COMMANDER = {
    "name": "Quiet, the Vanilla",
    "type_line": "Legendary Creature — Human Soldier",
    "cmc": 3.0,
    "oracle_text": "Vigilance",
}


def spell(name, mv, types="Instant"):
    return {"name": name, "type_line": types, "cmc": mv, "oracle_text": "Draw a card."}


# --- printed mana value versus what you actually pay ------------------------


def test_dismember_mana_value_claim_is_falsified():
    errors = contradictions(
        DISMEMBER, "Dismember has mana value 1, so it fits the low curve.", {}
    )
    assert errors == [MSG_MANA_VALUE]


def test_dismember_payment_claim_is_not_a_mana_value_claim():
    """Three mana value, castable for one generic plus four life."""
    assert (
        contradictions(
            DISMEMBER,
            "Dismember has mana value 3 but you can pay four life to cast it "
            "for {1} on turn one.",
            {},
        )
        == []
    )


def test_phyrexian_payment_exempts_cost_phrasing():
    assert contradictions(DISMEMBER, "Dismember is a one-mana instant.", {}) == []


def test_possessive_mana_value_claim_is_checked():
    assert contradictions(DISMEMBER, "Its mana value is 1.", {}) == [MSG_MANA_VALUE]


def test_correct_mana_value_claim_passes():
    assert contradictions(DISMEMBER, "Its mana value is 3.", {}) == []


def test_cost_phrasing_without_alternative_payment_is_still_checked():
    assert contradictions(VEGETATION, "This is a two-mana sorcery.", {}) == [
        MSG_MANA_COST
    ]


def test_missing_printed_mana_value_is_unknown_not_zero():
    unknown = {"name": "Unpriced Card", "type_line": "Instant"}
    assert contradictions(unknown, "It has mana value 1.", {}) == []


def test_multi_face_mana_value_claims_are_left_unknown():
    modal = {
        "name": "Brazen Borrower // Petty Theft",
        "type_line": "Creature — Faerie Rogue // Instant — Adventure",
        "cmc": 3.0,
        "oracle_text": "Flash\nFlying",
    }
    assert contradictions(modal, "It has mana value 1.", {}) == []


def test_threshold_prose_is_not_a_mana_value_claim():
    assert (
        contradictions(
            spell("Cheap Trick", 1.0),
            "It has mana value 3 or greater only in a different shell; run "
            "cards with mana value 3 or less alongside it.",
            {},
        )
        == []
    )


# --- commander cast triggers with a printed threshold -----------------------


def test_below_threshold_negative_claim_is_valid():
    assert (
        contradictions(
            spell("Two Drop", 2.0),
            "It does not trigger Ysh, so it is a filler pick.",
            THRESHOLD_COMMANDER,
        )
        == []
    )


def test_at_threshold_negative_claim_is_falsified():
    assert contradictions(
        spell("Three Drop", 3.0),
        "It does not trigger Ysh, so skip it.",
        THRESHOLD_COMMANDER,
    ) == [MSG_CAST_THRESHOLD]


def test_below_threshold_affirmative_claim_is_falsified():
    assert contradictions(
        spell("Two Drop", 2.0),
        "It triggers Ysh every time you cast it.",
        THRESHOLD_COMMANDER,
    ) == [MSG_CAST_THRESHOLD]


def test_creature_spell_negative_claim_is_valid_under_a_noncreature_trigger():
    assert (
        contradictions(
            spell("Big Body", 5.0, types="Creature — Bear"),
            "This creature does not trigger Ysh.",
            THRESHOLD_COMMANDER,
        )
        == []
    )


def test_unthresholded_trigger_keeps_the_original_message():
    assert contradictions(
        spell("Three Drop", 3.0),
        "It does not trigger Bob.",
        PLAIN_COMMANDER,
    ) == [MSG_CAST_TRIGGER]


def test_commander_without_a_cast_trigger_is_not_audited():
    assert (
        contradictions(
            spell("Three Drop", 3.0),
            "It does not trigger Quiet.",
            NO_TRIGGER_COMMANDER,
        )
        == []
    )


def test_land_is_left_unknown_rather_than_called_a_trigger():
    land = {"name": "Quiet Field", "type_line": "Land", "cmc": 0.0, "oracle_text": ""}
    assert (
        contradictions(land, "It does not trigger Ysh.", THRESHOLD_COMMANDER) == []
    )


# --- add one versus doubling ------------------------------------------------


def test_add_one_effect_described_as_doubling_is_falsified():
    assert contradictions(
        KAMI, "Kami of Whispered Hopes doubles your +1/+1 counters.", {}
    ) == [MSG_DOUBLING]


def test_add_one_effect_described_accurately_passes():
    assert (
        contradictions(
            KAMI, "Kami of Whispered Hopes adds one extra +1/+1 counter.", {}
        )
        == []
    )


def test_doubling_effect_described_as_add_one_is_falsified():
    assert contradictions(DOUBLER, "It adds one additional counter each time.", {}) == [
        MSG_ADD_ONE
    ]


def test_doubling_effect_described_accurately_passes():
    assert contradictions(DOUBLER, "It doubles your +1/+1 counters.", {}) == []


def test_doubles_as_idiom_is_not_a_magnitude_claim():
    assert contradictions(KAMI, "It doubles as a mana sink late.", {}) == []


# --- printed types versus types named in rules text -------------------------


def test_token_type_in_rules_text_is_not_the_card_type():
    assert contradictions(
        KATHARI_BOMBER, "Kathari Bomber is a Goblin, so it fits the tribe.", {}
    ) == [MSG_CARD_TYPE]


def test_printed_subtype_claim_passes():
    assert (
        contradictions(
            KATHARI_BOMBER, "It is a Bird Shaman that makes a Goblin token.", {}
        )
        == []
    )


def test_token_creation_prose_is_not_a_type_claim():
    assert (
        contradictions(KATHARI_BOMBER, "It creates a 1/1 red Goblin token.", {}) == []
    )


def test_deck_theme_prose_is_not_a_type_claim():
    assert (
        contradictions(KATHARI_BOMBER, "It is a fine card in a Goblin deck.", {}) == []
    )


def test_unlisted_subtype_vocabulary_is_left_unknown():
    """An unchecked subtype word is an unknown, not a verified claim."""
    assert (
        contradictions(KATHARI_BOMBER, "It is a Kavu with evasion.", {}) == []
    )


def test_missing_type_line_is_not_a_type_contradiction():
    untyped = {"name": "Unlabeled", "cmc": 2.0, "oracle_text": ""}
    assert contradictions(untyped, "It is a Goblin.", {}) == []


# --- contract ---------------------------------------------------------------


def test_empty_reasoning_and_bad_records_return_no_claims():
    assert contradictions(DISMEMBER, "", {}) == []
    assert contradictions(DISMEMBER, None, {}) == []
    assert contradictions(None, "It has mana value 1.", None) == []


def test_repeated_claims_are_reported_once():
    errors = contradictions(
        DISMEMBER,
        "Dismember has mana value 1. Dismember has mana value 1.",
        {},
    )
    assert errors == [MSG_MANA_VALUE]
