"""Evidence-based prerequisite evaluation for single cards against a decklist.

Scope is deliberately narrow: this is not a rules engine and never authorizes a
cut. Every result carries coverage="incomplete" and cut_authorized=False.
Statuses mean:
  supported   - a printed prerequisite has static supporting evidence in the deck
  unsupported - the caller declared the decklist complete and it statically lacks
                the named/typed/mana-value target
  unknown     - data is incomplete, parsing was partial, or the prerequisite
                depends on game state (colors of permanents, tokens, etc.)
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from typing import Any

COLOR_WORDS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4}

NAMED_SEARCH_RE = re.compile(
    r"[Ss]earch(?:es)? your library for a card named ([^,.;:\n)\"]+)"
)
TYPED_SEARCH_RE = re.compile(
    r"[Ss]earch(?:es)? your library for an? ([A-Z][\w'’-]*(?: [A-Z][\w'’-]*)*) card"
)
SAME_MV_RE = re.compile(
    r"[Ss]earch(?:es)? your library for a card with the same mana value as this card"
)
TRANSMUTE_RE = re.compile(r"Transmute (?:\{[^}]*\})+")
SACRIFICE_RE = re.compile(r"Sacrifice ([^:.\n]*)")
TOKEN_SOURCE_RE = re.compile(
    r"create[s]? (?:a|an|one|two|three|[0-9]+)[^.\n]*token", re.IGNORECASE
)
COLOR_CHANGE_RE = re.compile(
    r"(choose a color|the chosen color|becomes? the color|are the color)", re.IGNORECASE
)

BOILERPLATE = [
    r"put (?:it|them) onto the battlefield",
    r"put (?:it|them) into your hand(?: this way)?",
    r"reveal (?:it|them)",
    r"then shuffle",
    r"shuffle(?: your library)?",
]


def _as_list(value: Any) -> list[str]:
    """Accept either a real list or the JSON-encoded list form used by fixtures."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            return [str(v) for v in json.loads(value)]
        except ValueError:
            return []
    return []


def card_colors(card: dict[str, Any]) -> list[str] | None:
    """Actual colors of the card: explicit `colors`, else derived from mana_cost.

    color_identity is never consulted. Returns None when neither field exists,
    which callers treat as incomplete data rather than "colorless".
    """
    if "colors" in card:
        raw = card["colors"]
        if not isinstance(raw, list):
            try:
                raw = json.loads(raw) if isinstance(raw, str) else None
            except ValueError:
                raw = None
        if not isinstance(raw, list) or any(c not in COLOR_WORDS.values() for c in raw):
            return None
        return sorted(set(raw))
    cost = card.get("mana_cost")
    if (
        not isinstance(cost, str)
        or not cost
        or re.search(r"\bDevoid\b", str(card.get("oracle_text", "")))
    ):
        return None
    found = set()
    for symbol in re.findall(r"\{([^}]*)\}", str(cost)):
        for part in symbol.split("/"):
            if part.upper() in COLOR_WORDS.values():
                found.add(part.upper())
    return sorted(found)


def _is_creature(card: dict[str, Any]) -> bool:
    return "Creature" in str(card.get("type_line", "")).split(" // ")[0]


def _names(deck: Sequence[dict[str, Any]], indices: Sequence[int]) -> list[str]:
    return sorted({str(deck[i].get("name", "")) for i in indices})


def _match_distinct(
    reqs: list[str], pools: dict[str, list[int]], used: tuple[int, ...] = ()
) -> bool:
    """Can each required color be paid by a *different* deck card?"""
    if not reqs:
        return True
    for idx in pools.get(reqs[0], []):
        if idx in used:
            continue
        if _match_distinct(reqs[1:], pools, used + (idx,)):
            return True
    return False


def _ability(
    status: str,
    kind: str,
    evidence: list[str],
    requirements: dict[str, Any],
    reason: str,
    supporting_cards: list[str] | None = None,
) -> dict[str, Any]:
    out = {
        "status": status,
        "kind": kind,
        "evidence": evidence,
        "requirements": requirements,
        "reason": reason,
    }
    if supporting_cards is not None:
        out["supporting_cards"] = supporting_cards
    return out


def _missing(deck: Sequence[dict[str, Any]], field: str) -> list[str]:
    return sorted({str(c.get("name", "?")) for c in deck if c.get(field) in (None, "")})


