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

VERSION = "card-facts.v3"
COLORS = "WUBRG"
BASICS = dict(zip(("Plains", "Island", "Swamp", "Mountain", "Forest"), COLORS))

# Deck construction reads the first role as the card's slot. Alphabetical order
# made "board_wipe" outrank "land" and "draw" outrank "ramp"; order by what the
# slot actually has to be, lands first because a land can never fill a spell
# slot. Roles outside this list keep a stable alphabetical tail.
ROLE_PRIORITY = (
    "land",
    "ramp",
    "removal",
    "board_wipe",
    "draw",
    "wincon",
    "recursion",
    "tutor",
    "protection",
    "utility",
)


def order_roles(roles) -> list[str]:
    """Sort roles so the first entry is the most slot-defining one."""
    return sorted(
        set(roles),
        key=lambda r: (
            ROLE_PRIORITY.index(r) if r in ROLE_PRIORITY else len(ROLE_PRIORITY),
            r,
        ),
    )


def primary_role(roles) -> str:
    ordered = order_roles(roles)
    return ordered[0] if ordered else "utility"


class CardFacts(BaseModel):
    version: str = VERSION
    oracle_hash: str
    roles: list[str] = Field(default_factory=list)
    primary_role: str = "utility"
    capabilities: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    # Conditions attached to the capability they gate, so a caller can tell
    # "mana, but only with three artifacts" from "mana, but only once".
    capability_conditions: dict[str, list[str]] = Field(default_factory=dict)
    # Aspects this parser could not decide. Absence of a capability means
    # "not verified", and these entries say so explicitly; they are never
    # evidence that the card lacks the effect.
    unknown: list[str] = Field(default_factory=list)
    exclusion: str | None = None
    land_colors: list[str] = Field(default_factory=list)
    provenance: str = "deterministic-supported-shapes"


def _text(card: dict) -> str:
    return str(card.get("oracle_text") or "")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


# --- supported conditional shapes -----------------------------------------
# Each pattern below describes one printed shape. Anything broader is left
# undetected on purpose: a missing capability is an unknown, not a denial.

# Ability words ("Landfall — Whenever ...") precede the trigger itself.
_TRIGGER_RE = re.compile(
    r"^(?:[a-z' \-]{0,30}—\s*)?(?:whenever|when |at the beginning)"
)
_ADD_MANA_RE = re.compile(
    r"\badd (?:\{|one mana|two mana|three mana|x mana|an amount of|that much)"
)
_ONCE_PER_TURN_RE = re.compile(
    r"once (?:during )?each (?:of your )?turns?|only once each turn"
)
_METALCRAFT_RE = re.compile(r"metalcraft|three or more artifacts")
_POWER_MANA_RE = re.compile(r"(?:equal to|where x is) [^.\n]*\bpower\b")
_COMBAT_DAMAGE_RE = re.compile(
    r"deals combat damage to (?:a player|an opponent|one or more players)"
)
_ANY_DAMAGE_RE = re.compile(
    r"deals (?:noncombat )?damage to (?:a player|an opponent|one or more players)"
)
_NONCREATURE_DAMAGE_RE = re.compile(
    r"whenever you cast (?:a noncreature spell|an instant or sorcery spell)"
    r"[^.\n]*deals (?:\d+|x) damage to "
    r"(?:each opponent|target opponent|target player|any target)"
)
_TUTOR_RE = re.compile(
    r"search your library for (?:up to \w+ )?(?:a |an )?([^.,\n]{0,60}?) cards?\b"
)
_TREASURE_RE = re.compile(r"creates? [^.\n]*treasure token")
_LAND_TARGET_RE = re.compile(r"\b(?:land|basic|plains|island|swamp|mountain|forest)\b")


