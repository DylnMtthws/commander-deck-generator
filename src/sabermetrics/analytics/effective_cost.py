"""Effective mana cost calculator for alternative casting costs.

Parses oracle text for alternative casting methods (morph, evoke, dash,
madness, unearth, disguise, megamorph) and returns the minimum effective
CMC a card can be deployed for.

``casting_options`` is the structured view: every way the stored text supports
putting the card into play, with the mana actually paid, the conditions that
gate it, and whether it is a cast at all. Printed mana value is never altered
by any of this; it is reported alongside, not replaced.

Pure-function module (no DB access), following oracle_keywords.py conventions:
module-level compiled regexes, deterministic outputs.
"""

import re

# ---------------------------------------------------------------------------
# Mana cost string parser
# ---------------------------------------------------------------------------

# Matches mana symbols like {2}, {B}, {W/U}, {X}, {C}
_MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")


def _parse_mana_cost_cmc(cost_str: str) -> float:
    """Convert a mana cost string to CMC.

    Args:
        cost_str: Mana cost like "{2}{B}{B}" or "{1}{R}" or "{X}{G}".

    Returns:
        Converted mana value as float. X counts as 0.
    """
    total = 0.0
    for match in _MANA_SYMBOL_RE.finditer(cost_str):
        symbol = match.group(1).upper()
        if symbol == "X":
            continue  # X = 0 for CMC purposes
        try:
            total += float(symbol)
        except ValueError:
            # Single color symbol (W, U, B, R, G, C) or hybrid (W/U)
            if "/" in symbol:
                # Hybrid: each half is 1 mana; CMC counts the higher
                # Per rules: hybrid {W/U} contributes 1 to CMC
                total += 1.0
            else:
                total += 1.0
    return total


# ---------------------------------------------------------------------------
# Alternative cost extraction
# ---------------------------------------------------------------------------

# Morph/Megamorph/Disguise — always costs {3} face-down (game rule)
_FACE_DOWN_RE = re.compile(
    r"\b(?:morph|megamorph|disguise)\b",
    re.IGNORECASE,
)

# Evoke cost: "Evoke {cost}" or "Evoke—{cost}"
_EVOKE_RE = re.compile(
    r"\bevoke\s*[—\-]?\s*(\{[^}]+\}(?:\{[^}]+\})*)",
    re.IGNORECASE,
)

# Dash cost: "Dash {cost}"
_DASH_RE = re.compile(
    r"\bdash\s+(\{[^}]+\}(?:\{[^}]+\})*)",
    re.IGNORECASE,
)

# Madness cost: "Madness {cost}"
_MADNESS_RE = re.compile(
    r"\bmadness\s+(\{[^}]+\}(?:\{[^}]+\})*)",
    re.IGNORECASE,
)

# Unearth cost: "Unearth {cost}"
_UNEARTH_RE = re.compile(
    r"\bunearth\s+(\{[^}]+\}(?:\{[^}]+\})*)",
    re.IGNORECASE,
)


def parse_alternative_costs(oracle_text: str | None) -> list[dict]:
    """Extract alternative casting costs from oracle text.

    Args:
        oracle_text: Card's oracle text (may be None).

    Returns:
        List of dicts with keys "method" and "cmc".
    """
    if not oracle_text:
        return []

    results: list[dict] = []

    # Face-down mechanics (morph/megamorph/disguise) always cost {3}
    if _FACE_DOWN_RE.search(oracle_text):
        results.append({"method": "face_down", "cmc": 3.0})

    # Evoke
    match = _EVOKE_RE.search(oracle_text)
    if match:
        results.append(
            {
                "method": "evoke",
                "cmc": _parse_mana_cost_cmc(match.group(1)),
            }
        )

    # Dash
    match = _DASH_RE.search(oracle_text)
    if match:
        results.append(
            {
                "method": "dash",
                "cmc": _parse_mana_cost_cmc(match.group(1)),
            }
        )

    # Madness
    match = _MADNESS_RE.search(oracle_text)
    if match:
        results.append(
            {
                "method": "madness",
                "cmc": _parse_mana_cost_cmc(match.group(1)),
            }
        )

    # Unearth
    match = _UNEARTH_RE.search(oracle_text)
    if match:
        results.append(
            {
                "method": "unearth",
                "cmc": _parse_mana_cost_cmc(match.group(1)),
            }
        )

    return results


# ---------------------------------------------------------------------------
# Structured casting options
# ---------------------------------------------------------------------------

# Conditions that come with each alternative cast, so a caller never sees a
# cheap number without the string attached to it.
_METHOD_CONDITIONS = {
    "face_down": [
        "enters_as_a_2_2_with_no_abilities",
        "turning_face_up_costs_the_printed_morph_cost",
    ],
    "evoke": ["sacrificed_when_it_enters"],
    "dash": ["returns_to_hand_at_end_of_turn"],
    "madness": ["requires_discarding_this_card"],
}