def _resolve(
    found: list[str],
    catalog_complete: bool,
    incomplete: list[str],
    kind: str,
    evidence: list[str],
    requirements: dict[str, Any],
    target: str,
) -> dict[str, Any]:
    """Shared supported/unsupported/unknown resolution for search prerequisites."""
    if found:
        return _ability(
            "supported",
            kind,
            evidence,
            requirements,
            f"Deck statically contains {target}; this is card presence in the deck, "
            "not availability on the battlefield or in the library at any time.",
            found,
        )
    if incomplete:
        return _ability(
            "unknown",
            kind,
            evidence,
            dict(requirements, incomplete_data=incomplete),
            f"Deck entries lack the field needed to evaluate {target}.",
            [],
        )
    if catalog_complete:
        return _ability(
            "unsupported",
            kind,
            evidence,
            requirements,
            f"Decklist was supplied as complete and statically lacks {target}. This judges "
            "one prerequisite only; the card is not assessed as useless.",
            [],
        )
    return _ability(
        "unknown",
        kind,
        evidence,
        requirements,
        f"No match for {target}, but the decklist was not declared complete, so absence "
        "is not established.",
        [],
    )


def _named_search(
    match: re.Match, deck: Sequence[dict[str, Any]], catalog_complete: bool
) -> dict[str, Any]:
    target = match.group(1).strip()
    reqs: dict[str, Any] = {"searched_card_name": target}
    exact, faces = [], []
    for card in deck:
        name = str(card.get("name", ""))
        if name == target:
            exact.append(name)
        elif " // " in name and target in [f.strip() for f in name.split(" // ")]:
            faces.append(name)
    if not exact and faces:
        return _ability(
            "unknown",
            "named_search",
            [match.group(0)],
            dict(reqs, matched_split_card_faces=sorted(set(faces))),
            "Only a split/multi-face card whose face name matches was found; face-name "
            "matching is not confirmed by the supplied text, so this stays unknown.",
            sorted(set(faces)),
        )
    return _resolve(
        sorted(set(exact)),
        catalog_complete,
        _missing(deck, "name"),
        "named_search",
        [match.group(0)],
        reqs,
        f'a card named "{target}"',
    )


def _typed_search(
    match: re.Match, deck: Sequence[dict[str, Any]], catalog_complete: bool
) -> dict[str, Any]:
    kw = match.group(1).strip()
    pattern = re.compile(rf"\b{re.escape(kw)}\b")
    found = sorted(
        {
            str(c.get("name", ""))
            for c in deck
            if pattern.search(str(c.get("type_line", "")).split(" // ")[0])
        }
    )
    return _resolve(
        found,
        catalog_complete,
        (
            []
            if found
            else _missing(deck, "type_line")
            + [
                str(c.get("name", "?"))
                for c in deck
                if " // " in str(c.get("type_line", ""))
            ]
        ),
        "typed_search",
        [match.group(0)],
        {"searched_card_type": kw},
        f"a card whose type line includes {kw}",
    )


