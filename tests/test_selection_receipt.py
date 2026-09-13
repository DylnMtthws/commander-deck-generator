"""Behavioral coverage for selection_receipt.build_receipt."""

from __future__ import annotations

import copy
import json
import math

import pytest

from sabermetrics.intelligence.selection_receipt import build_receipt


def _card(name: str, count: int | None = None, **extra: object) -> dict:
    payload: dict = {"name": name}
    if count is not None:
        payload["count"] = count
    payload.update(extra)
    return payload


def _decision(
    card: str,
    action: str,
    reason: str,
    alternatives: list[str] | None = None,
    **extra: object,
) -> dict:
    payload: dict = {
        "card": card,
        "action": action,
        "reason": reason,
        "alternatives": [] if alternatives is None else alternatives,
    }
    payload.update(extra)
    return payload


def test_empty_inputs_yield_empty_receipt() -> None:
    receipt = build_receipt([], [], [])
    assert receipt == {
        "added": [],
        "removed": [],
        "unchanged": [],
        "decisions": [],
        "unresolved": [],
    }
    json.dumps(receipt)


def test_default_count_is_one_and_is_not_written_back() -> None:
    before = [_card("Sol Ring")]
    after = [_card("Sol Ring")]
    receipt = build_receipt(before, after, [])
    assert receipt["unchanged"] == [{"name": "Sol Ring", "count": 1}]
    assert receipt["added"] == []
    assert receipt["removed"] == []
    assert "count" not in before[0]
    assert "count" not in after[0]


def test_multiset_repeated_basics_match_count_field() -> None:
    repeated = [_card("Forest"), _card("Forest"), _card("Forest")]
    counted = [_card("Forest", 3)]
    mixed = [_card("Forest", 2), _card("Forest")]
    from_repeated = build_receipt(repeated, counted, [])
    from_counted = build_receipt(counted, mixed, [])
    from_mixed = build_receipt(mixed, repeated, [])
    for receipt in (from_repeated, from_counted, from_mixed):
        assert receipt["added"] == []
        assert receipt["removed"] == []
        assert receipt["unchanged"] == [{"name": "Forest", "count": 3}]


def test_multiset_partial_overlap_splits_added_removed_unchanged() -> None:
    before = [
        _card("Forest", 3),
        _card("Island"),
        _card("Island"),
        _card("Swamp", 1),
        _card("Sol Ring"),
    ]
    after = [
        _card("Forest"),
        _card("Island", 2),
        _card("Mountain", 2),
        _card("Arcane Signet"),
    ]
    receipt = build_receipt(before, after, [])
    assert receipt["added"] == [
        {"name": "Arcane Signet", "count": 1},
        {"name": "Mountain", "count": 2},
    ]
    assert receipt["removed"] == [
        {"name": "Forest", "count": 2},
        {"name": "Sol Ring", "count": 1},
        {"name": "Swamp", "count": 1},
    ]
    assert receipt["unchanged"] == [
        {"name": "Forest", "count": 1},
        {"name": "Island", "count": 2},
    ]


def test_full_add_and_full_remove_are_not_listed_as_unchanged() -> None:
    before = [_card("Lightning Bolt"), _card("Forest", 2)]
    after = [_card("Forest", 2), _card("Ponder")]
    receipt = build_receipt(before, after, [])
    assert receipt["added"] == [{"name": "Ponder", "count": 1}]
    assert receipt["removed"] == [{"name": "Lightning Bolt", "count": 1}]
    assert receipt["unchanged"] == [{"name": "Forest", "count": 2}]


