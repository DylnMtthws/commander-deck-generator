"""Draw package generator (6.5.4).

Deterministic card draw selection: prefer repeatable over one-shot,
adjusted for commanders that provide inherent card advantage.
"""

import logging
from pathlib import Path

from sabermetrics.analytics.empirical_valuation import empirical_bonus
from sabermetrics.config import settings
from sabermetrics.models.template import DeckTemplate
from sabermetrics.pipeline.greedy_optimizer import is_playable_as_land
from sabermetrics.pipeline.slot_assigner import SlotAssignment

logger = logging.getLogger(__name__)


class DrawPackageGenerator:
    """Generate the card draw package for a deck."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def generate(
        self,
        color_identity: list[str],
        target_count: int,
        budget_remaining: float,
        template: DeckTemplate,
        already_placed: list[dict],
        role_tag_pool: list[dict],
        power_target: int = 3,
        commander: dict | None = None,
    ) -> list[SlotAssignment]:
        """Generate draw package sorted by CVAR, preferring repeatable draw.

        Args:
            color_identity: Commander's color identity.
            target_count: Target number of draw cards.
            budget_remaining: Remaining deck budget.
            template: Deck template for context.
            already_placed: Cards already in the deck.
            role_tag_pool: Pre-filtered cards with role_tags containing "draw".

        Returns:
            List of SlotAssignment for draw cards.
        """
        used_names = {c.get("name", "") for c in already_placed}
        assignments: list[SlotAssignment] = []
        running_price = 0.0
        from sabermetrics.intelligence.experiment import current

        if hasattr(self, "selection_receipt"):
            del self.selection_receipt
        route_mode = current().draw_package_policy == "routes"
        if route_mode:
            self.selection_receipt = {
                "mode": "actual_draw_routes",
                "assessments": [],
                "budget": budget_remaining,
                "target": target_count,
                "scope": "Known route constraints gate reservation; unknown coverage remains unverified, and conditional opportunities are not guaranteed draw.",
            }

        # Score candidates
        needed_types = template.unmet_type_targets(already_placed)
        candidates: list[tuple[dict, float]] = []
        for card in role_tag_pool:
            name = card.get("name", "")
            if name in used_names:
                continue
            # Lands are the land package's domain; placing one here inflates
            # the deck's land total past the template target.
            if is_playable_as_land(card.get("type_line") or ""):
                continue
            if card.get("_anti_engine"):
                continue
            if route_mode:
                from sabermetrics.intelligence.draw_route_assessment import (
                    assess_draw_routes,
                )

                assessment = assess_draw_routes(
                    card, already_placed, commander or {}, power_target
                )
                self.selection_receipt["assessments"].append(
                    {"name": name, **assessment}
                )
                if assessment["status"] == "blocked":
                    continue

            cvar = card.get("_cvar_score", 0.3)
            oracle = (card.get("oracle_text") or "").lower()
            type_line = (card.get("type_line") or "").lower()

            # Prefer repeatable draw (permanents with draw triggers)
            is_repeatable = (
                "creature" in type_line
                or "enchantment" in type_line
                or "artifact" in type_line
            ) and (
                "whenever" in oracle or "at the beginning" in oracle or "each" in oracle
            )
            if is_repeatable:
                cvar += 0.15

            # Budget preference
            price = float(card.get("price_usd", 0) or 0)
            if price <= 2.0:
                cvar += 0.03

            # Empirical grounding: additive, never penalizes absence (ADR-005)
            cvar += empirical_bonus(
                card,
                settings.scoring.generator_empirical_weight,
                settings.scoring.generator_empirical_noisy_weight,
            )

            # Type-need: prefer on-type cards while the archetype's engine
            # type is undersupplied (corpus targets; empty without one).
            if needed_types:
                tl = (card.get("type_line") or "").lower()
                if any(t in tl for t in needed_types):
                    cvar += settings.scoring.generator_type_need_weight

            candidates.append((card, cvar))

        candidates.sort(key=lambda x: x[1], reverse=True)

        if current().draw_package_policy in {"budgeted", "coverage"}:
            from sabermetrics.intelligence.draw_portfolio import select_portfolio

            candidates, self.selection_receipt = select_portfolio(
                candidates,
                target_count,
                budget_remaining,
                diversity=current().draw_package_policy == "coverage",
                max_mana_value=(
                    3 if power_target == 5 else 4 if power_target == 4 else 5
                ),
            )

        for card, score in candidates:
            if len(assignments) >= target_count:
                break

            name = card.get("name", "")
            if name in used_names:
                continue

            price = float(card.get("price_usd", 0) or 0)
            if (
                route_mode or budget_remaining > 0
            ) and running_price + price > budget_remaining:
                continue

            assignments.append(
                SlotAssignment(
                    card=card,
                    slot_role="draw",
                    score=round(score, 4),
                    alternatives=[],
                )
            )
            used_names.add(name)
            running_price += price

        if route_mode:
            self.selection_receipt["selected"] = [a.card["name"] for a in assignments]
            self.selection_receipt["spent"] = running_price

        logger.info(
            "Draw generator: %d draw cards (target %d)",
            len(assignments),
            target_count,
        )
        return assignments
