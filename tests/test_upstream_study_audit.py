"""Independent receipts cannot certify a different request or persisted deck."""

from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    from run_function_study import audit_upstream

    land = {
        "name": "Island",
        "oracle_id": None,
        "type_line": "Basic Land — Island",
        "oracle_text": "{T}: Add {U}.",
        "mana_cost": "",
        "cmc": 0,
        "color_identity": '["U"]',
        "keywords": "[]",
        "colors": None,
        "price_usd": 0,
        "is_legal_in_99": True,
        "_slot_role": "land",
    }
    cards = [deepcopy(land) for _ in range(99)]
    commander = {
        "name": "Commander",
        "oracle_id": "commander-oracle",
        "type_line": "Legendary Creature — Wizard",
        "oracle_text": "",
        "mana_cost": "{U}",
        "cmc": 1,
        "color_identity": ["U"],
        "keywords": [],
        "colors": ["U"],
    }
    data = {
        "deck": {
            "commander": commander,
            "cards": [
                {
                    "card": {
                        **c,
                        "oracle_id": "",
                        "color_identity": ["U"],
                        "keywords": [],
                        "current_price_usd": 0,
                    },
                    "slot_role": "land",
                }
                for c in cards
            ],
        }
    }
    policy = {"swap_policy": "preserve", "rebalance_policy": "preserve"}
    record = {
        "mode": "preserve",
        "status": "accepted",
        "before": cards,
        "after": deepcopy(cards),
        "commander": deepcopy(commander),
        "budget": 100,
        "protected": ["Island"],
    }
    upstream = {
        "policy": policy.copy(),
        "snapshots": {
            key: deepcopy(cards)
            for key in ["greedy", "after_strategy_variant", "after_rebalance", "final"]
        },
        "transactions": [
            {**deepcopy(record), "stage": stage} for stage in ["swap", "rebalance"]
        ],
        "cumulative_validation": {"allowed": False, "fabricated": True},
    }
    return audit_upstream, data, upstream, policy


def check(sample):
    audit, data, upstream, policy = sample
    return audit(data, upstream, policy, 100, {"Island"})


def test_valid_normalized_roundtrip_recomputes_cumulative(sample):
    result = check(sample)
    assert result["errors"] == []
    assert result["cumulative"]["allowed"]
    assert "fabricated" not in result["cumulative"]


def test_synthesized_basic_missing_keywords_normalizes_to_model_default(sample):
    for snapshot in sample[2]["snapshots"].values():
        for card in snapshot:
            card.pop("keywords")
    for record in sample[2]["transactions"]:
        for key in ("before", "after"):
            for card in record[key]:
                card.pop("keywords")
    assert check(sample)["errors"] == []


def test_actual_keyword_loss_is_not_normalized_away(sample):
    sample[2]["snapshots"]["final"][0]["keywords"] = '["Flying"]'
    assert "final_snapshot_persistence_mismatch" in check(sample)["errors"]


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("stage", "other", "stage_mismatch"),
        ("mode", "current", "mode_mismatch"),
        ("budget", 101, "budget_mismatch"),
        ("protected", [], "protected_mismatch"),
        ("status", "unknown_status", "invalid_transaction_status"),
        ("commander", {}, "commander_mismatch"),
    ],
)
def test_transaction_bound_to_actual_request(sample, field, value, error):
    sample[2]["transactions"][0][field] = value
    assert any(error in e for e in check(sample)["errors"])


@pytest.mark.parametrize(
    "snapshot,error",
    [
        ("after_strategy_variant", "first_transaction_input_mismatch"),
        ("after_rebalance", "last_transaction_output_mismatch"),
        ("final", "final_snapshot_persistence_mismatch"),
    ],
)
def test_boundary_snapshot_cannot_describe_a_different_deck(sample, snapshot, error):
    sample[2]["snapshots"][snapshot][0]["oracle_text"] = "Different printed function"
    assert error in check(sample)["errors"]


@pytest.mark.parametrize("change", ["price", "role", "colors", "duplicate"])
def test_final_persistence_detects_resource_role_color_and_multiplicity_changes(
    sample, change
):
    wrapper = sample[1]["deck"]["cards"][0]
    if change == "price":
        wrapper["price_usd"] = 1
    elif change == "role":
        wrapper["slot_role"] = "draw"
    elif change == "colors":
        wrapper["card"]["colors"] = []
    else:
        sample[1]["deck"]["cards"].pop()
    assert "final_snapshot_persistence_mismatch" in check(sample)["errors"]


def test_missing_receipts_fail_closed(sample):
    sample[2]["transactions"] = []
    del sample[2]["snapshots"]["greedy"]
    result = check(sample)
    assert "missing_optimizer_transactions" in result["errors"]
    assert "missing_snapshot:greedy" in result["errors"]


def test_cumulative_unproved_function_change_is_reported_not_comparator_failure(sample):
    # The guarded stages are unchanged; an unguarded earlier strategy variant
    # removed a printed function. This must appear in cumulative evidence.
    sample[2]["snapshots"]["greedy"][0]["oracle_text"] += " Draw a card."
    result = check(sample)
    assert result["errors"] == []
    assert not result["cumulative"]["allowed"]
