"""Behavioral coverage for function_receipt.compare_functions.

Examples are synthetic structured facts, not real Oracle extraction.
"""

from __future__ import annotations

import copy
import json
import math

import pytest

from sabermetrics.intelligence.function_receipt import (
    UNKNOWN_REMOVAL_REASON,
    compare_functions,
)

FORBIDDEN_KEYS = frozenset(
    {
        "better",
        "improved",
        "improvement",
        "quality",
        "winner",
    }
)


def _fn(
    key: str,
    scope: str,
    confidence: str = "supported",
    evidence: list[str] | None = None,
) -> dict:
    return {
        "key": key,
        "scope": scope,
        "confidence": confidence,
        "evidence": ["synthetic fact"] if evidence is None else evidence,
    }


def _card(
    card_id: str,
    name: str,
    functions: list[dict],
    count: int | None = None,
    **extra: object,
) -> dict:
    payload: dict = {
        "id": card_id,
        "name": name,
        "functions": functions,
        "coverage_complete": bool(functions),
    }
    if count is not None:
        payload["count"] = count
    payload.update(extra)
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


def test_empty_inputs_yield_unchanged_receipt() -> None:
    receipt = compare_functions([], [])
    assert receipt == {
        "added": [],
        "removed": [],
        "lost_functions": [],
        "protected_removed": [],
        "unknown_removals": [],
        "changed": False,
        "status": "unchanged",
    }
    json.dumps(receipt)


def test_lost_removal_creature_scope_distinct_from_nonland_permanent() -> None:
    before = [
        _card(
            "syn-rem-creature",
            "Synthetic Creature Removal",
            [_fn("removal", "creature", evidence=["destroy target creature"])],
        )
    ]
    after = [
        _card(
            "syn-rem-permanent",
            "Synthetic Nonland Permanent Removal",
            [
                _fn(
                    "removal",
                    "nonland permanent",
                    evidence=["destroy target nonland permanent"],
                )
            ],
        )
    ]
    receipt = compare_functions(before, after)
    assert receipt["lost_functions"] == [
        {
            "key": "removal",
            "scope": "creature",
            "before": 1,
            "after": 0,
            "lost": 1,
        }
    ]
    lost_scopes = {(row["key"], row["scope"]) for row in receipt["lost_functions"]}
    assert ("removal", "nonland permanent") not in lost_scopes
    assert receipt["added"] == [
        {
            "id": "syn-rem-permanent",
            "name": "Synthetic Nonland Permanent Removal",
            "count": 1,
        }
    ]
    assert receipt["removed"] == [
        {"id": "syn-rem-creature", "name": "Synthetic Creature Removal", "count": 1}
    ]
    assert receipt["status"] == "changes_observed"
    assert receipt["changed"] is True


def test_lost_token_generation_and_elf_tutoring_not_offset_by_generic_draw() -> None:
    before = [
        _card(
            "syn-token",
            "Synthetic Token Generator",
            [_fn("token_generation", "creature", evidence=["create a creature token"])],
        ),
        _card(
            "syn-elf-tutor",
            "Synthetic Elf Tutor",
            [_fn("tutoring", "elf", evidence=["search library for an elf"])],
        ),
    ]
    after = [
        _card(
            "syn-draw",
            "Synthetic Generic Draw",
            [_fn("draw", "card", evidence=["draw a card"])],
        )
    ]
    receipt = compare_functions(before, after)
    assert receipt["lost_functions"] == [
        {
            "key": "token_generation",
            "scope": "creature",
            "before": 1,
            "after": 0,
            "lost": 1,
        },
        {
            "key": "tutoring",
            "scope": "elf",
            "before": 1,
            "after": 0,
            "lost": 1,
        },
    ]
    assert ("draw", "card") not in {
        (row["key"], row["scope"]) for row in receipt["lost_functions"]
    }
    assert receipt["added"] == [
        {"id": "syn-draw", "name": "Synthetic Generic Draw", "count": 1}
    ]


