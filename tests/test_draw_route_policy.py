"""Policy boundaries use mocked route facts, not claimed Oracle parsing coverage."""

import json
from copy import deepcopy
from typing import get_args

import pytest

from sabermetrics.intelligence import draw_route_policy as policy
from sabermetrics.pipeline.slot_assigner import SlotAssignment, SlotRole


@pytest.mark.parametrize(
    "field,value",
    [
        ("role_tags", '["draw"]'),
        ("role_tags", ["draw"]),
        ("_verified_roles", ["draw"]),
        ("_primary_role", "draw"),
        ("_facts", {"roles": ["draw"], "unparsed": ["example"]}),
    ],
)
def test_all_draw_credit_locations_are_removed_and_reported(field, value):
    card = {"name": "Synthetic blocked route", field: value}
    assert policy.constrain_draw_role(card, {"status": "blocked"}) is True
    assert "draw" not in json.loads(card["role_tags"])
    assert "draw" not in card["_verified_roles"]
    assert card.get("_primary_role") != "draw"
    assert "draw" not in card.get("_facts", {}).get("roles", [])
    assert policy.constrain_draw_role(card, {"status": "blocked"}) is False


def test_blocked_removes_draw_but_preserves_other_roles_and_detaches_facts():
    facts = {"roles": ["draw", "removal"], "nested": {"evidence": [1]}}
    card = {
        "role_tags": '["draw", "tribal", "removal"]',
        "_verified_roles": ["draw", "removal"],
        "_primary_role": "draw",
        "_facts": facts,
    }
    policy.constrain_draw_role(card, {"status": "blocked"})
    assert card["_primary_role"] == "removal"
    assert json.loads(card["role_tags"]) == ["tribal", "removal"]
    assert card["_facts"]["roles"] == ["removal"]
    card["_facts"]["nested"]["evidence"].append(2)
    assert facts == {"roles": ["draw", "removal"], "nested": {"evidence": [1]}}


@pytest.mark.parametrize("status", ["unverified", "conditional", "supported"])
def test_nonblocked_assessment_does_not_mutate_metadata(status):
    card = {
        "role_tags": ["draw"],
        "_facts": {"roles": ["draw"]},
        "_primary_role": "draw",
    }
    before = deepcopy(card)
    assert policy.constrain_draw_role(card, {"status": status}) is False
    assert card == before


@pytest.mark.parametrize("enforce", [False, True])
def test_final_audit_uses_actual_assignments_and_only_enforces_requested_policy(
    monkeypatch, enforce
):
    assignments = [
        SlotAssignment(
            card={"name": n, "_primary_role": "draw", "role_tags": '["draw"]'},
            slot_role="draw",
            score=1,
        )
        for n in ["blocked", "unknown", "conditional"]
    ]
    calls = []
    commander = {"name": "Synthetic commander"}

    def assess(card, support, cmd, power):
        calls.append((card, support, cmd, power))
        return {
            "status": {
                "blocked": "blocked",
                "unknown": "unverified",
                "conditional": "conditional",
            }[card["name"]]
        }

    monkeypatch.setattr(policy, "assess_draw_routes", assess)
    before = [x.model_dump() for x in assignments]
    result = policy.audit_assignments(assignments, commander, 3, enforce=enforce)
    assert len(calls) == 3
    for card, support, cmd, power in calls:
        assert all(
            actual is expected.card for actual, expected in zip(support, assignments)
        )
        assert len(support) == 3 and cmd is commander and power == 3
    assert result["role_corrections"] == (["blocked"] if enforce else [])
    assert result["blocked_draw_slots"] == ([] if enforce else ["blocked"])
    assert result["unverified_draw_slots"] == ["unknown"]
    if not enforce:
        assert [x.model_dump() for x in assignments] == before
    else:
        assert assignments[0].slot_role == "utility"
        assert assignments[1].slot_role == assignments[2].slot_role == "draw"


@pytest.mark.parametrize(
    "primary,tags,expected",
    [
        ("tribal", ["tribal", "protection"], "protection"),
        ("draw", ["draw", "unknown"], "utility"),
        (None, [], "utility"),
        ("removal", ["draw"], "removal"),
    ],
)
def test_enforced_fallback_always_validates_as_real_slot_assignment(
    monkeypatch, primary, tags, expected
):
    monkeypatch.setattr(policy, "assess_draw_routes", lambda *a: {"status": "blocked"})
    a = SlotAssignment(
        card={
            "name": "Synthetic",
            "_primary_role": primary,
            "role_tags": json.dumps(tags),
        },
        slot_role="draw",
        score=1,
    )
    policy.audit_assignments([a], {}, 3, enforce=True)
    assert a.slot_role == expected
    assert a.slot_role in get_args(SlotRole)
    SlotAssignment.model_validate(a.model_dump())


def test_candidate_change_receipt_includes_verified_only_mutations(monkeypatch):
    monkeypatch.setattr(policy, "assess_draw_routes", lambda *a: {"status": "blocked"})
    cards = [
        {"name": "Verified only", "_verified_roles": ["draw"]},
        {"name": "No draw", "role_tags": '["removal"]'},
    ]
    receipts = policy.constrain_candidates(cards, [], {}, 3)
    assert [r["name"] for r in receipts] == ["Verified only"]


def test_classifier_cannot_restore_blocked_draw_and_retains_removal():
    from sabermetrics.pipeline.slot_assigner import _classify_card_role

    card = {
        "type_line": "Sorcery",
        "oracle_text": "Destroy target creature. Draw a card.",
        "role_tags": '["draw", "removal"]',
    }
    policy.constrain_draw_role(card, {"status": "blocked"})
    assert _classify_card_role(card) == "removal"
    assert _classify_card_role(card, llm_role="draw") == "removal"
    policy.constrain_draw_role(card, {"status": "unverified"})
    assert "_draw_route_blocked" not in card
    assert _classify_card_role(card) == "draw"
    assert "draw" not in json.loads(card["role_tags"])


def test_final_reassessment_clears_marker_on_all_slots(monkeypatch):
    card = {"name": "Reassessed", "type_line": "Creature", "_draw_route_blocked": True}
    assignment = SlotAssignment(card=card, slot_role="utility", score=1)
    monkeypatch.setattr(
        policy, "assess_draw_routes", lambda *a: {"status": "conditional"}
    )
    policy.audit_assignments([assignment], {}, 3, enforce=True)
    assert "_draw_route_blocked" not in assignment.card
