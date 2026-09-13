"""Behavioral coverage for CandidateTrace.

Examples are synthetic public card dicts, not live catalog or model output.
"""

from __future__ import annotations

import copy
import json

import pytest

from sabermetrics.intelligence.candidate_trace import (
    CARD_FIELD_WHITELIST,
    CandidateTrace,
)

FORBIDDEN_KEYS = frozenset(
    {
        "tokens",
        "user",
        "prompt",
        "private_prompt",
        "_facts",
        "payload",
        "_empirical_reliable",
        "nested_payload",
    }
)


def _card(name: str, **extra: object) -> dict:
    payload: dict = {"name": name}
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


def test_multiple_watched_names_are_sorted_unique() -> None:
    trace = CandidateTrace(["Sol Ring", "Lightning Bolt", "Sol Ring", "Abrade"])
    data = trace.to_dict()
    assert data == {
        "names": ["Abrade", "Lightning Bolt", "Sol Ring"],
        "stages": [],
    }
    json.dumps(data)


def test_constructor_accepts_generator_and_dedupes() -> None:
    trace = CandidateTrace(name for name in ["B", "A", "A", "B"])
    assert trace.to_dict()["names"] == ["A", "B"]


def test_exact_case_names_are_distinct_and_do_not_match() -> None:
    trace = CandidateTrace(["Sol Ring", "sol ring"])
    trace.record(
        "screen",
        [
            _card("Sol Ring", id="upper"),
            _card("Lightning Bolt", id="other"),
        ],
    )
    cards = trace.to_dict()["stages"][0]["cards"]
    assert [row["name"] for row in cards] == ["Sol Ring", "sol ring"]
    by_name = {row["name"]: row for row in cards}
    assert by_name["Sol Ring"]["present"] is True
    assert by_name["Sol Ring"]["matches"] == [{"name": "Sol Ring", "id": "upper"}]
    assert by_name["sol ring"]["present"] is False
    assert by_name["sol ring"]["matches"] == []


def test_matching_does_not_strip_so_padded_names_stay_distinct() -> None:
    padded = "Sol Ring "
    trace = CandidateTrace(["Sol Ring", padded])
    trace.record("screen", [_card("Sol Ring", id="exact")])
    rows = {row["name"]: row for row in trace.to_dict()["stages"][0]["cards"]}
    assert rows["Sol Ring"]["present"] is True
    assert rows[padded]["present"] is False
    assert rows[padded]["matches"] == []


def test_absent_watched_name_is_explicit_present_false() -> None:
    trace = CandidateTrace(["Sol Ring", "Abrade"])
    trace.record("screen", [_card("Abrade", id="ab")])
    rows = trace.to_dict()["stages"][0]["cards"]
    assert rows[0] == {
        "name": "Abrade",
        "present": True,
        "matches": [{"name": "Abrade", "id": "ab"}],
    }
    assert rows[1] == {"name": "Sol Ring", "present": False, "matches": []}


def test_all_printings_and_identical_duplicates_keep_input_order() -> None:
    first = _card("Sol Ring", id="sr-a", price_usd=5.0)
    later = _card("Sol Ring", id="sr-c", price_usd=1.0)
    duplicate = _card("Sol Ring", id="sr-a", price_usd=5.0)
    other = _card("Lightning Bolt", id="lb")
    trace = CandidateTrace(["Lightning Bolt", "Sol Ring"])
    trace.record("printings", [first, other, later, duplicate])
    sol = trace.to_dict()["stages"][0]["cards"][1]
    assert sol["name"] == "Sol Ring"
    assert sol["present"] is True
    assert sol["matches"] == [
        {"name": "Sol Ring", "id": "sr-a", "price_usd": 5.0},
        {"name": "Sol Ring", "id": "sr-c", "price_usd": 1.0},
        {"name": "Sol Ring", "id": "sr-a", "price_usd": 5.0},
    ]
    bolt = trace.to_dict()["stages"][0]["cards"][0]
    assert bolt["matches"] == [{"name": "Lightning Bolt", "id": "lb"}]