def test_lost_cost_reduction_library_manipulation_and_graveyard_fuel() -> None:
    before = [
        _card(
            "syn-cost",
            "Synthetic Cost Reducer",
            [_fn("cost_reduction", "generic", evidence=["spells cost less"])],
        ),
        _card(
            "syn-library",
            "Synthetic Library Manipulator",
            [_fn("library_manipulation", "library", evidence=["look at the top card"])],
        ),
        _card(
            "syn-yard",
            "Synthetic Graveyard Fuel",
            [_fn("graveyard_fuel", "graveyard", evidence=["mill cards"])],
        ),
    ]
    after = [
        _card(
            "syn-draw",
            "Synthetic Generic Draw",
            [_fn("draw", "card", evidence=["draw a card"])],
        )
    ]
    receipt = compare_functions(before, after)
    assert receipt["lost_functions"] == [
        {
            "key": "cost_reduction",
            "scope": "generic",
            "before": 1,
            "after": 0,
            "lost": 1,
        },
        {
            "key": "graveyard_fuel",
            "scope": "graveyard",
            "before": 1,
            "after": 0,
            "lost": 1,
        },
        {
            "key": "library_manipulation",
            "scope": "library",
            "before": 1,
            "after": 0,
            "lost": 1,
        },
    ]


def test_protected_removed_even_with_same_role_replacement() -> None:
    before = [
        _card(
            "syn-protected",
            "Synthetic Protected Engine",
            [_fn("ramp", "mana", evidence=["add mana"])],
        )
    ]
    after = [
        _card(
            "syn-ramp-alt",
            "Synthetic Ramp Replacement",
            [_fn("ramp", "mana", evidence=["add mana"])],
        )
    ]
    receipt = compare_functions(before, after, protected_ids=["syn-protected"])
    assert receipt["protected_removed"] == [
        {"id": "syn-protected", "name": "Synthetic Protected Engine", "count": 1}
    ]
    assert receipt["removed"] == receipt["protected_removed"]
    assert receipt["lost_functions"] == []
    assert receipt["status"] == "changes_observed"


def test_partial_replacement_cannot_offset_supported_loss() -> None:
    before = [
        _card(
            "syn-token-supported",
            "Synthetic Supported Token Generator",
            [
                _fn(
                    "token_generation",
                    "creature",
                    "supported",
                    ["create a creature token"],
                )
            ],
        )
    ]
    after = [
        _card(
            "syn-token-partial",
            "Synthetic Partial Token Generator",
            [
                _fn(
                    "token_generation",
                    "creature",
                    "partial",
                    ["might create a token"],
                )
            ],
        )
    ]
    receipt = compare_functions(before, after)
    assert receipt["lost_functions"] == [
        {
            "key": "token_generation",
            "scope": "creature",
            "before": 1,
            "after": 0,
            "lost": 1,
        }
    ]
    assert receipt["unknown_removals"] == []
    assert receipt["added"][0]["id"] == "syn-token-partial"


def test_noop_is_unchanged_not_improvement() -> None:
    cards = [
        _card("syn-draw", "Synthetic Generic Draw", [_fn("draw", "card")]),
        _card("syn-ramp", "Synthetic Ramp", [_fn("ramp", "mana")], count=2),
    ]
    receipt = compare_functions(cards, copy.deepcopy(cards))
    assert receipt["status"] == "unchanged"
    assert receipt["changed"] is False
    assert receipt["added"] == []
    assert receipt["removed"] == []
    assert receipt["lost_functions"] == []
    assert receipt["protected_removed"] == []
    assert FORBIDDEN_KEYS.isdisjoint(_keys(receipt))
    assert "improved" not in json.dumps(receipt)


def test_added_coverage_is_changes_observed_not_improvement() -> None:
    before = [_card("syn-draw", "Synthetic Generic Draw", [_fn("draw", "card")])]
    after = [
        _card("syn-draw", "Synthetic Generic Draw", [_fn("draw", "card")]),
        _card("syn-extra", "Synthetic Extra Draw", [_fn("draw", "card")]),
    ]
    receipt = compare_functions(before, after)
    assert receipt["status"] == "changes_observed"
    assert receipt["lost_functions"] == []
    assert FORBIDDEN_KEYS.isdisjoint(_keys(receipt))


