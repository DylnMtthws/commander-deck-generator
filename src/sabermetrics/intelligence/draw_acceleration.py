"""Commander mana-support helper for restricted tap-mana (Giada-style) abilities.

Fail-closed: only exact, standalone Oracle lines are recognized. This module
never mutates inputs, never reduces printed CMC, and never claims that a spell
is castable on a given turn. Listed setup_requirements are unproven conditions.
"""

from __future__ import annotations

import re

_TYPE_SPLIT = re.compile(r"\s+[—–]\s+")
_COST_WHOLE = re.compile(r"^(?:\{[^}]+\})+$")
_COST_SYMBOL = re.compile(r"\{([^}]+)\}")
_GENERIC_SYMBOL = re.compile(r"^\d+$")
_COLORS = frozenset("WUBRG")

# Exact standalone line: "{T}: Add {W}. Spend this mana only to cast an Angel spell."
# Other single fixed color/subtype are accepted only when this same syntax matches.
_RESTRICTED_TAP_MANA = re.compile(
    r"^\{T\}: Add \{([WUBRG])\}\. Spend this mana only to cast (an?) "
    r"([A-Z][A-Za-z]*) spell\.$"
)

_VIVI_LINE = (
    "{0}: Add X mana in any combination of {U} and/or {R}, "
    "where X is Vivi Ornitier's power. "
    "Activate only during your turn and only once each turn."
)

_GIADA_SETUP = (
    "commander_on_battlefield",
    "commander_untapped",
    "summoning_sickness_cleared_or_haste",
)
_VIVI_RESTRICTIONS = ("own_turn", "once_each_turn")
_VIVI_SETUP = (
    "commander_on_battlefield",
    "power_and_activation_state_required",
)


def commander_mana_support(
    commander: dict, card: dict, *, route_kind: str = "cast"
) -> dict:
    """Return whether `commander` can contribute mana toward `card`.

    Recognized outcomes:
      * verified — exact Giada-style restricted tap-mana applies to this cast
      * state_dependent — exact Vivi variable-power mana ability; no fixed pips
      * unsupported — everything else (unknown commander, other routes, etc.)

    A single activation contributes at most one mana. Eligible casts need the
    produced color in the printed cost, or a positive generic pip that color
    could pay. Hybrid, variable, and malformed costs fail closed.
    """
    if not isinstance(commander, dict) or not isinstance(card, dict):
        return _unsupported("Inputs are not Oracle record dicts.")

    lines = _oracle_lines(commander.get("oracle_text"))
    if lines is None:
        return _unsupported("Commander Oracle text is missing or malformed.")

    vivi_hits = sum(1 for line in lines if line == _VIVI_LINE)
    tap_hits = [m for m in (_RESTRICTED_TAP_MANA.match(line) for line in lines) if m]

    if vivi_hits and tap_hits:
        return _unsupported("Commander mixes unrecognized mana-ability combination.")
    if vivi_hits > 1 or len(tap_hits) > 1:
        return _unsupported("Commander mana ability is not a unique exact line.")
    if vivi_hits == 1:
        return _vivi_result()
    if not tap_hits:
        return _unsupported("No recognized commander mana ability.")

    if any("activate only" in line.lower() for line in lines):
        return _unsupported("Additional activation restrictions are not modeled.")

    match = tap_hits[0]
    color = match.group(1)
    article = match.group(2)
    subtype = match.group(3)
    expected_article = "an" if subtype[0] in "AEIOU" else "a"
    if article != expected_article:
        return _unsupported("Restricted tap-mana line is not exact official syntax.")

    commander_types, _commander_subtypes = _parse_type_line(commander.get("type_line"))
    if "Creature" not in commander_types:
        return _unsupported(
            "Commander is not a Creature; tap summoning-sickness cannot be verified."
        )

    if route_kind != "cast":
        return _unsupported("route_kind is not cast.")

    card_types, card_subtypes = _parse_type_line(card.get("type_line"))
    if "//" in str(card.get("type_line") or ""):
        return _unsupported("Card type line is not a single verifiable face.")
    if (
        not set(card_types).intersection({"Creature", "Kindred", "Tribal"})
        or subtype not in card_subtypes
    ):
        return _unsupported(
            "Card type line does not establish the required creature subtype."
        )

    cost_kind = _cost_eligibility(card.get("mana_cost"), color)
    if cost_kind == "empty":
        return _unsupported("Card has no mana cost.")
    if cost_kind == "unknown":
        return _unsupported(
            "Mana cost is hybrid, variable, malformed, or otherwise unknown."
        )
    if cost_kind == "wrong_color":
        return _unsupported(
            "Mana cost has no matching color pip and no positive generic mana."
        )

    return {
        "status": "verified",
        "mana_by_color": {color: 1},
        "applicable_pips": 1,
        "casting_only": True,
        "restrictions": [f"casting_only_{subtype.lower()}"],
        "setup_requirements": list(_GIADA_SETUP),
        "reason": (
            f"Exact restricted tap-mana ability produces one {color} to cast "
            f"{article} {subtype} spell; setup conditions are unproven."
        ),
    }


def _vivi_result() -> dict:
    return {
        "status": "state_dependent",
        "mana_by_color": {},
        "applicable_pips": 0,
        "casting_only": False,
        "restrictions": list(_VIVI_RESTRICTIONS),
        "setup_requirements": list(_VIVI_SETUP),
        "reason": (
            "Mana amount depends on commander power and activation state; "
            "no fixed contribution."
        ),
    }


def _unsupported(reason: str) -> dict:
    return {
        "status": "unsupported",
        "mana_by_color": {},
        "applicable_pips": 0,
        "casting_only": False,
        "restrictions": [],
        "setup_requirements": [],
        "reason": reason,
    }


def _oracle_lines(oracle_text: object) -> list[str] | None:
    if not isinstance(oracle_text, str):
        return None
    return [line.strip() for line in oracle_text.splitlines() if line.strip()]


def _parse_type_line(type_line: object) -> tuple[list[str], list[str]]:
    if not isinstance(type_line, str) or not type_line.strip():
        return [], []
    text = type_line.strip()
    if "//" in text:
        return [], []
    parts = _TYPE_SPLIT.split(text, maxsplit=1)
    types = parts[0].split()
    subtypes = parts[1].split() if len(parts) > 1 else []
    return types, subtypes


def _cost_eligibility(mana_cost: object, produced_color: str) -> str:
    if mana_cost is None:
        return "empty"
    if not isinstance(mana_cost, str):
        return "unknown"
    cost = mana_cost.strip()
    if cost == "":
        return "empty"
    if _COST_WHOLE.fullmatch(cost) is None:
        return "unknown"

    generic = 0
    has_produced = False
    for symbol in _COST_SYMBOL.findall(cost):
        if _GENERIC_SYMBOL.fullmatch(symbol):
            generic += int(symbol)
            continue
        if symbol in _COLORS:
            if symbol == produced_color:
                has_produced = True
            continue
        return "unknown"

    if has_produced or generic > 0:
        return "eligible"
    return "wrong_color"
