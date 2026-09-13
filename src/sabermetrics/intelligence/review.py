"""Small falsifiable checks on model claims, never a general rules verifier.

Every check here compares one explicit model claim against one printed card
field. Silence means "no supported check fired", never "the prose is correct".
Fuzzy strategic prose is deliberately not treated as a claim: only phrasing
tight enough to be falsified by printed data is examined.

Two distinctions carry most of the value:

* printed mana value is not what you pay. Dismember has mana value 3 and can be
  cast for one generic mana plus four life; a mana-value claim is checked
  against ``cmc`` always, a cast-cost claim is not checked when the card offers
  an alternative or Phyrexian payment.
* "one more" is not "twice as many", and a creature type printed in rules text
  (a Goblin token) is not the card's own type line.
"""

from __future__ import annotations

import re
from typing import Any, Final

MSG_MANA_COST: Final = "Model mana-cost claim contradicts printed card data."
MSG_MANA_VALUE: Final = "Model mana-value claim contradicts printed mana value."
MSG_CAST_TRIGGER: Final = (
    "Model cast-trigger claim contradicts commander and card types."
)
MSG_CAST_THRESHOLD: Final = (
    "Model cast-trigger claim contradicts the commander's printed mana value "
    "threshold."
)
MSG_DOUBLING: Final = (
    "Model doubling claim contradicts a printed add-one replacement effect."
)
MSG_ADD_ONE: Final = (
    "Model add-one claim contradicts a printed doubling replacement effect."
)
MSG_CARD_TYPE: Final = "Model card-type claim contradicts the printed type line."

_WORDS: Final = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_NUMBER: Final = r"\d{1,2}|" + "|".join(_WORDS)

_GENERIC_SUBJECTS: Final = (
    "this card",
    "this spell",
    "this creature",
    "this artifact",
    "this enchantment",
    "this instant",
    "this sorcery",
    "this permanent",
    "the card",
    "it",
    "this",
)

_MV_TERM: Final = r"(?:mana value|mv|converted mana cost)"
# A number followed by a comparator is a threshold statement about a class of
# cards, not a claim about this card's printed value.
_COMPARATOR: Final = r"(?!\s*(?:or (?:greater|more|higher|less|fewer|lower)|\+))"

_COST_CLAIM_RE: Final = re.compile(
    r"\b(?:a|an|this is a) (" + "|".join(_WORDS) + r")[ -]mana "
    r"(?:instant|sorcery|spell|pump|artifact|creature|aura|counterspell)\b"
)
_ALT_PAYMENT_MARKERS: Final = ("rather than pay", "without paying")
_PHYREXIAN_RE: Final = re.compile(r"\{[^}]*/p\}", re.IGNORECASE)

_CAST_TRIGGER_RE: Final = re.compile(
    r"whenever you cast (?:a|an|your first)\s+"
    r"(?P<kind>noncreature spell|creature spell|instant or sorcery spell"
    r"|artifact spell|enchantment spell|spell)"
    r"(?:[^.\n]{0,60}?\bwith mana value (?P<threshold>\d{1,2})\s+or\s+"
    r"(?P<direction>greater|more|less|fewer))?"
)

# Printed replacement shapes that are routinely described as doubling.
_PLUS_ONE_SHAPE_RE: Final = re.compile(
    r"that many plus one|plus one \+1/\+1 counter"
    r"|(?:add|adds) (?:an additional|one additional)",
    re.IGNORECASE,
)
_DOUBLING_SHAPE_RE: Final = re.compile(
    r"twice that many|twice that much|twice as many|double the (?:number|amount)",
    re.IGNORECASE,
)
_DOUBLING_CLAIM_RE: Final = re.compile(
    # "doubles as a sacrifice outlet" is an idiom, not a magnitude claim.
    r"\b(?:doubles?|doubling|doubled)\b(?!\s+as\s+an?\b)"
    r"[^.\n]{0,40}?\b(?:counters?|mana)\b"
    r"|\btwice (?:as many|that many|as much|that much)\b"
    r"[^.\n]{0,40}?\b(?:counters?|mana)\b"
    r"|\b(?:counters?|mana)\b[^.\n]{0,30}?\b(?:are|is|get|gets) doubled\b"
)
_ADD_ONE_CLAIM_RE: Final = re.compile(
    r"\b(?:one (?:extra|additional|more)|an (?:extra|additional)|plus one)\b"
    r"[^.\n]{0,30}?\b(?:counters?|mana)\b"
)

