from copy import deepcopy
from types import SimpleNamespace

import pytest

from sabermetrics.intelligence import upstream_guard as guard
from sabermetrics.pipeline.slot_assigner import SlotAssignment

COMMANDER = {"name": "Test commander", "color_identity": ["U", "R"], "oracle_text": ""}


def card(name="Weave Fate", cost="{3}{U}", text="Draw two cards.", price=1):
    return {
        "name": name,
        "mana_cost": cost,
        "cmc": int(cost[1]) + 1,
        "oracle_text": text,
        "type_line": "Instant",
        "color_identity": ["U"],
        "price_usd": price,
        "is_legal_in_99": True,
    }


def deck():
    land = {
        "name": "Island",
        "type_line": "Basic Land — Island",
        "oracle_text": "{T}: Add {U}.",
        "color_identity": ["U"],
        "price_usd": 0,
        "is_legal_in_99": True,
    }
    return [SlotAssignment(card=card(), slot_role="draw", score=0)] + [
        SlotAssignment(card=deepcopy(land), slot_role="land", score=0)
        for _ in range(98)
    ]


@pytest.fixture(autouse=True)
def preserve(monkeypatch):
    monkeypatch.setattr(
        guard,
        "current",
        lambda: SimpleNamespace(swap_policy="preserve", rebalance_policy="preserve"),
    )


def run_proposal(
    original,
    incoming,
    *,
    stage="swap",
    commander=COMMANDER,
    protected=(),
    budget=3,
    callback=None,
):
    @guard.preserve_stage(stage + "_policy", stage)
    def optimizer(
        deck,
        candidates,
        budget,
        commander=None,
        transaction_log=None,
        protected_names=None,
        tracer=None,
    ):
        if callback:
            callback(deck, candidates)
        deck[0] = SlotAssignment(card=candidates[0], slot_role="draw", score=10)
        return deck, (
            1 if stage == "swap" else {"upgrades": 1, "unbundles": 1, "spent": 99}
        )

    ledger = []
    result = optimizer(
        original,
        [incoming],
        budget,
        commander=commander,
        protected_names=protected,
        transaction_log=ledger,
    )
    return result, ledger


def test_proved_upgrade_commits_and_receipt_is_immutable():
    original = deck()
    (result, swaps), log = run_proposal(original, card("Quick Study", "{2}{U}"))
    assert result is original and swaps == 1 and result[0].card["name"] == "Quick Study"
    assert log[0]["validation"]["allowed"] and log[0]["status"] == "accepted"
    result[0].card["oracle_text"] = "changed later"
    assert log[0]["after"][0]["oracle_text"] == "Draw two cards."
    assert log[0]["before"][0]["name"] == "Weave Fate"


@pytest.mark.parametrize(
    "change",
    [
        {"text": "Target player draws two cards."},
        {"price": None},
        {"price": -1},
        {"price": float("nan")},
        {"price": float("inf")},
        {"price": 4},
        {"text": "Draw two cards. Skip your next turn."},
    ],
)
def test_unproved_or_overbudget_change_rejects_without_accepted_credit(change):
    original = deck()
    before = deepcopy(original)
    (result, stats), log = run_proposal(
        original, card("Candidate", "{2}{U}", **change), stage="rebalance"
    )
    assert result == before and original == before
    assert stats["upgrades"] == stats["unbundles"] == stats["spent"] == 0
    assert log[0]["status"] == "rejected"
    assert log[0]["proposed_stats"]["spent"] == 99
    assert log[0]["before"] == log[0]["after"]


def test_repeatable_draw_cannot_be_sold_for_generic_immediate_draw():
    original = deck()
    original[0].card.update(
        name="Mystic Remora",
        mana_cost="{U}",
        cmc=1,
        type_line="Enchantment",
        oracle_text="Cumulative upkeep {1}\nWhenever an opponent casts a noncreature spell, you may draw a card unless that player pays {4}.",
    )
    (result, count), log = run_proposal(original, card("Quick Study", "{2}{U}"))
    assert count == 0 and result[0].card["name"] == "Mystic Remora"
    assert "unknown_removed_functionality" in log[0]["validation"]["reasons"]


@pytest.mark.parametrize(
    "context,truncate,reason",
    [
        (None, False, "missing_commander_context"),
        (COMMANDER, True, "incomplete_mainboard"),
    ],
)
def test_incomplete_context_never_runs_optimizer(context, truncate, reason):
    original = deck()[:1] if truncate else deck()

    def forbidden(*args):
        raise AssertionError("must not run")

    (result, count), log = run_proposal(
        original, card(), commander=context, callback=forbidden
    )
    assert count == 0 and result is original and log[0]["reason"] == reason