def _mana_shapes(front: str, front_type: str, caps: set, cap_conditions: dict) -> None:
    """Classify printed mana production; burst is kept apart from ramp."""
    spell = "instant" in front_type or "sorcery" in front_type
    creature = "creature" in front_type
    for raw_line in front.splitlines():
        line = raw_line.strip()
        if not _ADD_MANA_RE.search(line):
            continue
        head, sep, body = line.partition(":")
        if not sep or _ADD_MANA_RE.search(head):
            head, body = "", line
        conditions: list[str] = []
        if _TRIGGER_RE.match(line):
            # A triggered ability is not a mana ability a player can rely on.
            caps.add("triggered_mana")
            cap_conditions.setdefault("triggered_mana", []).append(
                "mana_requires_trigger_to_resolve"
            )
            continue
        if "exile this card from your hand" in head:
            capability = "burst_mana"
            conditions.append("exiled_from_hand_instead_of_being_cast")
        elif head and "sacrifice" in head:
            capability = "burst_mana"
            conditions.append("requires_sacrificing_the_source")
        elif head and "{t}" in head:
            capability = "mana_source"
        elif head.strip() == "{0}" and _POWER_MANA_RE.search(line):
            capability = "mana_source"
            conditions.append("power_dependent_free_activation")
        elif not head and spell:
            capability = "burst_mana"
            conditions.append("one_shot_spell_mana")
        elif not head and _ONCE_PER_TURN_RE.search(line):
            # A per-turn permission to add mana, not an activated ability.
            capability = "mana_source"
            conditions.append("once_per_turn_only")
        else:
            continue
        if "discard your hand" in line:
            conditions.append("requires_discarding_your_hand")
        if "spend this mana only" in line:
            conditions.append("mana_usage_is_restricted")
        if "for each" in body or " x " in f" {body} ":
            conditions.append("mana_amount_varies")
        if _METALCRAFT_RE.search(line) and "activate only" in line:
            conditions.append("requires_metalcraft_three_artifacts")
        elif "activate only" in line:
            conditions.append("conditional_activation_restriction")
        if _ONCE_PER_TURN_RE.search(line) and "once_per_turn_only" not in conditions:
            conditions.append("once_per_turn_only")
        if capability == "mana_source" and creature:
            conditions.append("creature_mana_requires_no_summoning_sickness")
        if capability == "burst_mana":
            conditions.append("burst_mana_is_not_repeatable_ramp")
        caps.add(capability)
        cap_conditions.setdefault(capability, []).extend(conditions)
        if _POWER_MANA_RE.search(line):
            power_conditions = conditions + ["mana_amount_depends_on_creature_power"]
            caps.add("power_based_mana")
            cap_conditions.setdefault("power_based_mana", []).extend(power_conditions)
            if "once_per_turn_only" in conditions:
                caps.add("power_based_mana_once_per_turn")
                cap_conditions.setdefault("power_based_mana_once_per_turn", []).extend(
                    power_conditions
                )
    if _TREASURE_RE.search(front):
        caps.add("burst_mana")
        cap_conditions.setdefault("burst_mana", []).extend(
            ["requires_sacrificing_a_treasure", "burst_mana_is_not_repeatable_ramp"]
        )


def _payoff_shapes(front: str, caps: set, cap_conditions: dict, roles: set) -> None:
    """Damage-gated draw, cast-gated damage, and variable draw counts."""
    for raw_line in front.splitlines():
        line = raw_line.strip()
        if _TRIGGER_RE.match(line) and "draw" in line:
            if _COMBAT_DAMAGE_RE.search(line):
                caps.add("draw_on_combat_damage")
                cap_conditions.setdefault("draw_on_combat_damage", []).append(
                    "requires_connecting_in_combat"
                )
                roles.add("draw")
            elif _ANY_DAMAGE_RE.search(line):
                caps.add("draw_on_opponent_damage")
                cap_conditions.setdefault("draw_on_opponent_damage", []).append(
                    "requires_a_damage_source"
                )
                roles.add("draw")
        if "draw that many cards" in line:
            caps.add("draw_that_many")
            cap_conditions.setdefault("draw_that_many", []).append(
                "draw_amount_depends_on_variable_state"
            )
            roles.add("draw")
        if re.search(r"draw cards equal to|draw a card for each", line):
            caps.add("draw_variable")
            cap_conditions.setdefault("draw_variable", []).append(
                "draw_amount_depends_on_variable_state"
            )
            roles.add("draw")
    if re.search(
        r"as long as .*paired.*each.*whenever this creature deals damage to an opponent, draw a card",
        front,
        re.DOTALL,
    ):
        caps.add("draw_on_opponent_damage")
        cap_conditions.setdefault("draw_on_opponent_damage", []).append(
            "requires_soulbond_pair_and_damage_source"
        )
        roles.add("draw")
    if _NONCREATURE_DAMAGE_RE.search(front):
        caps.add("noncreature_cast_damage")
        cap_conditions.setdefault("noncreature_cast_damage", []).append(
            "requires_noncreature_spell_density"
        )


