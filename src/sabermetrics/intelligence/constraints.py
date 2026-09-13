"""Deterministic deck-constraint audits for declared lines, not a rules engine.

This module answers two narrow questions about a finished list:

* ``audit_deck`` — do the printed prerequisites of supported card shapes hold in
  this exact 99? It reports broken declared lines, missing named search targets
  and prerequisites it cannot prove.
* ``tutor_targets`` — which entries of the provided list does a supported search
  effect actually match, using printed mana value, type line and zone rules?

Only supported printed shapes are parsed. An empty finding list is **not** a
proof that a deck is sound, and an unmatched card is **not** a claim that the
card does nothing: both cases are reported as ``unknown`` wherever the caller
could otherwise read silence as a verdict. Nothing here calls a model, the deck
builder, or a data store, and nothing here is a legality checker.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Final

# --- vocabulary ------------------------------------------------------------

SEVERITY_ERROR: Final = "error"
SEVERITY_WARNING: Final = "warning"
SEVERITY_UNKNOWN: Final = "unknown"
SEVERITIES: Final = (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_UNKNOWN)

# Search resolved against the provided list.
STATUS_RESOLVED: Final = "resolved"
# A search or tutor clause is present but its printed shape is not supported.
STATUS_UNKNOWN: Final = "unknown"
# No library-search or transmute shape was found at all.
STATUS_NONE: Final = "none"
STATUSES: Final = (STATUS_RESOLVED, STATUS_UNKNOWN, STATUS_NONE)

CODE_PACT_DUPLICATE_NAMES: Final = "pact_duplicate_names"
CODE_NAMED_SEARCH_NO_TARGET: Final = "named_search_no_target"
CODE_NAMED_SEARCH_TYPES_UNKNOWN: Final = "named_search_types_unknown"
CODE_TRANSMUTE_NO_TARGET: Final = "transmute_no_target"
CODE_TRANSMUTE_TARGETS_UNKNOWN: Final = "transmute_targets_unknown"
CODE_SACRIFICE_COLOR_UNPROVEN: Final = "sacrifice_color_unproven"
CODE_SACRIFICE_COLOR_UNSATISFIED: Final = "sacrifice_color_unsatisfied"

COLOR_LETTERS: Final = {
    "white": "W",
    "blue": "U",
    "black": "B",
    "red": "R",
    "green": "G",
}

BASIC_LAND_NAMES: Final = frozenset(
    {
        "plains",
        "island",
        "swamp",
        "mountain",
        "forest",
        "wastes",
        "snow-covered plains",
        "snow-covered island",
        "snow-covered swamp",
        "snow-covered mountain",
        "snow-covered forest",
    }
)

# --- supported printed shapes ---------------------------------------------
# Each pattern below describes one printed shape. Anything broader is left
# undetected on purpose and surfaces as an explicit unknown.

# Tainted Pact style: repeat-until-duplicate-name exile of your own library.
_PACT_EXILE_RE = re.compile(r"exile the top card of your library", re.IGNORECASE)
_PACT_STOP_RE = re.compile(r"exile (?:two|2) cards with the same name", re.IGNORECASE)

# Laboratory Maniac / Jace, Wielder of Mysteries / Thassa's Oracle.
_LIBRARY_EMPTY_PAYOFF_RE = re.compile(
    r"(?:while|if) (?:your|their) library has no cards in it"
    r"[^.\n]{0,80}you win the game"
    r"|(?:number of cards in your library)[^.\n]{0,60}you win the game",
    re.IGNORECASE,
)
# Printed text is the evidence; these names are a fallback for records whose
# oracle text was not supplied. They are not a closed list of real payoffs.
_LIBRARY_EMPTY_PAYOFF_NAMES: Final = frozenset(
    {"thassa's oracle", "laboratory maniac", "jace, wielder of mysteries"}
)

_SEARCH_RE = re.compile(r"[Ss]earch your library for ([^.\n]{0,90})")
# "a Dragon card", "an Elf permanent card", "up to two Dragon cards".
_NAMED_TARGET_RE = re.compile(
    r"^(?:up to \w+\s+)?(?:a|an|one|two|three)\s+"
    r"([A-Z][A-Za-z'-]+)\s+(?:permanent\s+)?cards?\b"
)
_TRANSMUTE_RE = re.compile(r"\btransmute\b\s*((?:\{[^{}\n]{1,4}\})+)?", re.IGNORECASE)
# "{T}, Sacrifice a green creature:" — a colored prerequisite on an activation.
# The noun is restricted to words that appear in a printed type line, so the
# audit never reasons about a category it cannot check ("a green permanent").
_SACRIFICE_COLOR_RE = re.compile(
    r"[Ss]acrifice (?:a|an|another|two|three)\s+"
    r"(white|blue|black|red|green)\s+"
    r"(creature|artifact|enchantment|land|planeswalker)\b",
)
_MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")


def audit_deck(cards: list[dict], commander: dict) -> list[dict]:
    """Report broken or unprovable printed prerequisites in a finished list.

    Args:
        cards: The 99 mainboard entries as dicts with at least ``name``, and
            ideally ``oracle_text``, ``type_line``, ``cmc``/``mana_value``,
            ``colors`` and ``mana_cost``. Non-dict entries are ignored.
        commander: The commander record. It is used only to note that a
            command-zone card is not a legal library-search target; commander
            color identity is never treated as proof about card colors.

    Returns:
        A list of ``{code, severity, card, message}`` dicts in deck order.
        ``severity`` is ``error`` (a declared line in this list is broken),
        ``warning`` (a printed prerequisite has no match here, but the card is
        still legal and playable) or ``unknown`` (the supplied data cannot
        settle the prerequisite either way). An empty list means no supported
        rule fired, not that the deck is sound.
    """
    deck = [c for c in (cards or []) if isinstance(c, dict)]
    cmdr = commander if isinstance(commander, dict) else {}
    findings: list[dict[str, Any]] = []
    findings.extend(_audit_repeat_exile_line(deck, commander))
    for card in deck:
        findings.extend(_audit_named_search(card, deck, cmdr))
        findings.extend(_audit_sacrifice_prerequisite(card, deck))
        findings.extend(_audit_transmute(card, deck))
    return _dedupe(findings)


def tutor_targets(card: dict, cards: list[dict]) -> dict:
    """Resolve a supported search effect against the provided list.

    Args:
        card: The card holding the search effect. ``oracle_text`` carries the
            printed shape; ``cmc``/``mana_value`` carries the printed mana
            value used by transmute.
        cards: Entries the search may find. The source card is excluded from
            its own target list (it is on the stack or in hand when the effect
            is used, not in the library).

    Returns:
        ``{status, targets, limitations}``. ``status`` is ``resolved`` (shape
        supported, ``targets`` enumerated from this list), ``unknown`` (a
        search clause is present but its shape or the supplied data is not
        supported) or ``none`` (no search or transmute shape found). ``targets``
        is a list of names in list order; an empty list under ``resolved`` means
        this list contains no legal choice. ``limitations`` is always populated
        for a resolved search and states what the target list does not prove.
    """
    if not isinstance(card, dict):
        return {"status": STATUS_NONE, "targets": [], "limitations": []}
    pool = [c for c in (cards or []) if isinstance(c, dict)]
    oracle = _oracle(card)

    exact = _exact_named_target(oracle)
    if exact:
        return {
            "status": STATUS_RESOLVED,
            "targets": [
                _name(c)
                for c in pool
                if _name(c).casefold() == exact.casefold()
                and not _is_same_card(card, c)
            ],
            "limitations": [
                "Named target must still be in the library when the effect resolves."
            ],
        }
    transmute = _transmute_cost(card)
    if transmute is not None:
        return _transmute_targets(card, pool, transmute)

    named = _named_search_type(oracle)
    if named:
        return _named_targets(card, pool, named)

    clause = _SEARCH_RE.search(oracle)
    if clause is not None:
        return {
            "status": STATUS_UNKNOWN,
            "targets": [],
            "limitations": [
                (
                    "Library search is present but its printed shape is not "
                    f"supported here: 'search your library for {clause[1].strip()}'."
                ),
                "Unknown means unparsed, not that the effect finds nothing.",
            ],
        }
    return {
        "status": STATUS_NONE,
        "targets": [],
        "limitations": [
            (
                "No library-search or transmute shape was found in the supplied "
                "oracle text. Missing oracle text reads the same as no search."
            )
        ],
    }


# --- deck-level rules ------------------------------------------------------


def _audit_repeat_exile_line(deck: list[dict], commander: dict) -> list[dict]:
    """Flag repeated names only when a library-emptying payoff is present.

    A Tainted Pact style effect stops at the second copy of any card name, so
    repeated basics cap how deep it digs. On its own that is a fine deck: the
    card still digs for a specific answer. The line only breaks when the list
    also contains a payoff that needs the library actually emptied.
    """
    pact_cards = [c for c in deck if _is_repeat_exile_shape(c)]
    if not pact_cards:
        return []
    payoffs = [c for c in deck if _is_library_empty_payoff(c)]
    if not payoffs:
        return []
    duplicates = _duplicate_names(deck)
    if not duplicates:
        return []

    summary = ", ".join(f"{name} x{count}" for name, count in duplicates)
    basics = [name for name, _ in duplicates if name.lower() in BASIC_LAND_NAMES]
    payoff_names = ", ".join(sorted({_name(c) for c in payoffs if _name(c)}))
    legality = (
        " Duplicate basic land names are legal in Commander; the broken"
        " constraint concerns library emptying, not deck legality."
        if basics
        else ""
    )
    return [
        _finding(
            CODE_PACT_DUPLICATE_NAMES,
            (
                SEVERITY_ERROR
                if "pact_library_empty" in commander.get("_declared_lines", [])
                else SEVERITY_WARNING
            ),
            _name(pact),
            f"{_name(pact)} stops exiling at the second copy of a repeated "
            f"name, so it cannot reliably empty this library: {summary}. "
            f"The list also contains {payoff_names}; this is a conditional line risk, not proof that the line was declared."
            + legality,
        )
        for pact in pact_cards
    ]


def _duplicate_names(deck: list[dict]) -> list[tuple[str, int]]:
    counts = Counter(_name(c) for c in deck if _name(c))
    repeated = [(name, count) for name, count in counts.items() if count > 1]
    return sorted(repeated, key=lambda item: (-item[1], item[0]))


def _is_repeat_exile_shape(card: dict) -> bool:
    oracle = _oracle(card)
    return bool(_PACT_EXILE_RE.search(oracle) and _PACT_STOP_RE.search(oracle))


def _is_library_empty_payoff(card: dict) -> bool:
    if _LIBRARY_EMPTY_PAYOFF_RE.search(_oracle(card)):
        return True
    return _name(card).lower() in _LIBRARY_EMPTY_PAYOFF_NAMES


# --- card-level rules ------------------------------------------------------


def _audit_named_search(card: dict, deck: list[dict], commander: dict) -> list[dict]:
    """A named search needs a real target in the library, not in the theme."""
    exact = _exact_named_target(_oracle(card))
    if exact:
        if any(
            _name(c).casefold() == exact.casefold()
            for c in deck
            if not _is_same_card(card, c)
        ):
            return []
        return [
            _finding(
                CODE_NAMED_SEARCH_NO_TARGET,
                SEVERITY_WARNING,
                _name(card),
                f"Named search target {exact} is absent from the library list. The optional ability has no listed target; the card is not illegal.",
            )
        ]
    named = _named_search_type(_oracle(card))
    if not named:
        return []
    resolved = _named_targets(card, deck, named)
    if resolved["targets"]:
        return []
    untyped = sum(1 for c in deck if not _is_same_card(card, c) and not _type_line(c))
    if resolved["status"] == STATUS_UNKNOWN or untyped:
        return [
            _finding(
                CODE_NAMED_SEARCH_TYPES_UNKNOWN,
                SEVERITY_UNKNOWN,
                _name(card),
                f"{_name(card)} searches for a {named} card and no typed entry "
                f"matches, but {untyped} supplied entries carry no type line, "
                "so a target cannot be confirmed or ruled out.",
            )
        ]
    command_zone = (
        f" {_name(commander)} matches {named} but sits in the command zone,"
        " which a library search cannot reach."
        if _matches_named_type(commander, named)
        else ""
    )
    return [
        _finding(
            CODE_NAMED_SEARCH_NO_TARGET,
            SEVERITY_WARNING,
            _name(card),
            f"{_name(card)} searches for a {named} card and no entry in this "
            f"list has {named} in its type line, so the search can only fail "
            "to find." + command_zone + " The card stays legal and castable; "
            "this is an unusable optional ability, not an illegal inclusion.",
        )
    ]


def _audit_sacrifice_prerequisite(card: dict, deck: list[dict]) -> list[dict]:
    """Colored sacrifice costs are only satisfied by proven card colors."""
    match = _SACRIFICE_COLOR_RE.search(_oracle(card))
    if not match:
        return []
    color_word, noun = match[1].lower(), match[2].lower()
    letter = COLOR_LETTERS[color_word]
    pool = [c for c in deck if _name(c) != _name(card) and _matches_noun(c, noun)]
    if not pool:
        return [
            _finding(
                CODE_SACRIFICE_COLOR_UNSATISFIED,
                SEVERITY_WARNING,
                _name(card),
                f"{_name(card)} needs to sacrifice a {color_word} {noun} and "
                f"this list has no other {noun} entry at all.",
            )
        ]
    unproven = 0
    for other in pool:
        colors = _card_colors(other)
        if colors is None:
            unproven += 1
        elif letter in colors:
            return []
    if unproven:
        return [
            _finding(
                CODE_SACRIFICE_COLOR_UNPROVEN,
                SEVERITY_UNKNOWN,
                _name(card),
                f"{_name(card)} needs to sacrifice a {color_word} {noun}. No "
                f"entry is proven {color_word} and {unproven} {noun} entries "
                "carry no printed colors or mana cost. Deck color identity is "
                f"not proof that any {noun} is {color_word}.",
            )
        ]
    return [
        _finding(
            CODE_SACRIFICE_COLOR_UNSATISFIED,
            SEVERITY_WARNING,
            _name(card),
            f"{_name(card)} needs to sacrifice a {color_word} {noun}; "
            "the static color scan found no matching entry. "
            "Token production and color-changing effects are not modeled by this "
            "check, so activation feasibility remains unproven. The card is still legal.",
        )
    ]


def _audit_transmute(card: dict, deck: list[dict]) -> list[dict]:
    cost = _transmute_cost(card)
    if cost is None:
        return []
    resolved = _transmute_targets(card, deck, cost)
    if resolved["targets"]:
        return []
    source_mv = _printed_mv(card)
    if resolved["status"] == STATUS_UNKNOWN or source_mv is None:
        return [
            _finding(
                CODE_TRANSMUTE_TARGETS_UNKNOWN,
                SEVERITY_UNKNOWN,
                _name(card),
                f"{_name(card)} transmutes for its own printed mana value, "
                "which is missing from the supplied data, so its target set "
                "cannot be resolved.",
            )
        ]
    unknown_mv = sum(
        1 for c in deck if not _is_same_card(card, c) and _printed_mv(c) is None
    )
    if unknown_mv:
        return [
            _finding(
                CODE_TRANSMUTE_TARGETS_UNKNOWN,
                SEVERITY_UNKNOWN,
                _name(card),
                f"{_name(card)} transmutes for printed mana value "
                f"{_mv_text(source_mv)}; no entry with known mana value "
                f"matches and {unknown_mv} entries have no mana value data.",
            )
        ]
    shown_cost = cost or "an unparsed cost"
    return [
        _finding(
            CODE_TRANSMUTE_NO_TARGET,
            SEVERITY_WARNING,
            _name(card),
            f"{_name(card)} transmutes only for printed mana value "
            f"{_mv_text(source_mv)} and no other entry in this list has that "
            f"mana value. The transmute cost {shown_cost} is what you pay, "
            "not what you search for.",
        )
    ]


# --- target resolution -----------------------------------------------------


def _named_targets(card: dict, pool: list[dict], named: str) -> dict:
    typed = [c for c in pool if not _is_same_card(card, c) and _type_line(c)]
    if not typed:
        return {
            "status": STATUS_UNKNOWN,
            "targets": [],
            "limitations": [
                (
                    f"Search for a {named} card could not be resolved: no supplied "
                    "entry carries a type line."
                )
            ],
        }
    targets = _names_in_order(c for c in typed if _matches_named_type(c, named))
    limitations = [
        (
            f"Only entries with {named} in the printed type line are legal "
            "choices; a themed name or rules text mention is not a type."
        ),
        (
            "Targets are deck entries, not proof the card is still in the library "
            "when the search resolves."
        ),
        "A commander in the command zone is not a legal library-search target.",
    ]
    sacrifice = _SACRIFICE_COLOR_RE.search(_oracle(card))
    if sacrifice:
        limitations.append(
            f"Using this ability also requires sacrificing a {sacrifice[1].lower()} "
            f"{sacrifice[2].lower()}, which this target list does not prove."
        )
    untyped = sum(1 for c in pool if not _is_same_card(card, c) and not _type_line(c))
    if untyped:
        limitations.append(
            f"{untyped} supplied entries carry no type line and were neither "
            "included nor ruled out."
        )
    if not targets:
        limitations.append(
            f"No supplied entry has {named} in its type line, so the search "
            "can only fail to find."
        )
    return {"status": STATUS_RESOLVED, "targets": targets, "limitations": limitations}


def _transmute_targets(card: dict, pool: list[dict], cost: str) -> dict:
    """Transmute searches for the transmuted card's printed mana value.

    The activation cost is what you pay; it is never the searched mana value.
    A printed mana value of 1 therefore cannot find a 0 or a 3.
    """
    source_mv = _printed_mv(card)
    if source_mv is None:
        return {
            "status": STATUS_UNKNOWN,
            "targets": [],
            "limitations": [
                (
                    "Transmute is present but the card's printed mana value is "
                    "missing, so the searched mana value is unknown."
                )
            ],
        }
    others = [c for c in pool if not _is_same_card(card, c)]
    targets = _names_in_order(c for c in others if _printed_mv(c) == source_mv)
    unknown_mv = [c for c in others if _printed_mv(c) is None]
    shown_cost = cost or "an unparsed cost"
    limitations = [
        (
            "Transmute searches for a card with printed mana value "
            f"{_mv_text(source_mv)} exactly; no other mana value is a legal choice."
        ),
        (
            f"The transmute cost {shown_cost} is the activation cost and is not "
            "the searched mana value."
        ),
        (
            "Transmute is activated from your hand, discards this card, and puts "
            "the found card into your hand; it does not cast anything."
        ),
        (
            "Targets are deck entries, not proof the card is still in the library "
            "when transmute resolves."
        ),
    ]
    if unknown_mv:
        limitations.append(
            f"{len(unknown_mv)} supplied entries have no mana value data and "
            "were neither included nor ruled out."
        )
    return {"status": STATUS_RESOLVED, "targets": targets, "limitations": limitations}


def _named_search_type(oracle: str) -> str | None:
    for clause in _SEARCH_RE.finditer(oracle):
        match = _NAMED_TARGET_RE.match(clause[1].strip())
        if match:
            return match[1]
    return None


def _matches_named_type(card: Any, named: str) -> bool:
    if not isinstance(card, dict):
        return False
    line = _type_line(card).lower()
    if not line:
        return False
    subtypes = line.split("—")[-1] if "—" in line else line
    return re.search(rf"\b{re.escape(named.lower())}s?\b", subtypes) is not None


def _matches_noun(card: dict, noun: str) -> bool:
    line = _type_line(card).lower()
    return bool(line) and re.search(rf"\b{re.escape(noun)}s?\b", line) is not None


# --- card data helpers -----------------------------------------------------


def _transmute_cost(card: dict) -> str | None:
    match = _TRANSMUTE_RE.search(_oracle(card))
    if not match:
        return None
    return match[1] or ""


def _card_colors(card: dict) -> set[str] | None:
    """Printed colors, or ``None`` when they are not independently proven.

    Color identity is deliberately not consulted: a card legal in a green deck
    is not therefore a green card, and a colorless artifact creature in a green
    deck never satisfies a "sacrifice a green creature" cost.
    """
    raw = card.get("colors")
    if isinstance(raw, (list, tuple, set)):
        return {str(c).strip().upper() for c in raw if str(c).strip()}
    cost = card.get("mana_cost")
    if not isinstance(cost, str) or not cost.strip():
        return None
    if "devoid" in _oracle(card).lower():
        return None
    colors: set[str] = set()
    for symbol in _MANA_SYMBOL_RE.findall(cost.upper()):
        for part in re.split(r"[/]", symbol):
            if part in COLOR_LETTERS.values():
                colors.add(part)
    return colors


def _printed_mv(card: Any) -> float | None:
    if not isinstance(card, dict):
        return None
    for key in ("cmc", "mana_value"):
        value = card.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _mv_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _oracle(card: Any) -> str:
    if not isinstance(card, dict):
        return ""
    return str(card.get("oracle_text") or "")


def _type_line(card: Any) -> str:
    if not isinstance(card, dict):
        return ""
    return str(card.get("type_line") or "")


def _name(card: Any) -> str:
    if not isinstance(card, dict):
        return ""
    return str(card.get("name") or "").strip()


def _is_same_card(source: dict, other: dict) -> bool:
    """Identity for "this effect cannot find itself"."""
    source_id, other_id = source.get("id"), other.get("id")
    if source_id is not None and other_id is not None:
        return bool(source_id == other_id)
    return _name(source) == _name(other) and bool(_name(source))


def _names_in_order(cards) -> list[str]:
    seen: dict[str, None] = {}
    for card in cards:
        name = _name(card)
        if name:
            seen.setdefault(name, None)
    return list(seen)


def _finding(code: str, severity: str, card: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "card": card, "message": message}


def _dedupe(findings: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for finding in findings:
        key = (finding["code"], finding["card"], finding["message"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def _exact_named_target(oracle: str) -> str | None:
    match = re.search(
        r"search your library for (?:a|an) card named ([^.\n]{1,200}?)(?=, (?:put|reveal)|\.)",
        oracle,
        re.IGNORECASE,
    )
    return match[1].strip() if match else None