# Non-cast ways to use a card. These never count as casting it.
_NONCAST_CONDITIONS = {
    "unearth": [
        "activated_ability_from_graveyard_is_not_a_cast",
        "exiled_at_the_next_end_step",
    ],
    "transmute": [
        "discarding_to_transmute_is_not_a_cast",
        "finds_a_different_card_of_the_same_mana_value",
    ],
}

_FLASHBACK_RE = re.compile(
    r"\bflashback\s*[—\-]?\s*(\{[^}]+\}(?:\{[^}]+\})*)", re.IGNORECASE
)
_TRANSMUTE_RE = re.compile(
    r"\btransmute\s*[—\-]?\s*(\{[^}]+\}(?:\{[^}]+\})*)", re.IGNORECASE
)
_CONVOKE_RE = re.compile(r"\bconvoke\b", re.IGNORECASE)
_PHYREXIAN_RE = re.compile(r"\{[wubrgc]/p\}", re.IGNORECASE)

# "...rather than pay this spell's mana cost" / commander-gated free casts.
_PITCH_RE = re.compile(r"[^.\n]*rather than pay this spell.s mana cost", re.IGNORECASE)
_FREE_CAST_RE = re.compile(
    r"[^.\n]*\byou may cast this spell without paying its mana cost", re.IGNORECASE
)

_LIFE_RE = re.compile(r"pay (\d+) life", re.IGNORECASE)
_EXILE_CARD_RE = re.compile(
    r"exile (?:a|an|one|two) (\w+) cards? from your hand", re.IGNORECASE
)
_REVEAL_CARD_RE = re.compile(
    r"reveal (?:a|an|one|two|three) (\w+) cards? from your hand", re.IGNORECASE
)
_SACRIFICE_RE = re.compile(r"sacrifice (?:a|an) ([\w-]+)", re.IGNORECASE)
_DISCARD_RE = re.compile(r"discard (?:a|an|one) (\w+) card", re.IGNORECASE)


def _option(
    method: str, mana_paid: float, conditions: list[str], is_cast: bool
) -> dict:
    return {
        "method": method,
        "mana_paid": max(0.0, float(mana_paid)),
        "conditions": list(conditions),
        "is_cast": bool(is_cast),
    }


def _alternative_cost_conditions(clause: str) -> list[str]:
    """Name the requirements of a pitch / free cast clause, or say they are unknown."""
    conditions: list[str] = []
    match = _LIFE_RE.search(clause)
    if match:
        conditions.append(f"costs_{match.group(1)}_life")
    match = _EXILE_CARD_RE.search(clause)
    if match:
        conditions.append(
            f"requires_exiling_{'two' if 'two ' in match.group(0).lower() else 'a'}_{match.group(1).lower()}_card{'s' if 'two ' in match.group(0).lower() else ''}_from_hand"
        )
    match = _REVEAL_CARD_RE.search(clause)
    if match:
        conditions.append(
            f"requires_revealing_a_{match.group(1).lower()}_card_from_hand"
        )
    match = _DISCARD_RE.search(clause)
    if match:
        conditions.append(f"requires_discarding_a_{match.group(1).lower()}_card")
    match = _SACRIFICE_RE.search(clause)
    if match:
        conditions.append(f"requires_sacrificing_a_{match.group(1).lower()}")
    if re.search(r"if you control a commander", clause, re.IGNORECASE):
        conditions.append("requires_controlling_a_commander")
    if re.search(
        r"it's not your turn|during an opponent's turn", clause, re.IGNORECASE
    ):
        conditions.append("only_when_it_is_not_your_turn")
    if re.search(r"return an island you control", clause, re.IGNORECASE):
        conditions.append("requires_returning_an_island_you_control")
    if not conditions:
        # The clause exists but its requirement is not a supported shape.
        conditions.append("alternative_cost_requirement_not_parsed")
    return conditions


def _faces(card: dict) -> list[tuple[str, str, str]]:
    """Return (face name, face mana cost, face type line) where text supports it."""
    faces = card.get("card_faces")
    result: list[tuple[str, str, str]] = []
    if isinstance(faces, list) and faces:
        for face in faces:
            if not isinstance(face, dict):
                continue
            result.append(
                (
                    str(face.get("name") or ""),
                    str(face.get("mana_cost") or ""),
                    str(face.get("type_line") or ""),
                )
            )
        return result
    mana_cost = str(card.get("mana_cost") or "")
    if " // " in mana_cost:
        names = str(card.get("name") or "").split(" // ")
        types = str(card.get("type_line") or "").split(" // ")
        for i, cost in enumerate(mana_cost.split(" // ")):
            result.append(
                (
                    names[i] if i < len(names) else "",
                    cost,
                    types[i] if i < len(types) else "",
                )
            )
    return result