def test_receipt_is_order_invariant() -> None:
    before = [_card("Island"), _card("Forest", 2), _card("Mountain")]
    after = [_card("Mountain"), _card("Forest"), _card("Plains"), _card("Forest")]
    decisions = [
        _decision("Mountain", "keep", "red source", ["Forgotten Cave"]),
        _decision("Forest", "replace", "cut a copy", ["Plains"]),
        _decision("Sol Ring", "unresolved", "no substitute listed", []),
    ]
    forward = build_receipt(before, after, decisions)
    backward = build_receipt(
        list(reversed(before)),
        list(reversed(after)),
        list(reversed(decisions)),
    )
    shuffled_before = [_card("Mountain"), _card("Island"), _card("Forest", 2)]
    shuffled_after = [_card("Forest", 2), _card("Plains"), _card("Mountain")]
    shuffled_decisions = [
        _decision("Sol Ring", "unresolved", "no substitute listed", []),
        _decision("Forest", "replace", "cut a copy", ["Plains"]),
        _decision("Mountain", "keep", "red source", ["Forgotten Cave"]),
    ]
    shuffled = build_receipt(shuffled_before, shuffled_after, shuffled_decisions)
    assert forward == backward == shuffled
    assert [row["name"] for row in forward["added"]] == ["Plains"]
    assert [row["name"] for row in forward["removed"]] == ["Island"]
    assert [row["name"] for row in forward["unchanged"]] == ["Forest", "Mountain"]
    assert [row["card"] for row in forward["decisions"]] == [
        "Forest",
        "Mountain",
        "Sol Ring",
    ]
    assert [row["card"] for row in forward["unresolved"]] == ["Sol Ring"]


def test_inputs_are_not_mutated() -> None:
    before = [_card("Forest", 2, tags=["basic"])]
    after = [_card("Forest"), _card("Island", price=0.25)]
    alternatives = ["Command Tower"]
    decisions = [
        _decision(
            "Forest",
            "replace",
            "trim a basic",
            alternatives,
            score=-1.5,
            metrics={"price": 0.01},
        )
    ]
    before_snapshot = copy.deepcopy(before)
    after_snapshot = copy.deepcopy(after)
    decisions_snapshot = copy.deepcopy(decisions)
    before_id = id(before[0])
    after_id = id(after[1])
    alternatives_id = id(alternatives)
    metrics_id = id(decisions[0]["metrics"])
    receipt = build_receipt(before, after, decisions)
    assert before == before_snapshot
    assert after == after_snapshot
    assert decisions == decisions_snapshot
    assert id(before[0]) == before_id
    assert id(after[1]) == after_id
    assert id(decisions[0]["alternatives"]) == alternatives_id
    assert id(decisions[0]["metrics"]) == metrics_id
    assert [card["name"] for card in before] == ["Forest"]
    assert [card["name"] for card in after] == ["Forest", "Island"]
    receipt["added"].append({"name": "mutated", "count": 1})
    receipt["decisions"][0]["reason"] = "rewritten"
    receipt["decisions"][0]["alternatives"].append("Exotic Orchard")
    receipt["decisions"][0]["metrics"]["price"] = 99.0
    assert before == before_snapshot
    assert after == after_snapshot
    assert decisions == decisions_snapshot
    assert decisions[0]["alternatives"] == ["Command Tower"]


def test_unresolved_decisions_and_reasons_are_preserved() -> None:
    reason = "oracle text conflict; no supported swap"
    decision = _decision(
        "Gaea's Cradle",
        "unresolved",
        reason,
        ["Nykthos, Shrine to Nyx"],
        score=9.0,
        note="leave in place",
    )
    receipt = build_receipt(
        [_card("Gaea's Cradle"), _card("Forest")],
        [_card("Gaea's Cradle"), _card("Forest")],
        [decision],
    )
    assert receipt["unresolved"] == receipt["decisions"]
    assert receipt["unresolved"][0]["reason"] == reason
    assert receipt["unresolved"][0]["alternatives"] == ["Nykthos, Shrine to Nyx"]
    assert receipt["unresolved"][0]["score"] == 9.0
    assert receipt["unresolved"][0]["note"] == "leave in place"
    assert receipt["unresolved"][0]["action"] == "unresolved"
    assert receipt["unresolved"][0] is receipt["decisions"][0]
    assert receipt["unresolved"][0] is not decision


