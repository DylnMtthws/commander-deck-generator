"""Independent positive and adversarial transaction checks, not score snapshots."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sabermetrics.intelligence.function_guard import (
    guarded_repair,
    simple_draw,
    substitution_proof,
    validate_transition,
)


def spell(name, text="Draw two cards.", cost="{3}{U}", **updates):
    tokens = __import__("re").findall(r"\{([^}]+)\}", cost)
    card = {
        "name": name,
        "oracle_text": text,
        "type_line": "Instant",
        "mana_cost": cost,
        "cmc": sum(int(x) if x.isdigit() else 1 for x in tokens),
        "price_usd": 1,
        "color_identity": ["U"],
        "role_tags": ["draw"],
    }
    card.update(updates)
    return card


COMMANDER = {"name": "Example", "color_identity": ["U"]}
PUBLIC = json.loads(
    (
        Path(__file__).parents[1]
        / "docs/experiments/function-preservation/public-fixtures.json"
    ).read_text()
)["cards"]


@pytest.mark.parametrize("card", PUBLIC, ids=lambda c: c["name"])
def test_previously_lost_functions_never_become_generic_draw(card):
    assert simple_draw(card) is None
    assert not substitution_proof(card, spell("Generic draw"))["allowed"]


@pytest.mark.parametrize(
    "text",
    [
        "Draw two cards. Discard a card.",
        "Draw two cards. Skip your next turn.",
        "Draw two cards. (Only if you control a Wizard.)",
        "Target player draws two cards.",
        "Draw two cards. Flashback {3}{U}",
        "Draw X cards.",
        "Draw two cards, then untap two lands.",
        "When this creature enters, draw two cards.",
    ],
)
def test_full_oracle_consumption_required(text):
    assert simple_draw(spell("Complex", text)) is None


@pytest.mark.parametrize("cost", ["{X}{U}", "{U/P}", "{2/U}", "", "{S}{U}"])
def test_unknown_alternative_costs_do_not_receive_proof(cost):
    assert simple_draw(spell("Cost", cost=cost)) is None


def test_true_draw_upgrade_preserves_timing_pips_and_net_advantage():
    old = spell("Old")
    new = spell("New", cost="{2}{U}")
    assert substitution_proof(old, new)["allowed"]
    receipt = validate_transition([old], [new], COMMANDER, 1)
    assert receipt["allowed"] and receipt["improved"]
    assert len(receipt["proofs"]) == 1


@pytest.mark.parametrize(
    "new",
    [
        spell("Slower", cost="{4}{U}"),
        spell("Sorcery", type_line="Sorcery"),
        spell("Pips", cost="{1}{U}{U}"),
        spell("Less", "Draw a card."),
        spell("Equivalent"),
        spell("Color shift", cost="{2}{B}"),
    ],
)
def test_draw_quantity_cannot_buy_lost_resources(new):
    assert not substitution_proof(spell("Old"), new)["allowed"]


def test_declared_protection_overrides_a_valid_simple_draw_upgrade():
    assert not substitution_proof(spell("Old"), spell("New", cost="{2}{U}"), {"Old"})[
        "allowed"
    ]


def test_noop_is_not_improvement():
    cards = [spell("Old")]
    receipt = validate_transition(cards, cards, COMMANDER, 1)
    assert receipt["allowed"] and receipt["status"] == "unchanged"
    assert not receipt["improved"]


def test_multifunction_early_reservation_diff_is_rejected():
    old = spell("Interaction", "Counter target spell. Draw a card.")
    new = spell("Generic", "Draw three cards.")
    receipt = validate_transition([old], [new], COMMANDER, 1)
    assert not receipt["allowed"]
    assert "unknown_removed_functionality" in receipt["reasons"]


def test_one_incoming_card_cannot_justify_multiple_losses():
    before = [spell("A"), spell("B")]
    after = [
        spell("Excellent", "Draw three cards.", "{2}{U}"),
        spell("Blank", "", "{1}"),
    ]
    assert not validate_transition(before, after, COMMANDER, 2)["allowed"]


def test_package_matching_finds_nongreedy_valid_assignment():
    before = [
        spell("Flexible", "Draw two cards.", "{3}{U}"),
        spell("Tight", "Draw three cards.", "{3}{U}"),
    ]
    after = [
        spell("Three", "Draw three cards.", "{2}{U}"),
        spell("Two", "Draw two cards.", "{2}{U}"),
    ]
    gate = validate_transition(before, after, COMMANDER, 2)
    assert gate["allowed"] and len(gate["proofs"]) == 2


def test_unknown_coverage_blocks_even_when_recognized_functions_remain():
    old = spell("Utility", "Scry 2. Draw a card.")
    new = spell("New", "Scry 2. Draw two cards.")
    assert not validate_transition([old], [new], COMMANDER, 1)["allowed"]


@pytest.mark.parametrize(
    "update",
    [
        {"price_usd": 2},
        {"price_usd": None},
        {"color_identity": ["B"]},
        {"is_legal_in_99": False},
    ],
)
def test_transaction_rechecks_hard_constraints(update):
    new = spell("New", cost="{2}{U}", **update)
    assert not validate_transition([spell("Old")], [new], COMMANDER, 1)["allowed"]


def test_repair_is_order_independent_bounded_and_does_not_mutate():
    cards = [spell("Old")]
    candidates = [
        spell("Cheap", cost="{2}{U}"),
        spell("More", "Draw three cards.", "{3}{U}"),
    ]
    frozen = deepcopy((cards, candidates))
    a, receipt = guarded_repair(cards, candidates, COMMANDER, 1)
    b, _ = guarded_repair(cards, list(reversed(candidates)), COMMANDER, 1)
    assert a == b and (cards, candidates) == frozen
    assert receipt["guard"]["improved"]
    assert a[0]["name"] == "More"


def test_new_cards_cannot_inherit_old_model_approval():
    new = spell("New", cost="{2}{U}", _fit_pass=True, _llm_fit_score=1)
    cards, receipt = guarded_repair([spell("Old")], [new], COMMANDER, 1)
    assert receipt["guard"]["improved"]
    assert not any(k.startswith(("_fit_", "_llm_fit")) for k in cards[0])


def test_forged_cmc_does_not_lower_cost():
    assert simple_draw(spell("Forged", cmc=1)) is None


def test_duplicate_incoming_and_card_count_loss_rejected():
    before = [spell("Old A"), spell("Old B")]
    new = spell("New", cost="{2}{U}")
    assert not validate_transition(before, [new, new], COMMANDER, 2)["allowed"]
    assert not validate_transition(before, [new], COMMANDER, 2)["allowed"]


def test_public_targeted_draw_is_protected_but_weave_fate_can_improve():
    fixtures = json.loads(
        (
            Path(__file__).parents[1]
            / "docs/experiments/function-preservation/public-positive-fixtures.json"
        ).read_text()
    )["cards"]
    by_name = {c["name"]: {**c, "price_usd": 1} for c in fixtures}
    for old_name in ("Weave Fate",):
        before = [by_name[old_name]]
        after, receipt = guarded_repair(before, [by_name["Quick Study"]], COMMANDER, 1)
        assert after[0]["name"] == "Quick Study"
        assert receipt["guard"]["improved"]
        proof = receipt["guard"]["proofs"][0]
        assert proof["before"]["mana"] == 4 and proof["after"]["mana"] == 3
        assert proof["before"]["draw"] == proof["after"]["draw"] == 2

    # Inspiration can target another player: cheaper self-draw loses that option.
    before = [by_name["Inspiration"]]
    after, receipt = guarded_repair(before, [by_name["Quick Study"]], COMMANDER, 1)
    assert after == before
    assert not receipt["guard"]["improved"]


def test_missing_oracle_id_model_normalization_is_not_a_card_replacement():
    before = spell("Placeholder", "")
    after = {**before, "oracle_id": ""}
    gate = validate_transition([before], [after], COMMANDER, 1)
    assert gate["allowed"] and gate["status"] == "unchanged"
    # An actual new identity is not silently merged with the placeholder.
    after["oracle_id"] = "actual-new-oracle-identity"
    assert not validate_transition([before], [after], COMMANDER, 1)["allowed"]


def test_duplicate_basic_records_do_not_alias_different_functional_facts():
    synthetic = spell(
        "Island", "", cost="{0}", type_line="Basic Land — Island", color_identity=[]
    )
    canonical = {
        **synthetic,
        "oracle_id": "canonical-island",
        "oracle_text": "({T}: Add {U}.)",
        "color_identity": ["U"],
    }
    before = [synthetic, synthetic, canonical]
    after = [{**synthetic, "oracle_id": ""}, {**synthetic, "oracle_id": ""}, canonical]
    assert validate_transition(before, after, COMMANDER, 3)["status"] == "unchanged"
    after[0] = {**after[0], "oracle_text": "{T}: Add {B}."}
    assert not validate_transition(before, after, COMMANDER, 3)["allowed"]
