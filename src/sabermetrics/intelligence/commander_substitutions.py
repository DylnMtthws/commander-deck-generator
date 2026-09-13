"""Complete local effect proofs constrained by printed commander contracts.

No popularity, free-form LLM rating or unparsed clause can authorize a cut.
"""

import re
from collections import Counter

from sabermetrics.intelligence.commander_contracts import contribution
from sabermetrics.intelligence.draw_selection import identity


def fixed_cost(card):
    value = card.get("mana_cost") or ""
    parts = re.findall(r"\{(\d+|[WUBRGC])\}", value)
    if not parts or "".join("{" + p + "}" for p in parts) != value:
        return None
    mana = sum(int(p) if p.isdigit() else 1 for p in parts)
    if card.get("cmc", card.get("mana_value")) != mana:
        return None
    return {"mana": mana, "pips": dict(Counter(p for p in parts if not p.isdigit()))}


def extended_profile(card):
    """Full text consumption for each admitted family, including optional riders."""
    cost = fixed_cost(card)
    if cost is None:
        return None
    typ = card.get("type_line") or ""
    if "Creature" in typ:
        if card.get("power") is None or card.get("toughness") is None:
            return None
        from sabermetrics.intelligence.creature_resources import creature_resources

        body = creature_resources(card)
        if body is None:
            return None
        return {
            "family": "creature",
            "type": typ,
            **cost,
            "body": body,
            "evidence": body["evidence"],
        }
    if typ not in {"Instant", "Sorcery"}:
        return None
    text = (card.get("oracle_text") or "").strip()
    name = card.get("name") or ""
    normalized = text.replace(name, "This spell") if name else text
    base = {"type": typ, **cost, "evidence": [text]}
    # An option to sacrifice an artifact is not mandatory and cannot erase the
    # original discard route. No presumed artifacts are needed for old-route use.
    match = re.fullmatch(
        r"As an additional cost to cast this spell, (discard a card|sacrifice an artifact or discard a card)\.\s*Draw (two|three) cards\.",
        text,
    )
    if match:
        choices = ["discard:1"]
        if match[1].startswith("sacrifice"):
            choices.append("sacrifice:artifact:1")
        return {
            **base,
            "family": "additional_draw",
            "draw": {"two": 2, "three": 3}[match[2]],
            "options": choices,
        }
    # Explicitly verify optional kicker reminder rather than stripping arbitrary
    # parenthesized text that might hide a restriction.
    kicker = None
    match = re.match(
        r"Kicker \{(\d+)\} \(You may pay an additional \{(\d+)\} as you cast this spell\.\)\s*",
        normalized,
    )
    if match:
        if match[1] != match[2]:
            return None
        kicker = int(match[1])
        normalized = normalized[match.end() :]
    match = re.fullmatch(
        r"This spell deals (\d+) damage to (any target|target creature)\.(.*)",
        normalized,
        re.DOTALL,
    )
    if not match or not 1 <= int(match[1]) <= 20:
        return None
    tail = match[3].strip()
    result = {
        **base,
        "family": "damage",
        "damage": int(match[1]),
        "target": match[2],
        "kicker": None,
        "player_scry": False,
    }
    if kicker is not None:
        extra = re.fullmatch(
            r"If this spell was kicked, it deals (\d+) damage instead\.", tail
        )
        if not extra or not result["damage"] < int(extra[1]) <= 20:
            return None
        result["kicker"] = {"cost": kicker, "damage": int(extra[1])}
    elif tail:
        if (
            tail
            != "If a player is dealt damage this way, scry 1. (Look at the top card of your library. You may put that card on the bottom.)"
        ):
            return None
        result["player_scry"] = True
    return result


def commander_preservation(old, new, commander):
    before = contribution(old, commander or {})
    after = contribution(new, commander or {})
    new_values = {(r["kind"], r["scope"]): r["value"] for r in after["contributions"]}
    losses = []
    for row in before["contributions"]:
        value = row["value"]
        changed = new_values.get((row["kind"], row["scope"]))
        # Partial positive evidence still protects a potential support piece.
        # This does not claim its activation threshold is met on the battlefield.
        if (
            isinstance(value, (int, float))
            and value > 0
            and (not isinstance(changed, (int, float)) or changed < value)
        ):
            losses.append(
                {
                    "kind": row["kind"],
                    "scope": row["scope"],
                    "before": value,
                    "after": changed,
                }
            )
    return {
        "allowed": not losses,
        "losses": losses,
        "before": before,
        "after": after,
        "scope": "detected printed contributions only; all card-effect proofs still required",
    }


