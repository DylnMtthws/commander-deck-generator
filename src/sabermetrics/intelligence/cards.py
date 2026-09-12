"""Conservative, inspectable card capabilities, independent of popularity tags.

This is a supported-shape parser, not a general Oracle interpreter. Only a
positive verified capability may satisfy a strategy requirement. Conditions
remain visible and never turn into unconditional ramp or mana fixing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

VERSION = "card-facts.v2"
COLORS = "WUBRG"
BASICS = dict(zip(("Plains", "Island", "Swamp", "Mountain", "Forest"), COLORS))


class CardFacts(BaseModel):
    version: str = VERSION
    oracle_hash: str
    roles: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    exclusion: str | None = None
    land_colors: list[str] = Field(default_factory=list)
    provenance: str = "deterministic-supported-shapes"


def _text(card: dict) -> str:
    return str(card.get("oracle_text") or "")


@lru_cache(maxsize=40000)
def _analyze(name: str, text: str, types: str) -> str:
    t = text.lower()
    front = re.sub(r"\([^)]*\)", "", t.split(" // ")[0])
    front_type = types.split("//")[0].lower()
    roles: set[str] = set()
    caps: set[str] = set()
    conditions: list[str] = []
    exclusion = None
    land = "land" in front_type
    # Parse specific useful clauses; never let a land back face imply ramp.
    if "landfall" in front or re.search(
        r"whenever a land (?:you control )?enters", front
    ):
        caps.add("landfall")
    if re.search(r"you may play (?:an additional|two additional) lands?", front):
        caps.add("extra_land_play_once" if "this turn" in front else "extra_land_play")
        roles.add("ramp")
    if re.search(r"(?:play|put).*lands? (?:cards? )?from your graveyard", front):
        caps.add("land_recursion")
        roles.add("recursion")
    if re.search(
        r"return target land card from your graveyard to the battlefield", front
    ):
        caps.add("land_recursion")
        roles.add("recursion")
    if (
        "search your library" in front
        and re.search(r"(?:land|forest|island) card", front)
        and "onto the battlefield" in front
    ):
        if land or "sacrifice a land" in front:
            caps.add("land_access")
            conditions.append("land_search_does_not_guarantee_net_acceleration")
        else:
            caps.add("land_ramp")
            roles.add("ramp")
    if "land card from your hand onto the battlefield" in front:
        caps.add("land_from_hand")
        roles.add("ramp")
    if not land and re.search(r"(?:^|\n)\{t\}: add (?:\{[cwubrg]\}|one mana)", front):
        roles.add("ramp")
        caps.add("mana_source")
    if re.search(r"draw (?:a|one|two|three|four|[0-9]+|x) cards?", front):
        roles.add("draw")
    if re.search(
        r"(?:destroy|exile|return) target (?:nonland |noncreature |attacking |tapped )?(?:permanent|creature|artifact|enchantment|planeswalker)",
        front,
    ):
        roles.add("removal")
    if "counter target spell" in front:
        if "same name" in front:
            conditions.append("counter_requires_matching_exiled_card")
        else:
            roles.add("removal")
    if re.search(
        r"(?:destroy|exile|return) (?:all|each) (?:nonland |nonartifact |nontoken )?(?:creatures|permanents|artifacts|enchantments)",
        front,
    ):
        if not re.search(r"whenever|if |when you do", front):
            roles.add("board_wipe")
        else:
            conditions.append("conditional_board_wipe")
    if re.search(r"return target (?:\w+ )?card from your graveyard", front):
        roles.add("recursion")
    if re.search(
        r"(?:creatures|permanents) you control (?:gain|have).*?(?:hexproof|indestructible)|equipped creature has.*shroud",
        front,
    ):
        roles.add("protection")
    if "landfall" in caps:
        # Evidence must occur in the trigger's clause, not in an unrelated
        # activated ability elsewhere on the same card (e.g. spend energy).
        clauses = " ".join(
            line[line.find("whenever a land") :]
            for line in front.splitlines()
            if "whenever a land" in line and '"whenever a land' not in line
        )
        if re.search(r"draw (?:a|one|two|three|x) cards?|investigate", clauses):
            caps.add("landfall_cards")
        if "create" in clauses and "token" in clauses:
            caps.add("landfall_tokens")
            if "creature token" in clauses or "token creature" in clauses:
                caps.add("landfall_board")
                roles.add("wincon")
        if "+1/+1 counter" in clauses or "gets +" in clauses or "damage" in clauses:
            caps.add("landfall_growth")
    same_name = bool(
        re.search(
            r"search your library.*(?:same name|named "
            + re.escape(name.lower())
            + r")",
            front,
        )
    )
    if same_name:
        conditions.append("same_name_target_not_guaranteed_in_singleton")
        roles.discard("ramp")
        roles.discard("tutor")
        # An instant/sorcery whose only payoff is same-name search cannot be
        # treated as a functional tutor without an explicitly modeled target.
        if "instant" in front_type or "sorcery" in front_type:
            exclusion = "same-name search requires an external matching target"
    colors: set[str] = set()
    if land:
        roles.add("land")
        if "as you drafted" in t:
            exclusion = "mana production requires draft choices"
        for basic, color in BASICS.items():
            if basic.lower() in front_type:
                colors.add(color)
        for line in front.splitlines():
            if re.search(r"\{t\}: add", line):
                if re.search(
                    r"activate only|that a |chosen|pay |other .*you control", line
                ):
                    conditions.append("conditional_colored_mana")
                    continue
                colors.update(c.upper() for c in re.findall(r"\{([wubrg])\}", line))
                if (
                    "any color in your commander's color identity" in line
                    or "one mana of any color." in line
                ):
                    colors.update(COLORS)
        if not colors:
            conditions.append("no_verified_unconditional_colored_mana")
    if "//" in types:
        conditions.append("multiple_faces_require_face_aware_model")
    if not text and name not in BASICS:
        conditions.append("oracle_text_unavailable")
    result = CardFacts(
        oracle_hash=hashlib.sha256((text + "\0" + types).encode()).hexdigest(),
        roles=sorted(roles),
        capabilities=sorted(caps),
        conditions=sorted(set(conditions)),
        exclusion=exclusion,
        land_colors=sorted(colors),
    )
    return result.model_dump_json()


def fact_key(card: dict) -> str:
    """Version and exact parser inputs identify a reusable compiled shape."""
    raw = [
        VERSION,
        str(card.get("name") or ""),
        _text(card),
        str(card.get("type_line") or ""),
    ]
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False).encode()).hexdigest()


@lru_cache(maxsize=2)
def _snapshot(path: str, modified: int) -> dict:
    del modified
    try:
        data = json.loads(Path(path).read_text())
        return (
            data["entries"]
            if isinstance(data, dict)
            and data.get("version") == VERSION
            and isinstance(data.get("entries"), dict)
            else {}
        )
    except (OSError, ValueError, TypeError):
        return {}


def facts_for(card: dict) -> CardFacts:
    """Return isolated facts so callers cannot mutate the shared cache."""
    path = os.getenv("SABER_CARD_FACTS")
    if path:
        try:
            row = _snapshot(path, Path(path).stat().st_mtime_ns).get(fact_key(card))
            if row is not None:
                facts = CardFacts.model_validate(row)
                expected = hashlib.sha256(
                    (_text(card) + "\0" + str(card.get("type_line") or "")).encode()
                ).hexdigest()
                if facts.version == VERSION and facts.oracle_hash == expected:
                    return facts
        except (OSError, ValueError, TypeError):
            pass  # Recompute from current Oracle facts; never trust stale data.
    return CardFacts.model_validate_json(
        _analyze(
            str(card.get("name") or ""), _text(card), str(card.get("type_line") or "")
        )
    )


def annotate(card: dict) -> dict:
    """Preserve discovery tags separately from verified functional roles."""
    result = dict(card)
    facts = facts_for(card)
    raw = card.get("role_tags") or []
    try:
        old = json.loads(raw) if isinstance(raw, str) else list(raw)
    except (ValueError, TypeError):
        old = []
    result["_discovery_roles"] = old
    # Preserve specialized discovery roles, but do not use unsupported ramp,
    # draw/removal/board-wipe claims as optimizer requirements.
    roles = set(old) - {"ramp", "draw", "removal", "board_wipe", "recursion"}
    roles.update(facts.roles)
    result["role_tags"] = json.dumps(sorted(roles) or ["utility"])
    result["_facts"] = facts.model_dump()
    return result


def usable_land(card: dict, colors: list[str]) -> bool:
    """Mana-base admission: only verified color production satisfies fixing."""
    facts = facts_for(card)
    return not facts.exclusion and bool(set(facts.land_colors) & set(colors))


def semantic_findings(cards: list[dict]) -> list[dict]:
    """Expose concrete final-list prerequisites without invented certainty."""
    findings = []
    for card in cards:
        facts = facts_for(card)
        if facts.exclusion:
            findings.append(
                {
                    "code": "unsupported_card_prerequisite",
                    "card": card.get("name"),
                    "message": facts.exclusion,
                    "severity": "failure",
                }
            )
        for condition in facts.conditions:
            findings.append(
                {
                    "code": condition,
                    "card": card.get("name"),
                    "message": condition.replace("_", " "),
                    "severity": "warning",
                }
            )
    return findings
