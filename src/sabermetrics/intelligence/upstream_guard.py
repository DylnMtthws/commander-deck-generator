"""Atomic optimizer transactions; objective scores never authorize function loss."""

import math
from copy import deepcopy
from functools import wraps
from inspect import signature

from sabermetrics.intelligence.experiment import current
from sabermetrics.intelligence.function_guard import validate_transition

FIELDS = (
    "id",
    "oracle_id",
    "name",
    "oracle_text",
    "type_line",
    "mana_cost",
    "cmc",
    "color_identity",
    "colors",
    "keywords",
    "power",
    "toughness",
    "is_legal_in_99",
    "price_usd",
    "current_price_usd",
    "_cvar_score",
    "_verified_roles",
    "_primary_role",
)


def snapshot(assignments):
    cards = []
    for assignment in assignments:
        card = {k: deepcopy(assignment.card[k]) for k in FIELDS if k in assignment.card}
        card["_slot_role"] = assignment.slot_role
        card["_assignment_score"] = assignment.score
        cards.append(card)
    return cards


def rejected_stats(stage, cards, budget):
    if stage == "swap":
        return 0
    prices = [c.get("price_usd", c.get("current_price_usd")) for c in cards]
    total = (
        sum(prices)
        if all(
            isinstance(p, (int, float)) and math.isfinite(p) and p >= 0 for p in prices
        )
        else None
    )
    return {
        "upgrades": 0,
        "unbundles": 0,
        "downgrades": 0,
        "spent": 0.0,
        "final_total": round(total, 2) if total is not None else None,
        "utilization": round(total / budget, 3)
        if total is not None
        and isinstance(budget, (int, float))
        and math.isfinite(budget)
        and budget > 0
        else 0.0,
    }


def preserve_stage(policy_field, stage):
    """Wrap pure in-memory optimizer work; external side effects are not rolled back."""

    def decorate(function):
        sig = signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            original = bound.arguments["deck"]
            before = snapshot(original)
            budget = bound.arguments["budget"]
            commander = deepcopy(bound.arguments.get("commander"))
            ledger = bound.arguments.get("transaction_log")
            protected = set(bound.arguments.get("protected_names") or ())
            mode = getattr(current(), policy_field)
            record = {
                "stage": stage,
                "mode": mode,
                "budget": budget,
                "commander": commander,
                "protected": sorted(protected),
                "before": before,
                "status": "pending",
            }
            valid_budget = (
                isinstance(budget, (int, float))
                and not isinstance(budget, bool)
                and math.isfinite(budget)
                and budget >= 0
            )
            if mode == "preserve" and (
                not commander or len(before) != 99 or not valid_budget
            ):
                reason = (
                    "missing_commander_context"
                    if not commander
                    else "incomplete_mainboard"
                    if len(before) != 99
                    else "invalid_budget"
                )
                record.update(
                    status="rejected",
                    reason=reason,
                    proposed=before,
                    after=before,
                    accepted_stats=rejected_stats(stage, before, budget),
                )
                if ledger is not None:
                    ledger.append(deepcopy(record))
                return original, rejected_stats(stage, before, budget)

            # Isolate nested card metadata, not merely the list of assignments.
            if mode == "preserve":
                isolated = deepcopy(
                    {"deck": original, "candidates": bound.arguments.get("candidates")}
                )
                bound.arguments["deck"] = isolated["deck"]
                if "candidates" in bound.arguments:
                    bound.arguments["candidates"] = isolated["candidates"]
            # In preserve mode, legacy trace events describe a proposal, not a
            # committed trade. The transaction ledger is the authoritative receipt.
            proposal_events = []
            if mode == "preserve":

                class ProposalTrace:
                    def record(self, **event):
                        proposal_events.append(deepcopy(event))

                bound.arguments["tracer"] = ProposalTrace()
            try:
                proposal, proposed_stats = function(*bound.args, **bound.kwargs)
                proposed = snapshot(proposal)
                check = (
                    validate_transition(before, proposed, commander, budget, protected)
                    if commander
                    else None
                )
                allowed = mode != "preserve" or bool(check and check["allowed"])
                record.update(
                    proposed=proposed,
                    proposed_stats=deepcopy(proposed_stats),
                    proposal_events=proposal_events,
                    validation=check,
                    status="accepted" if allowed else "rejected",
                )
                stats = (
                    proposed_stats if allowed else rejected_stats(stage, before, budget)
                )
                if mode == "preserve" and allowed and not check["changed"]:
                    stats = rejected_stats(stage, proposed, budget)
                record.update(
                    after=deepcopy(proposed if allowed else before),
                    accepted_stats=deepcopy(stats),
                )
                if ledger is not None:
                    ledger.append(deepcopy(record))
                if allowed:
                    original[:] = proposal
                return original, stats
            except Exception as exc:
                record.update(
                    status="error", error_type=type(exc).__name__, after=snapshot(original)
                )
                if ledger is not None:
                    ledger.append(deepcopy(record))
                raise

        return wrapped

    return decorate


def audit_transactions(records):
    """Recompute preservation from saved states, never trust a claimed pass flag."""
    errors = []
    checks = []
    previous = None
    for index, record in enumerate(records):
        before, after = record["before"], record["after"]
        if previous is not None and before != previous:
            errors.append(f"{index}:stage_chain_mismatch")
        previous = after
        budget = record.get("budget")
        valid_budget = (
            isinstance(budget, (int, float))
            and not isinstance(budget, bool)
            and math.isfinite(budget)
            and budget >= 0
        )
        check = (
            validate_transition(
                before,
                after,
                record["commander"],
                record["budget"],
                record["protected"],
            )
            if record.get("commander") and valid_budget
            else None
        )
        checks.append(check)
        if record["mode"] == "preserve":
            if record["status"] == "accepted" and (
                len(before) != 99 or not check or not check["allowed"]
            ):
                errors.append(f"{index}:unproved_preserve_commit")
            if record["status"] in {"rejected", "error"} and after != before:
                errors.append(f"{index}:rollback_changed_input")
            if record["status"] == "rejected" and record.get(
                "accepted_stats"
            ) != rejected_stats(record["stage"], before, budget):
                errors.append(f"{index}:rejected_proposal_credited")
        if record["mode"] == "off" and after != before:
            errors.append(f"{index}:off_mutated_input")
    return {
        "errors": errors,
        "checks": checks,
        "scope": "Recorded stage boundaries; not general baseline quality.",
    }
