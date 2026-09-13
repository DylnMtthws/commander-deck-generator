import math

import pytest

from sabermetrics.intelligence.experiment import Experiment, current, using
from sabermetrics.intelligence.selection import evidence_score, retain_candidates


def test_scope_restored_on_error():
    assert current() == Experiment()
    with using(Experiment(evidence_weight=0.25)):
        assert current().evidence_weight == 0.25
        with pytest.raises(RuntimeError), using(Experiment(evidence_weight=0.65)):
            raise RuntimeError()
        assert current().evidence_weight == 0.25
    assert current() == Experiment()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"evidence_weight": math.nan},
        {"land_risk_weight": math.inf},
        {"budget_recall": 1.5},
        {"evidence_weight": 1},
    ],
)
def test_invalid_controls_rejected(kwargs):
    with pytest.raises(ValueError):
        Experiment(**kwargs)


def test_baseline_score_reproduced():
    card = {
        "_selection_evidence_available": True,
        "_selection_inclusion": 0.25,
        "_selection_synergy": 0.3,
    }
    assert evidence_score(card, 0.6) == pytest.approx(
        0.45 * 0.6 + 0.45 * 0.5 + 0.1 * 0.3
    )


def test_affordable_recall_survives_expensive_competitors():
    expensive = [
        {
            "name": f"Premium{i}",
            "type_line": "Instant",
            "role_tags": ["removal"],
            "price_usd": 30,
            "_cvar_score": 0.9,
        }
        for i in range(400)
    ]
    cheap = {
        "name": "Affordable removal",
        "type_line": "Instant",
        "role_tags": ["removal"],
        "price_usd": 0.2,
        "_cvar_score": 0.5,
    }
    assert cheap not in retain_candidates(expensive + [cheap], set())
    with using(Experiment(budget_recall=12)):
        first = retain_candidates(expensive + [cheap], set())
        second = retain_candidates(list(reversed(expensive + [cheap])), set())
        assert cheap in first
        assert first == second
    assert cheap["_cvar_score"] == 0.5
