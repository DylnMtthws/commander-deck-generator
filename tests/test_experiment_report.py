"""Independent synthetic coverage for experiment_report.summarize."""

from __future__ import annotations

import copy
import json
import math

import pytest

from sabermetrics.intelligence.experiment_report import (
    DISCLAIMER,
    SCHEMA_VERSION,
    summarize,
)

FORBIDDEN_KEYS = frozenset(
    {
        "ci",
        "composite_score",
        "confidence_interval",
        "improved",
        "p_value",
        "pvalue",
        "rank",
        "significant",
        "significance",
        "weighted_score",
        "winner",
    }
)


def _row(
    case_id: str,
    arm: str,
    repeat: int,
    *,
    status: str = "completed",
    hard_failures: int = 0,
    flagged_cards: int = 0,
    price: float = 10.0,
    budget: float = 100.0,
    elapsed: float = 1.0,
    **metrics: object,
) -> dict:
    payload: dict = {
        "case_id": case_id,
        "arm": arm,
        "repeat": repeat,
        "status": status,
        "hard_failures": hard_failures,
        "flagged_cards": flagged_cards,
        "price": price,
        "budget": budget,
        "elapsed": elapsed,
    }
    payload.update(metrics)
    return payload


def _keys(obj: object) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.add(key)
            found.update(_keys(value))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_keys(item))
    return found


def test_empty_input_is_a_valid_report() -> None:
    report = summarize([])
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["arms"] == []
    assert report["comparisons"] == []
    assert report["disclaimer"] == DISCLAIMER
    assert "winner" not in report
    json.dumps(report)


def test_synthetic_rows_counts_and_completed_medians() -> None:
    rows = [
        _row(
            "alpha",
            "baseline",
            0,
            hard_failures=1,
            flagged_cards=4,
            price=40.0,
            elapsed=8.0,
        ),
        _row(
            "alpha",
            "baseline",
            1,
            hard_failures=5,
            flagged_cards=2,
            price=20.0,
            elapsed=4.0,
        ),
        _row(
            "bravo",
            "baseline",
            0,
            hard_failures=3,
            flagged_cards=6,
            price=30.0,
            elapsed=6.0,
        ),
        _row(
            "alpha",
            "candidate",
            0,
            hard_failures=0,
            flagged_cards=1,
            price=35.0,
            elapsed=7.0,
        ),
        _row(
            "alpha",
            "candidate",
            1,
            hard_failures=2,
            flagged_cards=3,
            price=15.0,
            elapsed=3.0,
        ),
    ]
    report = summarize(rows)
    arms = {entry["arm"]: entry for entry in report["arms"]}
    assert arms["baseline"]["attempted"] == 3
    assert arms["baseline"]["completed"] == 3
    assert arms["baseline"]["failed"] == 0
    assert arms["candidate"]["attempted"] == 2
    assert arms["baseline"]["medians"]["hard_failures"] == 3
    assert arms["baseline"]["medians"]["flagged_cards"] == 4
    assert arms["baseline"]["medians"]["price"] == 30.0
    assert arms["baseline"]["medians"]["elapsed"] == 6.0
    assert arms["candidate"]["medians"]["hard_failures"] == 1.0
    comparison = report["comparisons"][0]
    assert comparison["arm"] == "candidate"
    assert comparison["versus"] == "baseline"
    assert comparison["completed_pairs"] == 2
    assert comparison["attempted_pairs"] == 2
    assert comparison["median_deltas"]["hard_failures"] == -2.0
    assert comparison["median_deltas"]["flagged_cards"] == -1.0
    assert comparison["median_deltas"]["price"] == -5.0
    assert comparison["median_deltas"]["elapsed"] == -1.0
    paired_keys = [(row["case_id"], row["repeat"]) for row in comparison["paired"]]
    assert paired_keys == [("alpha", 0), ("alpha", 1)]
    assert comparison["paired"][0]["delta_hard_failures"] == -1
    assert comparison["missing"][0]["reason"] == "missing_arm"
    assert comparison["missing"][0]["case_id"] == "bravo"


