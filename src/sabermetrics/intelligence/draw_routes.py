"""Conservative, name-invariant Oracle-text compiler for draw routes.

route_profile(card) -> {"routes": [...], "unknown_clauses": [...], "complete": bool}

Only exact recognizers are implemented. Any draw-bearing clause that is not
recognized is reported verbatim in ``unknown_clauses`` and marks the profile
incomplete. Nothing is ever silently assumed free, generic, or absent.

Route mana schema
  spell      mana=casting MV, setup_mana=0, cost=casting cost string
  etb        mana=casting MV, setup_mana=0, cost=casting cost string
  channel    mana=channel cost, setup_mana=0, cost=channel cost string
  activated  mana=activation mana, setup_mana=casting MV, cost=activation string
  attack / combat_damage / triggered (passive on a permanent)
             mana=0, setup_mana=casting MV, cost=""
Any unknown mana amount inside a recognized route forces supported=False.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

KINDS = ("spell", "etb", "attack", "combat_damage", "activated", "channel", "triggered")
Route = dict[str, Any]

_NUM_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
}
_NUM_ALT = "|".join(_NUM_WORDS)
_FULL_COST_RE = re.compile(r"^(\{[^{}]+\})+$")
_SYMBOL_RE = re.compile(r"\{([^{}]+)\}")
_DRAW_RE = re.compile(r"\bdraws?\b(?![ -]steps?\b)", re.IGNORECASE)


# --------------------------------------------------------------------------- mana
def parse_mana(cost: str | None) -> float | None:
    """Sum finite numeric and single-colour symbols of a cost string that consists
    entirely of {..} symbols. Return None for anything else (X, hybrid, phyrexian,
    snow, tap, malformed, empty) so unknown costs are never treated as free."""
    if not isinstance(cost, str) or not _FULL_COST_RE.match(cost):
        return None
    total = 0.0
    for sym in _SYMBOL_RE.findall(cost):
        if sym.isdigit():
            try:
                total += float(sym)
            except (ValueError, OverflowError):
                return None
        elif sym in ("W", "U", "B", "R", "G", "C"):
            total += 1.0
        else:
            return None
    return total if math.isfinite(total) else None


# ----------------------------------------------------------------------- helpers
def _normalize(text: str, name: str) -> str:
    """Replace whole-word self-references with '~' so renamed cards match."""
    if not name:
        return text
    out = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", "~", text)
    short = name.split(",")[0].strip()
    if short and short != name:
        out = re.sub(r"(?<!\w)" + re.escape(short) + r"(?!\w)", "~", out)
    return re.sub(r"\bthis creature\b", "~", out)


def _clauses(text: str) -> list[str]:
    """Split Oracle text into paragraphs with reminder text removed."""
    stripped = re.sub(r"\s*\([^()]*\)", "", text)
    return [p.strip() for p in stripped.split("\n") if p.strip()]


def _route(
    kind: str,
    mana: float | None,
    setup: float | None,
    cost: str | None,
    draw: int | None,
    net: int | None,
    repeatable: bool,
    prereqs: list[str],
    evidence: str,
    supported: bool = True,
) -> Route:
    assert kind in KINDS
    if mana is None or setup is None:
        supported = False
    if not supported and "unsupported" not in prereqs:
        prereqs = list(prereqs) + ["unsupported"]
    return {
        "kind": kind,
        "mana": mana,
        "setup_mana": setup,
        "cost": cost,
        "draw_count": draw,
        "net_cards": net,
        "repeatable": repeatable,
        "prerequisites": list(prereqs),
        "evidence": evidence,
        "supported": supported,
    }


def _passive(
    ctx: dict[str, Any], kind: str, draw: int, net: int, prereqs: list[str], clause: str
) -> Route:
    return _route(kind, 0.0, ctx["mana"], "", draw, net, True, prereqs, clause)


# ------------------------------------------------------------------- recognizers
_SPELL_DRAW = re.compile(rf"^Draw ({_NUM_ALT}) cards?\.$", re.IGNORECASE)
_CHANNEL = re.compile(r"^Channel\s*[—-]\s*((?:\{[^{}]+\})+), Discard this card: (.+)$")
_CHANNEL_EFFECTS = (
    re.compile(rf"^Draw ({_NUM_ALT}) cards?\.$"),
    re.compile(
        r"^Put a \+1/\+1 counter on each creature you control\. Draw (a) card\.$"
    ),
)
_SHORELINE = re.compile(
    r"^Whenever (?:~|this creature) deals combat damage to a player, "
    r"if you control an Island, you may draw a card\.$"
)
_TAX = re.compile(
    r"^Whenever an opponent casts an? (noncreature )?spell, you may draw a card "
    r"unless that player pays (\{\d+\})\.$"
)
_MOLDERVINE = re.compile(
    r"^Whenever a creature you control dies, you gain 1 life and draw a card\.$"
)
_SANCTUARY = re.compile(
    r"^Whenever (?:~|this creature) enters or attacks, you may remove a counter from a "
    r"creature or planeswalker you control\. If you do, draw a card and create a "
    r"1/1 green and white Citizen creature token\.$"
)
_ARENA = re.compile(
    r"^At the beginning of your upkeep, you draw a card and you lose 1 life\.$"
)
_UNAGI = re.compile(
    r"^Whenever an opponent draws their second card each turn, you draw two cards\.$"
)
_ACTIVATED = re.compile(
    rf"^((?:\{{[^{{}}]+\}}, )*)\{{T\}}: Draw ({_NUM_ALT}) cards?\.$"
)
_ADDITIONAL = re.compile(r"^As an additional cost to cast this spell, (.+)\.$")
_ADDITIONAL_KNOWN = (
    (
        re.compile(r"^sacrifice an? (creature|artifact|artifact or creature)$"),
        "sacrifice",
        0,
    ),
    (re.compile(rf"^discard ({_NUM_ALT}) cards?$"), "discard", 1),
    (re.compile(r"^pay \d+ life$"), "life", 0),
)
_SPELL_HARMLESS = (
    re.compile(r"^Scry \d+\.$"),
    re.compile(
        r"^Look at the top (\w+) cards? of your library, then put (them|it) back"
        r"( in any order)?\.( You may shuffle\.)?$"
    ),
)
_ALT_COST = re.compile(
    r"\b(delve|affinity|convoke|improvise|flashback|escape|"
    r"overload|costs \{?\d*\}? less)\b",
    re.IGNORECASE,
)


def _rec_spell(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    if not ctx["is_spell"]:
        return None
    m = _SPELL_DRAW.match(clause)
    if not m:
        return None
    n = _NUM_WORDS[m.group(1).lower()]
    net: int | None = n - 1 - ctx["extra_cards_spent"]
    return [
        _route(
            "spell",
            ctx["mana"],
            0.0,
            ctx["mana_cost"],
            n,
            net,
            False,
            list(ctx["spell_prereqs"]),
            clause,
            ctx["spell_supported"],
        )
    ]


def _rec_channel(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    m = _CHANNEL.match(clause)
    if not m:
        return None
    cost, effect = m.group(1), m.group(2)
    for pat in _CHANNEL_EFFECTS:
        em = pat.match(effect)
        if em:
            n = _NUM_WORDS[em.group(1).lower()]
            return [
                _route(
                    "channel",
                    parse_mana(cost),
                    0.0,
                    cost,
                    n,
                    n - 1,
                    False,
                    ["discard"],
                    clause,
                )
            ]
    return None


def _rec_shoreline(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    if not _SHORELINE.match(clause):
        return None
    return [
        _passive(
            ctx, "combat_damage", 1, 1, ["island", "combat_damage", "attack"], clause
        )
    ]


def _rec_tax(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    m = _TAX.match(clause)
    if not m:
        return None
    prereqs = ["opponent_cast", "opponent_payment"]
    if ctx["cumulative_upkeep"]:
        prereqs.append("cumulative_upkeep")
    note = " [tax " + m.group(2) + (", noncreature spells only]" if m.group(1) else "]")
    return [_passive(ctx, "triggered", 1, 1, prereqs, clause + note)]


def _rec_moldervine(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    if not _MOLDERVINE.match(clause):
        return None
    return [_passive(ctx, "triggered", 1, 1, ["creature_death"], clause)]


def _rec_sanctuary(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    if not _SANCTUARY.match(clause):
        return None
    return [
        _route(
            "etb", ctx["mana"], 0.0, ctx["mana_cost"], 1, 0, False, ["counters"], clause
        ),
        _passive(ctx, "attack", 1, 1, ["attack", "counters"], clause),
    ]


def _rec_arena(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    if not _ARENA.match(clause):
        return None
    return [_passive(ctx, "triggered", 1, 1, ["life", "own_upkeep"], clause)]


def _rec_unagi(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    if not _UNAGI.match(clause):
        return None
    return [_passive(ctx, "triggered", 2, 2, ["opponent_second_draw"], clause)]


def _rec_activated(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    if ctx["is_spell"]:
        return None
    m = _ACTIVATED.match(clause)
    if not m:
        return None
    mana_part = m.group(1).replace(", ", "")
    n = _NUM_WORDS[m.group(2).lower()]
    cost = clause.split(":")[0]
    mana = 0.0 if not mana_part else parse_mana(mana_part)
    return [_route("activated", mana, ctx["mana"], cost, n, n, True, ["tap"], clause)]


def _rec_charge_counter(clause: str, ctx: dict[str, Any]) -> list[Route] | None:
    # The cost and scaling prerequisite are known; no initial/future charge count is assumed.
    match = re.fullmatch(
        r"((?:\{[^{}]+\})+), \{T\}: Put a charge counter on (?:this artifact|~), then draw a card for each charge counter on it\.",
        clause,
    )
    if ctx["is_spell"] or not match:
        return None
    return [
        _route(
            "activated",
            parse_mana(match.group(1)),
            ctx["mana"],
            match.group(1) + ", {T}",
            None,
            None,
            True,
            ["tap", "counters"],
            clause,
        )
    ]


_RECOGNIZERS: list[Callable[[str, dict[str, Any]], list[Route] | None]] = [
    _rec_charge_counter,
    _rec_channel,
    _rec_spell,
    _rec_shoreline,
    _rec_tax,
    _rec_moldervine,
    _rec_sanctuary,
    _rec_arena,
    _rec_unagi,
    _rec_activated,
]


# --------------------------------------------------------------------- entrypoint
def _spell_context(
    clauses: list[str], text: str, ctx: dict[str, Any], unknown: list[str]
) -> None:
    """Inspect every non-draw clause of a spell. Known additional costs become
    prerequisites; anything else cannot be modelled and makes routes unsupported."""
    prereqs: list[str] = []
    supported = True
    extra = 0
    for clause in clauses:
        if _DRAW_RE.search(clause):
            continue
        m = _ADDITIONAL.match(clause)
        if m:
            for pat, tag, spent in _ADDITIONAL_KNOWN:
                km = pat.match(m.group(1))
                if km:
                    prereqs.append(tag)
                    if spent:
                        extra += _NUM_WORDS[km.group(1).lower()]
                    break
            else:
                supported = False
                unknown.append(clause)
            continue
        if any(p.match(clause) for p in _SPELL_HARMLESS):
            continue
        supported = False
        unknown.append(clause)
    if _ALT_COST.search(text):
        supported = False
    ctx.update(
        spell_prereqs=prereqs, spell_supported=supported, extra_cards_spent=extra
    )


def route_profile(card: dict[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(card.get("oracle_text"), str)
        or not isinstance(card.get("type_line"), str)
        or not card["type_line"].strip()
    ):
        return {
            "routes": [],
            "unknown_clauses": ["missing_or_malformed_card_text"],
            "complete": False,
        }
    name = str(card.get("name") or "")
    text = _normalize(str(card.get("oracle_text") or ""), name)
    type_line = str(card.get("type_line") or "")
    mana_cost = card.get("mana_cost")
    clauses = _clauses(text)
    unknown: list[str] = []
    ctx: dict[str, Any] = {
        "mana": parse_mana(mana_cost),
        "mana_cost": mana_cost,
        "is_spell": bool(re.search(r"\b(Instant|Sorcery)\b", type_line)),
        "cumulative_upkeep": "cumulative upkeep" in text.lower(),
        "spell_prereqs": [],
        "spell_supported": True,
        "extra_cards_spent": 0,
    }
    if ctx["is_spell"] and any(_DRAW_RE.search(c) for c in clauses):
        _spell_context(clauses, text, ctx, unknown)

    routes: list[Route] = []
    for clause in clauses:
        if not _DRAW_RE.search(clause):
            if re.search(
                r"(?:put|return|add)[^.]*\b(?:into|to) (?:your|their|its owner.s) hand|exile[^.]*|(?:play|cast)[^.]*exil",
                clause,
                re.IGNORECASE,
            ):
                unknown.append(clause)
            continue
        matched = None
        for rec in _RECOGNIZERS:
            matched = rec(clause, ctx)
            if matched:
                break
        if matched:
            routes.extend(matched)
        else:
            unknown.append(clause)
    # Unknown clauses can coexist with a parsed independent route. Explicit
    # prevention/replacement of our own draw is different: its unresolved effect
    # changes whether the recognized route can deliver its stated cards.
    for clause in unknown:
        own_prevention = re.search(
            r"\b(?:you|players|a player|each player) (?:can't|can’t|cannot|can not|may not|may only) draw\b",
            clause,
            re.IGNORECASE,
        )
        own_replacement = re.search(
            r"\b(?:you|a player|each player|players) would draw\b",
            clause,
            re.IGNORECASE,
        ) and re.search(r"\binstead\b", clause, re.IGNORECASE)
        if own_prevention or own_replacement:
            for route in routes:
                route["supported"] = False
                if "unsupported" not in route["prerequisites"]:
                    route["prerequisites"].append("unsupported")
    return {"routes": routes, "unknown_clauses": unknown, "complete": not unknown}
