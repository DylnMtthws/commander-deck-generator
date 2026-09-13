"""Budgeted initial-package search with explicit trigger diversity.

A package-design heuristic, not a substitution proof or expected-card estimate.
Cards sharing a trigger still have distinct rules, costs and timing.
"""

import math
import re
from collections import defaultdict

from sabermetrics.intelligence.commander_contracts import printed_mana_value
from sabermetrics.intelligence.draw_selection import price


def trigger_group(card):
    text = (card.get("oracle_text") or "").lower()
    if re.search(
        r"whenever (?:enchanted|this) creature deals damage to an opponent, (?:you may )?draw",
        text,
    ):
        return "creature_damage_to_opponent"
    if re.search(r"whenever an opponent casts[^.\n]*, (?:you may )?draw", text):
        return "opponent_cast"
    if re.search(
        r"whenever you cast(?: or copy)?[^.\n]*, (?:you may )?draw", text
    ) and not re.search(r"then discard|discard a card", text):
        return "own_cast"
    if (card.get("type_line") or "") in {"Instant", "Sorcery"} and (
        re.search(r"\bdraw a card\b", text)
        or re.search(r"draw three cards.*put two cards from your hand", text, re.DOTALL)
    ):
        return "one_shot_smoothing"
    # Unknown clauses receive no artificial diversity credit. This fallback
    # is an uncertainty bucket, not evidence of equivalent card effects.
    return "unmodeled_draw"


def select_portfolio(
    scored, count, budget, width=48, diversity=True, max_mana_value=None
):
    """Keep bounded alternatives per slot count; every proposal respects full cap.

    First two examples of a detected trigger retain substantial weight; further
    redundancy has diminishing heuristic value. All other printed effects remain
    unknown to this objective. No full-deck preservation claim is made here.
    """
    if not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget < 0:
        raise ValueError("Finite nonnegative package budget required")
    if type(count) is not int or count < 0 or type(width) is not int or width < 1:
        raise ValueError("Invalid search bounds")
    items = sorted(
        [
            (c, float(s), price(c), trigger_group(c))
            for c, s in scored
            if price(c) is not None
            and (
                max_mana_value is None
                or (
                    printed_mana_value(c) is not None
                    and printed_mana_value(c) <= max_mana_value
                )
            )
            and not c.get("_anti_engine")
            and math.isfinite(float(s))
        ],
        key=lambda x: (-x[1], x[2], x[0]["name"]),
    )

    def value(indices):
        groups = defaultdict(list)
        for i in indices:
            groups[items[i][3]].append(max(0, items[i][1]))
        return sum(
            score * (1 if not diversity or n == 0 else 0.85 if n == 1 else 0.25)
            for scores in groups.values()
            for n, score in enumerate(sorted(scores, reverse=True))
        )

    def key(state):
        indices, cost = state
        return (
            -value(indices),
            cost,
            tuple(sorted(items[i][0]["name"] for i in indices)),
        )

    states = {0: [((), 0.0)]}
    examined = 0
    for i, (card, score, cost, group) in enumerate(items):
        for size in range(min(count, i + 1), 0, -1):
            proposals = list(states.get(size, []))
            for indices, spent in states.get(size - 1, []):
                examined += 1
                if spent + cost <= budget + 1e-6 and card["name"] not in {
                    items[j][0]["name"] for j in indices
                }:
                    proposals.append((indices + (i,), spent + cost))
            # Keep quality candidates AND low-cost alternatives, so a partial
            # expensive package does not eliminate every affordable completion.
            best = sorted(proposals, key=key)[: width // 2 + width % 2]
            cheap = sorted(proposals, key=lambda s: (s[1], key(s)))[: width // 2]
            states[size] = list({s[0]: s for s in best + cheap}.values())
    size = max((n for n, options in states.items() if options), default=0)
    chosen, spent = min(states[size], key=key)
    selected = [(items[i][0], items[i][1]) for i in chosen]
    return selected, {
        "mode": "trigger_diversity_beam" if diversity else "linear_score_beam",
        "budget": budget,
        "spent": round(spent, 6),
        "target": count,
        "selected": [
            {
                "name": c["name"],
                "group": trigger_group(c),
                "score": s,
                "price": price(c),
            }
            for c, s in selected
        ],
        "candidates": len(items),
        "states_examined": examined,
        "width_per_count": width,
        "max_mana_value": max_mana_value,
        "objective": value(chosen),
        "scope": "Initial package heuristic; groups are not equivalent effects or guaranteed draw, and bounded beam search is not globally optimal.",
    }