_CARD_TYPES: Final = (
    "artifact",
    "battle",
    "creature",
    "enchantment",
    "instant",
    "land",
    "planeswalker",
    "sorcery",
)
# A bounded, unambiguous subtype vocabulary. Words outside it are not checked:
# an unlisted subtype is an unknown, not a false claim.
_SUBTYPES: Final = (
    "angel",
    "beast",
    "bird",
    "cat",
    "cleric",
    "demon",
    "dinosaur",
    "dragon",
    "dwarf",
    "elemental",
    "elf",
    "giant",
    "goblin",
    "horror",
    "human",
    "insect",
    "knight",
    "merfolk",
    "ninja",
    "pirate",
    "rogue",
    "samurai",
    "shaman",
    "sliver",
    "snake",
    "soldier",
    "spirit",
    "vampire",
    "warrior",
    "wizard",
    "zombie",
)
_TYPE_VOCABULARY: Final = tuple(sorted(_CARD_TYPES + _SUBTYPES, key=len, reverse=True))
_TYPE_CLAIM_TAIL: Final = (
    r"(?=\s*[.,;:!?)]|\s*$|\s+(?:creature|creatures|card|cards|permanent"
    r"|permanents|spell|that|which|and|or|so|but|here|for|with)\b)"
)
# The card itself gaining a type is a different statement from its printed one.
_TYPE_GRANT_RE: Final = re.compile(
    r"\bbecomes? an? |\bin addition to its other|\bas well as an? "
    r"|\bchangeling\b|\b(?:every|all) creature types?\b",
    re.IGNORECASE,
)


def contradictions(card: dict, reasoning: str, commander: dict) -> list[str]:
    """Return falsified model claims about ``card`` as human-readable strings.

    Args:
        card: Printed card record (``name``, ``cmc``/``mana_value``,
            ``type_line``, ``mana_cost``, ``oracle_text``).
        reasoning: Model prose about that card.
        commander: Printed commander record, used for cast-trigger claims.

    Returns:
        Deduplicated messages, order preserved. An empty list means no
        supported check fired; it is not an endorsement of the prose.
    """
    card = card if isinstance(card, dict) else {}
    commander = commander if isinstance(commander, dict) else {}
    text = str(reasoning or "").lower()
    if not text:
        return []

    errors: list[str] = []
    subjects = _subject_pattern(card)
    _check_cost_phrasing(card, text, errors)
    _check_mana_value(card, text, subjects, errors)
    _check_cast_trigger(card, text, commander, subjects, errors)
    _check_modifier_shape(card, text, subjects, errors)
    _check_card_type(card, text, subjects, errors)
    return list(dict.fromkeys(errors))


# --- mana cost and mana value ---------------------------------------------


def _check_cost_phrasing(card: dict, text: str, errors: list[str]) -> None:
    """Phrasing like 'a one-mana instant' claims a payment, not a mana value."""
    printed = _printed_mv(card)
    if printed is None or _has_alternative_payment(card):
        return
    for match in _COST_CLAIM_RE.finditer(text):
        if _WORDS[match[1]] != printed:
            errors.append(MSG_MANA_COST)


