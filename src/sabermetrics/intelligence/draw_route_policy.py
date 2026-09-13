"""Route-aware role credit and final-deck diagnostics, independent of card ranking."""

import json
from copy import deepcopy
from typing import get_args

from sabermetrics.intelligence.draw_route_assessment import assess_draw_routes
from sabermetrics.pipeline.slot_assigner import SlotRole


def _roles(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return list(value) if isinstance(value, (list, tuple)) else []


def _fallback_role(card):
    valid = set(get_args(SlotRole)) - {"draw"}
    candidates = [
        card.get("_primary_role"),
        *_roles(card.get("role_tags")),
        *_roles(card.get("_verified_roles")),
    ]
    return next(
        (role for role in candidates if isinstance(role, str) and role in valid),
        "utility",
    )


def constrain_draw_role(card, assessment):
    """Known unusable draw cannot fulfill a draw quota; unknown is not a proof of absence."""
    if assessment["status"] != "blocked":
        # Reassessment clears only our classification veto. Previously removed
        # quota credit stays conservative until the next full role annotation.
        card.pop("_draw_route_blocked", None)
        return False
    card["_draw_route_blocked"] = True
    roles = _roles(card.get("role_tags"))
    verified = _roles(card.get("_verified_roles"))
    facts = card.get("_facts")
    fact_roles = _roles(facts.get("roles")) if isinstance(facts, dict) else []
    changed = (
        "draw" in roles
        or card.get("_primary_role") == "draw"
        or "draw" in verified
        or "draw" in fact_roles
    )
    if not changed:
        return False
    card["role_tags"] = json.dumps([r for r in roles if r != "draw"] or ["utility"])
    card["_verified_roles"] = [r for r in verified if r != "draw"]
    if card.get("_primary_role") == "draw":
        card["_primary_role"] = _fallback_role(card)
    if isinstance(facts, dict):
        card["_facts"] = deepcopy(facts)
        card["_facts"]["roles"] = [r for r in fact_roles if r != "draw"]
    return changed


def constrain_candidates(candidates, support_cards, commander, power):
    changed = []
    for card in candidates:
        assessment = assess_draw_routes(card, support_cards, commander, power)
        if constrain_draw_role(card, assessment):
            changed.append({"name": card["name"], "assessment": assessment})
    return changed


def audit_assignments(assignments, commander, power, *, enforce=False):
    """Use the actual final cards as static support, never a pool or a forecast."""
    support = [a.card for a in assignments]
    rows, corrections = [], []
    for assignment in assignments:
        card = assignment.card
        assessment = assess_draw_routes(card, support, commander, power)
        if enforce:
            constrain_draw_role(card, assessment)
        if (
            assignment.slot_role == "draw"
            and assessment["status"] == "blocked"
            and enforce
        ):
            assignment.slot_role = _fallback_role(card)
            corrections.append(card["name"])
        rows.append(
            {"name": card["name"], "slot_role": assignment.slot_role, **assessment}
        )
    return {
        "cards": rows,
        "role_corrections": corrections,
        "blocked_draw_slots": [
            r["name"]
            for r in rows
            if r["slot_role"] == "draw" and r["status"] == "blocked"
        ],
        "unverified_draw_slots": [
            r["name"]
            for r in rows
            if r["slot_role"] == "draw" and r["status"] == "unverified"
        ],
        "scope": "Static draw-route opportunities and policy costs; conditional/unknown routes are not guaranteed card advantage or turn-level availability.",
    }
