"""Deck synthesis narrative generator (D5.7).

User-facing narrative is rendered by the application from final-list card
facts and roles. Profile and fit still use model calls elsewhere; this
module does not emit free-form model prose. Name-only callers stay
conservative. Cost is zero because no synthesis model call is consumed.
"""

import logging
from pathlib import Path
from typing import Any

from sabermetrics.models.llm_responses import DeckSynthesisResponse
from sabermetrics.reasoning.narrative_grounding import (
    card_facts_from_dicts,
    format_deck_facts,
    render_deck_narrative,
)

logger = logging.getLogger(__name__)


class DeckSynthesizer:
    """Generate deck-level narrative and analysis."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def synthesize(
        self,
        profile_summary: str,
        deck_cards_with_reasoning: list[dict],
        bracket: int,
        bracket_reasoning: str,
    ) -> tuple[DeckSynthesisResponse, float]:
        """Generate a strategic narrative for a completed deck.

        Args:
            profile_summary: Compressed commander profile text. Not used as
                a source of commander identity or card claims.
            deck_cards_with_reasoning: Final-list dicts. Authoritative rows
                include name, mana value, oracle text, type, and role.
                Name-only dicts remain supported and stay conservative.
            bracket: Power bracket classification (1-5).
            bracket_reasoning: Explanation of bracket classification.

        Returns:
            Tuple of (DeckSynthesisResponse, cost_usd). Narrative rendering
            does not call a model, so cost is 0.0. Profile/fit costs are
            accounted by those callers.
        """
        del profile_summary
        facts = card_facts_from_dicts(deck_cards_with_reasoning)
        narrative = render_deck_narrative(facts, bracket, bracket_reasoning)
        logger.info(
            "Deck narrative rendered from %d listed cards (%d fact lines)",
            len(facts),
            len(narrative.key_synergies),
        )
        return narrative, 0.0

    def _format_deck_summary(
        self,
        deck_cards_with_reasoning: list[dict[str, Any]],
        facts: list[Any],
    ) -> str:
        by_name = {fact.name: fact for fact in facts}
        lines: list[str] = []
        for card_info in deck_cards_with_reasoning:
            name = card_info.get("name", "Unknown")
            role = card_info.get("slot_role") or card_info.get("role") or "other"
            score = card_info.get("fit_score", "?")
            reasoning = card_info.get("reasoning", "")
            fact = by_name.get(name)
            extra = ""
            if fact is not None:
                bits: list[str] = []
                if fact.mana_value is not None:
                    bits.append(f"MV={fact.mana_value:g}")
                if fact.type_line:
                    bits.append(fact.type_line)
                if fact.oracle_text:
                    bits.append(fact.oracle_text)
                if bits:
                    extra = " " + "; ".join(bits)
            lines.append(f"- {name} [{role}] (fit: {score}/10): {reasoning}{extra}")
        if not lines:
            return format_deck_facts(facts)
        return "\n".join(lines)
