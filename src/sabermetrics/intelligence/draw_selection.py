"""Contextual draw-package selection with explicit unsupported coverage.

Scenario utility is a transparent search heuristic, not expected wins. It never
turns unsupported text or opponent behaviour into guaranteed card advantage.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from copy import deepcopy
from functools import lru_cache

VERSION = "draw-selection.v1"


def price(card):
    value = card.get("price_usd", card.get("current_price_usd"))
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def identity(card):
    value = card.get("color_identity")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return set(value) if isinstance(value, (list, set, tuple)) else None


def roles(card):
    from sabermetrics.intelligence.selection import roles as read_roles

    return set(read_roles(card))


@lru_cache(maxsize=40000)
def _profile(text, typ, mv, cost):
    from sabermetrics.intelligence.draw_facts import draw_profile

    return draw_profile(
        {"oracle_text": text, "type_line": typ, "cmc": mv, "mana_cost": cost}
    )


def profile(card):
    return _profile(
        card.get("oracle_text") or "",
        card.get("type_line") or "",
        card.get("cmc", card.get("mana_value")),
        card.get("mana_cost") or "",
    )


def context(cards, commander):
    spells = [
        c
        for c in cards
        if "land" not in (c.get("type_line") or "").lower().split("//")[0]
    ]
    creatures = [c for c in spells if "creature" in (c.get("type_line") or "").lower()]
    token_text = "\n".join(
        c.get("oracle_text") or "" for c in spells + [commander]
    ).lower()
    token_sources = {
        c.get("name")
        for c in spells + [commander]
        if re.search(r"create[^.\n]*tokens?", (c.get("oracle_text") or "").lower())
    }
    creature_token_sources = {
        c.get("name")
        for c in spells + [commander]
        if re.search(
            r"create[^.\n]*creature tokens?", (c.get("oracle_text") or "").lower()
        )
    }
    return {
        "token_sources": token_sources,
        "creature_token_sources": creature_token_sources,
        "land_names": Counter(
            c.get("name") for c in cards if "land" in (c.get("type_line") or "").lower()
        ),
        "types": Counter(
            t
            for c in spells
            for t in re.findall(r"[a-z]+", (c.get("type_line") or "").lower())
        ),
        "color_count": len(identity(commander) or []),
        "creatures": len(creatures),
        "cheap_creatures": sum(
            float(c.get("cmc", c.get("mana_value", 99)) or 0) <= 3 for c in creatures
        ),
        "noncreatures": len(spells) - len(creatures),
        "tokens": bool(re.search(r"create[^.\n]*creature tokens?", token_text)),
        "sacrifice_outlets": sum(
            bool(
                re.search(
                    r"sacrifice (?:a|another) creature",
                    (c.get("oracle_text") or "").lower(),
                )
            )
            for c in spells
        ),
    }


def evaluate(card, ctx, power=3):
    """Conservative three-opportunity scenario. Unsupported gates earn no credit."""
    p = profile(card)
    row = {
        "card": card.get("name"),
        "status": "unknown",
        "credible": False,
        "independent": False,
        "utility": 0.0,
        "reason": "Unsupported draw effect.",
        "profile": p,
    }
    if p.get("status") != "supported" or p.get("confidence") == "partial":
        row["status"] = p.get("status", "unknown")
        return row
    prereqs = p.get("prerequisites", [])
    if "condition:created_token_this_turn" in prereqs and not (
        ctx["token_sources"] - {card.get("name")}
    ):
        row["reason"] = "Token-creation activation prerequisite lacks deck support."
        return row
    if (
        "condition:three_lands_same_name" in prereqs
        and max(ctx["land_names"].values(), default=0) < 10
    ):
        row["reason"] = "Same-name-land activation lacks a substantial basic-land base."
        return row
    for requirement in prereqs:
        if requirement.startswith("typal:"):
            typ = requirement.split(":", 1)[1]
            if typ == "creature":
                count = ctx["creatures"]
            elif typ == "noncreature":
                count = ctx["noncreatures"]
            else:
                count = ctx["types"].get(typ, 0)
            if count < (24 if typ == "creature" else 18):
                row["reason"] = (
                    f"Draw trigger lacks sufficient {typ} cards in this deck."
                )
                return row
    text = (card.get("oracle_text") or "").lower()
    typ = (card.get("type_line") or "").lower()
    if "transform" in text or "class" in typ:
        row["reason"] = (
            "Draw availability across transformed faces/levels is not modeled."
        )
        return row
    if "land" in typ.split("//")[0]:
        row["reason"] = "Land draw abilities do not replace spell draw slots."
        return row
    mv = p.get("mana_value")
    if mv is None:
        return row
    net = p.get("net_cards")
    mechanism = p.get("mechanism")
    # Context prerequisites are checked from supported printed clauses, never tags.
    creature_cast = "cast a creature spell" in text
    creature_etb = bool(re.search(r"(?:nontoken )?creature[^.\n]*enters", text))
    combat = "combat damage" in text
    death = bool(
        re.search(r"(?:creatures? die|creature dies|equipped creature dies)", text)
    )
    death = (
        death
        or "trigger:creature_dies" in prereqs
        or "trigger:equipped_creature_dies" in prereqs
    )
    sacrifice = bool(re.search(r"sacrifice (?:a|another) creature", text))
    if (creature_cast or creature_etb) and ctx["creatures"] < 24:
        row["reason"] = (
            "Creature draw requires a substantial creature-spell base (24 in this policy)."
        )
        return row
    if combat and ctx["cheap_creatures"] < 16:
        row["reason"] = (
            "Combat draw lacks supported attacker density; connection is not guaranteed."
        )
        return row
    if (death or sacrifice) and not (
        (ctx["creature_token_sources"] - {card.get("name")})
        or (ctx["creatures"] >= 24 and ctx["sacrifice_outlets"] >= 2)
    ):
        row["reason"] = (
            "Death/sacrifice draw lacks supported expendable creatures or sacrifice infrastructure."
        )
        return row
    # Narrow printed templates define scenario credit. Complex partial profiles
    # remain visible without borrowing a generic draw tag as evidence.
    if mechanism == "immediate":
        # Full effect coverage for simple draw spells. A recognized draw clause
        # cannot hide a restricted counterspell target, skipped turn, sacrifice,
        # or benefits to opponents elsewhere in the same spell.
        remaining = re.sub(r"\([^)]*\)", "", text)
        remaining = re.sub(
            r"(?:target player |you )?draws? (?:a|one|two|three|four|five|six|seven|\d+) cards?",
            "",
            remaining,
        )
        remaining = re.sub(
            r"(?:you |that player )?loses? (?:\d+|half your) life", "", remaining
        )
        remaining = re.sub(r"scry \d+", "", remaining)
        remaining = re.sub(r"\b(?:and|then)\b|[.,;\s]", "", remaining)
        if remaining:
            row["reason"] = (
                "Draw spell has additional effects/prerequisites outside the verified simple-draw contract."
            )
            return row
    if mechanism == "immediate":
        if net is None or net <= 0:
            row.update(
                status="filtering", reason="No verified net card advantage on casting."
            )
            return row
        gain = float(net)
        mana = float(mv)
        independent = not sacrifice
    elif mechanism == "recurring_self":
        if net is None or net <= 0:
            return row
        gain = max(0, 3 * float(net) - 1)
        mana = float(mv)
        independent = not combat
    elif mechanism == "recurring_opponent":
        if net is None or net <= 0:
            return row
        events = 3 if "trigger:opponent_casts_spell" in prereqs else 2
        gain = max(0, events * float(net) - 1)
        mana = float(mv)
        independent = False
    elif mechanism == "activated":
        activation = p.get("activation_mana")
        if activation is None:
            return row
        if "charge counter" in text and "for each charge counter" in text:
            gain = 5.0  # three activations draw1+2+3, less the card invested
        elif net is not None and net > 0:
            gain = 3 * float(net) - 1
        else:
            return row
        mana = float(mv) + 3 * float(activation)
        independent = not (sacrifice or combat or death)
    elif mechanism == "conditional" and "excludes:first_draw_step_card" in p.get(
        "prerequisites", []
    ):
        gain = 1.0
        mana = float(mv)
        independent = False
    elif mechanism == "conditional" and (
        creature_cast or creature_etb or combat or death
    ):
        if net is None or net <= 0:
            return row
        gain = 3 * float(net) - 1
        mana = float(mv) + (3 if "equip {1}" in text else 0)
        independent = not combat
    else:
        return row
    if gain <= 0:
        return row
    equip_cost = 0
    equip = re.search(r"\bequip ((?:\{[^}]+\})+)", text)
    if equip and mechanism == "recurring_self":
        from sabermetrics.intelligence.draw_facts import _mana_symbols_value

        equip_cost, exact = _mana_symbols_value(equip.group(1))
        if not exact:
            row["reason"] = "Equipment activation cost is unsupported."
            return row
        mana += 3 * equip_cost
    activation = float(p.get("activation_mana") or 0)
    first_access = float(mv) + activation + equip_cost
    if first_access > (3 if power == 5 else 4 if power == 4 else 5) or activation > 2:
        row["reason"] = "Draw setup/activation exceeds the supported tempo policy."
        return row
    if (
        power >= 4
        and mechanism == "activated"
        and "creature" in typ
        and "haste" not in text
    ):
        row["reason"] = (
            "Tap-creature draw is too delayed for this high-power selection policy."
        )
        return row
    if power == 5 and mechanism == "immediate" and float(mv) > 2:
        row["reason"] = (
            "Generic one-shot draw above two mana is not admitted as a highest-power upgrade."
        )
        return row
    if power == 5 and "trigger:your_upkeep" in prereqs:
        row["reason"] = "Delayed upkeep draw is not admitted as a high-power upgrade."
        return row
    # Higher-power builds need earlier access; this is a policy, not bracket proof.
    if power >= 4 and float(mv) > 4:
        row["reason"] = "Draw setup exceeds this high-power policy's four-mana limit."
        return row
    # Life is an explicit resource, not a free payment. The half-life scenario
    # starts at40; this is a conservative burden penalty, not a win estimate.
    life = 20 if "lose half your life" in text else 0
    loss = re.search(r"(?:you |player )?loses? (\d+) life", text)
    if loss:
        life = int(loss.group(1)) * (3 if mechanism == "recurring_self" else 1)
    mana += life / 5
    if ctx["color_count"] > 1:
        symbols = Counter(
            re.findall(r"\{([wubrg])\}", (card.get("mana_cost") or "").lower())
        )
        mana += 0.5 * max(0, max(symbols.values(), default=0) - 1)
    efficiency = gain / max(1.0, mana)
    utility = (
        efficiency
        + (0.35 if independent else 0)
        + (0.25 if mechanism != "immediate" else 0)
    )
    row.update(
        status="supported",
        credible=True,
        independent=independent,
        utility=round(utility, 6),
        reason=f"Supported {mechanism}; scenario gain {gain:g}, resource-cost score {mana:g}. "
        + (
            "Deck prerequisites met; not a gameplay guarantee."
            if independent
            else "Opponent/combat dependent; not reliable alone."
        ),
    )
    return row


def audit(cards, commander, power=3):
    ctx = context(cards, commander)
    rows = [evaluate(c, ctx, power) for c in cards]
    return {
        "version": VERSION,
        "scope": "supported draw mechanics; other card roles not certified",
        "credible": sum(r["credible"] for r in rows),
        "independent": sum(r["credible"] and r["independent"] for r in rows),
        "cards": rows,
    }


def repair(
    cards,
    candidates,
    commander,
    budget,
    power=3,
    protected=(),
    role_floors=None,
    type_floors=None,
):
    """Bounded swaps against whole-deck budget, preserving existing role floors.

    Output is independent of input candidate order. Source dicts are never mutated.
    """
    deck = deepcopy(cards)
    before = audit(deck, commander, power)
    decisions = []
    target = {1: 6, 2: 7, 3: 8, 4: 9, 5: 10}[power]
    protected = set(protected)
    colors = identity(commander)
    if colors is None or any(price(c) is None for c in deck):
        return deck, {
            "status": "unresolved",
            "reason": "Missing identity or prices",
            "before": before,
            "after": before,
            "decisions": [],
        }
    floors = role_floors or {}
    type_floors = type_floors or {}
    initial_roles = Counter(r for c in deck for r in roles(c))
    initial_types = {
        t: sum(t.casefold() in (c.get("type_line") or "").casefold() for c in deck)
        for t in type_floors
    }
    catalog = [
        c
        for c in candidates
        if price(c) is not None
        and identity(c) is not None
        and identity(c) <= colors
        and c.get("name") != commander.get("name")
        and c.get("is_legal_in_99", True)
    ]
    for _ in range(10):
        state = audit(deck, commander, power)
        if state["credible"] >= target and state["independent"] >= min(4, target):
            break
        names = {c["name"] for c in deck}
        spent = sum(price(c) for c in deck)
        options = []
        ctx = context(deck, commander)
        ranked = [
            (evaluate(c, ctx, power), c) for c in catalog if c["name"] not in names
        ]
        ranked = sorted(
            [(r, c) for r, c in ranked if r["credible"]],
            key=lambda item: (
                -item[0]["utility"] + 0.02 * price(item[1]),
                price(item[1]),
                item[1]["name"],
            ),
        )[:48]
        for result, incoming in ranked:
            if incoming["name"] in names:
                continue
            if not result["credible"]:
                continue
            # Avoid filling every draw slot with a conditional opponent engine.
            if state["independent"] < min(4, target) and not result["independent"]:
                continue
            for i, outgoing in enumerate(deck):
                if (
                    outgoing["name"] in protected
                    or "land"
                    in (outgoing.get("type_line") or "").lower().split("//")[0]
                ):
                    continue
                if state["cards"][i]["credible"]:
                    continue
                if float(outgoing.get("_selection_inclusion") or 0) >= 0.10:
                    continue
                # Keep unmodeled infrastructure/engine text rather than convert
                # uncertainty into permission to dismantle commander support.
                outgoing_text = (outgoing.get("oracle_text") or "").lower()
                if re.search(
                    r"create[^.\n]*tokens?|creatures you control have haste|copy target|flashback",
                    outgoing_text,
                ):
                    continue
                if spent - price(outgoing) + price(incoming) > budget + 1e-6:
                    continue
                # Preserve established ramp/interaction/engine functions. Unknown
                # draw-only and utility slots are preferred, not arbitrary cuts.
                if not roles(outgoing) or not roles(outgoing) <= {"draw", "utility"}:
                    continue
                lost = roles(outgoing) - roles(incoming) - {"draw", "utility"}
                if lost & {
                    "ramp",
                    "removal",
                    "board_wipe",
                    "protection",
                    "wincon",
                    "tutor",
                    "recursion",
                }:
                    continue
                trial = deck[:i] + [incoming] + deck[i + 1 :]
                counts = Counter(r for c in trial for r in roles(c))
                if any(
                    counts[r] < min(n, initial_roles[r])
                    for r, n in floors.items()
                    if r != "draw"
                ):
                    continue
                if any(
                    sum(
                        t.casefold() in (c.get("type_line") or "").casefold()
                        for c in trial
                    )
                    < min(n, initial_types[t])
                    for t, n in type_floors.items()
                ):
                    continue
                after = audit(trial, commander, power)
                if (
                    after["credible"] <= state["credible"]
                    or after["independent"] < state["independent"]
                ):
                    continue
                # Utility drives choice, known price breaks ties; low empirical
                # support only prioritizes outgoing cuts, never validates a card.
                score = result["utility"] - 0.2 * price(incoming) / max(1, budget)
                cut_support = float(outgoing.get("_selection_inclusion") or 0)
                options.append(
                    (
                        -score,
                        cut_support,
                        price(incoming),
                        incoming["name"],
                        outgoing["name"],
                        i,
                        incoming,
                        result,
                    )
                )
        if not options:
            break
        best = min(options, key=lambda x: x[:5])
        i, incoming, result = best[5:]
        outgoing = deck[i]
        alternative_names = list(
            dict.fromkeys(x[3] for x in sorted(options, key=lambda x: x[:5]))
        )[:5]
        decisions.append(
            {
                "card": outgoing["name"],
                "action": "replace",
                "reason": "Unverified draw/utility slot replaced: " + result["reason"],
                "alternatives": alternative_names,
                "selected": incoming["name"],
            }
        )
        incoming = deepcopy(incoming)
        incoming["_draw_selection_reason"] = result["reason"]
        # A previous model fit on a different context cannot certify this swap.
        for key in list(incoming):
            if key.startswith(("_fit_", "_llm_fit")):
                incoming.pop(key)
        deck[i] = incoming
    after = audit(deck, commander, power)
    from sabermetrics.intelligence.selection_receipt import build_receipt

    change_receipt = build_receipt(cards, deck, decisions)
    return deck, {
        "changes": change_receipt,
        "status": (
            "met"
            if after["credible"] >= target and after["independent"] >= min(4, target)
            else "unresolved"
        ),
        "target": target,
        "independent_target": min(4, target),
        "before": before,
        "after": after,
        "decisions": decisions,
    }


def select_package(candidates, placed, commander, budget, count, power=3):
    """Reserve verified draw before discretionary spending, within its own cap.

    Supports only prerequisites demonstrable from already placed cards/commander.
    Future creature density is not invented to admit a conditional engine early.
    """
    selected = []
    names = {c["name"] for c in placed}
    colors = identity(commander)
    ctx = context(placed, commander)
    ranked = []
    for c in candidates:
        cost = price(c)
        ci = identity(c)
        if (
            cost is None
            or ci is None
            or colors is None
            or not ci <= colors
            or c["name"] in names
            or c["name"] == commander.get("name")
            or not c.get("is_legal_in_99", True)
        ):
            continue
        result = evaluate(c, ctx, power)
        if result["credible"]:
            ranked.append(
                (
                    -result["utility"] + 0.2 * cost / max(1, budget),
                    cost,
                    c["name"],
                    c,
                    result,
                )
            )
    spent = 0
    for _, cost, name, card, result in sorted(ranked, key=lambda r: r[:3]):
        if name in names:
            continue
        if len(selected) >= count:
            break
        if spent + cost > budget + 1e-6:
            continue
        names.add(name)
        selected.append(deepcopy(card))
        selected[-1]["_draw_selection_reason"] = result["reason"]
        spent += cost
    return selected