def _valid_mv(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _transmute(
    mv_match: re.Match,
    deck: Sequence[dict[str, Any]],
    card: dict[str, Any],
    catalog_complete: bool,
    extra_evidence: list[str],
) -> dict[str, Any]:
    source_mv = _valid_mv(card.get("cmc"))
    evidence = extra_evidence + [mv_match.group(0)]
    reqs: dict[str, Any] = {
        "same_mana_value_as_source": source_mv,
        "mana_value_source": "printed cmc of this card, not the activation cost",
    }
    if source_mv is None:
        return _ability(
            "unknown",
            "same_mana_value_search",
            evidence,
            reqs,
            "Printed mana value of the source card is missing, so targets cannot be scoped.",
            [],
        )
    found = sorted(
        {
            str(c.get("name", ""))
            for c in deck
            if _valid_mv(c.get("cmc")) == source_mv
            and str(c.get("name", "")) != str(card.get("name", ""))
        }
    )
    return _resolve(
        found,
        catalog_complete,
        (
            []
            if found
            else [
                str(c.get("name", "?")) for c in deck if _valid_mv(c.get("cmc")) is None
            ]
        ),
        "same_mana_value_search",
        evidence,
        reqs,
        f"another deck card with mana value {source_mv}",
    )


def _sacrifice(
    match: re.Match, deck: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    clause = match.group(1)
    if "creature" not in clause.lower():
        return None
    colors: dict[str, int] = {}
    generic = 0
    for part in re.split(r",| and ", clause):
        if "creature" not in part.lower():
            continue
        normalized = part.strip()
        parsed = re.fullmatch(
            r"(a|an|one|two|three|four|[0-9]+) (?:(white|blue|black|red|green) )?creatures?",
            normalized,
            re.IGNORECASE,
        )
        if not parsed:
            return _ability(
                "unknown",
                "sacrifice_colored_creatures",
                [match.group(0)],
                {"unparsed_cost": clause},
                "Sacrifice cost shape is not fully parsed; no resource counts are inferred.",
            )
        head = parsed.group(1).lower()
        count = int(head) if head.isdigit() else NUM_WORDS[head]
        word = parsed.group(2).lower() if parsed.group(2) else None
        if word:
            colors[word] = colors.get(word, 0) + count
        else:
            generic += count
    pools: dict[str, list[int]] = {}
    for word in colors:
        letter = COLOR_WORDS[word]
        pools[word] = [
            i
            for i, c in enumerate(deck)
            if _is_creature(c) and letter in (card_colors(c) or [])
        ]
    pools["any"] = [i for i, c in enumerate(deck) if _is_creature(c)]
    reqs: dict[str, Any] = {
        "sacrifice_colored_creatures": colors,
        "sacrifice_any_creatures": generic,
        "distinct_creatures_required": sum(colors.values()) + generic,
        "color_source": "card colors (or mana_cost fallback); color_identity is not used",
        "observed_matches": {w: _names(deck, pools[w]) for w in colors},
        "distinct_assignment_found": _match_distinct(
            [w for w, n in colors.items() for _ in range(n)] + ["any"] * generic, pools
        ),
        "colorless_or_unknown_color_entries": _missing(deck, "mana_cost"),
    }
    tokens = sorted(
        {
            str(c.get("name", ""))
            for c in deck
            if TOKEN_SOURCE_RE.search(str(c.get("oracle_text", "")))
        }
    )
    shifters = sorted(
        {
            str(c.get("name", ""))
            for c in deck
            if COLOR_CHANGE_RE.search(str(c.get("oracle_text", "")))
        }
    )
    reqs["token_sources"] = tokens
    reqs["color_changing_sources"] = shifters
    reason = (
        "Colored sacrifice costs depend on battlefield state: tokens, color-changing "
        "effects and creatures gained from opponents can all pay, so a static decklist "
        "cannot prove this impossible. Observed static matches are listed as support."
    )
    if tokens or shifters:
        reason += (
            " Explicit caveat: the deck contains token-creating and/or color-changing "
            "sources ({}), which can supply colors not present on printed cards.".format(
                ", ".join(tokens + shifters)
            )
        )
    support = sorted({n for w in colors for n in reqs["observed_matches"][w]})
    return _ability(
        "unknown",
        "sacrifice_colored_creatures",
        [match.group(0)],
        reqs,
        reason,
        support,
    )


def _residual_is_empty(paragraph: str, spans: list[tuple[int, int]]) -> bool:
    chars = list(paragraph)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    text = "".join(chars)
    text = re.sub(r"\{[^}]*\}", " ", text)
    for pattern in BOILERPLATE:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return not re.search(r"[A-Za-z0-9]", text)


def evaluate_prerequisites(
    card: dict[str, Any], deck: list[dict[str, Any]], *, catalog_complete: bool = False
) -> dict[str, Any]:
    """Evaluate the printed prerequisites of `card` against `deck`.

    catalog_complete asserts only that the supplied decklist is complete; it never
    means the rules coverage here is complete.
    """
    deck = list(deck or [])
    abilities: list[dict[str, Any]] = []
    fallback_text: list[str] = []
    remaining_text: list[str] = []
    oracle = card.get("oracle_text")

    if not oracle:
        abilities.append(
            _ability(
                "unknown",
                "incomplete_data",
                [],
                {},
                "No oracle text was supplied for this card.",
                [],
            )
        )
        oracle = ""

    for paragraph in str(oracle).split("\n"):
        if not paragraph.strip():
            continue
        spans: list[tuple[int, int]] = []
        produced: list[dict[str, Any]] = []
        for match in NAMED_SEARCH_RE.finditer(paragraph):
            produced.append(_named_search(match, deck, catalog_complete))
            spans.append(match.span())
        for match in TYPED_SEARCH_RE.finditer(paragraph):
            if any(s <= match.start() < e for s, e in spans):
                continue
            produced.append(_typed_search(match, deck, catalog_complete))
            spans.append(match.span())
        for match in SAME_MV_RE.finditer(paragraph):
            extra = [m.group(0) for m in TRANSMUTE_RE.finditer(paragraph)]
            produced.append(_transmute(match, deck, card, catalog_complete, extra))
            spans.append(match.span())
            for m in TRANSMUTE_RE.finditer(paragraph):
                spans.append(m.span())
        for match in SACRIFICE_RE.finditer(paragraph):
            ability = _sacrifice(match, deck)
            if ability is not None:
                produced.append(ability)
                spans.append(match.span())
        abilities.extend(produced)
        if not produced:
            remaining_text.append(paragraph)
        elif not _residual_is_empty(paragraph, spans):
            fallback_text.append(paragraph)

    return {
        "abilities": abilities,
        "fallback_text": fallback_text,
        "remaining_text": remaining_text,
        "coverage": "incomplete",
        "cut_authorized": False,
    }
