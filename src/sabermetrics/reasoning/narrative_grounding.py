"""Render final-deck narrative from supplied card facts and roles.

The application owns user-facing prose. Named cards come only from the final
list. Name-only rows stay conservative: names are listed, abilities are not
invented.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from sabermetrics.models.llm_responses import DeckSynthesisResponse

_CORE_ROLES = ("ramp", "draw", "removal")
_CORE_ROLE_LABELS = {
    "ramp": "ramp",
    "draw": "card draw",
    "removal": "removal",
}
_MEMBERSHIP_NAME_LIMIT = 12
_SYNERGY_LIMIT = 8


@dataclass(frozen=True)
class CardFact:
    """Authoritative facts for one final-list card."""

    name: str
    mana_value: float | None = None
    oracle_text: str | None = None
    type_line: str | None = None
    role: str | None = None


def card_facts_from_dicts(cards: list[dict[str, Any]] | None) -> list[CardFact]:
    """Normalize builder dicts; name-only rows stay name-only."""
    facts: list[CardFact] = []
    for raw in cards or []:
        if not isinstance(raw, dict):
            continue
        name = _first_str(raw, "name")
        if not name or name == "Unknown":
            continue
        mana_value = _optional_float(
            raw.get("mana_value", raw.get("cmc", raw.get("mv")))
        )
        oracle = _first_str(raw, "oracle_text", "oracle") or None
        type_line = _first_str(raw, "type_line", "type") or None
        role = _first_str(raw, "role", "slot_role") or None
        facts.append(
            CardFact(
                name=name,
                mana_value=mana_value,
                oracle_text=oracle,
                type_line=type_line,
                role=role,
            )
        )
    return facts


def has_authoritative_facts(facts: list[CardFact]) -> bool:
    """True when at least one card carries oracle, type, or mana value."""
    return any(
        (fact.oracle_text and fact.oracle_text.strip())
        or (fact.type_line and fact.type_line.strip())
        or fact.mana_value is not None
        for fact in facts
    )


def format_deck_facts(facts: list[CardFact]) -> str:
    """Human-readable fact block for prompts or debugging."""
    lines: list[str] = []
    for fact in facts:
        parts = [f"- {fact.name}"]
        if fact.role:
            parts.append(f"role={fact.role}")
        if fact.mana_value is not None:
            parts.append(f"mana_value={fact.mana_value:g}")
        if fact.type_line:
            parts.append(f"type={fact.type_line}")
        if fact.oracle_text:
            parts.append(f"oracle={fact.oracle_text}")
        lines.append(" | ".join(parts))
    return "\n".join(lines) if lines else "(no card facts supplied)"


def membership_names(facts: list[CardFact]) -> set[str]:
    return {fact.name for fact in facts}


def render_deck_narrative(
    facts: list[CardFact],
    bracket: int,
    bracket_reasoning: str,
) -> DeckSynthesisResponse:
    """Plain-English summary from membership, roles, and printed text."""
    names = [fact.name for fact in facts]
    if not names:
        return DeckSynthesisResponse(
            game_plan="This deck list has no named cards.",
            key_synergies=["No named cards are in this list."],
            weaknesses=["With no cards listed, the deck has no available plays."],
            suggested_play_pattern=_play_with_bracket(
                "There are no listed cards to play.",
                bracket,
                bracket_reasoning,
            ),
        )

    commander = _commander_from_facts(facts)
    role_sentence = _role_sentence(facts)
    membership = _membership_phrase(names)
    count = len(names)

    if not has_authoritative_facts(facts):
        lead = f"{commander} heads this list. " if commander else ""
        game_plan = (
            f"{lead}The list includes {membership}. "
            "These cards are listed by name only, so their abilities are unknown."
        ).strip()
        synergies = [f"{name} is in the list." for name in names[:_SYNERGY_LIMIT]]
        weaknesses = [
            "These cards are listed by name only, so their abilities are unknown."
        ]
        weaknesses.extend(_unmet_role_warnings(facts))
        play = _play_with_bracket(
            f"Play {membership} from this list.",
            bracket,
            bracket_reasoning,
        )
        return DeckSynthesisResponse(
            game_plan=game_plan,
            key_synergies=synergies,
            weaknesses=weaknesses,
            suggested_play_pattern=play,
        )

    lead = f"{commander} is the commander. " if commander else ""
    game_bits = [
        f"{lead}This list has {count} card{'s' if count != 1 else ''}: {membership}.".strip()
    ]
    if role_sentence:
        game_bits.append(role_sentence)
    commander_fact = next((fact for fact in facts if fact.name == commander), None)
    if commander_fact and _printed_oracle(commander_fact):
        game_bits.append(
            f"{commander_fact.name} reads: {_printed_oracle(commander_fact)}"
        )
    game_plan = " ".join(game_bits)

    synergies = _engine_fact_lines(facts, commander)
    weaknesses = _unmet_role_warnings(facts)
    if not weaknesses:
        weaknesses = [_composition_note(facts)]
    play = _play_with_bracket(
        _play_pattern(facts, commander),
        bracket,
        bracket_reasoning,
    )
    return DeckSynthesisResponse(
        game_plan=game_plan,
        key_synergies=synergies,
        weaknesses=weaknesses,
        suggested_play_pattern=play,
    )


def facts_only_narrative(
    facts: list[CardFact],
    profile_summary: str,
    bracket: int,
    bracket_reasoning: str,
) -> DeckSynthesisResponse:
    """Compatibility wrapper. Commander context comes from card facts, not summary."""
    del profile_summary
    return render_deck_narrative(facts, bracket, bracket_reasoning)


def _commander_from_facts(facts: list[CardFact]) -> str | None:
    role_hits = [
        fact for fact in facts if (fact.role or "").strip().lower() == "commander"
    ]
    if len(role_hits) == 1:
        return role_hits[0].name
    return None


def _role_counts(facts: list[CardFact]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for fact in facts:
        role = (fact.role or "").strip().lower()
        if role:
            counts[role] += 1
    return counts


def _role_sentence(facts: list[CardFact]) -> str:
    counts = _role_counts(facts)
    if not counts:
        return ""
    parts = [f"{count} {role}" for role, count in sorted(counts.items())]
    return "Roles: " + ", ".join(parts) + "."


def _unmet_role_warnings(facts: list[CardFact]) -> list[str]:
    counts = _role_counts(facts)
    if not counts:
        return []
    warnings: list[str] = []
    for role in _CORE_ROLES:
        if counts.get(role, 0) == 0:
            warnings.append(f"This list has no {_CORE_ROLE_LABELS[role]} cards.")
    return warnings


def _composition_note(facts: list[CardFact]) -> str:
    counts = _role_counts(facts)
    if not counts:
        return "Every listed card is included with its printed text."
    parts = [f"{count} {role}" for role, count in sorted(counts.items())]
    return "This list covers " + ", ".join(parts) + "."


def _engine_fact_lines(facts: list[CardFact], commander: str | None) -> list[str]:
    ordered = sorted(
        facts,
        key=lambda fact: (
            0 if fact.name == commander else 1,
            0 if _printed_oracle(fact) else 1,
            fact.name,
        ),
    )
    lines: list[str] = []
    for fact in ordered:
        lines.append(_card_fact_line(fact))
        if len(lines) >= _SYNERGY_LIMIT:
            break
    if not lines:
        lines.append("No named cards were supplied to summarize.")
    return lines


def _card_fact_line(fact: CardFact) -> str:
    bits: list[str] = []
    if fact.role:
        bits.append(fact.role)
    if fact.mana_value is not None:
        bits.append(f"mana value {fact.mana_value:g}")
    if fact.type_line:
        bits.append(fact.type_line)
    header = f"{fact.name} ({', '.join(bits)})" if bits else fact.name
    oracle = _printed_oracle(fact)
    if oracle:
        return f"{header}: {oracle}"
    return f"{header} is in the list."


def _play_pattern(facts: list[CardFact], commander: str | None) -> str:
    by_role: dict[str, list[str]] = {}
    for fact in facts:
        role = (fact.role or "").strip().lower()
        if role:
            by_role.setdefault(role, []).append(fact.name)
    steps: list[str] = []
    ramp = by_role.get("ramp") or []
    if ramp:
        steps.append("Open with " + _join_names(ramp[:3]))
    if commander:
        commander_fact = next((fact for fact in facts if fact.name == commander), None)
        oracle = _printed_oracle(commander_fact) if commander_fact else ""
        if oracle:
            steps.append(f"Cast {commander} and follow its printed text")
        else:
            steps.append(f"Cast {commander}")
    removal = by_role.get("removal") or []
    if removal:
        steps.append("Hold " + _join_names(removal[:3]) + " for interaction")
    draw = by_role.get("draw") or []
    if draw:
        steps.append("Use " + _join_names(draw[:3]) + " to refill")
    if not steps:
        steps.append("Play " + _membership_phrase([fact.name for fact in facts]))
    return "; ".join(steps) + "."


def _play_with_bracket(play: str, bracket: int, bracket_reasoning: str) -> str:
    text = play.rstrip()
    if text and not text.endswith("."):
        text += "."
    note = (bracket_reasoning or "").strip()
    if note:
        return f"{text} Reported bracket {bracket}: {note}."
    return f"{text} Reported bracket {bracket}."


def _membership_phrase(names: list[str], limit: int = _MEMBERSHIP_NAME_LIMIT) -> str:
    if not names:
        return "no named cards"
    if len(names) == 1:
        return names[0]
    if len(names) <= limit:
        return ", ".join(names[:-1]) + f", and {names[-1]}"
    shown = ", ".join(names[:limit])
    return f"{shown}, and {len(names) - limit} more"


def _join_names(names: list[str]) -> str:
    if not names:
        return "the listed cards"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _printed_oracle(fact: CardFact | None) -> str:
    if fact is None or not fact.oracle_text:
        return ""
    return " ".join(fact.oracle_text.split())


def _first_str(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
