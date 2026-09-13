"""Actual public effects and adversarial Commander preservation boundaries."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sabermetrics.intelligence.commander_substitutions import (
    commander_preservation,
    extended_profile,
    extended_proof,
)
from sabermetrics.intelligence.function_guard import guarded_repair, validate_transition

DOCS = Path(__file__).parents[1] / "docs/experiments/commander-substitutions"
CARDS = {
    c["name"]: {**c, "price_usd": 1}
    for c in json.loads((DOCS / "public-spells.json").read_text())["cards"]
}
VIVI = {
    "name": "Example Vivi",
    "color_identity": ["U", "R"],
    "oracle_text": "Whenever you cast a noncreature spell, put a +1/+1 counter on Vivi and it deals 1 damage to each opponent.",
}
KRENKO = {
    "name": "Example Goblin",
    "color_identity": ["R"],
    "oracle_text": "{T}: Create X 1/1 red Goblin creature tokens, where X is the number of Goblins you control.",
}


@pytest.mark.parametrize("name", ["Shock", "Burst Lightning", "Play with Fire"])
@pytest.mark.parametrize("facts", [None, {"roles": []}, {"roles": ["utility"]}])
def test_proven_damage_replacement_role_survives_incomplete_facts(name, facts):
    from sabermetrics.pipeline.deck_builder import _heuristic_role

    card = deepcopy(CARDS[name])
    if facts is not None:
        card["_facts"] = facts
    assert _heuristic_role(card) == "removal"


def test_player_only_damage_is_not_creature_removal():
    from sabermetrics.pipeline.deck_builder import _heuristic_role

    card = {**CARDS["Shock"], "oracle_text": "This spell deals 2 damage to target player.",
            "_facts": {"roles": ["utility"]}}
    assert _heuristic_role(card) == "utility"


@pytest.mark.parametrize(
    "incoming", ["Lightning Bolt", "Burst Lightning", "Play with Fire"]
)
def test_actual_burn_upgrade_preserves_vivi_cast_trigger(incoming):
    old, new = CARDS["Shock"], CARDS[incoming]
    proof = extended_proof(old, new, commander=VIVI)
    assert proof["allowed"], proof
    assert proof["commander"]["allowed"]
    assert any(
        r["scope"] == "cast:noncreature" and r["value"]
        for r in proof["commander"]["after"]["contributions"]
    )
    assert validate_transition([old], [new], VIVI, 1)["improved"]


def test_artifact_payment_is_an_extra_option_not_required_support():
    old, new = CARDS["Thrill of Possibility"], CARDS["Demand Answers"]
    proof = extended_proof(old, new, commander=KRENKO)
    assert proof["allowed"]
    assert "discard:1" in proof["after"]["options"]
    assert validate_transition([old], [new], KRENKO, 1)["improved"]
    assert not extended_proof(new, old, commander=KRENKO)["allowed"]


@pytest.mark.parametrize(
    "change",
    [
        {"oracle_text": "This spell deals 4 damage to target creature."},
        {
            "oracle_text": "This spell deals 3 damage to any target. Skip your next turn."
        },
        {
            "oracle_text": "This spell deals 3 damage to any target. (Sacrifice a creature.)"
        },
        {"type_line": "Sorcery"},
        {"mana_cost": "{1}{R}", "cmc": 2},
        {"color_identity": ["B"]},
    ],
)
def test_stronger_damage_does_not_erase_lost_function_or_cost(change):
    new = {**CARDS["Lightning Bolt"], **change}
    assert not extended_proof(CARDS["Shock"], new, commander=VIVI)["allowed"]


def test_kicker_mode_cannot_disappear_behind_bigger_base_damage():
    assert not extended_proof(
        CARDS["Burst Lightning"], CARDS["Lightning Bolt"], commander=VIVI
    )["allowed"]
    assert not extended_proof(
        CARDS["Play with Fire"], CARDS["Lightning Bolt"], commander=VIVI
    )["allowed"]


def test_kicker_reminder_and_effect_must_agree():
    card = deepcopy(CARDS["Burst Lightning"])
    card["oracle_text"] = card["oracle_text"].replace(
        "additional {4}", "additional {1}"
    )
    assert extended_profile(card) is None


def test_unknown_additional_cost_or_sacrifice_only_cannot_replace_discard():
    new = deepcopy(CARDS["Demand Answers"])
    new["oracle_text"] = new["oracle_text"].replace(
        "sacrifice an artifact or discard a card", "sacrifice an artifact"
    )
    assert extended_profile(new) is None


def test_full_deck_gate_rejects_hidden_cut_even_when_one_upgrade_passes():
    draw = {
        "name": "Tutor",
        "type_line": "Sorcery",
        "mana_cost": "{R}",
        "cmc": 1,
        "color_identity": ["R"],
        "price_usd": 1,
        "oracle_text": "Search your library for a card, then shuffle.",
    }
    before = [CARDS["Shock"], draw]
    after = [CARDS["Lightning Bolt"], CARDS["Demand Answers"]]
    gate = validate_transition(before, after, KRENKO, 2)
    assert not gate["allowed"]
    assert "unknown_removed_functionality" in gate["reasons"]


def test_budget_and_protection_still_block_upgrade():
    old = {**CARDS["Shock"], "price_usd": 0.06}
    new = {**CARDS["Lightning Bolt"], "price_usd": 0.78}
    deck, receipt = guarded_repair([old], [new], KRENKO, 0.06)
    assert deck == [old] and not receipt["guard"]["improved"]
    deck, receipt = guarded_repair([old], [new], KRENKO, 1, protected={"Shock"})
    assert deck == [old] and not receipt["guard"]["improved"]


def test_body_missing_stats_and_draw_creature_do_not_replace_vivi_spell():
    creature = {
        "name": "Body",
        "type_line": "Creature — Elf",
        "oracle_text": "",
        "mana_cost": "{R}",
        "cmc": 1,
        "color_identity": ["R"],
    }
    assert extended_profile(creature) is None
    assert not commander_preservation(CARDS["Shock"], creature, VIVI)["allowed"]


def body(name, typ="Creature — Goblin", power="1", toughness="1", text="", cost="{R}"):
    return {
        "name": name,
        "type_line": typ,
        "power": power,
        "toughness": toughness,
        "oracle_text": text,
        "mana_cost": cost,
        "cmc": 1,
        "color_identity": ["R"],
        "price_usd": 1,
    }


def test_complete_body_keeps_goblin_and_gains_haste():
    a, b = body("Old"), body("New", text="Haste")
    assert extended_proof(a, b, commander=KRENKO)["allowed"]
    assert validate_transition([a], [b], KRENKO, 1)["improved"]


@pytest.mark.parametrize(
    "new",
    [
        body("Elf", typ="Creature — Elf"),
        body("Tiny", power="0"),
        body("Weak", toughness="0"),
        body("Defender", text="Defender"),
        body("Restricted", text="This creature can't block."),
        body("Legendary", typ="Legendary Creature — Goblin"),
    ],
)
def test_commander_preference_does_not_erase_body_losses(new):
    assert not extended_proof(body("Old"), new, commander=KRENKO)["allowed"]


def test_unknown_power_stays_unknown_in_proof_and_serialization():
    c = body("Star", power="*")
    assert extended_profile(c) is None
    card = body("Known")
    after = {**card, "power": "2"}
    # Changed stats must be visible to the transaction identity, not a no-op.
    assert validate_transition([card], [after], KRENKO, 1)["changed"]
