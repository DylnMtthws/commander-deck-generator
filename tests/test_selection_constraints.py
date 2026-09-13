"""Deterministic deck-constraint audits over synthetic lists.

Card records below carry only the printed clauses under test, abridged from
public Oracle text. No production records, no model calls and no paid builds.
Where a printed shape matters more than a specific card, the fixture says so in
its name so a wrong recollection of one real card cannot silently define the
rule being tested.
"""

from __future__ import annotations

import json

from sabermetrics.intelligence.constraints import (
    CODE_NAMED_SEARCH_NO_TARGET,
    CODE_NAMED_SEARCH_TYPES_UNKNOWN,
    CODE_PACT_DUPLICATE_NAMES,
    CODE_SACRIFICE_COLOR_UNPROVEN,
    CODE_SACRIFICE_COLOR_UNSATISFIED,
    CODE_TRANSMUTE_NO_TARGET,
    SEVERITIES,
    STATUS_NONE,
    STATUS_RESOLVED,
    STATUS_UNKNOWN,
    audit_deck,
    tutor_targets,
)


def card(name, *, text="", types="Creature", mv=2.0, cost=None, colors=None):
    record = {
        "id": name,
        "name": name,
        "oracle_text": text,
        "type_line": types,
        "cmc": mv,
    }
    if cost is not None:
        record["mana_cost"] = cost
    if colors is not None:
        record["colors"] = colors
    return record


def basics(name, count, letter="C"):
    return [
        {
            "id": f"{name}-{i}",
            "name": name,
            "oracle_text": f"({{T}}: Add {{{letter}}}.)",
            "type_line": f"Basic Land — {name}",
            "cmc": 0.0,
        }
        for i in range(count)
    ]


TAINTED_PACT = card(
    "Tainted Pact",
    text=(
        "Exile the top card of your library. You may put that card into your "
        "hand. Repeat this process until you put a card into your hand or you "
        "exile two cards with the same name."
    ),
    types="Instant",
    mv=2.0,
    cost="{1}{B}",
)
THASSAS_ORACLE = card(
    "Thassa's Oracle",
    text=(
        "When this creature enters, look at the top X cards of your library, "
        "where X is your devotion to blue. Put one of them on top of your "
        "library and the rest on the bottom in a random order. If X is greater "
        "than or equal to the number of cards in your library, you win the game."
    ),
    types="Creature — Merfolk Wizard",
    mv=2.0,
    cost="{U}{U}",
)
LAB_MANIAC = card(
    "Laboratory Maniac",
    text=(
        "If you would draw a card while your library has no cards in it, you "
        "win the game instead."
    ),
    types="Creature — Human Wizard",
    mv=3.0,
    cost="{2}{U}",
)

DRAGONS_HERALD = card(
    "Synthetic Dragon Tutor",
    text=(
        "{T}, Sacrifice a green creature: Search your library for a Dragon "
        "card, reveal it, put it into your hand, then shuffle."
    ),
    types="Creature — Human Shaman",
    mv=3.0,
    cost="{2}{R}",
    colors=["R"],
)
HELLKITE_OVERLORD = card(
    "Hellkite Overlord",
    text="Flying, trample, haste\n{R}: This creature gets +1/+0 until end of turn.",
    types="Creature — Dragon",
    mv=8.0,
    colors=["B", "R", "G"],
)

DIZZY_SPELL = {
    "name": "Dizzy Spell",
    "oracle_text": "Target creature gets -3/-0 until end of turn.\nTransmute {1}{U}{U}{U} ({1}{U}{U}{U}, Discard this card: Search your library for a card with the same mana value as this card, reveal it, put it into your hand, then shuffle. Transmute only as a sorcery.)",
    "type_line": "Instant",
    "cmc": 1.0,
    "mana_cost": "{U}",
    "color_identity": '["U"]',
}

CURIOSITY = card(
    "Curiosity",
    text=(
        "Enchant creature\nWhenever enchanted creature deals damage to a "
        "player, you may draw a card."
    ),
    types="Enchantment — Aura",
    mv=1.0,
    cost="{U}",
)
OPHIDIAN_EYE = card("Ophidian Eye", types="Enchantment — Aura", mv=3.0, cost="{2}{U}")
GITAXIAN_PROBE = card("Gitaxian Probe", types="Sorcery", mv=1.0, cost="{U/P}")
MOX_AMBER = card("Mox Amber", types="Legendary Artifact", mv=0.0, cost="{0}")

COMMANDER = card("Azula, Fire Lord", types="Legendary Creature — Human Noble", mv=4.0)
DRAGON_COMMANDER = card(
    "The Ur-Dragon", types="Legendary Creature — Dragon Avatar", mv=9.0
)


def codes(findings):
    return [f["code"] for f in findings]


# --- repeated names and the declared library-emptying line -----------------