def test_failed_runs_remain_in_denominator_and_unpaired() -> None:
    rows = [
        _row("alpha", "baseline", 0, hard_failures=4, elapsed=10.0),
        _row("alpha", "baseline", 1, status="failed", hard_failures=9, elapsed=99.0),
        _row("alpha", "candidate", 0, hard_failures=1, elapsed=8.0),
        _row("alpha", "candidate", 1, status="failed", hard_failures=8, elapsed=80.0),
        _row("bravo", "baseline", 0, status="failed", hard_failures=7, elapsed=50.0),
        _row("bravo", "candidate", 0, hard_failures=0, elapsed=5.0),
    ]
    report = summarize(rows)
    arms = {entry["arm"]: entry for entry in report["arms"]}
    assert arms["baseline"]["attempted"] == 3
    assert arms["baseline"]["completed"] == 1
    assert arms["baseline"]["failed"] == 2
    assert arms["candidate"]["attempted"] == 3
    assert arms["candidate"]["failed"] == 1
    assert arms["baseline"]["medians"]["hard_failures"] == 4
    assert arms["baseline"]["medians"]["elapsed"] == 10.0
    comparison = report["comparisons"][0]
    assert comparison["attempted_pairs"] == 3
    assert comparison["completed_pairs"] == 1
    assert comparison["paired"][0]["case_id"] == "alpha"
    assert comparison["paired"][0]["repeat"] == 0
    unpaired_keys = {
        (row["case_id"], row["repeat"], row["reason"]) for row in comparison["unpaired"]
    }
    assert ("alpha", 1, "failed_both") in unpaired_keys
    assert ("bravo", 0, "failed_baseline") in unpaired_keys
    assert comparison["missing"] == []
    assert comparison["median_deltas"]["hard_failures"] == -3
    # Failed elapsed 99/80 must not pull the completed-only median.
    assert comparison["median_deltas"]["elapsed"] == -2.0


def test_missing_pairs_are_listed_not_dropped() -> None:
    rows = [
        _row("kept", "baseline", 0, hard_failures=2),
        _row("kept", "candidate", 0, hard_failures=1),
        _row("only-base", "baseline", 0, hard_failures=5),
        _row("only-arm", "candidate", 1, hard_failures=3),
    ]
    comparison = summarize(rows)["comparisons"][0]
    assert comparison["attempted_pairs"] == 1
    assert comparison["completed_pairs"] == 1
    missing = {
        (row["case_id"], row["repeat"], row["reason"]) for row in comparison["missing"]
    }
    assert missing == {
        ("only-arm", 1, "missing_baseline"),
        ("only-base", 0, "missing_arm"),
    }
    by_case = {row["case_id"]: row for row in comparison["missing"]}
    assert by_case["only-arm"]["baseline_status"] is None
    assert by_case["only-arm"]["arm_status"] == "completed"
    assert by_case["only-base"]["arm_status"] is None


def test_reversed_input_is_deterministic() -> None:
    rows = [
        _row(
            "zeta",
            "treatment",
            1,
            hard_failures=2,
            flagged_cards=1,
            salt=0.2,
        ),
        _row(
            "alpha",
            "baseline",
            0,
            hard_failures=4,
            flagged_cards=3,
            salt=0.4,
        ),
        _row(
            "alpha",
            "treatment",
            0,
            hard_failures=1,
            flagged_cards=0,
            salt=0.1,
        ),
        _row(
            "zeta",
            "baseline",
            1,
            hard_failures=6,
            flagged_cards=5,
            salt=0.5,
        ),
        _row("mid", "other", 0, hard_failures=0, flagged_cards=0),
        _row("mid", "baseline", 0, hard_failures=1, flagged_cards=1),
    ]
    forward = summarize(rows)
    backward = summarize(list(reversed(rows)))
    assert forward == backward
    assert [entry["arm"] for entry in forward["arms"]] == [
        "baseline",
        "other",
        "treatment",
    ]
    assert [entry["arm"] for entry in forward["comparisons"]] == [
        "other",
        "treatment",
    ]
    treatment = forward["comparisons"][1]
    assert [(row["case_id"], row["repeat"]) for row in treatment["paired"]] == [
        ("alpha", 0),
        ("zeta", 1),
    ]


