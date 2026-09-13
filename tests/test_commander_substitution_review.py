"""Independent adversarial tests for eligibility and expanded local proofs."""

import re

import pytest

from sabermetrics.intelligence.commander_substitutions import (
    extended_profile,
    extended_proof,
)
from sabermetrics.intelligence.eligibility import main_deck_eligible


@pytest.mark.parametrize(
    "type_line",
    [
        "Stickers",
        "Plane — Ravnica",
        "Scheme",
        "Token Creature — Goblin",
        "Emblem",
        "Artifact — Attraction",
        "Artifact — Contraption",
        "Vanguard",
        "Conspiracy",
    ],
)
def test_upstream_legal_flag_cannot_admit_supplementary_cards(type_line):
    assert not main_deck_eligible({"type_line": type_line, "is_legal_in_99": True})


@pytest.mark.parametrize(
    "type_line",
    [
        "Basic Land — Island",
        "Enchantment — Saga",
        "Battle — Siege",
        "Kindred Instant — Elf",
        "Creature — Human // Land",
        "Legendary Planeswalker — Jace",
        "Artifact Creature — Golem",
    ],
)
def test_legitimate_deck_types_remain_eligible(type_line):
    assert main_deck_eligible({"type_line": type_line, "is_legal_in_99": True})


def card(name, text, cost="{R}", typ="Instant", **updates):
    parts = re.findall(r"\{([^}]+)\}", cost)
    result = {
        "name": name,
        "oracle_text": text,
        "mana_cost": cost,
        "type_line": typ,
        "cmc": sum(int(p) if p.isdigit() else 1 for p in parts),
        "color_identity": ["R"],
        "price_usd": 1,
    }
    result.update(updates)
    return result


def test_more_damage_cannot_hide_narrower_target_scope():
    old = card("Old", "This spell deals 2 damage to any target.")
    new = card("New", "This spell deals 4 damage to target creature.")
    assert not extended_proof(old, new)["allowed"]


def test_cheaper_damage_cannot_drop_optional_kicker_mode():
    old = card(
        "Old",
        "Kicker {4} (You may pay an additional {4} as you cast this spell.)\nThis spell deals 2 damage to any target. If this spell was kicked, it deals 4 damage instead.",
        cost="{1}{R}",
    )
    new = card("New", "This spell deals 3 damage to any target.")
    assert not extended_proof(old, new)["allowed"]


def test_optional_payment_route_cannot_be_lost_for_more_draw():
    old = card(
        "Old",
        "As an additional cost to cast this spell, sacrifice an artifact or discard a card.\nDraw two cards.",
    )
    new = card(
        "New",
        "As an additional cost to cast this spell, discard a card.\nDraw three cards.",
    )
    assert not extended_proof(old, new)["allowed"]


@pytest.mark.parametrize(
    "rider",
    [
        " You lose 3 life.",
        " Discard a card.",
        " This spell cannot be countered.",
        " Sacrifice a creature.",
    ],
)
def test_unconsumed_riders_prevent_coverage(rider):
    assert (
        extended_profile(
            card("Unknown", "This spell deals 3 damage to any target." + rider)
        )
        is None
    )


def test_missing_body_data_is_never_a_vanilla_equivalence_proof():
    assert extended_profile(card("Unknown body", "", typ="Creature — Goblin")) is None


def test_higher_stats_cannot_remove_original_tribe():
    old = card("Old elf", "", typ="Creature — Elf", power="1", toughness="1")
    new = card("New human", "", typ="Creature — Human", power="3", toughness="3")
    assert not extended_proof(old, new)["allowed"]


def test_higher_power_cannot_erase_small_creature_commander_trigger():
    commander = {
        "name": "Synthetic small creature commander",
        "oracle_text": "Whenever a creature with power 1 or less dies, return it to your hand.",
    }
    old = card("Old body", "", typ="Creature — Goblin", power="1", toughness="1")
    new = card("Larger body", "", typ="Creature — Goblin", power="2", toughness="2")
    assert not extended_proof(old, new, commander=commander)["allowed"]


def test_final_acceptance_rejects_sticker_even_when_format_flag_is_true():
    from sabermetrics.pipeline.quality import evaluate_final_deck

    forest = {
        "name": "Forest",
        "type_line": "Basic Land — Forest",
        "oracle_text": "",
        "color_identity": ["G"],
        "price_usd": 0,
        "is_legal_in_99": True,
    }
    sticker = {**forest, "name": "Synthetic sticker sheet", "type_line": "Stickers"}
    report = evaluate_final_deck(
        assignments=[forest.copy() for _ in range(98)] + [sticker],
        commander_name="Synthetic commander",
        commander_colors=["G"],
        budget_usd=50,
        requested_bracket=3,
        estimated_bracket=3,
        engine=None,
        engine_status="not_requested",
    )
    assert "card_type_eligibility" in {item.code for item in report.failures}