def test_repeated_basics_alone_are_not_a_pact_finding():
    """Duplicate basics are legal; without a payoff there is no declared line."""
    deck = [TAINTED_PACT, *basics("Swamp", 6), *basics("Island", 2)]
    assert CODE_PACT_DUPLICATE_NAMES not in codes(audit_deck(deck, COMMANDER))


def test_repeated_basics_break_the_declared_pact_line():
    deck = [
        TAINTED_PACT,
        THASSAS_ORACLE,
        *basics("Swamp", 6),
        *basics("Island", 2),
        *basics("Mountain", 2),
    ]
    findings = [
        f for f in audit_deck(deck, COMMANDER) if f["code"] == CODE_PACT_DUPLICATE_NAMES
    ]
    assert len(findings) == 1
    finding = findings[0]
    assert finding["severity"] == "warning"
    assert finding["card"] == "Tainted Pact"
    assert "Swamp x6" in finding["message"]
    assert "Island x2" in finding["message"]
    assert "Thassa's Oracle" in finding["message"]
    # Legal duplicates must not be reported as a legality problem.
    assert "legal in Commander" in finding["message"]


def test_library_empty_payoff_is_recognized_by_printed_shape():
    """Laboratory Maniac's printed win clause declares the same line."""
    deck = [TAINTED_PACT, LAB_MANIAC, *basics("Island", 3)]
    assert CODE_PACT_DUPLICATE_NAMES in codes(audit_deck(deck, COMMANDER))


def test_pact_line_with_unique_names_is_clean():
    deck = [
        TAINTED_PACT,
        THASSAS_ORACLE,
        *basics("Swamp", 1),
        *basics("Island", 1),
        CURIOSITY,
    ]
    assert CODE_PACT_DUPLICATE_NAMES not in codes(audit_deck(deck, COMMANDER))


def test_payoff_without_a_pact_effect_is_not_audited():
    deck = [THASSAS_ORACLE, *basics("Island", 9)]
    assert codes(audit_deck(deck, COMMANDER)) == []


# --- named searches need a real target -------------------------------------


def test_named_search_without_a_target_is_a_warning_not_a_ban():
    deck = [DRAGONS_HERALD, CURIOSITY, *basics("Mountain", 4)]
    findings = [
        f
        for f in audit_deck(deck, COMMANDER)
        if f["code"] == CODE_NAMED_SEARCH_NO_TARGET
    ]
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert findings[0]["card"] == "Synthetic Dragon Tutor"
    assert "Dragon" in findings[0]["message"]
    assert "stays legal" in findings[0]["message"]


def test_named_search_with_a_real_target_is_clean():
    deck = [DRAGONS_HERALD, HELLKITE_OVERLORD, *basics("Mountain", 4)]
    assert CODE_NAMED_SEARCH_NO_TARGET not in codes(audit_deck(deck, COMMANDER))


def test_commander_type_is_not_a_library_search_target():
    deck = [DRAGONS_HERALD, CURIOSITY]
    finding = next(
        f
        for f in audit_deck(deck, DRAGON_COMMANDER)
        if f["code"] == CODE_NAMED_SEARCH_NO_TARGET
    )
    assert "command zone" in finding["message"]


def test_missing_type_lines_are_unknown_not_a_missing_target():
    deck = [DRAGONS_HERALD, {"id": "x", "name": "Unlabeled", "cmc": 2.0}]
    finding = next(
        f
        for f in audit_deck(deck, COMMANDER)
        if f["code"] in (CODE_NAMED_SEARCH_NO_TARGET, CODE_NAMED_SEARCH_TYPES_UNKNOWN)
    )
    assert finding["code"] == CODE_NAMED_SEARCH_TYPES_UNKNOWN
    assert finding["severity"] == "unknown"


# --- colored sacrifice prerequisites ---------------------------------------


def test_colored_sacrifice_cost_is_unknown_when_colors_are_not_printed():
    """Deck color identity is never proof that a creature is green."""
    unproven = {
        "id": "Unproven Creature",
        "name": "Unproven Creature",
        "type_line": "Creature — Elf Druid",
        "cmc": 2.0,
    }
    deck = [DRAGONS_HERALD, unproven]
    finding = next(
        f
        for f in audit_deck(deck, COMMANDER)
        if f["code"] == CODE_SACRIFICE_COLOR_UNPROVEN
    )
    assert finding["severity"] == "unknown"
    assert "color identity is not proof" in finding["message"].lower()


def test_colored_sacrifice_cost_satisfied_by_printed_colors():
    green = card("Proven Druid", types="Creature — Elf Druid", mv=2.0, colors=["G"])
    deck = [DRAGONS_HERALD, green]
    assert CODE_SACRIFICE_COLOR_UNPROVEN not in codes(audit_deck(deck, COMMANDER))
    assert CODE_SACRIFICE_COLOR_UNSATISFIED not in codes(audit_deck(deck, COMMANDER))