def function_facts(profile):
    family = profile["family"]
    if family == "damage":
        scopes = [("damage", profile["target"])]
        if profile["player_scry"]:
            scopes.append(("selection", "damage_player_scry_1"))
        if profile["kicker"]:
            scopes.append(("optional_cost", "kicker"))
    elif family == "additional_draw":
        scopes = [("card_flow", "additional_draw:" + o) for o in profile["options"]]
    else:
        scopes = [("creature", "body")]
    return [
        {
            "key": kind,
            "scope": scope,
            "confidence": "supported",
            "evidence": [e for e in profile["evidence"] if e]
            or ["Printed creature type and resource metadata"],
        }
        for kind, scope in scopes
    ]


def extended_proof(old, new, protected=(), commander=None, support_cards=()):
    result = {
        "outgoing": old["name"],
        "incoming": new["name"],
        "allowed": False,
        "reason": "Incomplete extended substitution coverage.",
    }
    if old["name"] in protected:
        return {**result, "reason": "Explicitly protected commander or engine card."}
    a, b = extended_profile(old), extended_profile(new)
    if a is None or b is None or a["family"] != b["family"]:
        return result
    if identity(old) is None or identity(new) != identity(old):
        return {**result, "reason": "Spell color identity changes."}
    # Creature type details are checked below; instants never turn into sorceries.
    if a["family"] != "creature" and a["type"] != b["type"]:
        return {**result, "reason": "Casting category/timing changes."}
    if b["mana"] > a["mana"] or any(
        n > a["pips"].get(c, 0) for c, n in b["pips"].items()
    ):
        return {**result, "reason": "Casting demand increases."}
    text = (commander or {}).get("oracle_text") or ""
    if re.search(
        r"mana value|converted mana cost|mana cost|cascade|discover|devotion|\bodd\b|\beven\b|mana spent|mana you spent|spend[^.\n]*mana|spent[^.\n]*cast|cost[^.\n]*cast",
        text,
        re.IGNORECASE,
    ) and (a["mana"] != b["mana"] or a["pips"] != b["pips"]):
        return {**result, "reason": "Unmodeled commander cost sensitivity."}
    contracts = commander_preservation(old, new, commander)
    if not contracts["allowed"]:
        return {
            **result,
            "reason": "Commander contribution decreases.",
            "commander": contracts,
        }
    strict = b["mana"] < a["mana"] or sum(b["pips"].values()) < sum(a["pips"].values())
    gain = int(strict)
    if a["family"] == "damage":
        if (
            a["target"] != b["target"]
            or b["damage"] < a["damage"]
            or (a["player_scry"] and not b["player_scry"])
        ):
            return {
                **result,
                "reason": "Damage target/effect or selection option lost.",
            }
        if a["kicker"] and (
            not b["kicker"]
            or b["kicker"]["cost"] > a["kicker"]["cost"]
            or b["kicker"]["damage"] < a["kicker"]["damage"]
        ):
            return {**result, "reason": "Optional kicked mode lost or weakened."}
        gain += b["damage"] - a["damage"]
        strict |= bool(
            gain or b["player_scry"] != a["player_scry"] or b["kicker"] != a["kicker"]
        )
    elif a["family"] == "additional_draw":
        if b["draw"] < a["draw"] or not set(a["options"]) <= set(b["options"]):
            return {**result, "reason": "Existing draw/payment option lost."}
        gain += b["draw"] - a["draw"]
        strict |= bool(gain or set(b["options"]) - set(a["options"]))
    else:
        x, y = a["body"], b["body"]
        support_text = (
            text + "\n" + "\n".join(c.get("oracle_text") or "" for c in support_cards)
        )
        if re.search(r"\b(?:power|toughness)\b", support_text, re.IGNORECASE) and (
            x["power"] != y["power"] or x["toughness"] != y["toughness"]
        ):
            return {
                **result,
                "reason": "Commander/deck power or toughness sensitivity requires exact printed stats.",
            }
        if (
            x["types"] != y["types"]
            or x["supertypes"] != y["supertypes"]
            or not set(x["subtypes"]) <= set(y["subtypes"])
        ):
            return {
                **result,
                "reason": "Creature types or tribal support lost/changed.",
            }
        if (
            y["power"] < x["power"]
            or y["toughness"] < x["toughness"]
            or not set(x["keywords"]) <= set(y["keywords"])
        ):
            return {**result, "reason": "Creature body or keyword function decreases."}
        if (set(y["keywords"]) - set(x["keywords"])) & {"defender", "shroud"}:
            return {**result, "reason": "Additional restrictive keyword."}
        strict |= bool(
            y["power"] > x["power"]
            or y["toughness"] > x["toughness"]
            or set(y["keywords"]) - set(x["keywords"])
            or set(y["subtypes"]) - set(x["subtypes"])
        )
    if not strict:
        return {**result, "reason": "No strict supported improvement."}
    return {
        **result,
        "allowed": True,
        "reason": "Complete effect family preserves old options, resources and detected commander contributions.",
        "family": a["family"],
        "before": a,
        "after": b,
        "commander": contracts,
        "effect_gain": gain,
    }