def _tutor_shape(front: str, caps: set, cap_conditions: dict, roles: set) -> None:
    """Library search that is not already modelled as land ramp or access."""
    match = _TUTOR_RE.search(front)
    if not match:
        return
    target = match.group(1).strip()
    if _LAND_TARGET_RE.search(target):
        return  # Land search stays with the land_ramp / land_access shapes.
    caps.add("tutor")
    roles.add("tutor")
    conditions = [
        (
            "tutor_unrestricted"
            if target in ("", "a", "an")
            else f"tutor_limited_to_{_slug(target)}"
        )
    ]
    tail = front[match.end() : match.end() + 200]
    if "into your hand" in tail:
        caps.add("tutor_to_hand")
    elif "onto the battlefield" in tail:
        caps.add("tutor_to_battlefield")
    elif "on top of your library" in tail:
        caps.add("tutor_to_top")
        conditions.append("tutored_card_still_has_to_be_drawn")
    else:
        conditions.append("tutor_destination_not_determined")
    cap_conditions.setdefault("tutor", []).extend(conditions)


@lru_cache(maxsize=40000)
def _analyze(name: str, text: str, types: str) -> str:
    t = text.lower()
    front = re.sub(r"\([^)]*\)", "", t.split(" // ")[0])
    front_type = types.split("//")[0].lower()
    roles: set[str] = set()
    caps: set[str] = set()
    conditions: list[str] = []
    cap_conditions: dict[str, list[str]] = {}
    unknown: list[str] = []
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
    if not land:
        _mana_shapes(front, front_type, caps, cap_conditions)
        # Repeatable production is ramp; a single burst is not, and says so.
        if "mana_source" in caps:
            roles.add("ramp")
    _payoff_shapes(front, caps, cap_conditions, roles)
    _tutor_shape(front, caps, cap_conditions, roles)
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
        caps -= {"tutor", "tutor_to_hand", "tutor_to_battlefield", "tutor_to_top"}
        cap_conditions.pop("tutor", None)
        unknown.append("same_name_search_target_availability_unknown")
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
        unknown.append("back_face_effects_not_modeled")
    if not text and name not in BASICS:
        conditions.append("oracle_text_unavailable")
        unknown.append("oracle_text_unavailable")
    if "convoke" in front:
        unknown.append("convoke_mana_reduction_amount_unknown")
    if re.search(r'"[^"]*\bwhenever\b', front):
        # An ability granted to another object in quotes is a different card's
        # behaviour; this parser does not resolve who ends up with it.
        unknown.append("granted_abilities_in_quoted_text_not_modeled")
    if text and not caps and not roles:
        # No supported shape matched. That is an unresolved reading of the
        # card, not a statement that the card does nothing.
        unknown.append("no_supported_shape_detected")
    conditions.extend(c for values in cap_conditions.values() for c in values)
    result = CardFacts(
        oracle_hash=hashlib.sha256((text + "\0" + types).encode()).hexdigest(),
        roles=order_roles(roles),
        primary_role=primary_role(roles),
        capabilities=sorted(caps),
        conditions=sorted(set(conditions)),
        capability_conditions={
            k: sorted(set(v)) for k, v in sorted(cap_conditions.items())
        },
        unknown=sorted(set(unknown)),
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
    unverified = {"ramp", "draw", "removal", "board_wipe", "recursion"}
    roles = set(old) - unverified
    roles.update(facts.roles)
    ordered = order_roles(roles) or ["utility"]
    result["role_tags"] = json.dumps(ordered)
    # Verified and discovery-only claims stay distinguishable: a discovery tag
    # this parser could not confirm is unknown, never a confirmed absence.
    result["_verified_roles"] = list(facts.roles)
    result["_discovery_only_roles"] = sorted(set(old) - set(facts.roles))
    result["_unverified_discovery_roles"] = sorted(
        (set(old) & unverified) - set(facts.roles)
    )
    result["_primary_role"] = ordered[0]
    result["_facts"] = facts.model_dump()
    return result


def usable_land(card: dict, colors: list[str]) -> bool:
    """Mana-base admission: only verified color production satisfies fixing."""
    facts = facts_for(card)
    if facts.exclusion:
        return False
    if set(facts.land_colors) & set(colors):
        return True
    # Fetches are eligible sources with target prerequisites, not direct mana.
    # The mana-base selector separately discounts and tracks their targets.
    from sabermetrics.pipeline.mana_base import parse_land_colors

    info = parse_land_colors(
        str(card.get("oracle_text", "")), str(card.get("type_line", "")), colors
    )
    return info.is_fetch and bool(set(info.fetch_targets) & set(colors))


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
