"""Bounded whole-deck support checks; target counts are not gameplay availability."""

import re
from collections import Counter

from sabermetrics.intelligence.commander_contracts import (
    cast_categories,
    printed_mana_value,
)

_TYPES = {
    "artifact",
    "creature",
    "enchantment",
    "instant",
    "sorcery",
    "land",
    "planeswalker",
}
_SEARCH = re.compile(
    r"search your library for (?:a|an) (?:(artifact|creature|enchantment|instant|sorcery|land|planeswalker|instant or sorcery) )?card with mana value (\d+)( or less| or greater)?(?=[,.])",
    re.IGNORECASE,
)
_SENSITIVE = re.compile(
    r"mana value|converted mana cost|mana cost|cascade|discover|devotion|\bodd\b|\beven\b|mana spent|mana you spent|spend[^.\n]*mana|spent[^.\n]*cast|cost[^.\n]*cast",
    re.IGNORECASE,
)
_CAST = re.compile(
    r"whenever you cast (?:a|an) (noncreature|artifact|creature|enchantment|instant|sorcery|instant or sorcery) spell",
    re.IGNORECASE,
)


def _costs(cards):
    return Counter((printed_mana_value(c), c.get("mana_cost")) for c in cards)


def _count(cards, types, value, direction):
    def qualifies(card):
        mv = printed_mana_value(card)
        if mv is None:
            return False
        front = (
            (card.get("type_line") or "").split(" // ")[0].lower().split("—")[0].split()
        )
        if types and not set(types) & set(front):
            return False
        return (
            mv <= value
            if direction == " or less"
            else mv >= value
            if direction == " or greater"
            else mv == value
        )

    return sum(qualifies(c) for c in cards)


def validate_deck_context(before, after, commander):
    """Retain detected support across the complete transaction, including joint cuts.

    These are additional vetoes. Passing them never authorizes an effect swap or
    proves the library/board can supply a target at a particular time.
    """
    checks, losses = [], []
    cost_changed = _costs(before) != _costs(after)
    for provider in [commander, *before]:
        text = provider.get("oracle_text") or ""
        for reference in re.findall(r"\bnamed\b[^.\n]*", text, re.IGNORECASE):
            for name in sorted({c["name"] for c in before}):
                if re.search(
                    r"(?<!\w)" + re.escape(name) + r"(?!\w)", reference, re.IGNORECASE
                ):
                    a = sum(c["name"] == name for c in before)
                    b = sum(c["name"] == name for c in after)
                    row = {
                        "provider": provider.get("name"),
                        "kind": "named_card_reference",
                        "target": name,
                        "before": a,
                        "after": b,
                        "evidence": reference,
                    }
                    checks.append(row)
                    if b < a:
                        losses.append(row)
        remainder = text
        predicates = []
        for match in _SEARCH.finditer(text):
            types = match[1].lower().split(" or ") if match[1] else []
            predicates.append(
                (types, int(match[2]), (match[3] or "").lower(), match[0])
            )
            remainder = remainder.replace(match[0], "")
        transmute = re.search(
            r"search your library for a card with the same mana value as this card",
            text,
            re.IGNORECASE,
        )
        if transmute and re.search(r"\btransmute\b", text, re.IGNORECASE):
            mv = printed_mana_value(provider)
            if mv is not None:
                predicates.append(([], mv, "", transmute[0]))
                remainder = remainder.replace(transmute[0], "")
        for types, value, direction, evidence in predicates:
            # The provider is the access route, not evidence it can find itself.
            old = [c for c in before if c.get("name") != provider.get("name")]
            new = [c for c in after if c.get("name") != provider.get("name")]
            a, b = (
                _count(old, types, value, direction),
                _count(new, types, value, direction),
            )
            row = {
                "provider": provider.get("name"),
                "kind": "mana_value_access",
                "evidence": evidence,
                "before": a,
                "after": b,
            }
            checks.append(row)
            if b < a:
                losses.append(row)
        if cost_changed and _SENSITIVE.search(remainder):
            losses.append(
                {
                    "provider": provider.get("name"),
                    "kind": "unparsed_cost_sensitivity",
                    "evidence": remainder,
                    "reason": "Preserve exact deck casting-resource multiset until this dependency is modeled.",
                }
            )
        for match in _CAST.finditer(text):
            category = match[1].lower()
            a = sum(category in cast_categories(c) for c in before)
            b = sum(category in cast_categories(c) for c in after)
            row = {
                "provider": provider.get("name"),
                "kind": "cast_category",
                "evidence": match[0],
                "before": a,
                "after": b,
            }
            checks.append(row)
            if b < a:
                losses.append(row)
    return {
        "allowed": not losses,
        "checks": checks,
        "losses": losses,
        "scope": "Detected static access and cast categories only; not battlefield/library availability or complete interaction coverage.",
    }
