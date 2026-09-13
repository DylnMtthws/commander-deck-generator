import json
from pathlib import Path

import pytest

from sabermetrics.intelligence.cards import annotate

CARDS = {
    c["name"]: c
    for c in json.loads(
        (
            Path(__file__).parents[1]
            / "docs/experiments/commander-substitutions/public-spells.json"
        ).read_text()
    )["cards"]
}


@pytest.mark.parametrize("name", ["Shock", "Burst Lightning", "Play with Fire"])
@pytest.mark.parametrize("tags", [["utility"], ["draw"], ["land"], ["removal"]])
def test_complete_damage_evidence_repairs_canonical_role_metadata(name, tags):
    result = annotate({**CARDS[name], "role_tags": tags})
    assert json.loads(result["role_tags"]) == ["removal"]
    assert result["_verified_roles"] == ["removal"]
    assert result["_primary_role"] == "removal"
    assert result["_discovery_roles"] == tags
    assert result["_role_evidence"]["evidence"] == [CARDS[name]["oracle_text"]]


def test_player_only_effect_does_not_receive_creature_removal_evidence():
    result = annotate(
        {
            **CARDS["Shock"],
            "oracle_text": "Shock deals 2 damage to target player.",
            "role_tags": ["removal"],
        }
    )
    assert "removal" not in result["_verified_roles"]
    assert "_role_evidence" not in result


def test_changed_oracle_cannot_retain_old_role_proof():
    prior = annotate(CARDS["Shock"])
    changed = annotate(
        {**prior, "oracle_text": "Shock deals 2 damage to target player."}
    )
    assert "_role_evidence" not in changed
    assert "removal" not in changed["_verified_roles"]