def test_keep_and_replace_are_not_moved_into_unresolved() -> None:
    decisions = [
        _decision("Sol Ring", "keep", "fast mana", []),
        _decision(
            "Cultivate",
            "replace",
            "prefer cheaper ramp",
            ["Kodama's Reach"],
        ),
        _decision(
            "Dockside Extortionist",
            "unresolved",
            "ban status unknown",
            [],
        ),
    ]
    receipt = build_receipt(
        [_card("Sol Ring"), _card("Cultivate"), _card("Dockside Extortionist")],
        [_card("Sol Ring"), _card("Kodama's Reach"), _card("Dockside Extortionist")],
        decisions,
    )
    assert [row["card"] for row in receipt["decisions"]] == [
        "Cultivate",
        "Dockside Extortionist",
        "Sol Ring",
    ]
    assert [row["card"] for row in receipt["unresolved"]] == ["Dockside Extortionist"]
    assert receipt["unresolved"][0]["reason"] == "ban status unknown"
    keep = next(row for row in receipt["decisions"] if row["card"] == "Sol Ring")
    replace = next(row for row in receipt["decisions"] if row["card"] == "Cultivate")
    assert keep["action"] == "keep"
    assert keep["reason"] == "fast mana"
    assert replace["action"] == "replace"
    assert replace["alternatives"] == ["Kodama's Reach"]


def test_does_not_infer_quality_or_drop_unsupported_decisions() -> None:
    """Receipts report bags and echo decisions; they do not judge them."""
    before = [_card("Sol Ring"), _card("Mana Crypt")]
    after = [_card("Arcane Signet")]
    decisions = [
        _decision(
            "Sol Ring",
            "keep",
            "this keep is unsupported by the after list",
            [],
            score=-8.0,
        ),
        _decision(
            "Missing Card",
            "unresolved",
            "no catalog match",
            ["Also Missing"],
        ),
        _decision(
            "Mana Crypt",
            "replace",
            "called a staple; do not infer that this is good",
            ["Arcane Signet"],
            price=-0.5,
        ),
    ]
    receipt = build_receipt(before, after, decisions)
    assert receipt["added"] == [{"name": "Arcane Signet", "count": 1}]
    assert receipt["removed"] == [
        {"name": "Mana Crypt", "count": 1},
        {"name": "Sol Ring", "count": 1},
    ]
    assert receipt["unchanged"] == []
    by_card = {row["card"]: row for row in receipt["decisions"]}
    assert by_card["Sol Ring"]["action"] == "keep"
    assert by_card["Sol Ring"]["reason"] == "this keep is unsupported by the after list"
    assert by_card["Sol Ring"]["score"] == -8.0
    assert by_card["Mana Crypt"]["reason"] == (
        "called a staple; do not infer that this is good"
    )
    assert [row["card"] for row in receipt["unresolved"]] == ["Missing Card"]
    assert "quality" not in receipt
    assert "winner" not in receipt
    assert "supported" not in receipt


def test_decisions_are_sorted_by_card_and_alternatives_keep_supplied_order() -> None:
    decisions = [
        _decision(
            "Zendikar Resurgent",
            "keep",
            "draw",
            ["Guardian Project", "Beast Whisperer"],
        ),
        _decision(
            "Arcane Signet",
            "replace",
            "prefer rock",
            ["Sol Ring", "Fellwar Stone"],
        ),
        _decision(
            "Blighted Woodland",
            "unresolved",
            "ramp land",
            ["Myriad Landscape"],
        ),
    ]
    receipt = build_receipt([], [], decisions)
    assert [row["card"] for row in receipt["decisions"]] == [
        "Arcane Signet",
        "Blighted Woodland",
        "Zendikar Resurgent",
    ]
    assert receipt["decisions"][0]["alternatives"] == ["Sol Ring", "Fellwar Stone"]
    assert receipt["decisions"][2]["alternatives"] == [
        "Guardian Project",
        "Beast Whisperer",
    ]
    assert [row["card"] for row in receipt["unresolved"]] == ["Blighted Woodland"]


