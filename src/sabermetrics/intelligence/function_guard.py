"""Conservative, proof-carrying draw substitutions over a completed baseline.

Function extraction explains losses; missing extraction never grants permission.
Only a deliberately narrow, fully consumed Oracle grammar permits replacement.
This is a local resource/role dominance policy, not an optimal-play theorem.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from copy import deepcopy

from sabermetrics.intelligence.draw_selection import audit, identity, price

VERSION = "function-preservation.v3"
_NUMBERS = {
    "a": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
}


def simple_draw(card):
    """Consume the entire Oracle/cost/type: no hidden effects or assumed defaults."""
    typ = card.get("type_line")
    if typ not in {"Instant", "Sorcery"}:
        return None
    text = card.get("oracle_text") or ""
    match = re.fullmatch(
        r"(?:You )?[Dd]raw (a|one|two|three|four|five|six|seven|\d+) cards?\.",
        text.strip(),
    )
    if not match:
        return None
    quantity = _NUMBERS.get(match[1], int(match[1]) if match[1].isdigit() else 0)
    cost = card.get("mana_cost") or ""
    tokens = re.findall(r"\{(\d+|[WUBRGC])\}", cost)
    if not tokens or "".join("{" + t + "}" for t in tokens) != cost:
        return None
    mv = card.get("cmc", card.get("mana_value"))
    if not isinstance(mv, (int, float)) or not math.isfinite(mv):
        return None
    total = sum(int(t) if t.isdigit() else 1 for t in tokens)
    if mv != total or not 1 <= quantity <= 20:
        return None
    return {
        "type": typ,
        "draw": quantity,
        "mana": total,
        "pips": dict(Counter(t for t in tokens if not t.isdigit())),
        "evidence": [text],
    }


def stable_id(card):
    # Same Oracle semantics across printings; a changed record must not masquerade
    # as an unchanged card, even if its upstream ID or name was reused.
    payload = {
        k: card.get(k)
        for k in ("oracle_id", "name", "oracle_text", "type_line", "mana_cost")
    }
    # Both missing and empty IDs encode unknown identity in the card model;
    # real IDs and all functional text remain distinct.
    payload["oracle_id"] = card.get("oracle_id") or ""
    payload["color_identity"] = (
        sorted(identity(card)) if identity(card) is not None else None
    )
    mv = card.get("cmc", card.get("mana_value"))
    payload["mana_value"] = float(mv) if isinstance(mv, (int, float)) else None
    payload["power"] = str(card["power"]) if card.get("power") is not None else None
    payload["toughness"] = (
        str(card["toughness"]) if card.get("toughness") is not None else None
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def function_record(card):
    from sabermetrics.intelligence.card_functions import function_profile

    facts = function_profile(card)
    complete = simple_draw(card) is not None
    from sabermetrics.intelligence.commander_substitutions import (
        extended_profile,
        function_facts,
    )

    extended = extended_profile(card)
    if extended is not None:
        return {
            "id": stable_id(card),
            "name": card["name"],
            "functions": function_facts(extended),
            "coverage_complete": True,
        }
    # Pure draw is handled by the substitution proof. All other recognized
    # functions remain protected evidence; their absence means incomplete coverage.
    functions = (
        []
        if complete
        else [
            {
                "key": f["kind"],
                "scope": json.dumps(
                    [f.get("detail", "unspecified"), sorted(f.get("prerequisites", []))]
                ),
                "confidence": f.get("confidence", "supported"),
                "evidence": f.get("evidence", []),
            }
            for f in facts.get("functions", [])
        ]
    )
    return {
        "id": stable_id(card),
        "name": card["name"],
        "functions": functions,
        "coverage_complete": complete,
    }


def substitution_proof(
    outgoing, incoming, protected=(), commander=None, support_cards=()
):
    result = {
        "outgoing": outgoing["name"],
        "incoming": incoming["name"],
        "allowed": False,
        "reason": "Incomplete substitution coverage.",
    }
    if outgoing["name"] in protected:
        return {**result, "reason": "Explicitly protected commander or engine card."}
    old, new = simple_draw(outgoing), simple_draw(incoming)
    if old is None or new is None:
        from sabermetrics.intelligence.commander_substitutions import extended_proof

        return extended_proof(outgoing, incoming, protected, commander, support_cards)
    if identity(outgoing) is None or identity(incoming) != identity(outgoing):
        return {**result, "reason": "Spell color identity must be preserved."}
    from sabermetrics.intelligence.commander_substitutions import commander_preservation

    contracts = commander_preservation(outgoing, incoming, commander)
    if not contracts["allowed"]:
        return {
            **result,
            "reason": "Commander contribution decreases.",
            "commander": contracts,
        }
    commander_text = (commander or {}).get("oracle_text") or ""
    cost_sensitive = re.search(
        r"mana value|converted mana cost|mana cost|cascade|discover|devotion|"
        r"\bodd\b|\beven\b|mana spent|mana you spent|spend[^.\n]*mana|"
        r"spent[^.\n]*cast|cost[^.\n]*cast",
        commander_text,
        re.IGNORECASE,
    )
    if cost_sensitive and (old["mana"] != new["mana"] or old["pips"] != new["pips"]):
        return {
            **result,
            "reason": "Commander casting-cost sensitivity is not modeled; preserve exact mana demands.",
        }
    if old["type"] != new["type"]:
        return {**result, "reason": "Spell timing/type is not preserved."}
    if new["mana"] > old["mana"] or any(
        count > old["pips"].get(color, 0) for color, count in new["pips"].items()
    ):
        return {
            **result,
            "reason": "Casting resources increase or change color demand.",
        }
    if new["draw"] < old["draw"]:
        return {**result, "reason": "Immediate card advantage decreases."}
    strict = (
        new["draw"] > old["draw"]
        or new["mana"] < old["mana"]
        or sum(new["pips"].values()) < sum(old["pips"].values())
    )
    if not strict:
        return {**result, "reason": "No strict functional/resource improvement."}
    return {
        **result,
        "allowed": True,
        "reason": "Complete simple-draw coverage; same timing, no greater casting demand, no less draw, strict resource or draw gain.",
        "before": old,
        "after": new,
        "commander": contracts,
    }


def _hard_errors(cards, commander, budget, count):
    errors = []
    if len(cards) != count:
        errors.append("card_count")
    colors = identity(commander)
    if colors is None:
        errors.append("commander_identity_unknown")
    for c in cards:
        from sabermetrics.intelligence.eligibility import main_deck_eligible

        if not main_deck_eligible(c):
            errors.append("card_type_eligibility:" + c["name"])
        ci = identity(c)
        if ci is None or colors is None or not ci <= colors:
            errors.append("identity:" + c["name"])
        if not c.get("is_legal_in_99", True) or c["name"] == commander.get("name"):
            errors.append("legality:" + c["name"])
    if any(price(c) is None for c in cards):
        errors.append("price_unknown")
    elif sum(price(c) for c in cards) > budget + 1e-6:
        errors.append("budget")
    counts = Counter(c["name"] for c in cards)
    for name, number in counts.items():
        card = next(c for c in cards if c["name"] == name)
        # Existing special singleton exemptions are handled by the baseline
        # legality engine. New draw candidates can never use these exemptions.
        if number > 1 and "Basic" not in (card.get("type_line") or "").split():
            errors.append("singleton:" + name)
    return sorted(set(errors))


def validate_transition(before, after, commander, budget, protected=()):
    """Whole-deck guard, including changes outside a declared swap receipt."""
    from sabermetrics.intelligence.function_receipt import compare_functions

    records_before = [function_record(c) for c in before]
    records_after = [function_record(c) for c in after]
    receipt = compare_functions(
        records_before,
        records_after,
        protected_ids={stable_id(c) for c in before if c["name"] in protected},
    )
    old_counts, new_counts = Counter(map(stable_id, before)), Counter(
        map(stable_id, after)
    )
    old_map = {stable_id(c): c for c in before}
    new_map = {stable_id(c): c for c in after}
    removed = [
        old_map[k] for k, n in (old_counts - new_counts).items() for _ in range(n)
    ]
    added = [new_map[k] for k, n in (new_counts - old_counts).items() for _ in range(n)]
    # Bipartite matching avoids greedy assignment accidentally rejecting a valid
    # package, or letting one strong incoming card justify several outgoing cards.
    edges = {
        i: [
            j
            for j, c in enumerate(added)
            if substitution_proof(old, c, protected, commander, before)["allowed"]
        ]
        for i, old in enumerate(removed)
    }
    matched = {}

    def augment(i, visited):
        for j in edges[i]:
            if j in visited:
                continue
            visited.add(j)
            if j not in matched or augment(matched[j], visited):
                matched[j] = i
                return True
        return False

    all_proved = len(removed) == len(added) and all(augment(i, set()) for i in edges)
    proofs = [
        substitution_proof(removed[i], added[j], protected, commander, before)
        for j, i in sorted(matched.items())
    ]
    errors = _hard_errors(after, commander, budget, len(before))
    reasons = list(errors)
    if receipt["lost_functions"]:
        reasons.append("supported_function_loss")
    if receipt["protected_removed"]:
        reasons.append("protected_card_removed")
    if receipt["unknown_removals"]:
        reasons.append("unknown_removed_functionality")
    if not all_proved:
        reasons.append("missing_one_to_one_substitution_proof")
    from sabermetrics.intelligence.deck_context import validate_deck_context

    deck_context = validate_deck_context(before, after, commander)
    if not deck_context["allowed"]:
        reasons.append("deck_support_loss_or_unmodeled_dependency")
    allowed = not reasons
    changed = bool(removed or added)
    return {
        "version": VERSION,
        "allowed": allowed,
        "changed": changed,
        "improved": allowed and changed,
        "status": "rejected" if not allowed else "improved" if changed else "unchanged",
        "reasons": reasons,
        "functions": receipt,
        "proofs": proofs,
        "deck_context": deck_context,
        "scope": "complete effect-family substitutions and detected commander contracts; baseline quality not certified",
    }


def guarded_repair(cards, candidates, commander, budget, power=3, protected=()):
    """Search only proved substitutions; revalidate the final transaction."""
    baseline = deepcopy(cards)
    deck = deepcopy(cards)
    proofs = []
    colors = identity(commander)
    if colors is None or _hard_errors(deck, commander, budget, len(deck)):
        return baseline, {
            "status": "unresolved",
            "mode": "function_guard",
            "reason": "Baseline hard constraints prevent safe repair.",
            "decisions": [],
            "baseline_cards": baseline,
            "guard": validate_transition(
                baseline, baseline, commander, budget, protected
            ),
        }
    from sabermetrics.intelligence.commander_substitutions import extended_profile
    from sabermetrics.intelligence.eligibility import main_deck_eligible

    def supported(card):
        return main_deck_eligible(card) and (
            simple_draw(card) is not None or extended_profile(card) is not None
        )

    catalog = sorted(
        [
            c
            for c in candidates
            if supported(c)
            and price(c) is not None
            and identity(c) is not None
            and identity(c) <= colors
            and c.get("is_legal_in_99", True)
            and c["name"] != commander.get("name")
        ],
        key=lambda c: c["name"],
    )
    for _ in range(10):
        names = {c["name"] for c in deck}
        spent = sum(price(c) for c in deck)
        options = []
        for i, old in enumerate(deck):
            if not supported(old):
                continue
            for new in catalog:
                if (
                    new["name"] in names
                    or spent - price(old) + price(new) > budget + 1e-6
                ):
                    continue
                proof = substitution_proof(old, new, protected, commander, baseline)
                if not proof["allowed"]:
                    continue
                from sabermetrics.intelligence.deck_context import validate_deck_context

                trial = list(deck)
                trial[i] = new
                if not validate_deck_context(deck, trial, commander)["allowed"]:
                    continue
                a, b = proof["before"], proof["after"]
                options.append(
                    (
                        -proof.get("effect_gain", b.get("draw", 0) - a.get("draw", 0)),
                        b["mana"] - a["mana"],
                        price(new),
                        new["name"],
                        old["name"],
                        i,
                        new,
                        proof,
                    )
                )
        if not options:
            break
        *_, index, incoming, proof = min(options, key=lambda o: o[:5])
        incoming = deepcopy(incoming)
        for key in list(incoming):
            if key.startswith(("_fit_", "_llm_fit")):
                incoming.pop(key)
        incoming["_draw_selection_reason"] = proof["reason"]
        deck[index] = incoming
        proofs.append(proof)
    gate = validate_transition(baseline, deck, commander, budget, protected)
    if not gate["allowed"]:
        deck = baseline
    final = audit(deck, commander, power)
    target = {1: 6, 2: 7, 3: 8, 4: 9, 5: 10}[power]
    return deck, {
        "mode": "function_guard",
        "status": (
            "met"
            if final["credible"] >= target and final["independent"] >= min(4, target)
            else "unresolved"
        ),
        "target": target,
        "independent_target": min(4, target),
        "guard": gate,
        "decisions": proofs,
        "final": final,
        "baseline_cards": baseline,
        "reason": (
            "Only proved draw substitutions applied."
            if gate["allowed"]
            else "Rejected transaction; baseline retained."
        ),
    }