def _face_options(card: dict) -> tuple[list[dict], bool]:
    """Per-face cast options, plus whether face costs were unavailable."""
    multi = "//" in str(card.get("type_line") or "") or "//" in str(
        card.get("name") or ""
    )
    options: list[dict] = []
    for name, cost, type_line in _faces(card):
        if not cost or "land" in type_line.lower():
            continue  # A land back face is played, not cast for mana.
        method = "adventure" if "adventure" in type_line.lower() else "split_face"
        conditions = [f"face={name}"] if name else ["face_name_unavailable"]
        if method == "adventure":
            conditions.append("adventure_exiles_the_card_before_the_creature_is_cast")
        options.append(_option(method, _parse_mana_cost_cmc(cost), conditions, True))
    return options, multi and not options


def casting_options(card: dict) -> list[dict]:
    """Every supported way to put ``card`` onto the stack or the battlefield.

    Each entry is ``{"method", "mana_paid", "conditions", "is_cast"}``. The
    printed mana value of the card is never modified or reinterpreted: it is
    the ``normal`` option's ``mana_paid``, and alternatives are listed beside
    it. An option that is not a cast (unearth, transmute) carries
    ``is_cast=False`` so cast-count logic can exclude it.
    """
    printed_cmc = float(card.get("cmc", 0) or 0)
    oracle_text = str(card.get("oracle_text") or "")
    mana_cost = str(card.get("mana_cost") or "")

    face_options, faces_unavailable = _face_options(card)
    normal_conditions: list[str] = []
    if faces_unavailable:
        normal_conditions.append("face_costs_not_available_in_stored_text")
    is_land = "land" in str(card.get("type_line", "")).split("//")[0].lower()
    options = [_option("normal", printed_cmc, normal_conditions, not is_land)]
    options.extend(face_options)

    for alt in parse_alternative_costs(oracle_text):
        method = alt["method"]
        if method in _NONCAST_CONDITIONS:
            options.append(
                _option(method, alt["cmc"], _NONCAST_CONDITIONS[method], False)
            )
        else:
            options.append(
                _option(method, alt["cmc"], _METHOD_CONDITIONS.get(method, []), True)
            )

    match = _FLASHBACK_RE.search(oracle_text)
    if match:
        options.append(
            _option(
                "flashback",
                _parse_mana_cost_cmc(match.group(1)),
                ["cast_only_from_your_graveyard", "exiled_as_it_resolves"],
                True,
            )
        )

    match = _TRANSMUTE_RE.search(oracle_text)
    if match:
        options.append(
            _option(
                "transmute",
                _parse_mana_cost_cmc(match.group(1)),
                _NONCAST_CONDITIONS["transmute"],
                False,
            )
        )

    match = _PITCH_RE.search(oracle_text)
    if match:
        options.append(
            _option(
                "alternative_cost",
                0.0,
                _alternative_cost_conditions(match.group(0)),
                True,
            )
        )

    match = _FREE_CAST_RE.search(oracle_text)
    if match:
        options.append(
            _option(
                "free_cast", 0.0, _alternative_cost_conditions(match.group(0)), True
            )
        )

    phyrexian = len(_PHYREXIAN_RE.findall(mana_cost))
    if phyrexian:
        options.append(
            _option(
                "phyrexian",
                printed_cmc - phyrexian,
                [f"pays_2_life_for_each_of_{phyrexian}_phyrexian_symbols"],
                True,
            )
        )

    if _CONVOKE_RE.search(oracle_text):
        # Convoke taps creatures for mana. How many are available is a board
        # state question, so no reduction is claimed here.
        options.append(
            _option(
                "convoke",
                printed_cmc,
                [
                    "creatures_tapped_for_convoke_replace_mana",
                    "convoke_reduction_amount_unknown",
                ],
                True,
            )
        )

    seen: list[dict] = []
    for option in options:
        if option not in seen:
            seen.append(option)
    return seen


def compute_effective_cmc(card: dict) -> float:
    """Compute the minimum effective CMC considering alternative casting costs.

    Only options that actually cast the card count: unearth and transmute are
    ways to use a card from a different zone, not cheaper casts, so they never
    lower this number. The printed CMC is returned unchanged when nothing
    cheaper is supported.

    Args:
        card: Card dict with "cmc" and "oracle_text" fields.

    Returns:
        Effective CMC as float (always >= 0).
    """
    printed_cmc = float(card.get("cmc", 0) or 0)
    casts = [
        o["mana_paid"]
        for o in casting_options(card)
        if o["is_cast"]
        and "alternative_cost_requirement_not_parsed" not in o["conditions"]
    ]
    return float(max(0.0, min([printed_cmc, *casts])))