def _check_mana_value(card: dict, text: str, subjects: str, errors: list[str]) -> None:
    """Mana value is printed and is never changed by how the spell was paid."""
    printed = _printed_mv(card)
    if printed is None or not subjects:
        return
    if "//" in str(card.get("type_line") or "") or "//" in str(card.get("name") or ""):
        return  # Multi-face mana values are ambiguous in prose; left unknown.
    patterns = (
        rf"\b(?:a|an)\s+(?:printed\s+)?{_MV_TERM}\s*({_NUMBER})\b" + _COMPARATOR,
        rf"\b(?:{subjects})\s+(?:has|have)\s+(?:an?\s+)?(?:printed\s+)?"
        rf"{_MV_TERM}\s*(?:of\s+)?({_NUMBER})\b" + _COMPARATOR,
        rf"\b(?:{subjects})(?:'s|s'|s)?\s+(?:printed\s+)?{_MV_TERM}\s*"
        rf"(?:is|=|:)\s*({_NUMBER})\b" + _COMPARATOR,
        rf"\b(?:{subjects})\s+(?:is|sits)\s+(?:an?\s+)?(?:at\s+)?"
        rf"{_MV_TERM}\s*({_NUMBER})\b" + _COMPARATOR,
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if _number(match[1]) != printed:
                errors.append(MSG_MANA_VALUE)


def _has_alternative_payment(card: dict) -> bool:
    oracle = str(card.get("oracle_text") or "").lower()
    if any(marker in oracle for marker in _ALT_PAYMENT_MARKERS):
        return True
    return bool(_PHYREXIAN_RE.search(str(card.get("mana_cost") or "")))


# --- commander cast triggers ----------------------------------------------


def _check_cast_trigger(
    card: dict, text: str, commander: dict, subjects: str, errors: list[str]
) -> None:
    """Honor the commander's printed trigger condition, threshold included."""
    trigger = _CAST_TRIGGER_RE.search(str(commander.get("oracle_text") or "").lower())
    names = _name_pattern(commander)
    if trigger is None or not names or not subjects:
        return
    triggers = _card_triggers(card, trigger)
    if triggers is None:
        return
    threshold = trigger.group("threshold") is not None
    negative = re.search(
        rf"\b(?:{subjects})\s+(?:does not|doesn't|won't|will not|never)\s+"
        rf"trigger\s+(?:{names})",
        text,
    )
    affirmative = re.search(
        rf"\b(?:{subjects})\s+(?:triggers|will trigger|does trigger)\s+(?:{names})",
        text,
    )
    if triggers and negative:
        errors.append(MSG_CAST_THRESHOLD if threshold else MSG_CAST_TRIGGER)
    if not triggers and affirmative:
        errors.append(MSG_CAST_THRESHOLD if threshold else MSG_CAST_TRIGGER)


def _card_triggers(card: dict, trigger: re.Match) -> bool | None:
    """True/False when printed data settles it, ``None`` when it does not."""
    types = str(card.get("type_line") or "").split(" // ")[0].lower()
    if not types or "land" in types:
        return None  # Lands are not cast; land halves are left unknown.
    kind = trigger.group("kind")
    if kind == "noncreature spell":
        matches_kind = "creature" not in types
    elif kind == "creature spell":
        matches_kind = "creature" in types
    elif kind == "instant or sorcery spell":
        matches_kind = "instant" in types or "sorcery" in types
    elif kind == "artifact spell":
        matches_kind = "artifact" in types
    elif kind == "enchantment spell":
        matches_kind = "enchantment" in types
    else:
        matches_kind = True
    if not matches_kind:
        return False
    raw_threshold = trigger.group("threshold")
    if raw_threshold is None:
        return True
    printed = _printed_mv(card)
    if printed is None:
        return None
    limit = float(raw_threshold)
    if trigger.group("direction") in ("greater", "more"):
        return printed >= limit
    return printed <= limit


# --- replacement-effect magnitude -----------------------------------------


def _check_modifier_shape(
    card: dict, text: str, subjects: str, errors: list[str]
) -> None:
    """'That many plus one' and 'twice that many' are not interchangeable."""
    oracle = str(card.get("oracle_text") or "")
    plus_one = bool(_PLUS_ONE_SHAPE_RE.search(oracle))
    doubling = bool(_DOUBLING_SHAPE_RE.search(oracle))
    if plus_one == doubling:
        return  # Neither shape, or both: not a check this module can settle.
    for sentence in _sentences(text):
        if not re.search(rf"\b(?:{subjects})\b", sentence) and not re.match(
            r"\s*(?:doubles?|doubling|twice)\b", sentence
        ):
            continue
        magnitude = _DOUBLING_CLAIM_RE.search(sentence)
        negated = magnitude and re.search(
            r"(?:does not|doesn't|rather than|instead of|not|without)\s*$",
            sentence[: magnitude.start()],
        )
        if plus_one and magnitude and not negated:
            errors.append(MSG_DOUBLING)
        if doubling and _ADD_ONE_CLAIM_RE.search(sentence):
            errors.append(MSG_ADD_ONE)


# --- printed types ---------------------------------------------------------


def _check_card_type(card: dict, text: str, subjects: str, errors: list[str]) -> None:
    """Only the type line states the card's types; rules text does not."""
    type_line = str(card.get("type_line") or "").lower()
    if not type_line or not subjects:
        return
    oracle = str(card.get("oracle_text") or "")
    pattern = (
        rf"\b(?:{subjects})\s+(?:is|are)\s+an?\s+"
        rf"(?:[a-z'\-]+\s+){{0,2}}"
        rf"\b({'|'.join(_TYPE_VOCABULARY)})\b" + _TYPE_CLAIM_TAIL
    )
    for match in re.finditer(pattern, text):
        claimed = match[1]
        if re.search(rf"\b{re.escape(claimed)}s?\b", type_line):
            continue
        if _TYPE_GRANT_RE.search(oracle) and re.search(
            rf"\b{re.escape(claimed)}\b", oracle, re.IGNORECASE
        ):
            continue  # The card may gain the type; printed text is ambiguous.
        errors.append(MSG_CARD_TYPE)


# --- shared helpers --------------------------------------------------------


def _subject_pattern(card: dict) -> str:
    """Alternation matching prose references to this specific card."""
    names: list[str] = []
    raw = str(card.get("name") or "").strip().lower()
    for face in raw.split(" // "):
        face = face.strip()
        if not face:
            continue
        names.append(face)
        head = face.split(",")[0].strip()
        if len(head) > 3 and head not in names:
            names.append(head)
    ordered = sorted(set(names), key=len, reverse=True)
    return "|".join(re.escape(part) for part in ordered + list(_GENERIC_SUBJECTS))


def _name_pattern(commander: dict) -> str:
    names: list[str] = []
    raw = str(commander.get("name") or "").strip().lower()
    for face in raw.split(" // "):
        face = face.strip()
        if not face:
            continue
        names.append(face)
        head = face.split(",")[0].strip()
        if len(head) > 2:
            names.append(head)
    ordered = sorted(set(names), key=len, reverse=True)
    return "|".join(re.escape(part) for part in ordered)


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"[.;\n]", text) if part.strip()]


def _number(token: str) -> float:
    token = token.strip().lower()
    if token in _WORDS:
        return float(_WORDS[token])
    return float(token)


def _printed_mv(card: Any) -> float | None:
    """Printed mana value, or ``None`` when the record does not carry one."""
    if not isinstance(card, dict):
        return None
    for key in ("cmc", "mana_value"):
        value = card.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                return None
    return None
