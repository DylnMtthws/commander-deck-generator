"""Bounded candidate recall without pretending broad roles are substitutes."""

from __future__ import annotations

import json
from collections import defaultdict


def roles(card: dict) -> list[str]:
    value = card.get("role_tags") or []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            value = []
    return list(value)


def retain_candidates(
    cards: list[dict], protected: set[str], tracer=None
) -> list[dict]:
    """Union independent recall channels; dollars constrain admission, not dominance.

    Retain physical lands, explicit packages, relevant empirical candidates, and
    diverse roles/types/capabilities. Limits bound the quadratic optimizer without
    sacrificing an engine because an unrelated card has a cheaper printing.
    """
    from sabermetrics.intelligence.experiment import current

    experiment = current()
    selected: dict[str, dict] = {}
    reasons: dict[str, str] = {}

    def keep(card, reason):
        key = card.get("name", "")
        selected[key] = card
        reasons.setdefault(key, reason)

    ordered = sorted(
        cards, key=lambda c: (-float(c.get("_cvar_score", 0)), c.get("name", ""))
    )
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in ordered:
        name = c.get("name", "")
        front = (c.get("type_line") or "").split(" // ")[0].lower()
        if "land" in front:
            keep(c, "physical land retained independently of draw/fixing tags")
        if name in protected:
            keep(c, "protected executable package or infrastructure candidate")
        for role in roles(c):
            groups["role:" + role].append(c)
        for typ in (
            "artifact",
            "creature",
            "instant",
            "sorcery",
            "enchantment",
            "planeswalker",
        ):
            if typ in front:
                groups["type:" + typ].append(c)
        for cap in c.get("_facts", {}).get("capabilities", []):
            groups["cap:" + cap].append(c)
    corroborated = sorted(
        [c for c in ordered if float(c.get("_selection_inclusion", 0)) >= 0.10],
        key=lambda c: (
            -float(c.get("_selection_inclusion", 0)),
            -float(c.get("_cvar_score", 0)),
            c["name"],
        ),
    )
    for c in corroborated[:350]:
        keep(c, "commander/cohort evidence recall; inclusion is corroboration")
    for group in sorted(groups):
        for c in groups[group][:24]:
            keep(c, "diverse " + group + " recall")
    # Retain inexpensive functional alternatives before infrastructure spending.
    # Bands prevent a high-price ranking from consuming all discovery slots.
    if experiment.budget_recall:
        for group in sorted(groups):
            if not group.startswith(("role:", "cap:")):
                continue
            for ceiling in (0.25, 1.0, 3.0):
                affordable = [
                    c
                    for c in groups[group]
                    if 0 <= float(c.get("price_usd") or 0) <= ceiling
                ]
                for c in affordable[: experiment.budget_recall]:
                    keep(c, f"affordable {group} recall <= ${ceiling}")
    for c in ordered[:350]:
        keep(c, "structural recall channel")
    # Do not truncate protected packages or previously retained channels to a
    # global score order; that would recreate the original recall failure.
    result = [c for c in ordered if c["name"] in selected]
    if tracer is not None:
        for c in cards:
            retained = c["name"] in selected
            tracer.record(
                card_name=c["name"],
                card_id=c.get("id"),
                stage="candidate_recall",
                action="retained" if retained else "excluded",
                score=c.get("_cvar_score"),
                reason=reasons.get(
                    c["name"], "outside bounded recall channels; not declared dominated"
                ),
            )
    return result


def evidence_score(card: dict, base: float) -> float:
    """Keep mechanical discovery while adding an explicit empirical prior."""
    if not card.get("_selection_evidence_available"):
        return base
    rate = max(0.0, min(1.0, float(card.get("_selection_inclusion", 0))))
    synergy = max(0.0, min(1.0, float(card.get("_selection_synergy", 0))))
    # A prior is not a win estimate. Unseen cards retain a structural contribution;
    # cohort-supported cards gain priority without rarity or price bonuses.
    from sabermetrics.intelligence.experiment import current

    weight = current().evidence_weight
    return float(min(1.0, (0.9 - weight) * base + weight * rate**0.5 + 0.10 * synergy))