def test_input_mutation_does_not_change_recorded_history() -> None:
    keywords = ["Flash"]
    colors = ["W"]
    card = _card("Sol Ring", keywords=keywords, color_identity=colors, id="sr")
    original = copy.deepcopy(card)
    trace = CandidateTrace(["Sol Ring"])
    trace.record("screen", [card])
    keywords.append("Haste")
    colors.append("U")
    card["id"] = "mutated"
    card["name"] = "Changed"
    assert card != original
    match = trace.to_dict()["stages"][0]["cards"][0]["matches"][0]
    assert match == {
        "id": "sr",
        "name": "Sol Ring",
        "color_identity": ["W"],
        "keywords": ["Flash"],
    }


def test_to_dict_return_mutations_do_not_alter_internal_state() -> None:
    trace = CandidateTrace(["Sol Ring"])
    trace.record("screen", [_card("Sol Ring", keywords=["Flash"], id="sr")])
    first = trace.to_dict()
    first["names"].append("hack")
    first["stages"][0]["stage"] = "rewritten"
    first["stages"][0]["cards"][0]["present"] = False
    first["stages"][0]["cards"][0]["matches"][0]["keywords"].append("X")
    first["stages"][0]["cards"][0]["matches"][0]["id"] = "mutated"
    second = trace.to_dict()
    assert second["names"] == ["Sol Ring"]
    assert second["stages"][0]["stage"] == "screen"
    assert second["stages"][0]["cards"][0]["present"] is True
    assert second["stages"][0]["cards"][0]["matches"][0] == {
        "id": "sr",
        "name": "Sol Ring",
        "keywords": ["Flash"],
    }
    assert first is not second
    assert (
        first["stages"][0]["cards"][0]["matches"][0]
        is not second["stages"][0]["cards"][0]["matches"][0]
    )


def test_record_does_not_mutate_input_rows() -> None:
    card = _card("Sol Ring", tokens="secret", keywords=["Flash"])
    original = copy.deepcopy(card)
    trace = CandidateTrace(["Sol Ring"])
    trace.record("screen", [card])
    assert card == original


def test_instances_are_independent() -> None:
    left = CandidateTrace(["Abrade"])
    right = CandidateTrace(["Sol Ring"])
    left.record("screen", [_card("Abrade", id="a")])
    assert right.to_dict() == {"names": ["Sol Ring"], "stages": []}
    right.record("score", [_card("Sol Ring", id="s")])
    assert [row["name"] for row in left.to_dict()["stages"][0]["cards"]] == ["Abrade"]
    assert [row["name"] for row in right.to_dict()["stages"][0]["cards"]] == [
        "Sol Ring"
    ]
    assert left.to_dict()["stages"][0]["stage"] == "screen"
    assert right.to_dict()["stages"][0]["stage"] == "score"


def test_field_whitelist_copies_only_present_public_and_scoring_fields() -> None:
    card = _card(
        "Sol Ring",
        id="sr1",
        oracle_id="oracle-sr",
        oracle_text="{T}: Add {C}{C}.",
        type_line="Artifact",
        mana_cost="{1}",
        cmc=1,
        mana_value=1,
        color_identity=[],
        colors=[],
        power=None,
        toughness=None,
        keywords=[],
        layout="normal",
        is_legal_commander=False,
        is_legal_in_99=True,
        price_usd=1.25,
        current_price_usd=1.10,
        _cvar_score=0.8,
        _empirical_inclusion=0.9,
        _empirical_synergy=0.1,
        _anti_engine=False,
        _categorical_exclusion=None,
        role_tags=["ramp"],
        functional_categories=["mana"],
        tokens=["secret-token"],
        user="tester",
        prompt="private prompt text",
        private_prompt="do not copy",
        _facts={"roles": ["ramp"]},
        payload={"nested": True},
        nested_payload={"x": 1},
        _empirical_reliable=True,
    )
    trace = CandidateTrace(["Sol Ring"])
    trace.record("score", [card])
    match = trace.to_dict()["stages"][0]["cards"][0]["matches"][0]
    assert set(match) <= set(CARD_FIELD_WHITELIST)
    assert _keys(match).isdisjoint(FORBIDDEN_KEYS)
    assert "tokens" not in match
    assert "_facts" not in match
    assert "_empirical_reliable" not in match
    assert match["id"] == "sr1"
    assert match["_cvar_score"] == 0.8
    assert match["role_tags"] == ["ramp"]
    assert match["current_price_usd"] == 1.10
    json.dumps(trace.to_dict())