def test_counts_and_duplicate_facts_do_not_double_count() -> None:
    draw = _fn("draw", "card", evidence=["draw a card"])
    duplicate_facts = [
        draw,
        _fn("draw", "card", evidence=["draw a card"]),
        _fn("draw", "card", evidence=["draw a card", "draw a card"]),
    ]
    counted = [_card("syn-draw", "Synthetic Generic Draw", duplicate_facts, count=2)]
    repeated = [
        _card("syn-draw", "Synthetic Generic Draw", duplicate_facts),
        _card("syn-draw", "Synthetic Generic Draw", [draw]),
    ]
    noop = compare_functions(counted, repeated)
    assert noop["status"] == "unchanged"
    assert noop["changed"] is False
    lost_from_count = compare_functions(counted, [])
    lost_from_rows = compare_functions(repeated, [])
    expected = [
        {
            "key": "draw",
            "scope": "card",
            "before": 2,
            "after": 0,
            "lost": 2,
        }
    ]
    assert lost_from_count["lost_functions"] == expected
    assert lost_from_rows["lost_functions"] == expected
    assert lost_from_count["removed"] == [
        {"id": "syn-draw", "name": "Synthetic Generic Draw", "count": 2}
    ]
    mixed = compare_functions(
        [_card("syn-draw", "Synthetic Generic Draw", [_fn("draw", "card")], count=3)],
        [_card("syn-draw", "Synthetic Generic Draw", [_fn("draw", "card")])],
    )
    assert mixed["removed"] == [
        {"id": "syn-draw", "name": "Synthetic Generic Draw", "count": 2}
    ]
    assert mixed["lost_functions"] == [
        {
            "key": "draw",
            "scope": "card",
            "before": 3,
            "after": 1,
            "lost": 2,
        }
    ]


def test_early_stage_comparison_is_independent_of_downstream_guard() -> None:
    before = [
        _card(
            "syn-rem-creature",
            "Synthetic Creature Removal",
            [_fn("removal", "creature")],
            blocked_by_guard=True,
            guard_stage="downstream",
        )
    ]
    after = [
        _card(
            "syn-draw",
            "Synthetic Generic Draw",
            [_fn("draw", "card")],
            selected_by_guard=True,
            guard_stage="downstream",
        )
    ]
    before_snapshot = copy.deepcopy(before)
    after_snapshot = copy.deepcopy(after)
    receipt = compare_functions(before, after)
    assert receipt["lost_functions"] == [
        {
            "key": "removal",
            "scope": "creature",
            "before": 1,
            "after": 0,
            "lost": 1,
        }
    ]
    assert before == before_snapshot
    assert after == after_snapshot
    assert before[0]["blocked_by_guard"] is True
    assert after[0]["selected_by_guard"] is True
    assert "guard" not in receipt
    assert "selected" not in receipt


def test_unknown_removals_name_incomplete_coverage_not_bad_cards() -> None:
    before = [
        _card("syn-empty", "Synthetic Unlabeled", []),
        _card(
            "syn-partial",
            "Synthetic Partial Only",
            [_fn("draw", "card", "partial", ["maybe draw"])],
        ),
        _card(
            "syn-unknown",
            "Synthetic Unknown Only",
            [_fn("ramp", "mana", "unknown", [])],
        ),
        _card(
            "syn-mixed",
            "Synthetic Mixed Coverage",
            [
                _fn("removal", "creature", "supported", ["destroy target creature"]),
                _fn("draw", "card", "unknown", []),
            ],
        ),
        _card(
            "syn-supported",
            "Synthetic Supported Only",
            [_fn("tutoring", "elf")],
        ),
    ]
    receipt = compare_functions(before, [])
    reasons = {row["id"]: row for row in receipt["unknown_removals"]}
    assert set(reasons) == {
        "syn-empty",
        "syn-mixed",
        "syn-partial",
        "syn-unknown",
    }
    for row in receipt["unknown_removals"]:
        assert row["reason"] == UNKNOWN_REMOVAL_REASON
        assert "bad" not in row["reason"].lower()
        assert "incomplete functional coverage" in row["reason"]
    assert "syn-supported" not in reasons
    assert {
        (row["key"], row["scope"], row["lost"]) for row in receipt["lost_functions"]
    } == {
        ("removal", "creature", 1),
        ("tutoring", "elf", 1),
    }