def test_colored_sacrifice_cost_unsatisfied_when_every_color_is_known():
    red = card("Goblin Piker", types="Creature — Goblin Warrior", mv=2.0, colors=["R"])
    artifact = card(
        "Colorless Golem", types="Artifact Creature — Golem", mv=4.0, colors=[]
    )
    deck = [DRAGONS_HERALD, red, artifact]
    finding = next(
        f
        for f in audit_deck(deck, COMMANDER)
        if f["code"] == CODE_SACRIFICE_COLOR_UNSATISFIED
    )
    assert finding["severity"] == "warning"
    assert "still legal" in finding["message"]


def test_mana_cost_proves_color_when_colors_field_is_absent():
    green = {
        "id": "Cost Druid",
        "name": "Cost Druid",
        "type_line": "Creature — Elf Druid",
        "mana_cost": "{1}{G}",
        "cmc": 2.0,
    }
    deck = [DRAGONS_HERALD, green]
    assert CODE_SACRIFICE_COLOR_UNPROVEN not in codes(audit_deck(deck, COMMANDER))


# --- transmute --------------------------------------------------------------


def test_transmute_uses_printed_mana_value_not_the_activation_cost():
    """Dizzy Spell is mana value 1; {1}{U}{U} is what you pay, not what you find."""
    deck = [DIZZY_SPELL, CURIOSITY, OPHIDIAN_EYE, GITAXIAN_PROBE, MOX_AMBER]
    result = tutor_targets(DIZZY_SPELL, deck)
    assert result["status"] == STATUS_RESOLVED
    assert result["targets"] == ["Curiosity", "Gitaxian Probe"]
    assert "Ophidian Eye" not in result["targets"]
    assert "Gitaxian Probe" in result["targets"]
    assert "Mox Amber" not in result["targets"]
    assert any("{1}{U}{U}" in limit for limit in result["limitations"])
    assert any("activation cost" in limit for limit in result["limitations"])


def test_transmute_excludes_its_own_source_card():
    deck = [DIZZY_SPELL, CURIOSITY]
    assert "Dizzy Spell" not in tutor_targets(DIZZY_SPELL, deck)["targets"]


def test_transmute_without_a_matching_mana_value_is_a_warning():
    deck = [DIZZY_SPELL, OPHIDIAN_EYE, MOX_AMBER]
    finding = next(
        f for f in audit_deck(deck, COMMANDER) if f["code"] == CODE_TRANSMUTE_NO_TARGET
    )
    assert finding["severity"] == "warning"
    assert finding["card"] == "Dizzy Spell"


def test_transmute_target_present_produces_no_finding():
    deck = [DIZZY_SPELL, CURIOSITY, OPHIDIAN_EYE]
    assert CODE_TRANSMUTE_NO_TARGET not in codes(audit_deck(deck, COMMANDER))


# --- tutor_targets contract -------------------------------------------------


def test_named_tutor_targets_list_only_printed_types():
    deck = [DRAGONS_HERALD, HELLKITE_OVERLORD, CURIOSITY]
    result = tutor_targets(DRAGONS_HERALD, deck)
    assert result["status"] == STATUS_RESOLVED
    assert result["targets"] == ["Hellkite Overlord"]
    limits = result["limitations"]
    assert any("sacrificing a green creature" in limit for limit in limits)
    assert any("command zone" in limit for limit in result["limitations"])


def test_unsupported_search_shape_is_explicitly_unknown():
    weird = card(
        "Odd Tutor",
        text=(
            "Search your library for a card with the same name as a card in "
            "each opponent's graveyard, then shuffle."
        ),
        types="Instant",
        mv=2.0,
    )
    result = tutor_targets(weird, [weird, CURIOSITY])
    assert result["status"] == STATUS_UNKNOWN
    assert result["targets"] == []
    assert any("not that the effect finds nothing" in x for x in result["limitations"])


def test_no_search_shape_is_none_not_unknown():
    result = tutor_targets(CURIOSITY, [CURIOSITY, DIZZY_SPELL])
    assert result["status"] == STATUS_NONE
    assert result["targets"] == []
    assert result["limitations"]


def test_findings_are_json_safe_and_use_the_declared_vocabulary():
    deck = [
        TAINTED_PACT,
        THASSAS_ORACLE,
        DRAGONS_HERALD,
        DIZZY_SPELL,
        *basics("Swamp", 3),
    ]
    findings = audit_deck(deck, COMMANDER)
    assert findings
    assert json.loads(json.dumps(findings)) == findings
    for finding in findings:
        assert set(finding) == {"code", "severity", "card", "message"}
        assert finding["severity"] in SEVERITIES
        assert finding["card"]
        assert finding["message"].endswith((".", "!"))


def test_empty_inputs_do_not_invent_findings():
    assert audit_deck([], {}) == []
    empty = tutor_targets({}, [])
    assert empty["status"] == STATUS_NONE
    assert empty["targets"] == []
    # Missing oracle text must not read as a resolved, empty target set.
    assert any("Missing oracle text" in limit for limit in empty["limitations"])
