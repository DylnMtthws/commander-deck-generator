"""Optimizer role accounting uses complete_damage_role before cached tags."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from sabermetrics.analytics.role_targets import RoleTarget
from sabermetrics.analytics.synergy_matrix import SynergyMatrix
from sabermetrics.pipeline.greedy_optimizer import (
    _count_roles,
    _get_card_roles,
    greedy_fill,
)
from sabermetrics.pipeline.slot_assigner import SlotAssignment

_PUBLIC_SPELLS = (
    Path(__file__).resolve().parents[1]
    / "docs/experiments/commander-substitutions/public-spells.json"
)
CARDS = {
    card["name"]: card
    for card in json.loads(_PUBLIC_SPELLS.read_text(encoding="utf-8"))["cards"]
}

_PROOF_NAMES = ("Shock", "Burst Lightning", "Play with Fire")
_STALE_TAGS = ('["utility"]', "[]", ["utility"], [])


def _stale(card: dict, role_tags: str | list[str]) -> dict:
    """Incomplete cached metadata that must not hide a complete damage proof."""
    stale = deepcopy(card)
    stale["role_tags"] = role_tags
    stale["_facts"] = {"roles": []}
    stale["_primary_role"] = "utility"
    return stale


def _synergy(cards: list[dict]) -> SynergyMatrix:
    id_to_idx = {}
    idx_to_id = {}
    for i, card in enumerate(cards):
        cid = card.get("id") or card.get("oracle_id") or card["name"]
        card["id"] = cid
        id_to_idx[cid] = i
        idx_to_id[i] = cid
    return SynergyMatrix(
        matrix=np.zeros((len(cards), len(cards)), dtype=np.float32),
        card_id_to_index=id_to_idx,
        index_to_card_id=idx_to_id,
    )


@pytest.mark.parametrize("name", _PROOF_NAMES)
@pytest.mark.parametrize("role_tags", _STALE_TAGS)
def test_complete_damage_overrides_stale_cached_roles(name, role_tags) -> None:
    card = _stale(CARDS[name], role_tags)
    assert _get_card_roles(card) == ["removal"]
    counts = _count_roles(
        [SlotAssignment(card=card, slot_role="utility", score=0.0)]
    )
    assert counts.get("removal") == 1
    assert "utility" not in counts


def test_greedy_fill_assigns_complete_damage_as_removal() -> None:
    card = _stale(CARDS["Shock"], '["utility"]')
    card["price_usd"] = 0.10
    card["_cvar_score"] = 0.4
    assignments = greedy_fill(
        shell=[],
        candidates=[card],
        synergy=_synergy([card]),
        role_targets={
            "removal": RoleTarget(
                role="removal",
                target_count=7,
                min_count=5,
                max_count=11,
                need_by_turn=5,
                reliability=0.75,
            ),
        },
        budget_remaining=10.0,
        slots_remaining=1,
    )
    assert len(assignments) == 1
    assert assignments[0].slot_role == "removal"
    assert _get_card_roles(assignments[0].card) == ["removal"]
    assert _count_roles(assignments).get("removal") == 1


def test_player_only_damage_retains_cached_metadata_roles() -> None:
    card = _stale(CARDS["Shock"], '["utility"]')
    card["oracle_text"] = "This spell deals 2 damage to target player."
    assert _get_card_roles(card) == ["utility"]
    counts = _count_roles(
        [SlotAssignment(card=card, slot_role="utility", score=0.0)]
    )
    assert counts == {"utility": 1}


def test_unparsed_oracle_tail_retains_cached_metadata_roles() -> None:
    card = _stale(CARDS["Lightning Bolt"], '["utility"]')
    card["oracle_text"] = (
        "This spell deals 3 damage to any target. Skip your next turn."
    )
    assert _get_card_roles(card) == ["utility"]
    counts = _count_roles(
        [SlotAssignment(card=card, slot_role="utility", score=0.0)]
    )
    assert counts == {"utility": 1}


def test_unsupported_card_keeps_existing_role_tags() -> None:
    card = _stale(CARDS["Manalith"], '["ramp"]')
    assert _get_card_roles(card) == ["ramp"]
