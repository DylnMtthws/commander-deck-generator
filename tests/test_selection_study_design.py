import itertools

import pytest

from sabermetrics.intelligence.experiment import production_policy
from sabermetrics.intelligence.study_design import FACTORS, configurations, register


def test_all_implemented_factor_combinations_and_exact_production_are_present():
    rows = configurations()
    assert len(rows) == len({r["id"] for r in rows}) == 16
    assert sum(r["production"] for r in rows) == 1
    assert (
        next(r["policy"] for r in rows if r["production"])
        == production_policy().to_dict()
    )
    assert all(r["policy"]["preserve_functions"] for r in rows)
    assert rows == configurations()
    for a, b in itertools.combinations(FACTORS, 2):
        assert {(r["policy"][a], r["policy"][b]) for r in rows} == set(
            itertools.product(FACTORS[a], FACTORS[b])
        )


def test_registry_is_explicitly_unexecuted_and_enforces_full_workload_cap():
    kwargs = {
        "cases": [{"case_id": "a"}],
        "repeats": 3,
        "source_sha256": "a" * 64,
        "data_sha256": "b" * 64,
    }
    with pytest.raises(ValueError, match="48 builds"):
        register(**kwargs, max_builds=47)
    result = register(**kwargs, max_builds=48)
    assert result["planned_builds"] == 48
    assert result["status"] == "registered_not_executed"


@pytest.mark.parametrize(
    "change",
    [
        {"repeats": True},
        {"repeats": 0},
        {"source_sha256": ""},
        {"cases": []},
        {"cases": [{"case_id": "a"}, {"case_id": "a"}]},
    ],
)
def test_invalid_or_ambiguous_registration_rejected(change):
    values = {
        "cases": [{"case_id": "a"}],
        "repeats": 1,
        "max_builds": 16,
        "source_sha256": "a" * 64,
        "data_sha256": "b" * 64,
    }
    with pytest.raises(ValueError):
        register(**{**values, **change})


def test_offline_study_uses_production_template_not_budget_screen_override(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    from run_function_study import offline_builder_class
    from screen_budget import Replay

    from sabermetrics.pipeline.deck_builder import DeckBuilder

    offline = offline_builder_class()
    assert offline._derive_template is DeckBuilder._derive_template
    assert offline._derive_template is not Replay._derive_template
    assert offline._llm_safety_check is Replay._llm_safety_check


def test_persisted_role_audit_catches_unchanged_baseline_failure(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    from run_function_study import damage_role_failures

    card = {
        "name": "Shock",
        "type_line": "Instant",
        "mana_cost": "{R}",
        "cmc": 1,
        "oracle_text": "Shock deals 2 damage to any target.",
    }
    data = {"deck": {"cards": [{"card": card, "slot_role": "utility"}]}}
    assert damage_role_failures(data) == [
        {"card": "Shock", "actual": "utility", "expected": "removal"}
    ]
    data["deck"]["cards"][0]["slot_role"] = "removal"
    assert damage_role_failures(data) == []
