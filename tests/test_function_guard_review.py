"""Independent review regressions for commander-sensitive substitution proofs."""

import re

import pytest

from sabermetrics.intelligence.function_guard import guarded_repair, validate_transition


def draw(name, cost, color=("U",)):
    tokens = re.findall(r"\{([^}]+)\}", cost)
    return {
        "name": name,
        "oracle_text": "Draw two cards.",
        "type_line": "Instant",
        "mana_cost": cost,
        "cmc": sum(int(t) if t.isdigit() else 1 for t in tokens),
        "color_identity": list(color),
        "price_usd": 1,
        "is_legal_in_99": True,
    }


@pytest.mark.parametrize(
    "mechanic",
    [
        "Whenever you cast a spell with mana value 4 or greater, draw a card.",
        "Whenever you cast a spell with an even mana value, create a Treasure token.",
        "The first spell you cast each turn has cascade.",
    ],
)
def test_lower_cost_must_not_erase_commander_mana_value_function(mechanic):
    commander = {
        "name": "Synthetic cost-sensitive commander",
        "color_identity": ["U"],
        "oracle_text": mechanic,
    }
    old, new = draw("Old", "{3}{U}"), draw("New", "{2}{U}")
    result = validate_transition([old], [new], commander, 10)
    assert not result["allowed"]
    deck, _ = guarded_repair([old], [new], commander, 10)
    assert deck == [old]


def test_colorless_replacement_must_not_erase_blue_spell_trigger():
    commander = {
        "name": "Synthetic blue commander",
        "color_identity": ["U"],
        "oracle_text": "Whenever you cast a blue spell, draw a card.",
    }
    result = validate_transition(
        [draw("Blue", "{3}{U}")], [draw("Colorless", "{3}", ())], commander, 10
    )
    assert not result["allowed"]


def test_unrelated_function_loss_cannot_hide_behind_a_valid_draw_upgrade():
    commander = {"name": "Synthetic commander", "color_identity": ["U"]}
    engine = {
        "name": "Synthetic untap engine",
        "oracle_text": "Untap another target permanent.",
        "type_line": "Artifact",
        "mana_cost": "{2}",
        "cmc": 2,
        "color_identity": [],
        "price_usd": 1,
    }
    replacement = draw("Extra draw", "{2}{U}")
    result = validate_transition(
        [draw("Slow draw", "{3}{U}"), engine],
        [draw("Fast draw", "{2}{U}"), replacement],
        commander,
        10,
    )
    assert not result["allowed"]
    assert result["functions"]["unknown_removals"]


def test_exact_no_op_never_claims_improvement():
    card = draw("Unchanged draw", "{3}{U}")
    result = validate_transition([card], [card], {"color_identity": ["U"]}, 10)
    assert result["status"] == "unchanged"
    assert result["improved"] is False
