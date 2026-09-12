"""Executable archetype requirements with affordable protected packages."""

from __future__ import annotations

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


def make_plan(commander: dict, intent: str | None) -> StrategyPlan:
    text = (intent or "").lower()
    facts = facts_for(commander)
    landfall = "landfall" in text or (not text and "landfall" in facts.capabilities)
    if not landfall:
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
            -value,
            float(card.get("cmc") or 0),
            float(card.get("price_usd") or 0),
            card.get("name", ""),
        )

    pool = sorted(candidates, key=quality)
    for requirement, count in plan.requirements.items():

        def matching(c, r=requirement):
            return r in facts_for(c).capabilities

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
            if price < 0 or price > budget * 0.10 or spent + price > budget * 0.30:
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
        r: sum(r in facts_for(c).capabilities for c in cards)
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