def test_duplicate_card_decisions_raise_even_when_identical() -> None:
    identical = [
        _decision("Sol Ring", "keep", "fast mana", []),
        _decision("Sol Ring", "keep", "fast mana", []),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        build_receipt([], [], identical)
    contradictory = [
        _decision("Forest", "keep", "keep it", []),
        _decision("Island", "replace", "swap", ["Plains"]),
        _decision("Forest", "replace", "cut it", ["Plains"]),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        build_receipt([], [], contradictory)


def test_malformed_inputs_raise() -> None:
    valid_decision = _decision("Sol Ring", "keep", "fast mana", [])
    with pytest.raises(ValueError, match="before"):
        build_receipt(None, [], [])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="after"):
        build_receipt([], {"name": "Forest"}, [])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="decisions"):
        build_receipt([], [], {"card": "Sol Ring"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="dict"):
        build_receipt(["Forest"], [], [])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="dict"):
        build_receipt([], [], ["keep"])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="missing"):
        build_receipt([{"count": 1}], [], [])
    with pytest.raises(ValueError, match="missing"):
        build_receipt(
            [],
            [],
            [{"card": "Sol Ring", "action": "keep", "reason": "x"}],
        )
    with pytest.raises(ValueError, match="action"):
        build_receipt([], [], [_decision("Sol Ring", "cut", "nope", [])])
    with pytest.raises(ValueError, match="action"):
        build_receipt([], [], [_decision("Sol Ring", "unsupported", "nope", [])])
    with pytest.raises(ValueError, match="reason"):
        build_receipt(
            [],
            [],
            [{"card": "Sol Ring", "action": "keep", "reason": 1, "alternatives": []}],
        )
    with pytest.raises(ValueError, match="alternatives"):
        build_receipt(
            [],
            [],
            [
                {
                    "card": "Sol Ring",
                    "action": "keep",
                    "reason": "x",
                    "alternatives": "Sol Ring",
                }
            ],
        )
    with pytest.raises(ValueError, match="alternatives"):
        build_receipt(
            [],
            [],
            [_decision("Sol Ring", "keep", "x", [1])],  # type: ignore[list-item]
        )
    with pytest.raises(ValueError, match="card"):
        build_receipt([], [], [_decision(1, "keep", "x", [])])  # type: ignore[arg-type]
    build_receipt([], [], [valid_decision])


def test_empty_names_and_invalid_counts_raise() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_receipt([_card("")], [], [])
    with pytest.raises(ValueError, match="non-empty"):
        build_receipt([_card("   ")], [], [])
    with pytest.raises(ValueError, match="non-empty"):
        build_receipt([], [], [_decision("", "keep", "x", [])])
    with pytest.raises(ValueError, match="non-empty"):
        build_receipt([], [], [_decision("\n", "keep", "x", [])])
    for invalid in (0, -1, -3, 1.5, 1.0, "1", None, True, False):
        with pytest.raises(ValueError, match="positive integer"):
            build_receipt(
                [{"name": "Forest", "count": invalid}],
                [],
                [],
            )
        with pytest.raises(ValueError, match="positive integer"):
            build_receipt(
                [],
                [{"name": "Forest", "count": invalid}],
                [],
            )


def test_bool_count_is_rejected_rather_than_treated_as_one_or_zero() -> None:
    with pytest.raises(ValueError, match="bool"):
        build_receipt([{"name": "Forest", "count": True}], [], [])
    with pytest.raises(ValueError, match="bool"):
        build_receipt([{"name": "Forest", "count": False}], [], [])


def test_nonfinite_numeric_metrics_raise() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="nonfinite"):
            build_receipt([_card("Sol Ring", score=value)], [], [])
        with pytest.raises(ValueError, match="nonfinite"):
            build_receipt([], [_card("Sol Ring", price=value)], [])
        with pytest.raises(ValueError, match="nonfinite"):
            build_receipt(
                [],
                [],
                [_decision("Sol Ring", "keep", "x", [], score=value)],
            )
        with pytest.raises(ValueError, match="nonfinite"):
            build_receipt(
                [],
                [],
                [_decision("Sol Ring", "keep", "x", [], price=value)],
            )


