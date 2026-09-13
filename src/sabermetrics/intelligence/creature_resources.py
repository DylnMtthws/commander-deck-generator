"""Conservative creature-body resource proof from printed Oracle grammar.

``creature_resources(card)`` returns a fixed-shape resource dict only when a
single-front creature's printed fields are *fully consumed* by a narrow static
grammar: finite P/T, a fixed mana cost, an official creature type line, and
either an empty Oracle (vanilla) or a keyword-only body from a closed list.

Anything outside that grammar — alternative costs, triggered or activated text,
unknown keywords, unmapped reminder parentheses, multiface cards, inconsistent
printed mana value — returns ``None``. The helper never invents resource proof,
never ranks or equates bodies, and never trusts ``keywords`` metadata.

Only the Python standard library is used.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

__all__ = ["RESULT_KEYS", "creature_resources"]

RESULT_KEYS = (
    "power",
    "toughness",
    "mana_value",
    "mana_cost",
    "pips",
    "types",
    "supertypes",
    "subtypes",
    "keywords",
    "evidence",
)

# CR 205.4a
_SUPERTYPES = frozenset({"basic", "legendary", "ongoing", "snow", "world"})

# CR 205.2a, familiar modern names (Kindred replaces Tribal).
_CARD_TYPES: tuple[str, ...] = (
    "artifact",
    "battle",
    "conspiracy",
    "creature",
    "dungeon",
    "enchantment",
    "instant",
    "kindred",
    "land",
    "phenomenon",
    "plane",
    "planeswalker",
    "scheme",
    "sorcery",
    "tribal",
    "vanguard",
)
_CARD_TYPE_SET = frozenset(_CARD_TYPES)
_CARD_TYPE_ORDER = {name: index for index, name in enumerate(_CARD_TYPES)}

# Type combinations that can actually appear on a creature type line.
_CREATURE_LINE_TYPES = frozenset(
    {"artifact", "creature", "enchantment", "kindred", "land", "tribal"}
)

_SUPPORTED_KEYWORDS: tuple[str, ...] = tuple(
    sorted(
        (
            "flying",
            "first strike",
            "double strike",
            "deathtouch",
            "defender",
            "haste",
            "hexproof",
            "indestructible",
            "lifelink",
            "menace",
            "reach",
            "trample",
            "vigilance",
        ),
        key=len,
        reverse=True,
    )
)

# Exact official reminder sentences only. Unknown parentheses are rejected,
# never stripped as a convenience.
_KEYWORD_REMINDERS: dict[str, tuple[str, ...]] = {
    "deathtouch": (
        "Any amount of damage this deals to a creature is enough to destroy it.",
    ),
    "defender": ("This creature can't attack.",),
    "double strike": (
        "This creature deals both first-strike and regular combat damage.",
    ),
    "first strike": (
        "This creature deals combat damage before creatures without first strike.",
    ),
    "flying": (
        "This creature can't be blocked except by creatures with flying or reach.",
    ),
    "haste": (
        "This creature can attack and {T} as soon as it comes under your control.",
    ),
    "hexproof": (
        "This creature can't be the target of spells or abilities your opponents control.",
    ),
    "indestructible": (
        'Damage and effects that say "destroy" don\'t destroy this creature.',
    ),
    "lifelink": (
        "Damage dealt by this creature also causes you to gain that much life.",
    ),
    "menace": ("This creature can't be blocked except by two or more creatures.",),
    "reach": ("This creature can block creatures with flying.",),
    "trample": (
        "This creature can deal excess combat damage to the player or planeswalker it's attacking.",
        "This creature can deal excess combat damage to the player, planeswalker, or battle it's attacking.",
    ),
    "vigilance": ("Attacking doesn't cause this creature to tap.",),
}

_MANA_TOKEN_RE = re.compile(r"\{(\d+|[WUBRGC])\}")
_TYPE_SPLIT_RE = re.compile(r"\s*[—–]\s*|\s+-\s+")
_SUBTYPE_RE = re.compile(r"[^\W\d_][\w'\-]*", re.UNICODE)
_NONNEG_INT_RE = re.compile(r"0|[1-9]\d*")
_HAS_PREFIX_RE = re.compile(r"\s+has\s+", re.IGNORECASE)


def creature_resources(card: dict) -> dict | None:
    """Return static creature resources when Oracle is fully consumed.

    Args:
        card: Printed card dict (Scryfall-like keys). Not mutated.

    Returns:
        A resource dict with ``RESULT_KEYS``, or ``None`` when the body is not
        a proven vanilla/keyword-only creature under this grammar.
    """
    if not isinstance(card, dict):
        return None
    if _is_multiface(card):
        return None

    mana = _parse_mana_cost(card.get("mana_cost"))
    if mana is None:
        return None
    mana_cost, mana_value, pips = mana
    printed_mv = _printed_mana_value(card)
    if printed_mv is None or printed_mv != mana_value:
        return None

    power = _finite_nonneg_int(card.get("power"))
    toughness = _finite_nonneg_int(card.get("toughness"))
    if power is None or toughness is None:
        return None

    parsed_types = _parse_type_line(card.get("type_line"))
    if parsed_types is None:
        return None
    types, supertypes, subtypes = parsed_types

    keywords = _parse_oracle(card.get("oracle_text"), card.get("name"))
    if keywords is None:
        return None

    type_line = card["type_line"]
    evidence = [mana_cost, type_line, f"{card.get('power')}/{card.get('toughness')}"]
    oracle_text = card.get("oracle_text")
    if isinstance(oracle_text, str) and oracle_text.strip():
        evidence.append(oracle_text)

    return {
        "power": power,
        "toughness": toughness,
        "mana_value": mana_value,
        "mana_cost": mana_cost,
        "pips": dict(pips),
        "types": list(types),
        "supertypes": list(supertypes),
        "subtypes": list(subtypes),
        "keywords": list(keywords),
        "evidence": list(evidence),
    }


def _is_multiface(card: dict[str, Any]) -> bool:
    layout = card.get("layout")
    if isinstance(layout, str) and layout.casefold() in {
        "split",
        "transform",
        "modal_dfc",
        "adventure",
        "flip",
        "meld",
        "reversible_card",
    }:
        return True
    faces = card.get("card_faces")
    if isinstance(faces, list) and faces:
        return True
    for key in ("name", "type_line", "oracle_text", "mana_cost"):
        value = card.get(key)
        if isinstance(value, str) and "//" in value:
            return True
    return False


def _parse_mana_cost(mana_cost: object) -> tuple[str, int, dict[str, int]] | None:
    if not isinstance(mana_cost, str) or not mana_cost:
        return None
    tokens = _MANA_TOKEN_RE.findall(mana_cost)
    if not tokens:
        return None
    rebuilt = "".join("{" + token + "}" for token in tokens)
    if rebuilt != mana_cost:
        return None
    total = sum(int(token) if token.isdigit() else 1 for token in tokens)
    pips = dict(Counter(token for token in tokens if not token.isdigit()))
    return mana_cost, total, pips


def _printed_mana_value(card: dict[str, Any]) -> int | float | None:
    raw_values: list[object] = []
    if "cmc" in card:
        raw_values.append(card["cmc"])
    if "mana_value" in card:
        raw_values.append(card["mana_value"])
    if not raw_values:
        return None
    parsed: list[int | float] = []
    for value in raw_values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        parsed.append(value)
    first = parsed[0]
    if any(value != first for value in parsed):
        return None
    return first


def _finite_nonneg_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not _NONNEG_INT_RE.fullmatch(stripped):
            return None
        return int(stripped)
    return None


def _parse_type_line(
    type_line: object,
) -> tuple[list[str], list[str], list[str]] | None:
    if not isinstance(type_line, str):
        return None
    raw = type_line.strip()
    if not raw:
        return None
    parts = _TYPE_SPLIT_RE.split(raw, maxsplit=1)
    if len(parts) != 2:
        return None
    left = parts[0].strip()
    right = parts[1].strip()
    if not left or not right:
        return None
    words = left.split()
    if not words:
        return None

    supertypes: list[str] = []
    index = 0
    while index < len(words) and words[index].casefold() in _SUPERTYPES:
        folded = words[index].casefold()
        if folded in supertypes:
            return None
        supertypes.append(folded)
        index += 1

    types: list[str] = []
    while index < len(words):
        folded = words[index].casefold()
        if folded not in _CARD_TYPE_SET or folded not in _CREATURE_LINE_TYPES:
            return None
        if folded in types:
            return None
        types.append(folded)
        index += 1

    if "creature" not in types:
        return None
    if types != sorted(types, key=lambda name: _CARD_TYPE_ORDER[name]):
        return None

    subtypes: list[str] = []
    if right:
        for token in right.split():
            if not _SUBTYPE_RE.fullmatch(token):
                return None
            subtypes.append(token.casefold())
        if not subtypes:
            return None
    return types, supertypes, subtypes


def _parse_oracle(oracle_text: object, name: object) -> list[str] | None:
    if not isinstance(oracle_text, str):
        return None
    text = oracle_text.strip()
    if not text:
        return []

    remainder, consumed_self_name = _consume_self_name_prefix(name, text)
    remainder = remainder.strip()
    if consumed_self_name and not remainder:
        return None
    return _consume_keyword_body(remainder)


def _consume_self_name_prefix(name: object, text: str) -> tuple[str, bool]:
    """Strip an explicit ``'<card name> has '`` prefix only.

    Other leading names, including ``This creature has``, are left intact so
    they fail complete keyword consumption rather than being normalized away.
    """
    if not isinstance(name, str) or not name.strip():
        return text, False
    needle = name.strip()
    if len(text) < len(needle):
        return text, False
    if text[: len(needle)].casefold() != needle.casefold():
        return text, False
    tail = text[len(needle) :]
    match = _HAS_PREFIX_RE.match(tail)
    if match is None:
        return text, False
    return tail[match.end() :], True


def _consume_keyword_body(text: str) -> list[str] | None:
    if not text:
        return []
    length = len(text)
    pos = 0
    keywords: list[str] = []
    first = True
    while pos < length:
        pos = _skip_spaces(text, pos)
        if pos >= length:
            break
        if text[pos] == ".":
            break
        if not first:
            separator_end = _consume_keyword_separator(text, pos)
            if separator_end is None:
                return None
            pos = _skip_spaces(text, separator_end)
            if pos >= length:
                return None
        first = False
        matched = _match_keyword_at(text, pos)
        if matched is None:
            return None
        keyword, pos = matched
        pos = _skip_spaces(text, pos)
        reminder_end = _consume_optional_reminder(text, pos, keyword)
        if reminder_end is None:
            return None
        pos = reminder_end
        if keyword not in keywords:
            keywords.append(keyword)
    pos = _skip_spaces(text, pos)
    if pos < length and text[pos] == ".":
        pos += 1
        pos = _skip_spaces(text, pos)
    if pos != length:
        return None
    if not keywords:
        return None
    return keywords


def _skip_spaces(text: str, pos: int) -> int:
    length = len(text)
    while pos < length and text[pos] in " \t":
        pos += 1
    return pos


def _consume_keyword_separator(text: str, pos: int) -> int | None:
    if pos >= len(text):
        return None
    char = text[pos]
    if char == ",":
        pos += 1
        length = len(text)
        while pos < length and text[pos] in " \t\n\r":
            pos += 1
        return pos
    if char in "\n\r":
        length = len(text)
        while pos < length and text[pos] in "\n\r":
            pos += 1
        return pos
    return None


def _match_keyword_at(text: str, pos: int) -> tuple[str, int] | None:
    rest = text[pos:].casefold()
    for keyword in _SUPPORTED_KEYWORDS:
        if not rest.startswith(keyword):
            continue
        end = pos + len(keyword)
        if end < len(text) and text[end].isalpha():
            continue
        return keyword, end
    return None


def _consume_optional_reminder(text: str, pos: int, keyword: str) -> int | None:
    if pos >= len(text) or text[pos] != "(":
        return pos
    close = text.find(")", pos + 1)
    if close < 0:
        return None
    inner = text[pos + 1 : close]
    if "(" in inner:
        return None
    if not _reminder_is_mapped(keyword, inner):
        return None
    return close + 1


def _reminder_is_mapped(keyword: str, inner: str) -> bool:
    candidate = " ".join(inner.split())
    for reminder in _KEYWORD_REMINDERS.get(keyword, ()):
        if candidate.casefold() == reminder.casefold():
            return True
    return False