def test_inputs_are_not_mutated() -> None:
    functions = [_fn("draw", "card")]
    before = [_card("syn-draw", "Synthetic Generic Draw", functions, tags=["keep"])]
    after = [
        _card("syn-draw", "Synthetic Generic Draw", functions),
        _card("syn-extra", "Synthetic Extra", [_fn("ramp", "mana")], count=2),
    ]
    protected = ["syn-draw"]
    before_snapshot = copy.deepcopy(before)
    after_snapshot = copy.deepcopy(after)
    protected_snapshot = list(protected)
    before_id = id(before[0])
    functions_id = id(functions)
    receipt = compare_functions(before, after, protected_ids=protected)
    assert before == before_snapshot
    assert after == after_snapshot
    assert protected == protected_snapshot
    assert id(before[0]) == before_id
    assert id(before[0]["functions"]) == functions_id
    assert "count" not in before[0]
    receipt["added"].append({"id": "mutated", "name": "mutated", "count": 1})
    receipt["removed"].append({"id": "mutated", "name": "mutated", "count": 1})
    assert before == before_snapshot
    assert after == after_snapshot


def test_receipt_is_order_invariant_and_sorted() -> None:
    before = [
        _card("syn-b", "Bravo", [_fn("removal", "creature")]),
        _card("syn-a", "Alpha", [_fn("token_generation", "creature")], count=2),
    ]
    after = [
        _card("syn-c", "Charlie", [_fn("draw", "card")]),
        _card("syn-a", "Alpha", [_fn("token_generation", "creature")]),
    ]
    forward = compare_functions(before, after, protected_ids={"syn-b", "syn-a"})
    backward = compare_functions(
        list(reversed(before)),
        list(reversed(after)),
        protected_ids=("syn-a", "syn-b"),
    )
    assert forward == backward
    assert [row["id"] for row in forward["added"]] == ["syn-c"]
    assert [row["id"] for row in forward["removed"]] == ["syn-a", "syn-b"]
    assert [row["id"] for row in forward["protected_removed"]] == ["syn-a", "syn-b"]
    assert [(row["key"], row["scope"]) for row in forward["lost_functions"]] == [
        ("removal", "creature"),
        ("token_generation", "creature"),
    ]


def test_inconsistent_facts_for_same_id_raise() -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        compare_functions(
            [
                _card("syn-x", "Alpha", [_fn("draw", "card")]),
                _card("syn-x", "Beta", [_fn("draw", "card")]),
            ],
            [],
        )
    with pytest.raises(ValueError, match="inconsistent"):
        compare_functions(
            [
                _card("syn-x", "Alpha", [_fn("draw", "card")]),
                _card("syn-x", "Alpha", [_fn("ramp", "mana")]),
            ],
            [],
        )


def test_oracle_mismatch_between_arms_raises() -> None:
    with pytest.raises(ValueError, match="same facts oracle"):
        compare_functions(
            [_card("syn-x", "Alpha", [_fn("draw", "card")])],
            [_card("syn-x", "Alpha", [_fn("ramp", "mana")])],
        )
    with pytest.raises(ValueError, match="same facts oracle"):
        compare_functions(
            [_card("syn-x", "Alpha", [_fn("draw", "card")])],
            [_card("syn-x", "Beta", [_fn("draw", "card")])],
        )


def test_conflicting_duplicate_functions_raise_identical_are_collapsed() -> None:
    identical = compare_functions(
        [
            _card(
                "syn-x",
                "Alpha",
                [
                    _fn("removal", "creature", evidence=["destroy target creature"]),
                    _fn("removal", "creature", evidence=["destroy target creature"]),
                ],
            )
        ],
        [],
    )
    assert identical["lost_functions"] == [
        {
            "key": "removal",
            "scope": "creature",
            "before": 1,
            "after": 0,
            "lost": 1,
        }
    ]
    with pytest.raises(ValueError, match="conflicting duplicate"):
        compare_functions(
            [
                _card(
                    "syn-x",
                    "Alpha",
                    [
                        _fn("removal", "creature", "supported", ["destroy"]),
                        _fn("removal", "creature", "partial", ["destroy"]),
                    ],
                )
            ],
            [],
        )
    with pytest.raises(ValueError, match="conflicting duplicate"):
        compare_functions(
            [
                _card(
                    "syn-x",
                    "Alpha",
                    [
                        _fn(
                            "removal", "creature", evidence=["destroy target creature"]
                        ),
                        _fn("removal", "creature", evidence=["exile target creature"]),
                    ],
                )
            ],
            [],
        )


def test_supported_empty_evidence_is_invalid() -> None:
    with pytest.raises(ValueError, match="nonempty evidence"):
        compare_functions(
            [
                _card(
                    "syn-x",
                    "Alpha",
                    [_fn("draw", "card", "supported", [])],
                )
            ],
            [],
        )


