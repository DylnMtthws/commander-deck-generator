"""Executable archetype requirements with affordable protected packages."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from sabermetrics.intelligence.cards import facts_for


class StrategyPlan(BaseModel):
    version: str = "strategy-plan.v1"
    archetype: str = "general"
    intent: str = ""
    commander_capabilities: list[str] = Field(default_factory=list)
    requirements: dict[str, int] = Field(default_factory=dict)
    selected: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def make_plan(commander: dict, intent: str | None, power: int = 3) -> StrategyPlan:
    text = (intent or "").lower()
    facts = facts_for(commander)
    landfall = "landfall" in text or (not text and "landfall" in facts.capabilities)
    oracle = str(commander.get("oracle_text") or "").lower()
    if not landfall:
        requirements = {}
        archetype = "general"
        # Require both actual commander damage and the requested draw engine.
        cast_damage = (
            "whenever you cast a noncreature spell" in oracle
            and "damage to each opponent" in oracle
        )
        if cast_damage and "curiosity" in text:
            archetype = "cast_damage_draw"
            requirements = {"opponent_damage_draw": 2, "cheap_noncreature_cast": 10}
        elif (
            "while" in oracle and "attacking" in oracle and "copy that spell" in oracle
        ):
            archetype = "combat_cast"
            requirements = {"instant_spell": 12}
        elif "proliferate" in oracle:
            archetype = "counters"
            requirements = {"counter_permanent": 10}
        else:
            # Typal requirements arise from rules text, not commander names.
            for tribe in ("dragon", "vampire", "goblin", "elf", "zombie", "merfolk"):
                if re.search(rf"\b{tribe}s?\b", oracle) and (
                    "spells you cast" in oracle
                    or "spell" in oracle
                    or "number of" in oracle
                ):
                    archetype = "typal"
                    requirements = {"creature_type:" + tribe: 16}
                    break
            if "angel, demon, or dragon creature card" in oracle:
                archetype = "attack_cheat"
                requirements = {"creature_types:angel,demon,dragon": 14}
            elif "land card from your graveyard to the battlefield" in oracle:
                archetype = "graveyard_lands"
                requirements = {"graveyard_land_access": 4, "self_mill": 3}
        if requirements:
            return StrategyPlan(
                archetype=archetype,
                intent=intent or archetype,
                commander_capabilities=facts.capabilities,
                requirements=requirements,
                limitations=[
                    "Requirements verify supported engine ingredients, not a complete win or competitive strength."
                ],
            )
        return StrategyPlan(
            intent=intent or "",
            limitations=[
                "No specialized archetype plan; existing protected-engine contract remains active."
            ],
        )
    return StrategyPlan(
        archetype="landfall",
        intent=intent or "Landfall",
        commander_capabilities=facts.capabilities,
        requirements={
            "land_ramp": 3,
            "landfall_cards": 2,
            "landfall_board": 2,
            "extra_land_play": 1,
            "land_recursion": 1,
        },
    )


def reserve_plan(
    plan: StrategyPlan, candidates: list[dict], budget: float
) -> list[dict]:
    """Reserve functional enablers/payoffs before individual Pareto pruning.

    Whole-package budget is capped at 30%, leaving mana and interaction space.
    Missing pieces are reported, not satisfied with unrelated replacements.
    """
    if not plan.requirements:
        return []
    selected: list[dict] = []
    seen: set[str] = set()
    spent = 0.0

    def quality(card):
        caps = set(facts_for(card).capabilities)
        # Repeatable cards and board production matter more than a cheap
        # temporary stat bonus. Price is a constraint and final tiebreak.
        recurring = (
            "instant" not in card.get("type_line", "").lower()
            and "sorcery" not in card.get("type_line", "").lower()
        )
        value = 3 * len(
            caps
            & {"landfall_cards", "landfall_board", "extra_land_play", "land_recursion"}
        )
        value += int(recurring)
        return (
            -float(card.get("_selection_inclusion", 0)),
            -value,
            float(card.get("cmc") or 0),
            float(card.get("price_usd") or 0),
            card.get("name", ""),
        )

    pool = sorted(candidates, key=quality)
    for requirement, count in plan.requirements.items():

        def matching(c, r=requirement):
            return matches_requirement(c, r)

        have = sum(matching(c) for c in selected) + int(
            requirement in plan.commander_capabilities
        )
        for card in pool:
            price = float(card.get("price_usd") or 0)
            name = card.get("name", "")
            if have >= count:
                break
            if name in seen or not matching(card) or facts_for(card).exclusion:
                continue
            if price < 0 or price > budget * 0.25 or spent + price > budget * 0.45:
                continue
            selected.append(card)
            seen.add(name)
            spent += price
            have += 1
            plan.evidence.append(
                {
                    "card": name,
                    "requirement": requirement,
                    "reason": f'Verified {requirement.replace("_", " ")} effect; reserved before optimization.',
                }
            )
    plan.selected = [c["name"] for c in selected]
    return selected


def assess_plan(plan: StrategyPlan, cards: list[dict]) -> dict:
    counts = {
        r: sum(matches_requirement(c, r) for c in cards)
        + int(r in plan.commander_capabilities)
        for r in plan.requirements
    }
    missing = {
        r: {"actual": counts[r], "required": n}
        for r, n in plan.requirements.items()
        if counts[r] < n
    }
    return {
        **plan.model_dump(),
        "counts": counts,
        "missing": missing,
        "status": (
            "unavailable"
            if not plan.requirements
            else ("partial" if missing else "satisfied")
        ),
    }


def matches_requirement(card: dict, requirement: str) -> bool:
    """Supported predicates; conditions remain visible in the card facts."""
    text = re.sub(r"\([^)]*\)", "", str(card.get("oracle_text") or "")).lower()
    front = str(card.get("type_line") or "").split(" // ")[0].lower()
    if requirement == "opponent_damage_draw":
        return bool(
            re.search(
                r"whenever .*deals (?:noncombat )?damage to an opponent.*draw (?:a|that many) cards?",
                text,
                re.DOTALL,
            )
        ) and "combat damage" not in text.replace("noncombat damage", "damage")
    if requirement == "cheap_noncreature_cast":
        if "creature" in front or "land" in front:
            return False
        if float(card.get("cmc") or 0) <= 1:
            return True
        # Conditional free spells are potential fuel, not a guaranteed free cast.
        return (
            "rather than pay this spell's mana cost" in text
            or "without paying its mana cost" in text
            and "if you control a commander" in text
        )
    if requirement == "instant_spell":
        return "instant" in front
    if requirement == "counter_permanent":
        return (
            any(
                t in front
                for t in ("creature", "artifact", "enchantment", "planeswalker")
            )
            and ("counter" in text or "planeswalker" in front)
            and "counter target" not in text
        )
    if requirement.startswith("creature_type:"):
        return "creature" in front and bool(
            re.search(r"\b" + requirement.split(":", 1)[1] + r"\b", front)
        )
    if requirement.startswith("creature_types:"):
        return "creature" in front and any(
            re.search(r"\b" + t + r"\b", front)
            for t in requirement.split(":", 1)[1].split(",")
        )
    if requirement == "graveyard_land_access":
        return (
            "land" in text
            and "graveyard" in text
            and any(word in text for word in ("return", "play", "put"))
        )
    if requirement == "self_mill":
        return (
            bool(
                re.search(
                    r"(?:you |^|, )mill (?:a|one|two|three|four|five|[0-9]+|x)", text
                )
            )
            or "put the top" in text
            and "your graveyard" in text
        )
    return requirement in facts_for(card).capabilities
