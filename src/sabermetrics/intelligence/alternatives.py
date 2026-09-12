"""Bounded same-spell mana variants and held-out simulation confirmation."""

from __future__ import annotations

import time
from copy import deepcopy

from sabermetrics.intelligence.simulation import paired_improvement, run_probe


def compare_mana_variants(assignments: list, commander: dict) -> tuple[list, dict]:
    """Only substitute basic land colors; preserve every engine/spell/role.

    This comparison cannot trade interaction for goldfish speed. Broader spell
    search requires a model that can observe the changed spell effects.
    """
    start = time.monotonic()
    deadline = start + 15

    def probe(cards, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                "status": "unavailable",
                "reason": "Simulation time budget exhausted.",
            }
        return run_probe(cards, commander, timeout=min(3.0, remaining), **kwargs)

    basic_map = {
        "W": "Plains",
        "U": "Island",
        "B": "Swamp",
        "R": "Mountain",
        "G": "Forest",
    }
    colors = commander.get("color_identity") or []
    if len(colors) < 2:
        return assignments, {
            "status": "not_applicable",
            "reason": "No multicolor basic-land alternatives.",
        }
    baseline = probe([a.card for a in assignments])
    if baseline["status"] != "measured":
        return assignments, baseline
    variants = []
    indices = [
        i for i, a in enumerate(assignments) if a.card.get("name") in basic_map.values()
    ]
    for color in colors[:4]:
        variant = deepcopy(assignments)
        changed = 0
        for i in indices:
            if variant[i].card["name"] == basic_map[color]:
                continue
            card = variant[i].card
            card.update(
                {
                    "name": basic_map[color],
                    "id": f"basic-{basic_map[color].lower()}-variant-{i}",
                    "oracle_id": f"basic:{basic_map[color]}",
                    "type_line": f"Basic Land — {basic_map[color]}",
                    "oracle_text": "",
                    "color_identity": [color],
                    "price_usd": 0.0,
                    "image_uri": None,
                }
            )
            card.pop("_facts", None)
            changed += 1
            if changed == 2:
                break
        if changed:
            variants.append(variant)
    rows = []
    best = None
    best_delta = 0.0
    for i, variant in enumerate(variants):
        if time.monotonic() - start > 12:
            break
        measured = probe([a.card for a in variant])
        if measured["status"] != "measured":
            continue
        comparison = paired_improvement(baseline, measured)
        rows.append({"variant": i, **comparison})
        if comparison["improved"] and comparison["delta"] > best_delta:
            best = i
            best_delta = comparison["delta"]
    evidence = {
        "status": "measured",
        "scope": baseline["scope"],
        "baseline": {
            k: v for k, v in baseline["result"].items() if k != "cast_samples"
        },
        "comparisons": rows,
        "selected": "baseline",
    }
    if best is not None and time.monotonic() - start < 12:
        a = probe([a.card for a in assignments], games=5000, seed=837291)
        b = probe([a.card for a in variants[best]], games=5000, seed=837291)
        if a["status"] == b["status"] == "measured":
            confirmed = paired_improvement(a, b)
            evidence["confirmation"] = confirmed
            if confirmed["improved"]:
                evidence["selected"] = f"variant-{best}"
                evidence["selected_result"] = {
                    k: v for k, v in b["result"].items() if k != "cast_samples"
                }
                return variants[best], evidence
    return assignments, evidence


def choose_strategy_variant(
    baseline: list,
    infrastructure: list,
    candidates: list[dict],
    synergy,
    role_targets,
    budget: float,
    plan,
    profile_signals,
    type_targets=None,
) -> tuple[list, dict]:
    """Explore resource, payoff and balanced landfall variants cheaply.

    All candidates share protected infrastructure. Use verified capability
    coverage and functional role coverage, never an unobserved win estimate.
    """
    from sabermetrics.intelligence.cards import facts_for
    from sabermetrics.intelligence.strategy import assess_plan
    from sabermetrics.pipeline.greedy_optimizer import (
        _count_roles,
        deck_objective,
        greedy_fill,
    )

    if plan.archetype != "landfall":
        return baseline, {"status": "not_applicable", "candidates": 1}
    variants = [("balanced", baseline)]
    recipes = {
        "resources": {
            "land_ramp",
            "extra_land_play",
            "land_recursion",
            "landfall_cards",
        },
        "payoffs": {"landfall_tokens", "landfall_growth", "landfall_cards"},
    }
    original = {c["name"]: c for c in candidates}
    remaining = budget - sum(
        float(a.card.get("price_usd") or 0) for a in infrastructure
    )
    for name, capabilities in recipes.items():
        pool = []
        for card in candidates:
            copied = dict(card)
            if set(facts_for(card).capabilities) & capabilities:
                copied["_cvar_score"] = min(
                    1.0, float(copied.get("_cvar_score") or 0) + 0.20
                )
            pool.append(copied)
        additions = greedy_fill(
            shell=list(infrastructure),
            candidates=pool,
            synergy=synergy,
            role_targets=role_targets,
            budget_remaining=remaining,
            slots_remaining=max(0, 99 - len(infrastructure)),
            profile_signals=profile_signals,
            type_targets=type_targets,
        )
        for a in additions:
            a.card = original[a.card["name"]]
        variants.append((name, list(infrastructure) + additions))
    records = []
    best = baseline
    best_key = None
    baseline_counts = _count_roles(baseline)
    protected_roles = ("removal", "protection", "board_wipe", "recursion")
    for name, variant in variants:
        cards = [a.card for a in variant]
        names = [
            c.get("name") for c in cards if "Basic Land" not in c.get("type_line", "")
        ]
        price = sum(float(c.get("price_usd") or 0) for c in cards)
        counts = _count_roles(variant)
        if len(cards) != 99 or len(set(names)) != len(names) or price > budget + 1e-6:
            continue
        if any(
            counts.get(r, 0) < min(baseline_counts.get(r, 0), role_targets[r].min_count)
            for r in protected_roles
            if r in role_targets
        ):
            continue
        assessment = assess_plan(plan, cards)
        covered = sum(
            min(assessment["counts"][r] / n, 1) for r, n in plan.requirements.items()
        ) / len(plan.requirements)
        objective = deck_objective(
            cards, synergy, role_targets, profile_signals=profile_signals
        )
        key = (covered, objective, -price)
        records.append(
            {
                "variant": name,
                "requirement_coverage": covered,
                "structural_objective": round(objective, 5),
                "price_usd": round(price, 2),
            }
        )
        if best_key is None or key > best_key:
            best_key = key
            best = variant
            selected = name
    return best, {
        "status": "compared",
        "candidates": len(records),
        "selected": selected if records else "balanced",
        "comparisons": records,
        "basis": "Verified strategy coverage, then structural objective; interaction floors preserved. Not a simulation or win estimate.",
    }