def test_malformed_inputs_raise() -> None:
    valid = [_card("syn-x", "Alpha", [_fn("draw", "card")])]
    with pytest.raises(ValueError, match="before"):
        compare_functions(None, [])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="after"):
        compare_functions([], {"id": "syn-x"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="dict"):
        compare_functions(["Alpha"], [])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="missing"):
        compare_functions([{"name": "Alpha", "functions": []}], [])
    with pytest.raises(ValueError, match="missing"):
        compare_functions([{"id": "syn-x", "functions": []}], [])
    with pytest.raises(ValueError, match="missing"):
        compare_functions([{"id": "syn-x", "name": "Alpha"}], [])
    with pytest.raises(ValueError, match="functions"):
        compare_functions(
            [{"id": "syn-x", "name": "Alpha", "functions": {"key": "draw"}}],
            [],
        )
    with pytest.raises(ValueError, match="confidence"):
        compare_functions(
            [_card("syn-x", "Alpha", [_fn("draw", "card", "maybe")])],
            [],
        )
    with pytest.raises(ValueError, match="evidence"):
        compare_functions(
            [
                {
                    "id": "syn-x",
                    "name": "Alpha",
                    "functions": [
                        {
                            "key": "draw",
                            "scope": "card",
                            "confidence": "supported",
                            "evidence": "draw a card",
                        }
                    ],
                }
            ],
            [],
        )
    with pytest.raises(ValueError, match="protected_ids"):
        compare_functions([], [], protected_ids="syn-x")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-empty"):
        compare_functions([], [], protected_ids=[""])
    compare_functions(valid, valid)


def test_empty_names_ids_and_invalid_counts_raise() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        compare_functions([_card("", "Alpha", [])], [])
    with pytest.raises(ValueError, match="non-empty"):
        compare_functions([_card("   ", "Alpha", [])], [])
    with pytest.raises(ValueError, match="non-empty"):
        compare_functions([_card("syn-x", "", [])], [])
    with pytest.raises(ValueError, match="non-empty"):
        compare_functions([_card("syn-x", "Alpha", [_fn("", "card")])], [])
    with pytest.raises(ValueError, match="non-empty"):
        compare_functions([_card("syn-x", "Alpha", [_fn("draw", " ")])], [])
    for invalid in (0, -1, -3, 1.5, 1.0, "1", None, True, False):
        payload: dict = {
            "id": "syn-x",
            "name": "Alpha",
            "functions": [],
            "count": invalid,
        }
        with pytest.raises(ValueError, match="positive integer"):
            compare_functions([payload], [])
        with pytest.raises(ValueError, match="positive integer"):
            compare_functions([], [payload])


def test_bool_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="bool"):
        compare_functions(
            [{"id": "syn-x", "name": "Alpha", "functions": [], "count": True}],
            [],
        )
    with pytest.raises(ValueError, match="bool"):
        compare_functions(
            [{"id": "syn-x", "name": "Alpha", "functions": [], "count": False}],
            [],
        )


def test_nonfinite_numeric_metrics_raise() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="nonfinite"):
            compare_functions(
                [_card("syn-x", "Alpha", [_fn("draw", "card")], score=value)],
                [],
            )
        with pytest.raises(ValueError, match="nonfinite"):
            compare_functions(
                [
                    _card(
                        "syn-x",
                        "Alpha",
                        [_fn("draw", "card")],
                        metrics={"price": value},
                    )
                ],
                [],
            )


def test_missing_coverage_is_unknown_even_with_recognized_function():
    card = {
        "id": "x",
        "name": "Recognized but incomplete",
        "functions": [_fn("removal", "creature")],
    }
    result = compare_functions([card], [])
    assert result["unknown_removals"][0]["coverage_complete"] is False


def test_explicit_known_empty_is_distinct_from_unknown_empty():
    known = _card("known", "Pure draw", [], coverage_complete=True)
    unknown = _card("unknown", "Unmodeled", [])
    result = compare_functions([known, unknown], [])
    assert [r["id"] for r in result["unknown_removals"]] == ["unknown"]


def test_coverage_cannot_change_between_comparison_arms():
    card = _card("same", "Same card", [], coverage_complete=True)
    with pytest.raises(ValueError):
        compare_functions([card], [{**card, "coverage_complete": False}])
