"""Assess parsed draw routes against tempo, support, and commander context.

`route_profile` and `commander_mana_support` are upstream helpers. This module
does not parse oracle text or implement commander mana; it only scores already
parsed routes. `supported` on a profile route means the clause was parsed, not
that the current board has been proven.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy

from .draw_acceleration import commander_mana_support
from .draw_routes import route_profile

AVAILABLE = "available"
CONDITIONAL = "conditional"
BLOCKED = "blocked"
UNVERIFIED = "unverified"

KNOWN_KINDS = frozenset(
    {
        "spell",
        "etb",
        "attack",
        "combat_damage",
        "activated",
        "channel",
        "triggered",
    }
)
SPELL_ETB_KINDS = frozenset({"spell", "etb"})
ACTIVATION_KINDS = frozenset({"activated", "channel"})
INHERENTLY_CONDITIONAL_KINDS = frozenset({"attack", "combat_damage", "triggered"})

KNOWN_PREREQUISITES = frozenset(
    {
        "island",
        "combat_damage",
        "attack",
        "creature_death",
        "sacrifice",
        "discard",
        "tap",
        "counters",
        "opponent_cast",
        "opponent_second_draw",
        "own_upkeep",
        "opponent_payment",
        "cumulative_upkeep",
        "life",
        "creature_etb",
        "once_per_turn",
        "unsupported",
    }
)
# Board/event assumptions that make a route conditional (never independent).
CONDITIONAL_PREREQUISITES = frozenset(
    {
        "combat_damage",
        "attack",
        "creature_death",
        "sacrifice",
        "discard",
        "tap",
        "counters",
        "opponent_cast",
        "opponent_second_draw",
        "own_upkeep",
        "opponent_payment",
        "cumulative_upkeep",
        "life",
        "creature_etb",
    }
)
# Restrictions that do not, by themselves, change availability.
BENIGN_PREREQUISITES = frozenset({"once_per_turn"})

_TYPE_LINE_SPLIT = re.compile(r"\s*[—–−-]+\s*")
_SUBTYPE_SPLIT = re.compile(r"[\s,/]+")

_OVERALL_RANK = {
    AVAILABLE: 0,
    CONDITIONAL: 1,
    UNVERIFIED: 2,
    BLOCKED: 3,
}


def assess_draw_routes(card, support_cards, commander, power=3):
    """Score draw routes for one card in the current commander/support context.

    Returns a dict with ``status`` (available|conditional|blocked|unverified),
    enriched ``routes``, ``reasons``, and ``independent``.
    """
    profile = _safe_profile(card)
    routes = list(profile.get("routes") or [])
    assessed = []
    for route in routes:
        assessed.append(
            _assess_one_route(
                card=card,
                support_cards=support_cards,
                commander=commander,
                power=power,
                route=route,
            )
        )

    status, reasons = _aggregate(profile, assessed)
    independent = any(_is_independent_spell(route) for route in assessed)
    return {
        "status": status,
        "routes": assessed,
        "reasons": reasons,
        "independent": independent,
    }


def _safe_profile(card):
    try:
        profile = route_profile(card)
    except (TypeError, ValueError, KeyError, AttributeError):
        return {
            "routes": [],
            "unknown_clauses": ["route_profile_error"],
            "complete": False,
        }
    if not isinstance(profile, dict):
        return {
            "routes": [],
            "unknown_clauses": ["malformed_profile"],
            "complete": False,
        }
    routes = profile.get("routes")
    if routes is None:
        routes = []
    if not isinstance(routes, list):
        return {
            "routes": [],
            "unknown_clauses": ["malformed_routes"],
            "complete": False,
        }
    unknown = profile.get("unknown_clauses")
    if unknown is None:
        unknown = []
    if not isinstance(unknown, list):
        unknown = ["malformed_unknown_clauses"]
    complete = profile.get("complete")
    if complete is None or not isinstance(complete, bool):
        complete = False
    return {
        "routes": routes,
        "unknown_clauses": unknown,
        "complete": complete,
    }


def _tempo_cap(power):
    if not _is_finite_nonnegative_number(power):
        return None
    if power <= 3:
        return 5
    if power <= 4:
        return 4
    return 3


def _is_finite_nonnegative_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value >= 0


def _is_positive_card_count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(value) or value <= 0:
        return False
    return not (isinstance(value, float) and not value.is_integer())


def _assess_one_route(card, support_cards, commander, power, route):
    if not isinstance(route, dict):
        return {
            "kind": None,
            "mana": None,
            "setup_mana": None,
            "cost": None,
            "draw_count": None,
            "net_cards": None,
            "repeatable": False,
            "prerequisites": [],
            "evidence": "",
            "supported": False,
            "status": UNVERIFIED,
            "reasons": ["malformed_route"],
            "gross_mana": None,
            "conditional_mana": None,
            "commander_support": None,
        }

    enriched = deepcopy(route)
    reasons = []
    parse_unknown = False
    context_blocked = False
    context_conditional = False

    kind = enriched.get("kind")
    if kind not in KNOWN_KINDS:
        parse_unknown = True
        reasons.append("unknown_route_kind")

    if enriched.get("supported") is not True:
        parse_unknown = True
        reasons.append("unparsed_route")

    mana = enriched.get("mana")
    setup_mana = enriched.get("setup_mana")
    gross_mana = mana if _is_finite_nonnegative_number(mana) else None
    setup_valid = _is_finite_nonnegative_number(setup_mana)
    if mana is None or not _is_finite_nonnegative_number(mana):
        parse_unknown = True
        reasons.append("unknown_mana_cost")
        gross_mana = None
    if not setup_valid:
        parse_unknown = True
        reasons.append("unknown_setup_mana")

    prereq_unknown, prereq_blocked, prereq_conditional, prereq_reasons = (
        _assess_prerequisites(enriched.get("prerequisites"), support_cards)
    )
    parse_unknown = parse_unknown or prereq_unknown
    context_blocked = context_blocked or prereq_blocked
    context_conditional = context_conditional or prereq_conditional
    reasons.extend(prereq_reasons)

    if not _is_positive_card_count(enriched.get("draw_count")):
        parse_unknown = True
        reasons.append("unknown_draw_count")

    if kind in INHERENTLY_CONDITIONAL_KINDS or kind == "activated":
        context_conditional = True
        reasons.append(f"requires_{kind}")

    cap = _tempo_cap(power)
    if cap is None:
        parse_unknown = True
        reasons.append("unknown_power")

    support = _commander_support_for_route(commander, card, kind)
    enriched_support = deepcopy(support) if isinstance(support, dict) else None

    overcap_exception = False
    if cap is not None and gross_mana is not None:
        total_mana = (
            gross_mana + setup_mana
            if kind in (ACTIVATION_KINDS | INHERENTLY_CONDITIONAL_KINDS) and setup_valid
            else gross_mana
        )
        gross_over = total_mana > cap
        if gross_over:
            if _commander_overcap_applies(kind, gross_mana, cap, support):
                overcap_exception = True
                context_conditional = True
                reasons.append("optimistic_commander_mana")
            else:
                context_blocked = True
                reasons.append("exceeds_tempo_cap")
                if (
                    isinstance(support, dict)
                    and support.get("status") == "state_dependent"
                ):
                    reasons.append("state_dependent_commander_mana")

    if parse_unknown:
        status = UNVERIFIED
    elif context_blocked:
        status = BLOCKED
    elif context_conditional:
        status = CONDITIONAL
    else:
        status = AVAILABLE

    conditional_mana = gross_mana - 1 if overcap_exception else None
    enriched["prerequisites"] = (
        list(enriched["prerequisites"])
        if isinstance(enriched.get("prerequisites"), list)
        else []
    )
    enriched["initial_total_mana"] = (
        gross_mana + setup_mana
        if kind in (ACTIVATION_KINDS | INHERENTLY_CONDITIONAL_KINDS)
        and gross_mana is not None
        and setup_valid
        else gross_mana
    )
    enriched["status"] = status
    enriched["reasons"] = _dedupe(reasons)
    enriched["gross_mana"] = gross_mana
    enriched["conditional_mana"] = conditional_mana
    enriched["commander_support"] = enriched_support
    return enriched


def _commander_support_for_route(commander, card, kind):
    route_kind = "cast" if kind in SPELL_ETB_KINDS else kind
    if route_kind is None:
        route_kind = "cast"
    try:
        result = commander_mana_support(commander, card, route_kind=route_kind)
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    if not isinstance(result, dict):
        return None
    return result


def _commander_overcap_applies(kind, gross_mana, cap, support):
    """Spell/ETB may exceed the cap by exactly one with proved fixed commander mana."""
    if kind not in SPELL_ETB_KINDS:
        return False
    if support is None or not isinstance(support, dict):
        return False
    if support.get("status") != "verified":
        return False
    if gross_mana != cap + 1:
        return False
    pips = support.get("applicable_pips")
    if isinstance(pips, bool) or not isinstance(pips, (int, float)):
        return False
    return not (not math.isfinite(pips) or pips < 1)


def _assess_prerequisites(prerequisites, support_cards):
    unknown = False
    blocked = False
    conditional = False
    reasons = []
    if prerequisites is None:
        return True, False, False, ["missing_prerequisites"]
    if not isinstance(prerequisites, list):
        return True, False, False, ["malformed_prerequisites"]

    for item in prerequisites:
        if not isinstance(item, str) or not item:
            unknown = True
            reasons.append("unknown_prerequisite")
            continue
        if item == "island":
            island_status, island_reason = _island_support_status(support_cards)
            if island_status == UNVERIFIED:
                unknown = True
            elif island_status == BLOCKED:
                blocked = True
            if island_reason:
                reasons.append(island_reason)
            continue
        if item == "unsupported":
            unknown = True
            reasons.append("unsupported_prerequisite")
            continue
        if item in BENIGN_PREREQUISITES:
            continue
        if item in CONDITIONAL_PREREQUISITES:
            conditional = True
            reasons.append(f"requires_{item}")
            continue
        if item in KNOWN_PREREQUISITES:
            continue
        unknown = True
        reasons.append("unknown_prerequisite")
    return unknown, blocked, conditional, reasons


def _island_support_status(support_cards):
    """Current Island land subtype among support cards, never future/oracle/name."""
    if support_cards is None:
        return UNVERIFIED, "unknown_island_support"
    if not isinstance(support_cards, (list, tuple)):
        return UNVERIFIED, "unknown_island_support"

    saw_unknown = False
    saw_island = False
    for item in support_cards:
        verdict = _support_card_island_verdict(item)
        if verdict == "island":
            saw_island = True
        elif verdict == "unknown":
            saw_unknown = True
    if saw_island:
        return AVAILABLE, None
    if saw_unknown:
        return UNVERIFIED, "unknown_island_support"
    return BLOCKED, "missing_current_island_support"


def _support_card_island_verdict(card):
    if not isinstance(card, dict):
        return "unknown"
    if card.get("dynamic_types") or card.get("type_changeable"):
        return "unknown"
    type_line = card.get("type_line")
    if not isinstance(type_line, str) or not type_line.strip():
        return "unknown"
    faces = card.get("card_faces")
    ambiguous_faces = "//" in type_line or bool(faces)
    lines = [part.strip() for part in type_line.split("//")]
    texts = [card.get("oracle_text", "")]
    if faces:
        if not isinstance(faces, list):
            return "unknown"
        for face in faces:
            if (
                not isinstance(face, dict)
                or not isinstance(face.get("type_line"), str)
                or not face["type_line"].strip()
            ):
                return "unknown"
            lines.append(face["type_line"])
            texts.append(face.get("oracle_text", ""))
    if not all(lines):
        return "unknown"
    if any(_type_line_has_island_subtype(line) for line in lines):
        return "unknown" if ambiguous_faces else "island"
    text = "\n".join(t for t in texts if isinstance(t, str))
    if re.search(
        r"\b(?:lands?\b[^.\n]*\b(?:is|are|becomes?|become)\b[^.\n]*\bIslands?|(?:is|are|becomes?|become)\s+(?:an?\s+)?Islands?)\b",
        text,
        re.IGNORECASE,
    ):
        return "unknown"
    return "no_island"


def _type_line_has_island_subtype(type_line):
    """True only when the subtype section after an emdash contains token Island."""
    if not isinstance(type_line, str):
        return False
    if not _TYPE_LINE_SPLIT.search(type_line):
        return False
    parts = _TYPE_LINE_SPLIT.split(type_line, maxsplit=1)
    if len(parts) < 2:
        return False
    tokens = [token for token in _SUBTYPE_SPLIT.split(parts[1]) if token]
    return "Land" in parts[0].split() and "Island" in tokens


def _aggregate(profile, assessed):
    reasons = []
    unknown_clauses = [c for c in (profile.get("unknown_clauses") or []) if c]
    complete = profile.get("complete") is True

    if not assessed:
        if complete and not unknown_clauses:
            return BLOCKED, ["no_actual_draw_route"]
        reasons.append("no_routes")
        if unknown_clauses:
            reasons.append("unknown_clauses")
        if not complete:
            reasons.append("incomplete_profile")
        return UNVERIFIED, _dedupe(reasons)

    statuses = [route.get("status") for route in assessed]
    if AVAILABLE in statuses:
        status = AVAILABLE
        for route in assessed:
            if route.get("status") == AVAILABLE:
                reasons.extend(route.get("reasons") or [])
        return status, _dedupe(reasons)

    if CONDITIONAL in statuses:
        status = CONDITIONAL
        for route in assessed:
            if route.get("status") == CONDITIONAL:
                reasons.extend(route.get("reasons") or [])
        return status, _dedupe(reasons)

    if UNVERIFIED in statuses:
        status = UNVERIFIED
        for route in assessed:
            if route.get("status") == UNVERIFIED:
                reasons.extend(route.get("reasons") or [])
        if unknown_clauses:
            reasons.append("unknown_clauses")
        if not complete:
            reasons.append("incomplete_profile")
        return status, _dedupe(reasons)

    # All remaining routes are blocked. Unknown leftover clauses mean we cannot
    # close the card as unusable.
    if unknown_clauses or not complete:
        if unknown_clauses:
            reasons.append("unknown_clauses")
        if not complete:
            reasons.append("incomplete_profile")
        for route in assessed:
            reasons.extend(route.get("reasons") or [])
        return UNVERIFIED, _dedupe(reasons)

    for route in assessed:
        reasons.extend(route.get("reasons") or [])
    return BLOCKED, _dedupe(reasons)


def _is_independent_spell(route):
    if not isinstance(route, dict):
        return False
    if route.get("status") != AVAILABLE:
        return False
    if route.get("kind") != "spell":
        return False
    if not _is_positive_card_count(route.get("net_cards")):
        return False
    prereqs = route.get("prerequisites") or []
    if not isinstance(prereqs, list):
        return False
    for item in prereqs:
        if item in BENIGN_PREREQUISITES:
            continue
        if item:
            return False
    return True


def _dedupe(items):
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