def test_inputs_unchanged() -> None:
    rows = [
        _row("alpha", "baseline", 0, combo_hits=1),
        _row("alpha", "candidate", 0, combo_hits=2),
    ]
    snapshot = copy.deepcopy(rows)
    summarize(rows)
    assert rows == snapshot
    assert rows[0]["combo_hits"] == 1


def test_nonfinite_numeric_fields_raise() -> None:
    for field, value in (
        ("price", math.nan),
        ("elapsed", math.inf),
        ("budget", -math.inf),
        ("hard_failures", math.nan),
        ("combo_hits", math.inf),
    ):
        row = _row("alpha", "baseline", 0, combo_hits=1.0)
        row[field] = value
        with pytest.raises(ValueError, match="nonfinite"):
            summarize([row])


def test_duplicate_arm_case_repeat_raises() -> None:
    rows = [
        _row("alpha", "baseline", 0, hard_failures=1),
        _row("alpha", "baseline", 0, hard_failures=2),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        summarize(rows)
    # Same case/repeat on a different arm is a pair, not a duplicate.
    ok = [
        _row("alpha", "baseline", 0),
        _row("alpha", "candidate", 0),
        _row("alpha", "baseline", 1),
    ]
    report = summarize(ok)
    assert report["arms"][0]["attempted"] == 2


def test_zero_budget_invalid_for_completed_not_failed() -> None:
    completed = _row("alpha", "baseline", 0, budget=0.0)
    with pytest.raises(ValueError, match="zero budget"):
        summarize([completed])
    failed = _row("alpha", "baseline", 0, status="failed", budget=0.0)
    report = summarize([failed])
    assert report["arms"][0]["failed"] == 1
    assert report["arms"][0]["completed"] == 0
    assert report["arms"][0]["medians"]["hard_failures"] is None


def test_optional_metrics_stay_descriptive_no_invented_score() -> None:
    rows = [
        _row("alpha", "baseline", 0, salt=4.0, note="ok"),
        _row("alpha", "baseline", 1, salt=2.0),
        _row("alpha", "candidate", 0, salt=1.0),
        _row("alpha", "candidate", 1, salt=3.0),
    ]
    report = summarize(rows)
    arms = {entry["arm"]: entry for entry in report["arms"]}
    assert arms["baseline"]["medians"]["salt"] == 3.0
    comparison = report["comparisons"][0]
    assert "delta_salt" not in comparison["paired"][0]
    assert set(comparison["median_deltas"]) == {
        "hard_failures",
        "flagged_cards",
        "elapsed",
        "price",
    }
    assert FORBIDDEN_KEYS.isdisjoint(_keys(report))
    assert "score" not in comparison
    json.loads(json.dumps(report))


def test_pairing_uses_exact_case_and_repeat() -> None:
    rows = [
        _row("shared", "baseline", 0, hard_failures=10, price=50.0),
        _row("shared", "candidate", 1, hard_failures=1, price=20.0),
        _row("shared", "baseline", 1, hard_failures=8, price=40.0),
        _row("shared", "candidate", 0, hard_failures=3, price=30.0),
    ]
    comparison = summarize(rows)["comparisons"][0]
    assert comparison["missing"] == []
    assert comparison["completed_pairs"] == 2
    by_repeat = {row["repeat"]: row for row in comparison["paired"]}
    assert by_repeat[0]["delta_hard_failures"] == -7
    assert by_repeat[1]["delta_hard_failures"] == -7
    assert by_repeat[0]["delta_price"] == -20.0


def test_failed_attempt_needs_no_fabricated_deck_metrics():
    from sabermetrics.intelligence.experiment_report import summarize

    report = summarize(
        [
            {
                "case_id": "missing",
                "arm": "candidate",
                "repeat": 0,
                "status": "failed",
                "elapsed": 2.0,
                "budget": 100.0,
            }
        ]
    )
    assert report["arms"][0]["attempted"] == 1
    assert report["arms"][0]["failed"] == 1
    assert report["arms"][0]["medians"]["hard_failures"] is None