def test_nested_nonfinite_score_and_price_raise() -> None:
    with pytest.raises(ValueError, match="nonfinite"):
        build_receipt(
            [_card("Sol Ring", metrics={"score": math.nan})],
            [],
            [],
        )
    with pytest.raises(ValueError, match="nonfinite"):
        build_receipt(
            [],
            [_card("Sol Ring", price={"usd": math.inf})],
            [],
        )
    with pytest.raises(ValueError, match="nonfinite"):
        build_receipt(
            [],
            [],
            [
                _decision(
                    "Sol Ring",
                    "keep",
                    "x",
                    [],
                    metrics={"score": {"fit": -math.inf}},
                )
            ],
        )
    with pytest.raises(ValueError, match="nonfinite"):
        build_receipt(
            [],
            [],
            [
                _decision(
                    "Sol Ring",
                    "replace",
                    "x",
                    ["Arcane Signet"],
                    scores=[1.0, math.nan],
                )
            ],
        )
    with pytest.raises(ValueError, match="nonfinite"):
        build_receipt(
            [_card("Forest", nested={"inner": [{"price": math.inf}]})],
            [],
            [],
        )


def test_finite_negative_metrics_allowed_except_quantity_and_count() -> None:
    receipt = build_receipt(
        [_card("Sol Ring", score=-2.5, price=-0.01)],
        [_card("Sol Ring", score=-2.5, price=-0.01)],
        [
            _decision(
                "Sol Ring",
                "keep",
                "negative extras are still metrics",
                [],
                score=-9.0,
                price=-1.25,
                delta=-0.5,
                metrics={"score": -3, "price": -4.0},
            )
        ],
    )
    decision = receipt["decisions"][0]
    assert decision["score"] == -9.0
    assert decision["price"] == -1.25
    assert decision["delta"] == -0.5
    assert decision["metrics"]["score"] == -3
    assert decision["metrics"]["price"] == -4.0
    assert receipt["unchanged"] == [{"name": "Sol Ring", "count": 1}]
    for invalid in (0, -1, True, 2.0, math.nan):
        with pytest.raises(ValueError):
            build_receipt(
                [_card("Forest", quantity=invalid)],  # type: ignore[arg-type]
                [],
                [],
            )
        with pytest.raises(ValueError):
            build_receipt(
                [],
                [],
                [
                    _decision(
                        "Forest",
                        "keep",
                        "x",
                        [],
                        quantity=invalid,
                    )
                ],
            )
        with pytest.raises(ValueError):
            build_receipt(
                [],
                [],
                [
                    _decision(
                        "Forest",
                        "keep",
                        "x",
                        [],
                        extras={"count": invalid},
                    )
                ],
            )


def test_positive_nested_quantity_is_accepted_as_a_metric() -> None:
    receipt = build_receipt(
        [_card("Forest", 2)],
        [_card("Forest", 2)],
        [
            _decision(
                "Forest",
                "keep",
                "still two copies",
                [],
                quantity=2,
                extras={"count": 2},
            )
        ],
    )
    assert receipt["decisions"][0]["quantity"] == 2
    assert receipt["decisions"][0]["extras"]["count"] == 2
    assert receipt["unchanged"] == [{"name": "Forest", "count": 2}]


def test_extra_metrics_are_preserved_without_invented_fields() -> None:
    decision = _decision(
        "Rhystic Study",
        "keep",
        "tax piece",
        ["Mystic Remora"],
        fit_score=8.25,
        salt=-0.2,
        flags={"watchlisted": True},
    )
    receipt = build_receipt(
        [_card("Rhystic Study")],
        [_card("Rhystic Study")],
        [decision],
    )
    echoed = receipt["decisions"][0]
    assert echoed["fit_score"] == 8.25
    assert echoed["salt"] == -0.2
    assert echoed["flags"] == {"watchlisted": True}
    assert "verdict" not in echoed
    assert "quality" not in echoed
    dumped = json.loads(json.dumps(receipt))
    assert dumped["decisions"][0]["reason"] == "tax piece"


def test_empty_reason_is_preserved_rather_than_inferred() -> None:
    receipt = build_receipt(
        [_card("Island")],
        [_card("Island")],
        [_decision("Island", "unresolved", "", [])],
    )
    assert receipt["decisions"][0]["reason"] == ""
    assert receipt["unresolved"][0]["reason"] == ""