def test_protected_card_cannot_leave():
    original = deck()
    (_, count), log = run_proposal(
        original, card("Quick Study", "{2}{U}"), protected={"Weave Fate"}
    )
    assert count == 0 and "protected_card_removed" in log[0]["validation"]["reasons"]


def test_exception_cannot_mutate_nested_input_or_candidate_alias():
    original = deck()
    incoming = original[0].card
    before = deepcopy(original)

    def explode(trial, candidates):
        candidates[0]["oracle_text"] = "corrupted"
        trial[1].card["name"] = "corrupted"
        raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        run_proposal(original, incoming, callback=explode)
    assert original == before and incoming == before[0].card


def test_saved_validation_flag_cannot_authorize_tampered_commit():
    original = deck()
    _, log = run_proposal(original, card("Quick Study", "{2}{U}"))
    assert guard.audit_transactions(log)["errors"] == []
    log[0]["after"][0]["oracle_text"] = "Draw two cards. Skip your next turn."
    log[0]["validation"] = {"allowed": True}
    assert guard.audit_transactions(log)["errors"] == ["0:unproved_preserve_commit"]


def test_rejected_record_cannot_claim_changed_input_was_rolled_back():
    original = deck()
    _, log = run_proposal(original, card("Bad", "{2}{U}", price=4))
    log[0]["after"][0]["name"] = "different"
    assert "0:rollback_changed_input" in guard.audit_transactions(log)["errors"]


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), -1, None])
def test_invalid_budget_rejects_without_running_callback(budget):
    def forbidden(*args):
        raise AssertionError("must not run")

    (_, count), log = run_proposal(deck(), card(), budget=budget, callback=forbidden)
    assert count == 0 and log[0]["reason"] == "invalid_budget"


def test_mixed_proposal_cannot_use_good_upgrade_to_authorize_unknown_cut():
    original = deck()
    before = deepcopy(original)

    def mixed(trial, candidates):
        trial[1] = SlotAssignment(card=card("Extra spell"), slot_role="draw", score=1)

    (_, count), log = run_proposal(
        original, card("Quick Study", "{2}{U}"), callback=mixed
    )
    assert count == 0 and original == before
    assert log[0]["proposed"][0]["name"] == "Quick Study"
    assert log[0]["proposed"][1]["name"] == "Extra spell"
    assert log[0]["status"] == "rejected"


@pytest.mark.parametrize("stage", ["swap", "rebalance"])
@pytest.mark.parametrize("unknown_outgoing", [False, True])
def test_real_optimizer_accepts_proved_upgrade_and_blocks_unproved_sale(
    stage, unknown_outgoing
):
    """Run real scoring and trade search over all 99 slots, without mocking objective."""
    import numpy as np

    from sabermetrics.analytics.synergy_matrix import SynergyMatrix
    from sabermetrics.pipeline.greedy_optimizer import rebalance_budget, swap_refine

    original = deck()
    original[0].card["_cvar_score"] = 0.0
    if unknown_outgoing:
        original[0].card.update(
            name="Mystic Remora",
            mana_cost="{U}",
            cmc=1,
            type_line="Enchantment",
            oracle_text="Cumulative upkeep {1}\nWhenever an opponent casts a noncreature spell, you may draw a card unless that player pays {4}.",
        )
    before = deepcopy(original)
    incoming = card("Quick Study", "{2}{U}")
    incoming["_cvar_score"] = 1.0
    synergy = SynergyMatrix(
        matrix=np.zeros((0, 0)), card_id_to_index={}, index_to_card_id={}
    )
    log = []
    function = swap_refine if stage == "swap" else rebalance_budget
    result, stats = function(
        original,
        [incoming],
        synergy,
        {},
        3,
        commander=COMMANDER,
        transaction_log=log,
    )
    assert result is original and len(result) == 99
    assert log[0]["proposed"][0]["name"] == "Quick Study"
    if unknown_outgoing:
        assert original == before
        assert log[0]["status"] == "rejected"
        assert (
            stats == 0 if stage == "swap" else stats["upgrades"] == stats["spent"] == 0
        )
    else:
        assert original[0].card["name"] == "Quick Study"
        assert log[0]["status"] == "accepted"
        assert stats == 1 if stage == "swap" else stats["upgrades"] == 1
    assert guard.audit_transactions(log)["errors"] == []