def test_absent_whitelist_fields_are_not_defaulted_or_inferred() -> None:
    trace = CandidateTrace(["Sol Ring"])
    trace.record("screen", [_card("Sol Ring")])
    match = trace.to_dict()["stages"][0]["cards"][0]["matches"][0]
    assert match == {"name": "Sol Ring"}
    assert "cmc" not in match
    assert "_cvar_score" not in match
    assert "price_usd" not in match


def test_multiple_record_calls_preserve_call_order() -> None:
    trace = CandidateTrace(["Sol Ring"])
    trace.record("screen", [_card("Sol Ring", id="in")])
    trace.record("score", [])
    stages = trace.to_dict()["stages"]
    assert [item["stage"] for item in stages] == ["screen", "score"]
    assert stages[0]["cards"][0]["present"] is True
    assert stages[1]["cards"][0]["present"] is False


def test_duplicate_stage_labels_are_distinct_observations() -> None:
    trace = CandidateTrace(["Sol Ring"])
    trace.record("screen", [_card("Sol Ring", id="first")])
    trace.record("screen", [_card("Abrade")])
    stages = trace.to_dict()["stages"]
    assert [item["stage"] for item in stages] == ["screen", "screen"]
    assert stages[0]["cards"][0]["matches"][0]["id"] == "first"
    assert stages[1]["cards"][0]["present"] is False
    assert stages[1]["cards"][0]["matches"] == []


def test_record_accepts_generator_of_card_dicts() -> None:
    trace = CandidateTrace(["Sol Ring"])
    trace.record("screen", (_card("Sol Ring", id=n) for n in ("a", "b")))
    matches = trace.to_dict()["stages"][0]["cards"][0]["matches"]
    assert [item["id"] for item in matches] == ["a", "b"]


def test_empty_watchlist_records_empty_card_rows() -> None:
    trace = CandidateTrace([])
    trace.record("screen", [_card("Sol Ring")])
    assert trace.to_dict() == {
        "names": [],
        "stages": [{"stage": "screen", "cards": []}],
    }


@pytest.mark.parametrize(
    "names",
    [
        [""],
        ["  "],
        ["\n"],
        ["Sol Ring", ""],
        ["Sol Ring", None],
        ["Sol Ring", 1],
        "Sol Ring",
        b"Sol Ring",
        None,
    ],
)
def test_invalid_or_blank_names_are_rejected(names: object) -> None:
    with pytest.raises(ValueError):
        CandidateTrace(names)  # type: ignore[arg-type]


@pytest.mark.parametrize("stage", ["", "  ", "\t", None, 1])
def test_invalid_stage_is_rejected(stage: object) -> None:
    trace = CandidateTrace(["Sol Ring"])
    with pytest.raises(ValueError):
        trace.record(stage, [_card("Sol Ring")])  # type: ignore[arg-type]
    assert trace.to_dict()["stages"] == []


@pytest.mark.parametrize(
    "cards",
    [
        [_card("Sol Ring"), "not a dict"],
        [{"id": "sr"}],
        [{"name": ""}],
        [{"name": "  "}],
        [{"name": None}],
        [{"name": 1}],
        "Sol Ring",
        {"name": "Sol Ring"},
        None,
    ],
)
def test_malformed_card_rows_are_rejected(cards: object) -> None:
    trace = CandidateTrace(["Sol Ring"])
    with pytest.raises(ValueError):
        trace.record("screen", cards)  # type: ignore[arg-type]
    assert trace.to_dict()["stages"] == []


def test_failed_record_is_atomic_and_does_not_partially_append() -> None:
    trace = CandidateTrace(["Abrade", "Sol Ring"])
    trace.record("screen", [_card("Sol Ring", id="ok")])
    with pytest.raises(ValueError):
        trace.record(
            "score",
            [
                _card("Sol Ring", id="would-record"),
                {"id": "missing-name"},
            ],
        )
    data = trace.to_dict()
    assert [item["stage"] for item in data["stages"]] == ["screen"]
    assert data["stages"][0]["cards"][1]["matches"][0]["id"] == "ok"
    trace.record("final", [])
    assert [item["stage"] for item in trace.to_dict()["stages"]] == ["screen", "final"]


def test_invalid_stage_does_not_commit_even_with_valid_cards() -> None:
    trace = CandidateTrace(["Sol Ring"])
    with pytest.raises(ValueError):
        trace.record("", [_card("Sol Ring")])
    assert trace.to_dict()["stages"] == []
